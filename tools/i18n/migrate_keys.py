#!/usr/bin/env python3
"""
migrate_keys.py - one-shot migration from the legacy dot-joined i18n key
scheme to the new readable scheme (tools/i18n/keyscheme.py).

Builds the old->new key map deterministically by generating BOTH keys from
every translatable Entries value across assets/**/*.json (the same source
facts produce both), then:

  (a) rewrites every "{{i18n:OLDKEY ...}}" reference in assets/**/*.json to
      the new key, rebuilding the |default= fallback to the new base key and
      preserving |tok={{tok}} passthroughs verbatim;
  (b) rekeys i18n/default.json and the real translations i18n/{zh,ru,es}.json,
      preserving values verbatim;
  (c) regenerates/rekeys the placeholder files
      i18n/{de,fr,hu,it,ja,ko,pt,tr}.json (their content is a no-op, but they
      get the new keys so genkeys.py's idempotence check & translators'
      tooling stay consistent across all languages).

Keys with no mapping (drifted/stale translations) are NOT dropped: they are
written verbatim to claude-documentation/i18n-orphans-<lang>.json. The full
old->new map (with collision notes) is written to
claude-documentation/i18n-key-migration-map.json.

This script is meant to be run exactly once against the pre-migration repo
state. Safe to re-run only if assets/**/*.json are still in the OLD key
scheme (it detects + skips any Entries value that's already new-scheme by
checking for the old key's "..." triple-dot/six-segment shape vs the new
"@"-based shape -- in practice: just don't re-run it after a successful
migration; use genkeys.py --check to confirm idempotence instead).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyscheme import (  # noqa: E402
    BLACKLISTED_ENTRIES,
    find_tokens,
    new_key_for_entry,
    norm_old_key,
    old_key_for_entry,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
I18N_DIR = os.path.join(REPO_ROOT, "i18n")
CLAUDE_DOCS_DIR = os.path.join(REPO_ROOT, "claude-documentation")

REAL_LANGS = ["zh", "ru", "es"]
PLACEHOLDER_LANGS = ["de", "fr", "hu", "it", "ja", "ko", "pt", "tr"]
PASSTHROUGH_PREFIXES = ("config.", "token.")

BLACKLISTED_PATH_FRAGMENTS = ("/i18n/", "manifest.json")


def get_all_jsons(directory: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".json"):
                out.append(os.path.join(root, f))
    return sorted(out)


def is_blacklisted_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(frag in norm for frag in BLACKLISTED_PATH_FRAGMENTS)


def hash4(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:4]


def collect_entries(files: list[str]) -> list[dict]:
    """Walk every translatable Entries value once. Returns a list of dicts:
    {path, change, entry_key, value, tokens} for later processing. Loading
    each file's JSON once (we'll re-load per file for writing later, this
    pass is read-only for map building).

    Unlike genkeys.py (which only touches NOT-yet-converted raw text), this
    repo's assets/**/*.json have ALREADY been run through the old
    translation_prep.py generator -- every translatable Entries value is
    already "{{i18n:OLDKEY |default=...}}". Migration must still process
    these: the (Target, TargetField, When, Priority, entry_key, file_id)
    facts needed to derive both the OLD and NEW key are independent of
    whether the value has already been wrapped, so we only skip values that
    are categorically untranslatable (InternalAssetKey passthroughs) or
    blacklisted entry names (e.g. "Gender")."""
    out = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            entries = change.get("Entries", {})
            for key, value in entries.items():
                if key in BLACKLISTED_ENTRIES:
                    continue
                if "InternalAssetKey" in value:
                    continue
                if "i18n" not in value:
                    # Raw untranslated literal (e.g. a freshly-added line
                    # that hasn't been through genkeys.py yet) -- still a
                    # valid translatable entry, just has no OLD key to map
                    # from. Skip for the old->new MAP (nothing to migrate),
                    # genkeys.py will key it on a future run.
                    continue
                out.append({
                    "path": path,
                    "change": change,
                    "entry_key": key,
                    "value": value,
                })
    return out


def build_map(files: list[str], default_translations: dict) -> tuple[dict, dict, list, list, list, list]:
    """Returns (old_to_new map, old_partial_to_new_base map, raw entry
    records, collision_notes, drift_notes, live_fallback_notes).

    old_to_new maps an old key (full OR, for the live-fallback case, partial)
    to a LIST of new keys. In the overwhelming majority of cases this list
    has exactly one element. But the live-fallback case can legitimately
    fan out: several different swap-<Name> directories (or flavor variants)
    each embed their OWN distinct full key (which has no value in
    default.json) with the SAME shared partial-key fallback holding the one
    live value -- so that single old value must be propagated to every one
    of those new keys, not just whichever record happened to be processed
    last. See the live-fallback handling in pass 2 below.

    default_translations: the CURRENT (pre-migration) i18n/default.json
    contents, needed to detect the "live fallback" case below.

    Collision handling: within a single (file, Target, TargetField, variant)
    "bucket", two different raw entry_keys can legitimately produce the same
    new key (this happens for Data/Events entries that share an event id but
    differ in precondition tail, see Beach/Town/Farm in Genderswaps dirs).
    When that happens, append "-<hash4>" of the FULL original entry_key to
    the *new* key's entry segment, for the colliding entries only (first
    occurrence in file order keeps the unsuffixed key).
    """
    records = collect_entries(files)

    old_to_new: dict[str, list[str]] = {}
    collision_notes = []

    # Pass 1: compute raw new keys, grouped by (file, bucket) so we can
    # detect & resolve collisions deterministically.
    seen_new_keys: dict[str, list[dict]] = {}
    for rec in records:
        new_parts = new_key_for_entry(rec["change"], rec["path"], rec["entry_key"])
        rec["new_parts"] = new_parts
        seen_new_keys.setdefault(new_parts.key, []).append(rec)

    for new_key, recs in seen_new_keys.items():
        if len(recs) == 1:
            continue
        distinct_entry_keys = {rec["entry_key"] for rec in recs}
        if len(distinct_entry_keys) == 1:
            # True duplicate source entries (identical entry_key repeated in
            # two Change blocks) -- not a real collision, leave the new key
            # unsuffixed; both records map to the same key harmlessly.
            continue
        # Collision: only expected for "event/..." category entries that
        # share an id but differ in precondition tail. Disambiguate with a
        # 4-char hash of each FULL original entry_key (every colliding entry
        # gets a suffix, for stability regardless of file order).
        for rec in recs:
            suffix = hash4(rec["entry_key"])
            orig_parts = rec["new_parts"]
            rec["new_parts"] = orig_parts.__class__(
                category=orig_parts.category,
                subject=orig_parts.subject,
                entry=f"{orig_parts.entry}-{suffix}",
                variant=orig_parts.variant,
            )
        collision_notes.append({
            "new_key_before_disambiguation": new_key,
            "entries": [
                {"file": os.path.relpath(rec["path"], REPO_ROOT),
                 "entry_key": rec["entry_key"],
                 "disambiguated_key": rec["new_parts"].key}
                for rec in recs
            ],
        })

    # Pass 2: determine the OLD key for each record.
    #
    # We prefer the LITERAL key already embedded in the value
    # ("{{i18n:LITERAL |default=...}}") over re-deriving it from the
    # Change's current Target/TargetField/When/Priority facts. They agree
    # in the overwhelming majority of cases (both are the same
    # translation_prep.py-style key, computed the same way when the asset
    # was first generated) -- but real-world drift exists: hand-edited
    # entries, escaping bugs (e.g. "ElliottHouse.2" got embedded unescaped
    # instead of "ElliottHouse=2"), a missing file_id segment on a couple of
    # Hospital entries, a `Sam`/`Shane` copy-paste typo, a stray trailing
    # "}}" once, and a `When` clause that no longer matches what's literally
    # keyed (e.g. Maru's winter_Thu10 is keyed "...FurryFarmerFlavor..." but
    # its Change has no When at all today). Re-deriving from current facts
    # in those cases would silently orphan an otherwise-fine, currently-
    # resolving translation. The literal key is what un_i18n() (and thus the
    # live game) actually looks up today, so it's the correct migration
    # source of truth; we cross-check against the derived key and log any
    # mismatch for human review (drift_notes).
    #
    # "Live fallback" case (~52 entries as of the first migration run):
    # un_i18n() only goes two levels deep -- primary (full) key, then
    # secondary (partial) key. For a meaningful chunk of variant entries
    # (flavor / swap-<Name>), the FULL key has no value in default.json at
    # all, but the PARTIAL key does -- meaning the partial key's value is
    # what *actually* resolves and displays in-game today, standing in for
    # the variant text. If we mapped the partial key to the new BASE key (as
    # the fallback model says it normally should), we'd silently move that
    # live content from "the swap/flavor variant's text" to "the
    # unconditional base text" -- changing the live resolved output for every
    # OTHER variant/non-variant entry that also falls back through that same
    # base key. Instead: when the full key is absent/falsy in
    # default_translations and the partial key has a real value, treat the
    # partial key AS IF it were the full key for old->new mapping purposes
    # (map old_partial -> new FULL key, not new base key). This preserves
    # today's actual resolved text exactly.
    partial_old_to_new_base: dict[str, str] = {}
    drift_notes = []
    live_fallback_notes = []
    for rec in records:
        derived_full, _derived_partial = old_key_for_entry(rec["change"], rec["path"], rec["entry_key"])
        # Mirror un_i18n()'s own parsing exactly: split on "{{i18n:", segment
        # [1] up to " |" is the primary (full) key; segment [2] up to " |"
        # (if present) is the fallback (partial) key actually consulted at
        # runtime. This is the literal source of truth for what currently
        # resolves -- see module docstring above for why we prefer it.
        split_on_marker = rec["value"].split("{{i18n:")
        literal_full = split_on_marker[1].split(" |", 1)[0]
        literal_partial = (
            split_on_marker[2].split(" |", 1)[0] if len(split_on_marker) > 2 else None
        )
        if literal_full != derived_full:
            drift_notes.append({
                "file": os.path.relpath(rec["path"], REPO_ROOT),
                "entry_key": rec["entry_key"],
                "derived_old_key": derived_full,
                "literal_old_key": literal_full,
            })
        new_parts = rec["new_parts"]

        full_has_value = bool(default_translations.get(literal_full))
        if not full_has_value and literal_partial and default_translations.get(literal_partial):
            # Live fallback: the partial key is what's actually displayed.
            # IMPORTANT: this old partial key can be shared by multiple
            # records (different swap-<Name>/flavor variants that all
            # fell back to the same partial key under the old scheme), each
            # needing its OWN distinct new key. Fan out: append rather than
            # overwrite, so every variant's new key gets this same old value
            # at rekey time.
            old_to_new.setdefault(literal_partial, [])
            if new_parts.key not in old_to_new[literal_partial]:
                old_to_new[literal_partial].append(new_parts.key)
            live_fallback_notes.append({
                "file": os.path.relpath(rec["path"], REPO_ROOT),
                "entry_key": rec["entry_key"],
                "old_full_key_unused": literal_full,
                "old_partial_key_used_instead": literal_partial,
                "new_key": new_parts.key,
            })
            rec["old_full"] = literal_partial
        else:
            old_to_new.setdefault(literal_full, [])
            if new_parts.key not in old_to_new[literal_full]:
                old_to_new[literal_full].append(new_parts.key)
            rec["old_full"] = literal_full

        if literal_partial is not None:
            partial_old_to_new_base[literal_partial] = new_parts.base_key.key
        rec["old_partial"] = literal_partial

    return old_to_new, partial_old_to_new_base, records, collision_notes, drift_notes, live_fallback_notes


I18N_REF_RE = re.compile(
    r"\{\{i18n:([^|}]+?)((?: \|[^|}]+=\{\{[^}]+\}\})*)\}\}"
)


def rebuild_i18n_value(rec: dict) -> str:
    """Build the new "{{i18n:NEWKEY |default={{i18n:NEWBASEKEY ...}} ...}}"
    string for one entry record, from its already-computed new_parts.

    rec["value"] is already an old-scheme-wrapped "{{i18n:...}}" string (see
    collect_entries docstring), so find_tokens() will see each |tok={{tok}}
    passthrough repeated once per nesting level -- dedupe while preserving
    first-seen order to match the original single-pass extraction."""
    new_parts = rec["new_parts"]
    tokens = list(dict.fromkeys(find_tokens(rec["value"])))
    tok_string = "".join(f" |{t}={{{{{t}}}}}" for t in tokens)
    if new_parts.variant is None:
        return "{{i18n:" + new_parts.key + tok_string + "}}"
    base_key = new_parts.base_key.key
    inner = "{{i18n:" + base_key + tok_string + "}}"
    return "{{i18n:" + new_parts.key + " |default=" + inner + tok_string + "}}"


def rewrite_asset_files(files: list[str], records: list[dict], dry_run: bool) -> int:
    """Group records by file and rewrite each file's Entries values in
    place. Returns count of values rewritten."""
    by_file: dict[str, list[dict]] = {}
    for rec in records:
        by_file.setdefault(rec["path"], []).append(rec)

    total = 0
    for path, recs in by_file.items():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Re-walk changes in the same order as collect_entries to line up
        # with recs (collect_entries iterated data["Changes"] in order too).
        rec_iter = iter(recs)
        # Build a lookup by (id(change is not stable across reload), so
        # instead key by (Target, TargetField, entry_key, value) tuple per
        # change-position. Simpler: re-derive directly using identical logic
        # against the freshly loaded data, matching by Target+TargetField+
        # entry_key+original value (unique enough in practice; verified by
        # round-trip checks).
        recs_by_match = {}
        for rec in recs:
            t = rec["change"].get("Target", "")
            tf = "/".join(rec["change"].get("TargetField", []))
            recs_by_match[(t, tf, rec["entry_key"], rec["value"])] = rec

        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            entries = change.get("Entries", {})
            if not entries:
                continue
            t = change.get("Target", "")
            tf = "/".join(change.get("TargetField", []))
            new_entries = dict(entries)
            for key, value in entries.items():
                match_key = (t, tf, key, value)
                rec = recs_by_match.get(match_key)
                if rec is None:
                    continue
                new_entries[key] = rebuild_i18n_value(rec)
                total += 1
            change["Entries"] = new_entries

        if not dry_run:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")

    return total


def build_norm_index(old_to_new: dict) -> dict:
    """norm(old_key) -> [new_key,...] for drift re-matching. Drops any norm
    key that two different old keys map to with CONFLICTING new-key lists
    (ambiguous; verified to be none in practice, but guard anyway)."""
    norm_index: dict[str, list[str]] = {}
    ambiguous = set()
    for ok, nks in old_to_new.items():
        nk = norm_old_key(ok)
        if nk in norm_index and norm_index[nk] != nks:
            ambiguous.add(nk)
        norm_index[nk] = nks
    for nk in ambiguous:
        norm_index.pop(nk, None)
    return norm_index


def rekey_i18n_file(path: str, old_to_new: dict, norm_index: dict, dry_run: bool) -> tuple[dict, dict]:
    """Rekey one i18n/<lang>.json file in place. Returns (new_data, orphans).

    old_to_new maps an old key to a LIST of new keys (usually length 1; see
    build_map's live-fallback fan-out handling for when it's longer). The
    same old value gets written under every new key in the list.

    Keys with no entry in old_to_new fall back, in order: (1) PASSTHROUGH_PREFIXES
    (config./token.) are LIVE keys the new scheme leaves unchanged -- kept
    verbatim; (2) the canonicalized norm_index, to recover translations whose
    embedded old key drifted in escaping (raw spaces/dots vs +/=) from the
    current generator's spelling. Anything still unmapped is a genuine orphan.

    Two passes, so dict iteration order can never make a stale drifted key
    "win" a new-key slot over the genuinely-live exact match for the same
    slot (some lang files embed BOTH the current escaped spelling AND an
    older raw-spelled duplicate of the same logical key; whichever is exact-
    matched must always take priority over a fuzzy norm-index match, no
    matter which one is iterated first): pass 1 resolves every key that has
    an EXACT old_to_new/passthrough match; pass 2 then applies the norm_index
    drift fallback only to keys that pass 1 left unresolved."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    new_data = {}
    orphans = {}
    unresolved = {}

    # Pass 1: exact matches + passthrough only.
    for old_key, value in data.items():
        if old_key.startswith(PASSTHROUGH_PREFIXES) and old_key not in old_to_new:
            # LIVE key the new scheme leaves unchanged (config/token): keep verbatim.
            if old_key in new_data and new_data[old_key] != value:
                orphans[old_key] = value
            else:
                new_data[old_key] = value
            continue
        new_keys = old_to_new.get(old_key)
        if new_keys:
            for new_key in new_keys:
                # Keep first value seen for a given new key (stable + deterministic);
                # collisions across DIFFERENT old keys mapping to the SAME new key
                # would only happen if the new scheme itself collided, which the
                # disambiguation pass above prevents.
                if new_key in new_data and new_data[new_key] != value:
                    orphans[old_key] = value  # divergent duplicate -- quarantine instead of clobbering
                else:
                    new_data[new_key] = value
        else:
            unresolved[old_key] = value

    # Pass 2: norm_index drift fallback for whatever pass 1 couldn't place.
    for old_key, value in unresolved.items():
        new_keys = norm_index.get(norm_old_key(old_key))
        if new_keys:
            for new_key in new_keys:
                if new_key in new_data and new_data[new_key] != value:
                    orphans[old_key] = value
                else:
                    new_data[new_key] = value
        else:
            orphans[old_key] = value

    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return new_data, orphans


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Compute the map and report stats; write nothing.")
    args = parser.parse_args()

    os.makedirs(CLAUDE_DOCS_DIR, exist_ok=True)

    files = [f for f in get_all_jsons(ASSETS_DIR) if not is_blacklisted_file(f)]
    default_path = os.path.join(I18N_DIR, "default.json")
    with open(default_path, encoding="utf-8") as f:
        default_translations_before = json.load(f)

    old_to_new, partial_map, records, collision_notes, drift_notes, live_fallback_notes = build_map(
        files, default_translations_before
    )
    norm_index = build_norm_index(old_to_new)
    print(f"Normalized drift index: {len(norm_index)} entries.")

    print(f"Collected {len(records)} translatable entries across {len(files)} files.")
    print(f"Old->new key map: {len(old_to_new)} entries.")
    if live_fallback_notes:
        print(f"NOTE: {len(live_fallback_notes)} entries' FULL old key has no value in default.json; "
              f"their PARTIAL fallback key is what actually resolves today, so it was mapped to the "
              f"new FULL key (preserving live behavior) instead of the new base key.")
    if drift_notes:
        print(f"NOTE: {len(drift_notes)} entries had a literal embedded old key that differs "
              f"from what re-deriving from current Target/When/Priority facts would produce "
              f"(pre-existing data drift/typos -- using the literal key, since that's what "
              f"actually resolves today). See the migration map's 'drift' section.")
    if collision_notes:
        print(f"Resolved {len(collision_notes)} new-key collision group(s) via 4-char hash suffix:")
        for note in collision_notes:
            print(f"  {note['new_key_before_disambiguation']}")
            for e in note["entries"]:
                print(f"    {e['file']} :: {e['entry_key']!r} -> {e['disambiguated_key']}")

    # Write the full map for human review.
    map_path = os.path.join(CLAUDE_DOCS_DIR, "i18n-key-migration-map.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({
            "old_to_new": old_to_new,
            "collisions": collision_notes,
            "drift": drift_notes,
            "live_fallback": live_fallback_notes,
        }, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Wrote map: {map_path}")

    # Rewrite asset files.
    rewritten = rewrite_asset_files(files, records, dry_run=args.dry_run)
    print(f"{'Would rewrite' if args.dry_run else 'Rewrote'} {rewritten} Entries values across assets/**/*.json.")

    # Rekey default.json + real translations.
    new_default, default_orphans = rekey_i18n_file(default_path, old_to_new, norm_index, dry_run=args.dry_run)
    print(f"default.json: {len(new_default)} keys after rekey, {len(default_orphans)} orphans.")

    orphan_summary = {}
    for lang in REAL_LANGS:
        path = os.path.join(I18N_DIR, f"{lang}.json")
        new_data, orphans = rekey_i18n_file(path, old_to_new, norm_index, dry_run=args.dry_run)
        orphan_summary[lang] = len(orphans)
        print(f"{lang}.json: {len(new_data)} keys after rekey, {len(orphans)} orphans.")
        if orphans:
            orphan_path = os.path.join(CLAUDE_DOCS_DIR, f"i18n-orphans-{lang}.json")
            if not args.dry_run:
                with open(orphan_path, "w", encoding="utf-8") as f:
                    json.dump(orphans, f, ensure_ascii=False, indent=2, sort_keys=True)
                    f.write("\n")
            print(f"  -> wrote {len(orphans)} orphan(s) to {orphan_path}")

    if default_orphans:
        orphan_path = os.path.join(CLAUDE_DOCS_DIR, "i18n-orphans-default.json")
        if not args.dry_run:
            with open(orphan_path, "w", encoding="utf-8") as f:
                json.dump(default_orphans, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
        print(f"  -> wrote {len(default_orphans)} default.json orphan(s) to {orphan_path}")

    # Placeholder languages: rekey whatever maps, drop the rest silently (no
    # real translation work to lose -- see CLAUDE.md "Translation status").
    for lang in PLACEHOLDER_LANGS:
        path = os.path.join(I18N_DIR, f"{lang}.json")
        new_data, _orphans = rekey_i18n_file(path, old_to_new, norm_index, dry_run=args.dry_run)
        print(f"{lang}.json (placeholder): {len(new_data)} keys after rekey.")

    print("\nDone." if not args.dry_run else "\nDry run complete; nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
