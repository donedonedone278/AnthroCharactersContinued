#!/usr/bin/env python3
"""Re-sweep triage: cross-reference every review finding against the (now-fixed)
coverage index, to surface findings whose referenced line is ALREADY edited by
the mod -- i.e. candidate false positives from the coverage-detector blind spot.

Output: a markdown worklist grouping findings by coverage status, with the
covering variant labels + resolved edit text inline, so a reviewer can judge
each one (already-fixed -> REJECT vs partial-gap -> keep) without manual lookup.

Read-only: does NOT modify any review report. Writes one worklist file.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from review_inventory import (  # noqa: E402
    build_coverage_index, load_json, I18N_DIR, REPO_ROOT,
)

REPORTS_DIR = os.path.join(REPO_ROOT, "claude-documentation", "reports")
OUT_PATH = os.path.join(REPORTS_DIR, "resweep-coverage-triage.md")

# A finding header: "#### [SEVERITY] ID · <ref...>"
HEADER_RE = re.compile(r"^####\s*\[([^\]]+)\]\s*([A-Za-z0-9-]+)\s*·\s*(.+?)\s*$")
DECISION_RE = re.compile(r"^-\s*DECISION:\s*(.*)$")


_ABS_CAT = ("data/", "festival/", "strings/", "dialogue/", "event/")


def _remap_key(key: str) -> str:
    """Apply the two enumerator->mod key realignments coverage_line_key() does:
    festival/<f>/<e> -> data/<f>/<e>; data/MoviesReactions/<e> ->
    strings/MovieReactions/<e>."""
    if key.startswith("festival/"):
        key = "data/" + key[len("festival/"):]
    if key.startswith("data/MoviesReactions/"):
        key = "strings/MovieReactions/" + key[len("data/MoviesReactions/"):]
    return key


def finding_ref_to_index_keys(ref: str) -> list[str]:
    """Convert a finding's line reference into ALL coverage_index keys it touches,
    or [] if it isn't a data/festival ref we map.

    Findings use enumerator-form refs, and many list SEVERAL entries joined by
    " + " or ", " (e.g. "data/EngagementDialogue/Maru0 + Maru1",
    "festival/fall27/Jodi_y2 + Sam_y2", "data/SecretNotes/2 + /5",
    "data/mail/elliottLetter1-6 (titles)"). Each sub-entry inherits the leading
    "<cat>/<subject>/" prefix of the first piece unless it is itself an absolute
    "<cat>/..." key. Numeric ranges ("letter1-6") expand. Returns one index key
    per entry so the caller can report full vs partial coverage.
    """
    core = ref.split(" · ")[0].strip()
    core = re.sub(r"\s*\(.*?\)\s*$", "", core).strip()
    if not core.startswith(("data/", "festival/")):
        return []  # dialogue/event/strings/marriage first-piece -- out of scope
    pieces = re.split(r"\s*(?:\+|,)\s*", core)
    keys: list[str] = []
    prefix = ""  # running "<cat>/<subject>/" inherited by bare entries
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if piece.startswith(_ABS_CAT):
            # absolute key: its "<cat>/<subject>/" becomes the running prefix
            segs = piece.split("/")
            prefix = "/".join(segs[:2]) + "/"
            entry = "/".join(segs[2:])
            base = piece
        else:
            entry = piece.lstrip("/")
            base = prefix + entry if prefix else entry
        # expand a trailing numeric range on the entry, e.g. elliottLetter1-6
        m = re.match(r"^(.*?)(\d+)[–\-](\d+)$", entry)
        if m and prefix:
            stem, lo, hi = m.group(1), int(m.group(2)), int(m.group(3))
            for n in range(lo, hi + 1):
                keys.append(_remap_key(prefix + f"{stem}{n}"))
            continue
        keys.append(_remap_key(base))
    # de-dup, drop wildcard/unresolvable pieces (contain '*')
    out, seen = [], set()
    for k in keys:
        if "*" in k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def finding_variant(ref: str) -> str | None:
    """Pull the variant the finding targets, if it states one after ' · '."""
    parts = ref.split(" · ")
    if len(parts) < 2:
        return None
    v = parts[-1].strip().lstrip("@")
    return v or None


def parse_findings(path: str) -> list[dict]:
    out = []
    cur = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = HEADER_RE.match(line)
            if m:
                if cur:
                    out.append(cur)
                sev, fid, ref = m.group(1), m.group(2), m.group(3)
                cur = {"sev": sev, "id": fid, "ref": ref, "decision": None,
                       "report": os.path.basename(path)}
                continue
            if cur:
                md = DECISION_RE.match(line)
                if md and cur["decision"] is None:
                    cur["decision"] = md.group(1).strip()
    if cur:
        out.append(cur)
    return out


def cov_for(cov: dict, key: str) -> list:
    """Coverage for one key, with the Quests/NPCGiftTastes parent-key fallback
    (mod edits the whole tuple under data/<subj>/<id>; refs cite sub-fields)."""
    v = cov.get(key)
    if v:
        return v
    parts = key.split("/")
    if len(parts) > 3 and parts[0] == "data" and parts[1] in ("Quests", "NPCGiftTastes"):
        return cov.get("/".join(parts[:3]), [])
    return []


def main() -> int:
    default_translations = load_json(os.path.join(I18N_DIR, "default.json")) or {}
    cov = build_coverage_index(default_translations)

    findings = []
    for fn in sorted(os.listdir(REPORTS_DIR)):
        if fn.startswith("review-") and fn.endswith(".md") and fn != "review-INDEX.md":
            findings += parse_findings(os.path.join(REPORTS_DIR, fn))

    covered, partial, uncovered, skipped = [], [], [], []
    for fnd in findings:
        keys = finding_ref_to_index_keys(fnd["ref"])
        if not keys:
            skipped.append(fnd)
            continue
        per_key = [(k, cov_for(cov, k)) for k in keys]
        n_cov = sum(1 for _, v in per_key if v)
        fnd["index_keys"] = keys
        fnd["target_variant"] = finding_variant(fnd["ref"])
        fnd["per_key"] = per_key
        fnd["coverage"] = [v for _, vs in per_key for v in vs]
        if n_cov == len(keys):
            covered.append(fnd)
        elif n_cov > 0:
            partial.append(fnd)
        else:
            uncovered.append(fnd)

    lines = ["# Re-sweep coverage triage", "",
             f"Findings parsed: {len(findings)}  ·  "
             f"data/festival refs: {len(covered)+len(partial)+len(uncovered)}  ·  "
             f"fully-COVERED: **{len(covered)}**  ·  PARTIAL: {len(partial)}  ·  "
             f"still-uncovered: {len(uncovered)}  ·  "
             f"non-data refs (skipped): {len(skipped)}", "",
             "Multi-entry refs (joined by ' + ' / ', ', or numeric ranges like "
             "'letter1-6') are split and each entry checked; a finding is PARTIAL "
             "when some entries are covered and some not.", "",
             "Judge each covered/partial: claim fully satisfied by an existing "
             "variant -> **REJECT (already fixed)**; a different swap/flavor/year "
             "variant or an uncovered sub-entry -> **keep**. Don't auto-trust "
             "'covered' -- read the covering text.", ""]

    def render(f, show_per_key=False):
        tv = f["target_variant"] or "(unspecified)"
        lines.append(f"- **[{f['sev']}] {f['id']}** · `{f['ref']}`")
        lines.append(f"  - current DECISION: `{f['decision']}`  ·  "
                     f"finding targets variant: `{tv}`")
        if show_per_key:
            for k, vs in f["per_key"]:
                labs = sorted({v.variant_label or "(base)" for v in vs})
                lines.append(f"  - {'✓' if vs else '✗'} `{k}` "
                             f"{('['+','.join(labs)+']') if vs else '(uncovered)'}")
        labels = sorted({(v.variant_label or "(base)") for v in f["coverage"]})
        if labels:
            lines.append(f"  - covering variants: {', '.join(labels)}")
        for v in sorted(f["coverage"], key=lambda v: (v.variant_label or "")):
            txt = (v.edit_text or "").replace("\n", " ")
            if len(txt) > 240:
                txt = txt[:240] + "…"
            lines.append(f"    - `{v.variant_label or '(base)'}`: {txt}")
        lines.append("")

    lines.append("## FULLY-COVERED findings (candidate false positives)\n")
    by_report: dict[str, list[dict]] = {}
    for f in covered:
        by_report.setdefault(f["report"], []).append(f)
    for report in sorted(by_report):
        lines.append(f"### {report}\n")
        for f in by_report[report]:
            render(f)
    lines.append("")

    lines.append("## PARTIALLY-COVERED findings (some entries covered, some not)\n")
    for f in sorted(partial, key=lambda f: (f["report"], f["id"])):
        render(f, show_per_key=True)
    lines.append("")

    lines.append("## Still-uncovered data/festival findings (NOT false positives)\n")
    for f in sorted(uncovered, key=lambda f: (f["report"], f["id"])):
        lines.append(f"- [{f['sev']}] {f['id']} · `{f['ref']}` "
                     f"(index `{', '.join(f['index_keys'])}`) · DECISION `{f['decision']}`")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Findings: {len(findings)} | fully-covered: {len(covered)} | "
          f"partial: {len(partial)} | uncovered: {len(uncovered)} | "
          f"skipped(non-data): {len(skipped)}")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
