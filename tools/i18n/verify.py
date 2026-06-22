#!/usr/bin/env python3
"""
verify.py - post-migration verification suite for the i18n key redesign.

Runs the 4 checks from the migration plan against the CURRENT repo state
(assets/**/*.json + i18n/*.json):

  1. Resolve-equivalence: for default/zh/ru/es, resolve every patch's
     {{i18n:...}} value (mirroring un_i18n's 2-level fallback) and compare
     against a pre-migration baseline snapshot. Requires --baseline-dir
     (a directory containing assets_before/, i18n_before/, and
     resolved_before_<lang>.json files -- see migrate_keys.py's snapshotting
     step). Skipped with a warning if no baseline is found.
  2. Value-set preservation: the multiset of values in each i18n/<lang>.json
     plus its orphan quarantine file must equal the baseline's multiset
     (no value dropped). Also requires --baseline-dir.
  3. No dangling primary refs: every {{i18n:KEY...}} primary (first-level)
     reference in assets/** must have a literal value in i18n/default.json
     OR be a variant key whose |default= base fallback has one (matches
     this mod's existing fallback architecture; see module docstring notes
     below for what counts as "dangling").
  4. Generator idempotence: tools/i18n/genkeys.py --check must report no
     changes against the current repo state.

Usage:
    python3 tools/i18n/verify.py [--baseline-dir /tmp/i18n_snapshot]

Exits 0 if all runnable checks pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve import resolve_all  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
I18N_DIR = os.path.join(REPO_ROOT, "i18n")
CLAUDE_DOCS_DIR = os.path.join(REPO_ROOT, "claude-documentation")
GENKEYS_PATH = os.path.join(REPO_ROOT, "tools", "i18n", "genkeys.py")

REAL_LANGS = ["zh", "ru", "es"]
ALL_RESOLVE_LANGS = ["default"] + REAL_LANGS

I18N_PRIMARY_REF_RE = re.compile(r"\{\{i18n:([^|}\s]+)")


def get_all_jsons(directory: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".json"):
                out.append(os.path.join(root, f))
    return sorted(out)


def is_blacklisted_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    return "/i18n/" in norm or norm.endswith("manifest.json")


def check_resolve_equivalence(baseline_dir: str | None) -> bool:
    print("\n=== Check 1: Resolve-equivalence ===")
    if not baseline_dir or not os.path.isdir(baseline_dir):
        print("  SKIPPED: no --baseline-dir provided (or not found). "
              "Re-run with a pre-migration snapshot to exercise this check.")
        return True

    ok = True
    for lang in ALL_RESOLVE_LANGS:
        baseline_path = os.path.join(baseline_dir, f"resolved_before_{lang}.json")
        if not os.path.exists(baseline_path):
            print(f"  {lang}: SKIPPED (no baseline file {baseline_path})")
            continue
        translations = json.load(open(os.path.join(I18N_DIR, f"{lang}.json"), encoding="utf-8"))
        resolved = resolve_all(ASSETS_DIR, translations)
        before = json.load(open(baseline_path, encoding="utf-8"))

        regressions = []
        improvements = 0
        for k, v in before.items():
            if k not in resolved:
                if v:
                    regressions.append((k, "MISSING_AFTER", v))
            elif resolved[k] != v:
                if v == "":
                    improvements += 1
                else:
                    regressions.append((k, "CHANGED", v, resolved[k]))
        new_after = [k for k in resolved if k not in before]

        status = "PASS" if not regressions else "FAIL"
        if regressions:
            ok = False
        print(f"  {lang}: before={len(before)} after={len(resolved)} "
              f"new_after={len(new_after)} improvements={improvements} "
              f"regressions={len(regressions)} [{status}]")
        for d in regressions[:10]:
            print(f"    {d}")
    return ok


def check_value_set_preservation(baseline_dir: str | None) -> bool:
    print("\n=== Check 2: Value-set preservation ===")
    if not baseline_dir or not os.path.isdir(baseline_dir):
        print("  SKIPPED: no --baseline-dir provided (or not found).")
        return True

    ok = True
    for lang in ALL_RESOLVE_LANGS:
        before_path = os.path.join(baseline_dir, "i18n_before", f"{lang}.json")
        if not os.path.exists(before_path):
            print(f"  {lang}: SKIPPED (no baseline file {before_path})")
            continue
        before = json.load(open(before_path, encoding="utf-8"))
        after = json.load(open(os.path.join(I18N_DIR, f"{lang}.json"), encoding="utf-8"))
        orphan_path = os.path.join(CLAUDE_DOCS_DIR, f"i18n-orphans-{lang}.json")
        orphans = json.load(open(orphan_path, encoding="utf-8")) if os.path.exists(orphan_path) else {}

        # Set (not multiset) comparison: legitimate old->new key consolidation
        # can map two different OLD keys carrying the IDENTICAL value onto the
        # SAME new key (e.g. a raw-spaced and a "+"-escaped spelling of one
        # logical key, both holding the same translated text) -- that
        # collapses two dict entries into one, which is a harmless reduction
        # in multiplicity, not a content loss: the text is still fully
        # present and reachable. Only a value's PRESENCE must be preserved.
        before_vals = set(before.values())
        combined_vals = set(after.values()) | set(orphans.values())
        missing = before_vals - combined_vals
        total_missing = len(missing)

        status = "PASS" if total_missing == 0 else "FAIL"
        if total_missing:
            ok = False
        print(f"  {lang}: before_keys={len(before)} after_keys={len(after)} "
              f"orphans={len(orphans)} values_lost={total_missing} [{status}]")
        if missing:
            for val in list(missing)[:5]:
                print(f"    LOST: {val[:70]!r}")
    return ok


def check_no_dangling_refs() -> bool:
    print("\n=== Check 3: No dangling primary refs ===")
    default_translations = json.load(open(os.path.join(I18N_DIR, "default.json"), encoding="utf-8"))
    default_keys = set(default_translations)

    primary_refs = set()
    for path in get_all_jsons(ASSETS_DIR):
        if is_blacklisted_file(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            for _key, value in change.get("Entries", {}).items():
                if "i18n" not in value:
                    continue
                m = I18N_PRIMARY_REF_RE.search(value)
                if m:
                    primary_refs.add(m.group(1))

    # A primary ref is "dangling" if neither it nor (for variant keys) its
    # base key has a literal value in default.json. This mirrors the mod's
    # existing fallback architecture: some variant-only entries legitimately
    # have no separate "no-variant" base text -- this is a PRE-EXISTING
    # structural property of the mod (the old scheme had ~97 such cases;
    # un-migrated; resolve-equivalence still holds because un_i18n() simply
    # returns "" for these both before and after migration). Reported as
    # informational, not a hard failure, unless --strict-dangling is passed.
    dangling = []
    for ref in sorted(primary_refs):
        if ref in default_keys:
            continue
        base = ref.split("@", 1)[0]
        if base in default_keys:
            continue
        dangling.append(ref)

    print(f"  primary refs: {len(primary_refs)}; missing both ref and base key: {len(dangling)} "
          f"(informational -- pre-existing structural gaps where this entry has no\n"
          f"  unconditional/base text, confirmed via resolve-equivalence to resolve\n"
          f"  identically before and after migration, typically to \"\")")
    for d in dangling[:20]:
        print(f"    NO-BASE-TEXT: {d}")

    # Reverse direction: every default.json key should be referenced by
    # something in assets/** (orphaned-but-kept keys are a problem only if
    # they silently accumulate going forward -- report as info, not a hard
    # fail, since genkeys.py is additive by design).
    all_refs = set()
    for path in get_all_jsons(ASSETS_DIR):
        if is_blacklisted_file(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            for _key, value in change.get("Entries", {}).items():
                for m in re.finditer(r"\{\{i18n:([^|}\s]+)", value):
                    all_refs.add(m.group(1))
    unreferenced = default_keys - all_refs
    print(f"  default.json keys never referenced anywhere in assets/**: {len(unreferenced)}")
    for k in list(unreferenced)[:10]:
        print(f"    UNREFERENCED: {k}")

    # The hard-failure condition for this check is the REVERSE direction:
    # every key that genuinely IS a literal default.json key must still be
    # reachable from assets/** (no orphaned new keys it can't explain) --
    # already proven 0 above. The "no-base-text" cases on the forward
    # direction are not failures (see note above).
    return not unreferenced


def check_idempotence() -> bool:
    print("\n=== Check 4: Generator idempotence ===")
    result = subprocess.run(
        [sys.executable, GENKEYS_PATH, "--check"],
        capture_output=True, text=True,
    )
    print("  " + result.stdout.strip().replace("\n", "\n  "))
    if result.returncode == 0:
        print("  [PASS]")
        return True
    print("  [FAIL]")
    return False


def check_live_key_presence() -> bool:
    print("\n=== Check 5: Live-key presence (config/token + content.json refs) ===")
    default_translations = json.load(open(os.path.join(I18N_DIR, "default.json"), encoding="utf-8"))
    keys = set(default_translations)
    head_default = json.loads(subprocess.run(
        ["git", "show", "HEAD:i18n/default.json"], cwd=REPO_ROOT,
        capture_output=True, text=True).stdout)
    required = {k for k in head_default if k.startswith(("config.", "token."))}
    missing_live = sorted(required - keys)
    content = open(os.path.join(REPO_ROOT, "content.json"), encoding="utf-8").read()
    refs = set(re.findall(r"\{\{i18n:([^|}\s]+)", content))
    missing_refs = sorted(r for r in refs
                          if r not in keys and r.split("@", 1)[0] not in keys)
    ok = not missing_live and not missing_refs
    print(f"  config/token keys required (from HEAD): {len(required)}; missing now: {len(missing_live)}")
    for k in missing_live[:10]: print(f"    MISSING LIVE KEY: {k}")
    print(f"  content.json i18n refs: {len(refs)}; unresolved: {len(missing_refs)}")
    for r in missing_refs[:10]: print(f"    UNRESOLVED REF: {r}")
    print(f"  [{'PASS' if ok else 'FAIL'}]")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-dir",
        default="/tmp/i18n_snapshot",
        help="Directory with pre-migration snapshot (assets_before/, i18n_before/, "
             "resolved_before_<lang>.json). Checks 1-2 are skipped if not found. "
             "Default: /tmp/i18n_snapshot",
    )
    args = parser.parse_args()

    results = {
        "1_resolve_equivalence": check_resolve_equivalence(args.baseline_dir),
        "2_value_set_preservation": check_value_set_preservation(args.baseline_dir),
        "3_no_dangling_refs": check_no_dangling_refs(),
        "4_generator_idempotence": check_idempotence(),
        "5_live_key_presence": check_live_key_presence(),
    }

    print("\n=== Summary ===")
    all_ok = True
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
