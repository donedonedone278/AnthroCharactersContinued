#!/usr/bin/env python3
"""
genkeys.py - the rewritten i18n key generator for AnthroCharactersContinued.

Replaces ~/repos/HelperScripts/translation_prep.py going forward. Emits the
NEW readable key scheme (see tools/i18n/keyscheme.py) instead of the old
dot-joined scheme.

Usage:
    python3 tools/i18n/genkeys.py [--check]

Behavior:
  1. Walks assets/**/*.json (skipping i18n/, manifest.json) looking for
     EditData `Changes`.
  2. For every translatable Entries value (skipping blacklisted entry names,
     and values that already contain "i18n" or "InternalAssetKey" -- i.e.
     this is idempotent: once a value has been converted to
     "{{i18n:...}}", running again is a no-op), computes the new key via
     keyscheme.new_key_for_entry, rewrites the Entries value in place to the
     "{{i18n:KEY |default={{i18n:BASEKEY ...}} ...}}" form (omitting the
     |default= wrapper entirely for base/no-variant entries, since they have
     no fallback target), and stages the literal text into i18n/default.json
     (without clobbering an already-translated/manually-edited value).
  3. Also handles `ConfigSchema` / `DynamicTokens` like the old script, but
     since config.*/token.* keys are already in the new-enough scheme and
     out of scope for this migration, this script leaves content.json
     completely untouched -- only assets/**/*.json + i18n/default.json are
     written.

This script is idempotent: once assets/**/*.json have been migrated (every
translatable value already reads "{{i18n:...}}"), running it again makes no
changes to either assets/**/*.json or i18n/default.json.

--check runs in dry-run mode: reports what WOULD change without writing
anything, and exits non-zero if anything would change (useful as the
"generator idempotence" verification check).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyscheme import (  # noqa: E402
    BLACKLISTED_ENTRIES,
    find_tokens,
    new_key_for_entry,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
DEFAULT_I18N_PATH = os.path.join(REPO_ROOT, "i18n", "default.json")

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


def build_i18n_value(new_key: str, base_key: str | None, tokens: list[str]) -> str:
    tok_string = "".join(f" |{t}={{{{{t}}}}}" for t in tokens)
    if base_key is None:
        return "{{i18n:" + new_key + tok_string + "}}"
    inner = "{{i18n:" + base_key + tok_string + "}}"
    return "{{i18n:" + new_key + " |default=" + inner + tok_string + "}}"


def process_file(path: str, default_translations: dict, dry_run: bool) -> tuple[bool, int]:
    """Returns (changed, num_entries_converted)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    changed = False
    converted = 0
    changes = data.get("Changes", [])
    for change in changes:
        if change.get("Action") != "EditData":
            continue
        entries = change.get("Entries", {})
        if not entries:
            continue
        new_entries = dict(entries)
        for key, value in entries.items():
            if key in BLACKLISTED_ENTRIES:
                continue
            if "i18n" in value or "InternalAssetKey" in value:
                continue  # already converted -- idempotent no-op
            new_parts = new_key_for_entry(change, path, key)
            new_key = new_parts.key
            base_key = new_parts.base_key.key if new_parts.variant else None
            tokens = find_tokens(value)
            new_value = build_i18n_value(new_key, base_key, tokens)
            new_entries[key] = new_value
            if new_key not in default_translations:
                default_translations[new_key] = value
            changed = True
            converted += 1
        change["Entries"] = new_entries

    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return changed, converted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run: report what would change, write nothing, exit 1 if anything would change.",
    )
    args = parser.parse_args()

    files = [f for f in get_all_jsons(ASSETS_DIR) if not is_blacklisted_file(f)]

    with open(DEFAULT_I18N_PATH, encoding="utf-8") as f:
        default_translations = json.load(f)
    original_default_keys = set(default_translations)

    any_changed = False
    total_converted = 0
    changed_files = []
    for path in files:
        changed, converted = process_file(path, default_translations, dry_run=args.check)
        if changed:
            any_changed = True
            total_converted += converted
            changed_files.append((path, converted))

    new_default_keys = set(default_translations) - original_default_keys

    if args.check:
        if any_changed:
            print(f"genkeys --check: NOT idempotent. {len(changed_files)} file(s) would change, "
                  f"{total_converted} entries would be (re)converted, "
                  f"{len(new_default_keys)} new default.json keys would be added.")
            for path, converted in changed_files:
                print(f"  {os.path.relpath(path, REPO_ROOT)}: {converted} entries")
            return 1
        print("genkeys --check: idempotent (no changes).")
        return 0

    if any_changed and new_default_keys:
        with open(DEFAULT_I18N_PATH, "w", encoding="utf-8") as f:
            json.dump(default_translations, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"genkeys: converted {total_converted} entries across {len(changed_files)} file(s); "
          f"{len(new_default_keys)} new default.json keys added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
