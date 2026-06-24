#!/usr/bin/env python3
"""
vanilla_diff.py - diff our i18n overrides against vanilla Stardew Valley text.

Background: this mod was built by hand against an OLDER unpacked Stardew
Content. Where a vanilla line needed editing for genderswap/flavor, the
author overrode it (in all languages, though most non-English values are
just the game's own unmodified text). Since then the base game has shipped
typo/grammar/wording fixes. This tool surfaces every override that no longer
matches current vanilla text, so a human can decide "our intentional edit"
vs "upstream fix we should port".

Reuses tools/i18n/resolve.py (un_i18n) and tools/i18n/keyscheme.py
(category/subject/entry derivation) -- this module does not reimplement
either.

Two modes:

  --mode current (default, this pass)
      "old" side = our i18n override text, "new" side = CURRENT vanilla
      Content (~/repos/Content_unpacked by default). Surfaces every
      override != vanilla delta for human triage. This is the only mode
      with real data behind it right now (we have no old vanilla snapshot).

  --mode oldnew
      Given --old-content <dir> and --new-content <dir>, diffs OLD vanilla
      vs NEW vanilla, restricted to the entry keys our patches actually
      touch. This is the clean, low-noise workflow for the NEXT pass, once
      a pre-1.6.15 (or post-1.6.15) snapshot exists. Wired up now; exercised
      only via a synthetic pair until then.

Scope (prose categories only -- see keyscheme.category_and_subject):
  - dialogue  (Characters/Dialogue/*, including MarriageDialogue*)
  - event     (Data/Events/*)
  - strings   (Strings/*, EXCLUDING Strings/NPCNames)

Explicitly out of scope: name/* (Strings/NPCNames), data/* (Data/Characters
field edits -- single gender/relationship words, not prose), and anything
that isn't an i18n-backed EditData value (config/token live in content.json,
not asset patches).

Output: a Markdown report (claude-documentation/reports/vanilla-diff-<baseline>.md)
plus printed summary counts (in-sync / changed / likely-upstream) per
language and per category.

Usage:
    python3 tools/i18n/vanilla_diff.py --mode current
    python3 tools/i18n/vanilla_diff.py --mode oldnew --old-content <dir> --new-content <dir>
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve import get_all_jsons, un_i18n  # noqa: E402
from keyscheme import (  # noqa: E402
    BLACKLISTED_ENTRIES,
    category_and_subject,
    event_entry_id,
    full_variant,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
I18N_DIR = os.path.join(REPO_ROOT, "i18n")
CONTENT_JSON_PATH = os.path.join(REPO_ROOT, "content.json")
BASELINE_PATH = os.path.join(REPO_ROOT, "tools", "i18n", "dialogue_baseline.txt")
DEFAULT_VANILLA_DIR = os.path.expanduser("~/repos/Content_unpacked")
REPORTS_DIR = os.path.join(REPO_ROOT, "claude-documentation", "reports")

# Languages this pass cares about: the real-translation set + English base.
LANGS = ["default", "zh", "ru", "es"]

# Locale-file-suffix map (data-driven so widening to the full set is trivial).
LOCALE_SUFFIX = {
    "default": "",
    "zh": ".zh-CN",
    "ru": ".ru-RU",
    "es": ".es-ES",
    "de": ".de-DE",
    "fr": ".fr-FR",
    "hu": ".hu-HU",
    "it": ".it-IT",
    "ja": ".ja-JP",
    "ko": ".ko-KR",
    "pt": ".pt-BR",
    "tr": ".tr-TR",
}

PROSE_CATEGORIES = {"dialogue", "event", "strings"}

PRONOUN_RE = re.compile(
    r"\b(he|him|his|himself|she|her|hers|herself|He|Him|His|Himself|She|Her|Hers|Herself)\b"
)

# Small seed vocabulary for flavor/species ranking. Only used to RANK
# (likely-intentional vs likely-upstream), never to filter -- every
# override != vanilla line still appears in the report.
FLAVOR_VOCAB = {
    "fur", "furry", "scales", "scaly", "tail", "paws", "paw", "claws", "claw",
    "whiskers", "fangs", "snout", "muzzle", "feathers", "feathered", "fluffy",
    "species", "anthro", "fursona", "shed", "shedding", "molt", "molting",
    "purr", "purring", "growl", "howl", "bark", "meow", "hiss",
}


# ---------------------------------------------------------------------------
# Vanilla content loading (cached)
# ---------------------------------------------------------------------------

class VanillaStore:
    """Loads + caches vanilla Content/<...>/<file>.<locale>.json files, with
    English-base fallback when a per-language file is missing for an asset."""

    def __init__(self, content_dir: str):
        self.content_dir = content_dir
        self._cache: dict[str, Optional[dict]] = {}
        self.fallbacks_used: set[tuple[str, str]] = set()  # (asset_path, lang)

    def _load(self, path: str) -> Optional[dict]:
        if path in self._cache:
            return self._cache[path]
        data = None
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = None
        self._cache[path] = data
        return data

    def get_file(self, asset_path: str, lang: str) -> Optional[dict]:
        """asset_path is e.g. 'Characters/Dialogue/Abigail' or
        'Data/Events/Beach' or 'Strings/Characters' or
        'Strings/schedules/Abigail'. Returns the parsed vanilla dict for the
        given language, falling back to English base if the per-lang file
        is missing (and recording the fallback)."""
        suffix = LOCALE_SUFFIX.get(lang, "")
        full = os.path.join(self.content_dir, f"{asset_path}{suffix}.json")
        data = self._load(full)
        if data is not None:
            return data
        if suffix == "":
            return None
        base_full = os.path.join(self.content_dir, f"{asset_path}.json")
        data = self._load(base_full)
        if data is not None:
            self.fallbacks_used.add((asset_path, lang))
        return data


# ---------------------------------------------------------------------------
# Genderswap name set + segment labeling (noise ranking)
# ---------------------------------------------------------------------------

def load_swap_names() -> set[str]:
    """Build the set of genderswap names from content.json's "<Orig> to <New>"
    ConfigSchema keys plus the name/* i18n keys' resolved values."""
    names: set[str] = set()
    with open(CONTENT_JSON_PATH, encoding="utf-8") as f:
        content = json.load(f)
    swap_re = re.compile(r"^(\w+) to (\w+)$")
    for key in content.get("ConfigSchema", {}):
        m = swap_re.match(key)
        if m:
            names.add(m.group(1))
            names.add(m.group(2))

    default_path = os.path.join(I18N_DIR, "default.json")
    with open(default_path, encoding="utf-8") as f:
        default_translations = json.load(f)
    for key, value in default_translations.items():
        if key.startswith("name/") and value:
            names.add(value)
    return names


def label_segment(text: str, swap_names: set[str]) -> str:
    """Label a single changed diff segment as 'likely-intentional' or
    'likely-upstream'. Ranking only -- never used to filter."""
    for name in swap_names:
        if name and name in text:
            return "likely-intentional"
    if PRONOUN_RE.search(text):
        return "likely-intentional"
    lowered = text.lower()
    for word in FLAVOR_VOCAB:
        if word in lowered:
            return "likely-intentional"
    return "likely-upstream"


@dataclass
class DiffSegment:
    label: str
    old_text: str
    new_text: str


def word_diff(old: str, new: str, swap_names: set[str]) -> list[DiffSegment]:
    """Word-level diff between old and new text. Returns one DiffSegment per
    changed (replace/delete/insert) opcode, each labeled for noise-ranking."""
    old_words = old.split()
    new_words = new.split()
    sm = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    segments: list[DiffSegment] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old_seg = " ".join(old_words[i1:i2])
        new_seg = " ".join(new_words[j1:j2])
        label = label_segment(old_seg + " " + new_seg, swap_names)
        segments.append(DiffSegment(label=label, old_text=old_seg, new_text=new_seg))
    return segments


# ---------------------------------------------------------------------------
# Walk our patches and build (category, subject, entry) -> variants
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    file: str           # asset json file (repo-relative)
    target: str
    target_field: str
    entry_key: str       # raw CP entry key
    variant_label: Optional[str]  # None for base, else "flavor", "swap-X", ...
    i18n_value: str       # raw "{{i18n:...}}" string


@dataclass
class LogicalLine:
    category: str
    subject: str
    entry: str
    variants: list[Variant] = field(default_factory=list)

    @property
    def line_key(self) -> str:
        return f"{self.category}/{self.subject}/{self.entry}"


def is_blacklisted_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    return "/i18n/" in norm or norm.endswith("manifest.json")


def walk_logical_lines() -> dict[str, LogicalLine]:
    """Walk assets/**/*.json EditData changes (mirrors resolve_all's walk),
    scoped to prose categories, grouping variants of the same vanilla line
    under one LogicalLine keyed by category/subject/entry."""
    lines: dict[str, LogicalLine] = {}
    for path in get_all_jsons(ASSETS_DIR):
        if is_blacklisted_file(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            target = change.get("Target", "")
            target_field_list = change.get("TargetField", [])
            target_field = "/".join(target_field_list)
            when = change.get("When", {})

            category, subject = category_and_subject(target, target_field_list)
            if category not in PROSE_CATEGORIES:
                continue
            if target == "Strings/NPCNames":
                continue  # explicitly out of scope (not prose)

            entries = change.get("Entries", {})
            for entry_key, value in entries.items():
                if entry_key in BLACKLISTED_ENTRIES:
                    continue
                if "i18n" not in value:
                    continue

                entry = event_entry_id(entry_key) if category == "event" else entry_key
                line_key = f"{category}/{subject}/{entry}"
                line = lines.setdefault(
                    line_key, LogicalLine(category=category, subject=subject, entry=entry)
                )
                variant_label = full_variant(path, when)
                line.variants.append(
                    Variant(
                        file=os.path.relpath(path, REPO_ROOT),
                        target=target,
                        target_field=target_field,
                        entry_key=entry_key,
                        variant_label=variant_label,
                        i18n_value=value,
                    )
                )
    return lines


# ---------------------------------------------------------------------------
# Vanilla lookup per category
# ---------------------------------------------------------------------------

def vanilla_asset_path(category: str, subject: str, target: str) -> str:
    """Map (category, subject, target) -> the vanilla asset's base path
    (no locale suffix, no .json extension), e.g. 'Characters/Dialogue/Abigail',
    'Data/Events/Beach', 'Strings/schedules/Abigail'."""
    if category == "dialogue":
        return f"Characters/Dialogue/{subject}"
    if category == "event":
        return f"Data/Events/{subject}"
    if category == "strings":
        return f"Strings/{subject}"
    # Shouldn't happen given PROSE_CATEGORIES, but stay safe.
    return target


def lookup_vanilla_text(
    store: VanillaStore, category: str, subject: str, target: str,
    entry_key: str, lang: str,
) -> Optional[str]:
    """Returns vanilla text for this entry/lang, or None if no vanilla entry
    exists at all (VANILLA-MISSING)."""
    asset_path = vanilla_asset_path(category, subject, target)
    vanilla_data = store.get_file(asset_path, lang)
    if vanilla_data is None:
        return None

    if category == "event":
        # Entry lookup: match vanilla key whose split('/')[0] == our event id
        # (our entry_key has already had its precondition tail dropped by
        # event_entry_id upstream; vanilla keys still carry the full
        # preconditions tail, so compare on the leading id only).
        target_id = entry_key.split("/", 1)[0]
        for vkey, vval in vanilla_data.items():
            if vkey.split("/", 1)[0] == target_id:
                return vval
        return None

    # dialogue / strings: entry key verbatim.
    return vanilla_data.get(entry_key)


# ---------------------------------------------------------------------------
# "current" mode: override vs current vanilla
# ---------------------------------------------------------------------------

@dataclass
class VariantResult:
    variant_label: Optional[str]
    entry_key: str
    file: str
    lang: str
    status: str  # "in-sync" | "changed" | "vanilla-missing" | "no-override"
    override_text: str = ""
    vanilla_text: str = ""
    vanilla_fallback: bool = False
    segments: list[DiffSegment] = field(default_factory=list)


@dataclass
class LineReport:
    line: LogicalLine
    results: list[VariantResult] = field(default_factory=list)

    @property
    def has_changed(self) -> bool:
        return any(r.status in ("changed", "vanilla-missing") for r in self.results)

    @property
    def has_likely_upstream(self) -> bool:
        return any(
            seg.label == "likely-upstream"
            for r in self.results
            for seg in r.segments
        )


def resolve_override(value: str, translations: dict) -> str:
    return un_i18n(value, translations)


def run_current_mode(vanilla_dir: str) -> list[LineReport]:
    lines = walk_logical_lines()
    store = VanillaStore(vanilla_dir)
    swap_names = load_swap_names()

    translations_by_lang = {}
    for lang in LANGS:
        path = os.path.join(I18N_DIR, f"{lang}.json")
        with open(path, encoding="utf-8") as f:
            translations_by_lang[lang] = json.load(f)

    reports: list[LineReport] = []
    for line_key in sorted(lines):
        line = lines[line_key]
        report = LineReport(line=line)
        for variant in sorted(line.variants, key=lambda v: (v.variant_label or "", v.file, v.entry_key)):
            for lang in LANGS:
                override_text = resolve_override(variant.i18n_value, translations_by_lang[lang])
                if override_text == "":
                    report.results.append(VariantResult(
                        variant_label=variant.variant_label, entry_key=variant.entry_key,
                        file=variant.file, lang=lang, status="no-override",
                    ))
                    continue

                vanilla_text = lookup_vanilla_text(
                    store, line.category, line.subject, variant.target,
                    variant.entry_key, lang,
                )
                if vanilla_text is None:
                    report.results.append(VariantResult(
                        variant_label=variant.variant_label, entry_key=variant.entry_key,
                        file=variant.file, lang=lang, status="vanilla-missing",
                        override_text=override_text,
                    ))
                    continue

                fallback_used = (vanilla_asset_path(line.category, line.subject, variant.target), lang) in store.fallbacks_used

                if override_text == vanilla_text:
                    report.results.append(VariantResult(
                        variant_label=variant.variant_label, entry_key=variant.entry_key,
                        file=variant.file, lang=lang, status="in-sync",
                        override_text=override_text, vanilla_text=vanilla_text,
                        vanilla_fallback=fallback_used,
                    ))
                    continue

                segments = word_diff(vanilla_text, override_text, swap_names)
                report.results.append(VariantResult(
                    variant_label=variant.variant_label, entry_key=variant.entry_key,
                    file=variant.file, lang=lang, status="changed",
                    override_text=override_text, vanilla_text=vanilla_text,
                    vanilla_fallback=fallback_used, segments=segments,
                ))
        reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# "oldnew" mode: old vanilla vs new vanilla, restricted to touched entries
# ---------------------------------------------------------------------------

@dataclass
class OldNewResult:
    line_key: str
    entry_key: str
    lang: str
    status: str  # "in-sync" | "changed" | "missing-old" | "missing-new"
    old_text: str = ""
    new_text: str = ""
    segments: list[DiffSegment] = field(default_factory=list)


def run_oldnew_mode(old_dir: str, new_dir: str) -> list[OldNewResult]:
    lines = walk_logical_lines()
    old_store = VanillaStore(old_dir)
    new_store = VanillaStore(new_dir)
    swap_names = load_swap_names()

    results: list[OldNewResult] = []
    # Restrict to one (entry_key, target) per logical line -- preconditions
    # tail variations within an event are folded already by event_entry_id;
    # we just need the entry once per line, not once per mod variant.
    seen: set[tuple[str, str]] = set()
    for line_key in sorted(lines):
        line = lines[line_key]
        for variant in line.variants:
            dedupe_key = (line_key, variant.entry_key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            for lang in LANGS:
                old_text = lookup_vanilla_text(
                    old_store, line.category, line.subject, variant.target,
                    variant.entry_key, lang,
                )
                new_text = lookup_vanilla_text(
                    new_store, line.category, line.subject, variant.target,
                    variant.entry_key, lang,
                )
                if old_text is None:
                    results.append(OldNewResult(line_key=line_key, entry_key=variant.entry_key,
                                                 lang=lang, status="missing-old"))
                    continue
                if new_text is None:
                    results.append(OldNewResult(line_key=line_key, entry_key=variant.entry_key,
                                                 lang=lang, status="missing-new", old_text=old_text))
                    continue
                if old_text == new_text:
                    results.append(OldNewResult(line_key=line_key, entry_key=variant.entry_key,
                                                 lang=lang, status="in-sync",
                                                 old_text=old_text, new_text=new_text))
                    continue
                segments = word_diff(old_text, new_text, swap_names)
                results.append(OldNewResult(line_key=line_key, entry_key=variant.entry_key,
                                             lang=lang, status="changed",
                                             old_text=old_text, new_text=new_text,
                                             segments=segments))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_segments_md(segments: list[DiffSegment]) -> str:
    parts = []
    for seg in segments:
        marker = "U" if seg.label == "likely-upstream" else "I"
        parts.append(f"  - `[{marker}]` `{seg.old_text}` -> `{seg.new_text}`")
    return "\n".join(parts)


def render_current_report(reports: list[LineReport], baseline: str) -> str:
    out = []
    out.append(f"# Vanilla dialogue diff report (baseline {baseline})\n")
    out.append(
        "Mode: `current` -- diffs our i18n overrides against CURRENT vanilla "
        "Content (not an old/new vanilla diff; we have no pre-1.6.15 snapshot "
        "yet). Every override != vanilla line is listed once per logical line, "
        "grouped across all mod variants (base/flavor/swap/etc.) that share the "
        "same vanilla source. Lines with at least one `likely-upstream` segment "
        "are sorted first.\n"
    )
    out.append(
        "Segment labels: `[I]` likely-intentional (touches a genderswap name, "
        "an English pronoun, or flavor/species vocabulary), `[U]` "
        "likely-upstream (everything else). Labels only RANK; every "
        "override != vanilla line is included regardless of label.\n"
    )

    # Sort: lines with likely-upstream segments first, then alphabetically.
    sortable = sorted(
        reports,
        key=lambda r: (0 if r.has_likely_upstream else 1, r.line.line_key),
    )

    changed_count = 0
    upstream_count = 0
    for report in sortable:
        if not report.has_changed:
            continue
        changed_count += 1
        if report.has_likely_upstream:
            upstream_count += 1

        line = report.line
        out.append(f"\n## `{line.line_key}`\n")

        # vanilla text per lang (take from any "changed"/"in-sync" result)
        vanilla_by_lang: dict[str, tuple[str, bool]] = {}
        for r in report.results:
            if r.status in ("changed", "in-sync") and r.lang not in vanilla_by_lang:
                vanilla_by_lang[r.lang] = (r.vanilla_text, r.vanilla_fallback)

        for lang, (vtext, fallback) in vanilla_by_lang.items():
            fb_note = " _(English-base fallback; no per-lang vanilla file)_" if fallback else ""
            out.append(f"**Vanilla [{lang}]**{fb_note}: {vtext}\n")

        for r in report.results:
            if r.status != "changed":
                continue
            tag = " UPSTREAM-CANDIDATE" if any(s.label == "likely-upstream" for s in r.segments) else ""
            label = f"@{r.variant_label}" if r.variant_label else "(base)"
            out.append(f"\n- Variant `{label}` [{r.lang}] -- `{r.file}` entry `{r.entry_key}`{tag}")
            out.append(f"  - Override: {r.override_text}")
            out.append(render_segments_md(r.segments))

        missing = [r for r in report.results if r.status == "vanilla-missing"]
        for r in missing:
            label = f"@{r.variant_label}" if r.variant_label else "(base)"
            out.append(f"\n- **VANILLA-MISSING** variant `{label}` [{r.lang}] -- `{r.file}` "
                        f"entry `{r.entry_key}`: override = {r.override_text}")

    out.append(f"\n\n## Summary\n\nLogical lines with >=1 changed variant: {changed_count}\n"
                f"Of those, lines with >=1 likely-upstream segment: {upstream_count}\n")
    return "\n".join(out)


def render_json_dataset(reports: list[LineReport], lang: str) -> tuple[list[dict], list[dict]]:
    """Build the machine-readable English (or other single-lang) dataset for
    the Haiku classification pass.

    Returns (records, vanilla_missing):
      - records: one dict per logical line with >=1 "changed" variant result
        in `lang`, each variant's override text + its word-diff segments
        (vanilla/override text only -- the [I]/[U] heuristic label is not
        needed downstream, Haiku re-judges from scratch).
      - vanilla_missing: one dict per (line, variant) "vanilla-missing"
        result in `lang`, collected separately per the plan (not part of
        the main dataset; surfaced as a short "removed/renamed upstream"
        list).
    """
    records: list[dict] = []
    vanilla_missing: list[dict] = []

    for report in sorted(reports, key=lambda r: r.line.line_key):
        line = report.line
        lang_results = [r for r in report.results if r.lang == lang]

        changed = [r for r in lang_results if r.status == "changed"]
        if changed:
            variants = []
            for r in changed:
                variants.append({
                    "variant": f"@{r.variant_label}" if r.variant_label else "(base)",
                    "source": r.file,
                    "override": r.override_text,
                    "segments": [
                        {"vanilla": seg.old_text, "override": seg.new_text}
                        for seg in r.segments
                    ],
                })
            vanilla_text = changed[0].vanilla_text
            records.append({
                "id": line.line_key,
                "vanilla": vanilla_text,
                "variants": variants,
            })

        for r in lang_results:
            if r.status != "vanilla-missing":
                continue
            vanilla_missing.append({
                "id": line.line_key,
                "lang": r.lang,
                "variant": f"@{r.variant_label}" if r.variant_label else "(base)",
                "source": r.file,
                "override": r.override_text,
            })

    return records, vanilla_missing


def print_summary(reports: list[LineReport]) -> None:
    # Per-language, per-category counts.
    per_lang_category: dict[tuple[str, str], dict[str, int]] = {}

    def bump(lang: str, category: str, status: str) -> None:
        d = per_lang_category.setdefault((lang, category), {})
        d[status] = d.get(status, 0) + 1

    total_records = 0
    total_upstream_lines = 0
    total_changed_lines = 0

    for report in reports:
        line = report.line
        line_has_upstream = False
        line_has_changed = False
        for r in report.results:
            bump(r.lang, line.category, r.status)
            if r.status == "changed":
                total_records += 1
                line_has_changed = True
                if any(s.label == "likely-upstream" for s in r.segments):
                    line_has_upstream = True
        if line_has_changed:
            total_changed_lines += 1
        if line_has_upstream:
            total_upstream_lines += 1

    print("\n=== Per language / category counts ===")
    for (lang, category), counts in sorted(per_lang_category.items()):
        parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"  [{lang}] {category}: {parts}")

    print("\n=== Totals ===")
    print(f"  changed variant-records (override != vanilla): {total_records}")
    print(f"  logical lines with >=1 changed variant: {total_changed_lines}")
    print(f"  of those, with >=1 likely-upstream segment: {total_upstream_lines}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["current", "oldnew"], default="current")
    parser.add_argument("--vanilla-content", default=DEFAULT_VANILLA_DIR,
                         help="Vanilla Content dir for --mode current (default: ~/repos/Content_unpacked)")
    parser.add_argument("--old-content", help="Old vanilla Content dir for --mode oldnew")
    parser.add_argument("--new-content", help="New vanilla Content dir for --mode oldnew")
    parser.add_argument("--out", default=None, help="Override output report path")
    parser.add_argument("--format", choices=["md", "json"], default="md",
                         help="--mode current only: 'md' (default, existing report) or "
                              "'json' (machine-readable single-language dataset for the "
                              "Haiku classification pass; requires --lang)")
    parser.add_argument("--lang", default="default", choices=LANGS,
                         help="--format json only: which language's changed lines to emit")
    args = parser.parse_args()

    if args.mode == "current":
        if not os.path.isdir(args.vanilla_content):
            print(f"ERROR: vanilla content dir not found: {args.vanilla_content}", file=sys.stderr)
            return 1
        with open(BASELINE_PATH, encoding="utf-8") as f:
            baseline = f.read().strip()

        reports = run_current_mode(args.vanilla_content)
        print_summary(reports)

        if args.format == "json":
            records, vanilla_missing = render_json_dataset(reports, args.lang)
            out_path = args.out or os.path.join(
                REPORTS_DIR, f"vanilla-diff-{baseline}-{args.lang}.json")
            missing_path = os.path.join(
                REPORTS_DIR, f"vanilla-diff-{baseline}-{args.lang}-vanilla-missing.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
                f.write("\n")
            with open(missing_path, "w", encoding="utf-8") as f:
                json.dump(vanilla_missing, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"\nJSON dataset ({len(records)} lines) written to {out_path}")
            print(f"VANILLA-MISSING ({len(vanilla_missing)} records) written to {missing_path}")
            return 0

        md = render_current_report(reports, baseline)
        out_path = args.out or os.path.join(REPORTS_DIR, f"vanilla-diff-{baseline}.md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\nReport written to {out_path}")
        return 0

    # oldnew
    if not args.old_content or not args.new_content:
        print("ERROR: --mode oldnew requires --old-content and --new-content", file=sys.stderr)
        return 1
    if not os.path.isdir(args.old_content) or not os.path.isdir(args.new_content):
        print("ERROR: --old-content / --new-content must be existing directories", file=sys.stderr)
        return 1

    results = run_oldnew_mode(args.old_content, args.new_content)
    changed = [r for r in results if r.status == "changed"]
    missing_old = [r for r in results if r.status == "missing-old"]
    missing_new = [r for r in results if r.status == "missing-new"]
    in_sync = [r for r in results if r.status == "in-sync"]

    print("\n=== oldnew mode summary ===")
    print(f"  in-sync: {len(in_sync)}")
    print(f"  changed: {len(changed)}")
    print(f"  missing-old: {len(missing_old)}")
    print(f"  missing-new: {len(missing_new)}")
    for r in sorted(changed, key=lambda r: (r.line_key, r.entry_key, r.lang)):
        print(f"  CHANGED {r.line_key} entry={r.entry_key} [{r.lang}]")
        for seg in r.segments:
            marker = "U" if seg.label == "likely-upstream" else "I"
            print(f"    [{marker}] {seg.old_text!r} -> {seg.new_text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
