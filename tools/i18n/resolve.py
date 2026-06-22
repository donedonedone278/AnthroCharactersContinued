"""
Resolve-equivalence helpers: mirrors create_replacer.py's un_i18n() exactly,
plus a walker that resolves every translatable EditData Entries value across
assets/**/*.json for a given language. Used by verify.py to compare
before/after migration snapshots byte-for-byte.
"""
from __future__ import annotations

import json
import os


def un_i18n(i18n_str: str, translations: dict) -> str:
    """Faithful port of create_replacer.py's un_i18n(), but takes an
    already-loaded translations dict instead of a (base_dir, language) pair
    so it can be pointed at either a live i18n/<lang>.json or an in-memory
    snapshot.

    Mirrors the exact (slightly odd) 2-level-only lookup: split on
    "{{i18n:", take segment[1] as the primary key (up to " |"), look it up;
    if falsy, take segment[2] as the secondary/fallback key (up to " |"),
    look that up instead. Never recurses further, never resolves |tok=
    substitutions (matches the original's behavior before the separate
    formatter.format() token-substitution pass).
    """
    split1 = i18n_str.split("{{i18n:")
    if len(split1) < 2:
        return i18n_str
    key1 = split1[1].split(" |")[0]
    dialogue = translations.get(key1, "")
    if not dialogue:
        if len(split1) < 3:
            return dialogue
        key2 = split1[2].split(" |")[0]
        dialogue = translations.get(key2, "")
    return dialogue


def get_all_jsons(directory: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".json"):
                out.append(os.path.join(root, f))
    return sorted(out)


def resolve_all(assets_dir: str, translations: dict) -> dict[str, str]:
    """Walk every EditData change in assets_dir and resolve every Entries
    value through un_i18n(). Returns {(file, target, entry_key) repr -> resolved text}
    for values that look like i18n references; non-i18n values are skipped
    (they're not part of the resolve-equivalence contract -- e.g. Gender,
    InternalAssetKey)."""
    results: dict[str, str] = {}
    for path in get_all_jsons(assets_dir):
        norm = path.replace("\\", "/")
        if "/i18n/" in norm or norm.endswith("manifest.json"):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            target = change.get("Target", "")
            target_field = "/".join(change.get("TargetField", []))
            entries = change.get("Entries", {})
            for key, value in entries.items():
                if "i18n" not in value:
                    continue
                resolved = un_i18n(value, translations)
                ident = f"{os.path.relpath(path, assets_dir)}::{target}::{target_field}::{key}"
                results[ident] = resolved
    return results
