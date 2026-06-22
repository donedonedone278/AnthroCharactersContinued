"""
Shared key-scheme logic for the AnthroCharactersContinued i18n tooling.

This module knows how to derive BOTH the legacy (translation_prep.py-style)
i18n key and the new readable key scheme from the same source facts: a CP
EditData `Change` dict and the asset file path it came from.

New key grammar (see claude-documentation plan "Redesign the i18n key
scheme"):

    <category>/<subject>/<entry>[@<variant>]

category   - dialogue | event | name | data | strings  (config/token unchanged,
             and not handled by this module -- those keys are already clean
             and live in content.json, which this migration does not touch)
subject    - NPC name for character content; location/asset leaf otherwise
entry      - the original CP entry key, used verbatim (no escaping)
variant    - omitted for the base text, else one of:
               flavor
               furry
               flavor+furry
               swap-<Name>
               swap-<Name>+flavor
               swap-<Name>+furry
             ("furry" = content gated on `HasMod: krystedez.FurryFarmer`;
             folded together with Flavor because in this codebase every
             FurryFarmer-gated EditData change also implies flavor-style
             conditional text -- see plan open-question resolution.)

Old key grammar (mirrors HelperScripts/translation_prep.py exactly):

    '.'.join([target, target_field, escaped_entry_key, when_part,
               priority_part, file_id])

  - escaped_entry_key: entry key with "." -> "=" and " " -> "+"
  - when_part: looked up via SPECIAL_WHENS per `When` clause key (last match
    wins, mirroring the original script's loop-overwrite bug/behavior
    faithfully), then "Flavor" is appended (not prefixed) if the file lives
    under an "AnthroConfig" directory.
  - file_id: the parent directory name of the source json file
    (file.split('/')[-2])
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


BLACKLISTED_ENTRIES = {"Gender"}

SPECIAL_WHENS = {
    "HasMod: krystedez.FurryFarmer": "FurryFarmer",
    "HasMod: FlashShifter.StardewValleyExpandedCP": "SVE",
    "Flavor: True": "Flavor",
}

TOKEN_PATTERN = re.compile(r"{{(\w+)}}")


def find_tokens(text: str) -> list[str]:
    """Same extraction translation_prep.py uses to build |tok={{tok}} passthroughs."""
    return TOKEN_PATTERN.findall(text)


# ---------------------------------------------------------------------------
# OLD key (legacy, translation_prep.py-compatible)
# ---------------------------------------------------------------------------

def old_when_part(when: dict, file_path: str) -> str:
    when_part = ""
    for key, value in when.items():
        when_string = f"{key}: {value}"
        when_part = SPECIAL_WHENS.get(when_string, "")
    if "AnthroConfig" in file_path:
        when_part = when_part + "Flavor"
    return when_part


def old_escape_entry_key(key: str) -> str:
    return key.replace(".", "=").replace(" ", "+")


def old_file_id(file_path: str) -> str:
    return file_path.split("/")[-2]


def norm_old_key(k: str) -> str:
    """Canonicalize legacy-key escaping so equivalent old keys produced by
    different versions of the prep script compare equal. The current generator
    escapes ' '->'+' and '.'->'=' (see old_escape_entry_key); older placeholder
    snapshots embedded raw spaces/dots. Reversing both escapes maps both
    spellings to one canonical form. Used to re-match drifted i18n translations
    during migration."""
    return k.replace("=", ".").replace("+", " ")


def old_key_for_entry(change: dict, file_path: str, entry_key: str) -> tuple[str, str]:
    """Returns (full_key, partial_key) exactly as translation_prep.py's i18n_change did."""
    target = change.get("Target", "")
    target_field_list = change.get("TargetField", [])
    target_field = "/".join(target_field_list)
    when = change.get("When", {})
    when_part = old_when_part(when, file_path)
    priority_part = change.get("Priority", "")
    file_id = old_file_id(file_path)
    escaped = old_escape_entry_key(entry_key)
    full_key = ".".join([target, target_field, escaped, when_part, priority_part, file_id])
    partial_key = ".".join([target, target_field, escaped, when_part, priority_part])
    return full_key, partial_key


# ---------------------------------------------------------------------------
# NEW key scheme
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NewKeyParts:
    category: str
    subject: str
    entry: str
    variant: Optional[str]  # None for base

    @property
    def key(self) -> str:
        base = f"{self.category}/{self.subject}/{self.entry}"
        if self.variant:
            base += f"@{self.variant}"
        return base

    @property
    def base_key(self) -> "NewKeyParts":
        """The key this one falls back to under |default=, per the 3-tier
        fallback model (swap+flavor falls to flavor, not to swap; flavor and
        swap each fall to the plain base)."""
        return NewKeyParts(self.category, self.subject, self.entry, None)


def variant_bucket(when: dict, file_path: str) -> Optional[str]:
    """Compute the new-scheme variant suffix (without 'swap-<Name>' prefix)
    from the change's When clause and the file's AnthroConfig-ness. Returns
    one of: None, "flavor", "furry", "flavor+furry".
    """
    when_part = old_when_part(when, file_path)
    return {
        "": None,
        "Flavor": "flavor",
        "FurryFarmer": "furry",
        "FurryFarmerFlavor": "flavor+furry",
    }.get(when_part, None)


def swap_name_for_path(file_path: str) -> Optional[str]:
    """If file_path is under assets/Genderswaps/<Name>/, return <Name>."""
    m = re.search(r"/Genderswaps/([^/]+)/", file_path.replace("\\", "/"))
    return m.group(1) if m else None


def full_variant(file_path: str, when: dict) -> Optional[str]:
    ml = when.get("MarriageLine")
    if ml:
        return f"marriage-{ml}"
    swap_name = swap_name_for_path(file_path)
    bucket = variant_bucket(when, file_path)
    if swap_name:
        return f"swap-{swap_name}" + (f"+{bucket}" if bucket else "")
    return bucket  # may be None, "flavor", "furry", "flavor+furry"


# Targets that get their own new-scheme category, with a function deriving
# (category, subject) from (target, target_field_list).

_DIALOGUE_RE = re.compile(r"^Characters/Dialogue/(.+)$")
_EVENTS_RE = re.compile(r"^Data/Events/(.+)$")
_NPCNAMES = "Strings/NPCNames"
_DATA_CHARACTERS = "Data/Characters"
_STRINGS_RE = re.compile(r"^Strings/(.+)$")


def category_and_subject(target: str, target_field_list: list[str]) -> tuple[str, str]:
    m = _DIALOGUE_RE.match(target)
    if m:
        return "dialogue", m.group(1)

    m = _EVENTS_RE.match(target)
    if m:
        return "event", m.group(1)

    if target == _NPCNAMES:
        return "name", "Names"  # entry key (the char name) carries the subject; see below

    if target == _DATA_CHARACTERS:
        # data/<Char>/<field...>
        if not target_field_list:
            return "data", "Characters"
        return "data", target_field_list[0]

    m = _STRINGS_RE.match(target)
    if m:
        return "strings", m.group(1)

    # Fallback for anything unanticipated (e.g. "placeholder", other Data/*)
    # -- keep stable & readable rather than crashing.
    leaf = target.split("/")[-1] if target else "Unknown"
    return "data", leaf


def event_entry_id(entry_key: str) -> str:
    """Drop the precondition tail from an event entry key, keeping only the
    leading event id. Entry keys without a '/' (e.g. "choseToExplain") are
    returned unchanged."""
    return entry_key.split("/", 1)[0]


def data_characters_field_suffix(target_field_list: list[str]) -> str:
    """For Data/Characters, target_field_list[0] is the subject (char name);
    remaining segments (if any) form the field-path suffix before the
    entry key, e.g. ["Pierre", "FriendsAndFamily"] -> field suffix
    "FriendsAndFamily"."""
    return "/".join(target_field_list[1:])


def new_key_for_entry(change: dict, file_path: str, entry_key: str) -> NewKeyParts:
    target = change.get("Target", "")
    target_field_list = change.get("TargetField", [])
    when = change.get("When", {})

    category, subject = category_and_subject(target, target_field_list)

    if target == _NPCNAMES:
        # name/<Char>[@variant] -- the entry key IS the character name.
        entry = entry_key
        subject = entry_key
    elif category == "event":
        entry = event_entry_id(entry_key)
    elif category == "data" and target == _DATA_CHARACTERS:
        field_suffix = data_characters_field_suffix(target_field_list)
        entry = f"{field_suffix}/{entry_key}" if field_suffix else entry_key
    else:
        entry = entry_key

    variant = full_variant(file_path, when)
    return NewKeyParts(category=category, subject=subject, entry=entry, variant=variant)
