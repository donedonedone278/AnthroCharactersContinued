#!/usr/bin/env python3
"""
review_inventory.py - Stage-1 builder for the exhaustive English dialogue
review of AnthroCharactersContinued.

Enumerates EVERY English vanilla dialogue-bearing line (from
~/repos/Content_unpacked) across the corpus listed in
claude-documentation/plans/stage1-review-inventory-spec.md, and for each one
attaches:
  - the vanilla BASE text (verbatim)
  - the mod's CURRENT resolved EDIT text for every variant that already
    covers that line (via tools/i18n/vanilla_diff.walk_logical_lines() +
    tools/i18n/resolve.un_i18n())
  - mention-facts: which swappable characters (from tools/i18n/swaps.json)
    the line's text references, with that swap's full facts inlined.

This is INVENTORY + CONTEXT ATTACHMENT ONLY. No filtering, no verdicts.
Every vanilla line goes into exactly one Markdown packet under
claude-documentation/reports/_data/. Separately, computes the deterministic
Tier-R structured relational set (tierR.json + packet-tierR.md).

Usage:
    python3 tools/i18n/review_inventory.py                  # build everything
    python3 tools/i18n/review_inventory.py --content <dir>  # override vanilla dir
    python3 tools/i18n/review_inventory.py --self-check      # Tier-R anchor asserts
    python3 tools/i18n/review_inventory.py --only Harvey     # one packet only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve import un_i18n, get_all_jsons  # noqa: E402
from keyscheme import (  # noqa: E402
    category_and_subject, event_entry_id, full_variant, new_key_for_entry,
    BLACKLISTED_ENTRIES,
)
from vanilla_diff import (  # noqa: E402
    walk_logical_lines, is_blacklisted_file, word_diff, load_swap_names, VanillaStore,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
I18N_DIR = os.path.join(REPO_ROOT, "i18n")
SWAPS_PATH = os.path.join(REPO_ROOT, "tools", "i18n", "swaps.json")
OUT_DIR = os.path.join(REPO_ROOT, "claude-documentation", "reports", "_data")
DEFAULT_VANILLA_DIR = os.path.expanduser("~/repos/Content_unpacked")

LOCALE_SUFFIX_RE = re.compile(r"\.[a-z]{2}(-[A-Z]{2})?\.json$")

# The 12 swappable base names (for per-character packet enumeration + Tier R).
SWAP_BASE_NAMES = [
    "Abigail", "Emily", "Haley", "Leah", "Maru", "Penny",
    "Elliott", "Shane", "Sebastian", "Sam", "Harvey", "Alex",
]

# Gender-flip map for Tier-R needed-word computation. Keys are the vanilla
# Relative_<X> suffix (or the lowercase free-text label); values are the
# (M->F, F->M) flipped surface words. Direction comes from swap.direction.
RELATIVE_FLIP = {
    "Son": ("Son", "Daughter"),
    "Daughter": ("Son", "Daughter"),
    "Brother": ("Brother", "Sister"),
    "Sister": ("Brother", "Sister"),
    "HalfBrother": ("HalfBrother", "HalfSister"),
    "HalfSister": ("HalfBrother", "HalfSister"),
    "Nephew": ("Nephew", "Niece"),
    "Niece": ("Nephew", "Niece"),
    "Grandson": ("Grandson", "Granddaughter"),
    "Granddaughter": ("Grandson", "Granddaughter"),
    "EldestSon": ("EldestSon", "EldestDaughter"),
    "EldestDaughter": ("EldestSon", "EldestDaughter"),
    "YoungestSon": ("YoungestSon", "YoungestDaughter"),
    "YoungestDaughter": ("YoungestSon", "YoungestDaughter"),
    "YoungestBoy": ("YoungestBoy", "YoungestGirl"),
    "YoungestGirl": ("YoungestBoy", "YoungestGirl"),
    "LittleBrother": ("LittleBrother", "LittleSister"),
    "LittleSister": ("LittleBrother", "LittleSister"),
    "LittleBabyGirl": ("LittleBabyBoy", "LittleBabyGirl"),
    "LittleBabyBoy": ("LittleBabyBoy", "LittleBabyGirl"),
}

# Readable lowercase word for a flipped token, for the MUST_MINT message
# (best-effort; only used for display, not for the has-token check itself).
WORD_FOR_TOKEN = {
    "Son": "son", "Daughter": "daughter", "Brother": "brother", "Sister": "sister",
    "HalfBrother": "half-brother", "HalfSister": "half-sister",
    "Nephew": "nephew", "Niece": "niece",
    "Grandson": "grandson", "Granddaughter": "granddaughter",
    "EldestSon": "eldest son", "EldestDaughter": "eldest daughter",
    "YoungestSon": "youngest son", "YoungestDaughter": "youngest daughter",
    "YoungestBoy": "youngest boy", "YoungestGirl": "youngest girl",
    "LittleBrother": "little brother", "LittleSister": "little sister",
    "LittleBabyGirl": "little baby-girl", "LittleBabyBoy": "little baby boy",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def is_locale_file(filename: str) -> bool:
    """Filter by FILENAME only (stress-test-04 lesson) -- never by content."""
    return bool(LOCALE_SUFFIX_RE.search(filename))


def list_english_files(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    out = []
    for f in sorted(os.listdir(directory)):
        if not f.endswith(".json"):
            continue
        if is_locale_file(f):
            continue
        out.append(os.path.join(directory, f))
    return out


def load_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Mention:
    swap_base: str
    swap_name: str
    surface: str
    kind: str  # "base" | "swap" | "nickname" | "relative-holder"


@dataclass
class CoverageVariant:
    variant_label: Optional[str]  # None | "flavor" | "swap-<New>" | "swap-<New>+flavor" | "marriage-..."
    edit_text: str
    file: str
    entry_key: str


@dataclass
class LineRecord:
    category: str          # dialogue | event | festival | data | strings
    subject: str            # NPC name / location / asset leaf
    entry: str               # entry key (verbatim, precondition tail dropped for events)
    vanilla_base: str
    speaker: Optional[str]
    shared: bool
    coverage: list[CoverageVariant] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    source_note: str = ""    # extra context, e.g. event id / mail title

    @property
    def line_key(self) -> str:
        return f"{self.category}/{self.subject}/{self.entry}"

    @property
    def covered(self) -> bool:
        return len(self.coverage) > 0


# ---------------------------------------------------------------------------
# Swaps.json loading + mention scanning
# ---------------------------------------------------------------------------

def load_swaps() -> list[dict]:
    data = load_json(SWAPS_PATH)
    return data.get("swaps", []) if data else []


def build_mention_index(swaps: list[dict]) -> list[tuple[re.Pattern, str, str, str]]:
    """Build (compiled whole-word regex, swap_base, swap_name, kind, surface)
    tuples to scan line text against. One tuple per candidate surface form."""
    index: list[tuple[re.Pattern, str, str, str, str]] = []

    def add(surface: str, swap_base: str, swap_name: str, kind: str) -> None:
        if not surface:
            return
        pattern = re.compile(r"\b" + re.escape(surface) + r"\b", re.IGNORECASE)
        index.append((pattern, swap_base, swap_name, kind, surface))

    for s in swaps:
        base, swap = s["base"], s["swap"]
        add(base, base, swap, "base")
        add(swap, base, swap, "swap")
        for nick in s.get("nicknames", []):
            add(nick, base, swap, "nickname")
        for rel in s.get("relatives", []):
            holder = rel.get("holder")
            if holder:
                add(holder, base, swap, "relative-holder")
    return index


def scan_mentions(text: str, index: list[tuple]) -> list[Mention]:
    if not text:
        return []
    hits: list[Mention] = []
    seen: set[tuple] = set()
    for pattern, swap_base, swap_name, kind, surface in index:
        m = pattern.search(text)
        if m:
            key = (swap_base, kind, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            hits.append(Mention(swap_base=swap_base, swap_name=swap_name,
                                 surface=m.group(0), kind=kind))
    return hits


def swaps_by_base(swaps: list[dict]) -> dict[str, dict]:
    return {s["base"]: s for s in swaps}


# ---------------------------------------------------------------------------
# Coverage lookup (from walk_logical_lines())
# ---------------------------------------------------------------------------

def walk_data_prose() -> dict[str, list[CoverageVariant]]:
    """Recover coverage for EVERY 'data'-category mod edit.

    vanilla_diff.walk_logical_lines() only covers PROSE_CATEGORIES
    (dialogue/event/strings); it skips everything category_and_subject()
    labels "data" (Festivals, mail, SecretNotes, Quests, NPCGiftTastes,
    EngagementDialogue, ExtraDialogue, TV, Data/Characters, ...). We mirror
    that walk here for the data category and key each entry exactly as the mod
    resolves it (keyscheme.new_key_for_entry), so keys line up with
    coverage_line_key(). This subsumes the old Data/Characters-only walk.
    edit_text holds the raw i18n value; the caller resolves it via un_i18n()."""
    out: dict[str, list[CoverageVariant]] = {}
    for path in get_all_jsons(ASSETS_DIR):
        if is_blacklisted_file(path):
            continue
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for change in data.get("Changes", []):
            if change.get("Action") != "EditData":
                continue
            target = change.get("Target", "")
            target_field_list = change.get("TargetField", [])
            category, _ = category_and_subject(target, target_field_list)
            if category != "data":
                continue  # dialogue/event/strings handled by walk_logical_lines()
            when = change.get("When", {})
            variant_label = full_variant(path, when)
            for entry_key, value in change.get("Entries", {}).items():
                if entry_key in BLACKLISTED_ENTRIES:
                    continue
                if not isinstance(value, str) or "i18n" not in value:
                    continue
                line_key = new_key_for_entry(change, path, entry_key).base_key.key
                out.setdefault(line_key, []).append(CoverageVariant(
                    variant_label=variant_label,
                    edit_text=value,  # raw i18n; resolved by caller
                    file=os.path.relpath(path, REPO_ROOT),
                    entry_key=entry_key,
                ))
    return out


def build_coverage_index(default_translations: dict) -> dict[str, list[CoverageVariant]]:
    """line_key -> [CoverageVariant, ...] using vanilla_diff.walk_logical_lines()
    (dialogue/event/strings) PLUS a direct walk of all data-category EditData
    changes (excluded from walk_logical_lines()'s PROSE_CATEGORIES scope)."""
    logical = walk_logical_lines()
    out: dict[str, list[CoverageVariant]] = {}
    for line_key, line in logical.items():
        variants = []
        for v in line.variants:
            edit_text = un_i18n(v.i18n_value, default_translations)
            variants.append(CoverageVariant(
                variant_label=v.variant_label,
                edit_text=edit_text,
                file=v.file,
                entry_key=v.entry_key,
            ))
        out[line_key] = variants

    data_prose = walk_data_prose()
    for line_key, variants in data_prose.items():
        resolved = []
        for v in variants:
            resolved.append(CoverageVariant(
                variant_label=v.variant_label,
                edit_text=un_i18n(v.edit_text, default_translations),
                file=v.file,
                entry_key=v.entry_key,
            ))
        out.setdefault(line_key, []).extend(resolved)
    return out


# ---------------------------------------------------------------------------
# Corpus enumeration: one function per asset family.
# Each yields LineRecord (without coverage/mentions attached yet).
# ---------------------------------------------------------------------------

def walk_strings(obj, prefix=""):
    """Flatten a nested dict/list structure into (path, value) pairs for
    string leaves only. Arrays use [i], objects use /key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}/{k}" if prefix else str(k)
            yield from walk_strings(v, new_prefix)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_prefix = f"{prefix}[{i}]"
            yield from walk_strings(v, new_prefix)
    elif isinstance(obj, str):
        yield prefix, obj
    # skip numbers/bools/None -- not prose


def enum_dialogue(content_dir: str) -> list[LineRecord]:
    records = []
    ddir = os.path.join(content_dir, "Characters", "Dialogue")
    for path in list_english_files(ddir):
        leaf = os.path.splitext(os.path.basename(path))[0]  # e.g. "Abigail", "MarriageDialogueAbigail"
        data = load_json(path)
        if not isinstance(data, dict):
            continue

        if leaf == "MarriageDialogue":
            speaker = None  # shared -- whichever spouse
            shared = True
        elif leaf.startswith("MarriageDialogue"):
            speaker = leaf[len("MarriageDialogue"):]
            shared = False
        else:
            speaker = leaf
            shared = False

        for entry_key, value in data.items():
            if not isinstance(value, str):
                continue
            records.append(LineRecord(
                category="dialogue", subject=leaf, entry=entry_key,
                vanilla_base=value, speaker=speaker, shared=shared,
            ))
    return records


SPEAK_RE = re.compile(r'\b(?:speak|textAboveHead|end dialogue|splitSpeak)\s+(\S+)\s+"((?:[^"\\]|\\.)*)"')
MESSAGE_RE = re.compile(r'\bmessage\s+"((?:[^"\\]|\\.)*)"')
EVENT_SPEAKER_RE = re.compile(r'\b(?:speak|textAboveHead|end dialogue)\s+(\S+)\s+"')


def parse_event_speakers(script: str) -> list[str]:
    """Collect all distinct NPC ids named by speak/textAboveHead/end dialogue
    commands in the script, in first-seen order."""
    speakers: list[str] = []
    for m in EVENT_SPEAKER_RE.finditer(script):
        npc = m.group(1)
        if npc not in speakers:
            speakers.append(npc)
    return speakers


def enum_events(content_dir: str) -> list[LineRecord]:
    """One record per event id. BASE = the FULL vanilla event script verbatim
    (one block; reviewers parse it per checklist Part S3). Coverage for long
    scripts is rendered as compact word-diff CHANGES (see render_record_md),
    so we do NOT split into per-speak-line records anymore."""
    records = []
    edir = os.path.join(content_dir, "Data", "Events")
    for path in list_english_files(edir):
        loc = os.path.splitext(os.path.basename(path))[0]
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        seen_eids: set[str] = set()
        for raw_key, script in data.items():
            if not isinstance(script, str):
                continue
            eid = event_entry_id(raw_key)
            if eid in seen_eids:
                continue  # one record per event id; first raw_key wins
            seen_eids.add(eid)
            speakers = parse_event_speakers(script)
            records.append(LineRecord(
                category="event", subject=loc, entry=eid,
                vanilla_base=script,
                speaker=", ".join(speakers) if speakers else None,
                shared=False,
                source_note=f"raw_key={raw_key}",
            ))
    return records


def enum_festivals(content_dir: str) -> list[LineRecord]:
    records = []
    fdir = os.path.join(content_dir, "Data", "Festivals")
    for path in list_english_files(fdir):
        fname = os.path.splitext(os.path.basename(path))[0]
        if fname == "FestivalDates":
            continue  # pure date data, not prose
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if not isinstance(value, str):
                continue
            if key in ("conditions", "set-up", "set-up_y2"):
                # These are pure engine scripts with embedded speak/message
                # commands sometimes -- still extract any quoted display text.
                parts = value.split("/")
                found_any = False
                for part in parts:
                    m = SPEAK_RE.match(part)
                    if m:
                        npc, text = m.group(1), m.group(2)
                        if text.strip():
                            records.append(LineRecord(
                                category="festival", subject=fname, entry=f"{key}/{npc}",
                                vanilla_base=text, speaker=npc, shared=False,
                            ))
                            found_any = True
                if not found_any:
                    continue
                continue
            # Try to extract speak/message commands from slash-delimited
            # festival event scripts (mainEvent, *Win, etc.) the same way as
            # events; many of these double as event scripts.
            if "/" in value and ("speak " in value or "message " in value or "end dialogue" in value or "splitSpeak" in value):
                parts = value.split("/")
                npc_guess = None
                m_name = re.match(r"^([A-Za-z]+)", key)
                if m_name:
                    npc_guess = m_name.group(1)
                for part in parts:
                    m = SPEAK_RE.match(part)
                    if m:
                        npc, text = m.group(1), m.group(2)
                        if text.strip():
                            records.append(LineRecord(
                                category="festival", subject=fname, entry=f"{key}",
                                vanilla_base=text, speaker=npc, shared=False,
                            ))
                        continue
                    m2 = MESSAGE_RE.match(part)
                    if m2 and m2.group(1).strip():
                        records.append(LineRecord(
                            category="festival", subject=fname, entry=f"{key}",
                            vanilla_base=m2.group(1), speaker=npc_guess, shared=False,
                        ))
                continue
            # Otherwise: plain prose value (e.g. "name") -- only keep if it
            # doesn't look like pure engine data (over-include per spec).
            if key in ("name",):
                continue  # festival display name -- not dialogue, skip (pure id-like)
            m_name2 = re.match(r"^([A-Za-z]+)", key)
            records.append(LineRecord(
                category="festival", subject=fname, entry=key,
                vanilla_base=value,
                speaker=m_name2.group(1) if m_name2 else None,
                shared=False,
            ))
    return records


def enum_engagement(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Data", "EngagementDialogue.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        m = re.match(r"^([A-Za-z]+)", key)
        speaker = m.group(1) if m else None
        records.append(LineRecord(
            category="data", subject="EngagementDialogue", entry=key,
            vanilla_base=value, speaker=speaker, shared=False,
        ))
    return records


def enum_extra_dialogue(content_dir: str) -> list[LineRecord]:
    """Data/ExtraDialogue.json: situational one-off lines (spouse reactions,
    new-child, purchased-item gossip, summit-event chatter, ...). Flat
    key->string map. Emit each string entry as a prose record so it gets a
    packet line and a coverage match -- the mod edits Data/ExtraDialogue, which
    resolves to data/ExtraDialogue/<key> (== coverage_line_key for these)."""
    records = []
    path = os.path.join(content_dir, "Data", "ExtraDialogue.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str) or not value.strip():
            continue
        records.append(LineRecord(
            category="data", subject="ExtraDialogue", entry=key,
            vanilla_base=value, speaker=None, shared=False,
        ))
    return records


def enum_mail(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Data", "mail.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    sig_re = re.compile(r"-\s*([A-Za-z]+)\s*(?:%|$)")
    title_re = re.compile(r"\[#\]([^\^\]]+)")
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        speaker = None
        m = sig_re.search(value)
        if m:
            speaker = m.group(1)
        else:
            m2 = title_re.search(value)
            if m2:
                speaker = None
        records.append(LineRecord(
            category="data", subject="mail", entry=key,
            vanilla_base=value, speaker=speaker, shared=False,
        ))
    return records


def enum_secret_notes(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Data", "SecretNotes.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        records.append(LineRecord(
            category="data", subject="SecretNotes", entry=key,
            vanilla_base=value, speaker=None, shared=False,
        ))
    return records


def enum_movie_reactions(content_dir: str) -> list[LineRecord]:
    """Data/MoviesReactions.json references Strings/MovieReactions.json via
    [LocalizedText ...] -- the actual prose lives in the Strings file, so we
    enumerate from there (it's the dialogue-bearing source) and tag the NPC
    from the key prefix."""
    records = []
    path = os.path.join(content_dir, "Strings", "MovieReactions.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        m = re.match(r"^([A-Za-z]+)_", key)
        npc = m.group(1) if m else None
        records.append(LineRecord(
            category="data", subject="MoviesReactions", entry=key,
            vanilla_base=value, speaker=npc, shared=False,
        ))
    return records


QUEST_FIELD_NAMES = ["questType", "title", "text", "objective", "rewardDescription",
                      "targetLocation", "objectiveSlot", "currentObjective", "nextQuest", "partOfQuestChain"]


def enum_quests(content_dir: str) -> list[LineRecord]:
    """Data/Quests.json values are '/'-delimited field tuples
    (type/title/text/objective/targetLocation/...). Only emit prose fields
    (title, text/description, objective)."""
    records = []
    path = os.path.join(content_dir, "Data", "Quests.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        parts = value.split("/")
        # Layout (vanilla Quest data string): questType/title/description/objective/targetLocation/...
        prose_idx = {1: "title", 2: "text", 3: "objective"}
        for idx, field_name in prose_idx.items():
            if idx < len(parts) and parts[idx].strip():
                records.append(LineRecord(
                    category="data", subject="Quests", entry=f"{key}/{field_name}",
                    vanilla_base=parts[idx], speaker=None, shared=False,
                ))
    return records


def enum_gift_tastes(content_dir: str) -> list[LineRecord]:
    """Data/NPCGiftTastes.json per-NPC value is a '/'-delimited sequence of
    [response-prose, item-id-list, response-prose, item-id-list, ...]. Emit
    the prose (odd-indexed, 0-based even since pattern is text/ids/text/ids...)
    slots only; skip Universal_* (pure id lists, no prose) and id-list slots."""
    records = []
    path = os.path.join(content_dir, "Data", "NPCGiftTastes.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    response_labels = ["Love", "Like", "Dislike", "Hate", "Neutral"]
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        if key.startswith("Universal_"):
            continue  # pure id lists, no prose
        parts = value.split("/")
        # pattern: love_text / love_ids / like_text / like_ids / dislike_text / dislike_ids / hate_text / hate_ids / neutral_text / neutral_ids
        for i in range(0, len(parts), 2):
            text = parts[i]
            if not text.strip():
                continue
            label = response_labels[i // 2] if i // 2 < len(response_labels) else f"slot{i}"
            records.append(LineRecord(
                category="data", subject="NPCGiftTastes", entry=f"{key}/{label}",
                vanilla_base=text, speaker=key, shared=False,
            ))
    return records


def enum_strings_csfiles(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Strings", "StringsFromCSFiles.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        records.append(LineRecord(
            category="strings", subject="StringsFromCSFiles", entry=key,
            vanilla_base=value, speaker=None, shared=False,
        ))
    return records


def enum_strings_maps(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Strings", "StringsFromMaps.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        records.append(LineRecord(
            category="strings", subject="StringsFromMaps", entry=key,
            vanilla_base=value, speaker=None, shared=False,
        ))
    return records


def enum_strings_characters(content_dir: str) -> list[LineRecord]:
    records = []
    path = os.path.join(content_dir, "Strings", "Characters.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        records.append(LineRecord(
            category="strings", subject="Characters", entry=key,
            vanilla_base=value, speaker=None, shared=False,
        ))
    return records


def enum_data_characters_friends(content_dir: str) -> list[LineRecord]:
    """Data/Characters.json <Name>/FriendsAndFamily/<Rel> entries. These are
    short structured relation tokens (not free prose), but the spec lists
    them explicitly as part of the corpus (Tier-R source) -- emit them as
    LineRecords too so they get a packet line, in addition to the dedicated
    Tier-R computation."""
    records = []
    path = os.path.join(content_dir, "Data", "Characters.json")
    data = load_json(path)
    if not isinstance(data, dict):
        return records
    for holder, cdata in data.items():
        if not isinstance(cdata, dict):
            continue
        faf = cdata.get("FriendsAndFamily")
        if not isinstance(faf, dict):
            continue
        for rel_name, rel_value in faf.items():
            if not isinstance(rel_value, str):
                continue
            records.append(LineRecord(
                category="data", subject="Characters", entry=f"{holder}/FriendsAndFamily/{rel_name}",
                vanilla_base=rel_value, speaker=None, shared=False,
            ))
    return records


def enumerate_corpus(content_dir: str) -> list[LineRecord]:
    records: list[LineRecord] = []
    records += enum_dialogue(content_dir)
    records += enum_events(content_dir)
    records += enum_festivals(content_dir)
    records += enum_engagement(content_dir)
    records += enum_extra_dialogue(content_dir)
    records += enum_mail(content_dir)
    records += enum_secret_notes(content_dir)
    records += enum_movie_reactions(content_dir)
    records += enum_quests(content_dir)
    records += enum_gift_tastes(content_dir)
    records += enum_strings_csfiles(content_dir)
    records += enum_strings_maps(content_dir)
    records += enum_strings_characters(content_dir)
    records += enum_data_characters_friends(content_dir)
    return records


# ---------------------------------------------------------------------------
# Coverage line-key mapping. The mod's logical-line keys for dialogue/event/
# strings come straight from category_and_subject(); for data/* (engagement,
# mail, secretnotes, moviesreactions, quests, gifttastes, characters-friends)
# walk_logical_lines() ALSO covers them if the mod ever edits those targets
# (category_and_subject's Data/* fallback maps target leaf -> subject), so we
# mirror that mapping here to look coverage up consistently.
# ---------------------------------------------------------------------------

def coverage_line_key(rec: LineRecord) -> str:
    if rec.category == "dialogue":
        return f"dialogue/{rec.subject}/{rec.entry}"
    if rec.category == "event":
        return f"event/{rec.subject}/{rec.entry}"
    if rec.category == "strings":
        return f"strings/{rec.subject}/{rec.entry}"
    if rec.category == "festival":
        # category_and_subject's fallback would use the Data/Festivals leaf
        # ("Data/Festivals/<f>") -> subject = "<f>" (leaf.split('/')[-1]).
        return f"data/{rec.subject}/{rec.entry}"
    if rec.category == "data":
        if rec.subject == "MoviesReactions":
            # The prose lives in Strings/MovieReactions.json; the mod edits it via
            # Target "Strings/MovieReactions" -> category_and_subject() yields
            # ("strings", "MovieReactions") -> coverage index key
            # strings/MovieReactions/<entry>. enum_movie_reactions() reads the same
            # file but labels it data/MoviesReactions (Movies, plural), so realign
            # to the mod-resolution key here. (Note: "MovieReactions" singular.)
            return f"strings/MovieReactions/{rec.entry}"
        if rec.subject == "Characters":
            # data/Characters.json walk_logical_lines() key for FriendsAndFamily
            # edits is built from TargetField: data/<field_suffix>/<entry_key>
            # where field_suffix="FriendsAndFamily" and entry_key is the holder
            # name when TargetField=[holder, "FriendsAndFamily"]. Our rec.entry
            # is "<holder>/FriendsAndFamily/<rel_name>" -- remap accordingly.
            parts = rec.entry.split("/")
            if len(parts) == 3 and parts[1] == "FriendsAndFamily":
                holder, _, rel_name = parts
                return f"data/{holder}/FriendsAndFamily/{rel_name}"
        return f"data/{rec.subject}/{rec.entry}"
    return rec.line_key


def lookup_coverage(coverage_index: dict[str, list[CoverageVariant]],
                    rec: LineRecord) -> list[CoverageVariant]:
    """Coverage for rec, with parent-key fallback for the two families whose
    enumerator key is finer-grained than the mod's edit key. The mod edits the
    whole '/'-delimited tuple under one entry id (data/Quests/<id>,
    data/NPCGiftTastes/<NPC>), but the enumerator splits each tuple into
    per-field records (.../<id>/<field>); attach the tuple-level coverage to
    every sub-field record."""
    key = coverage_line_key(rec)
    variants = coverage_index.get(key)
    if variants:
        return variants
    if rec.category == "data" and rec.subject in ("Quests", "NPCGiftTastes"):
        parent = key.rsplit("/", 1)[0]
        return coverage_index.get(parent, [])
    return []


# ---------------------------------------------------------------------------
# Tier R: deterministic structured relational set
# ---------------------------------------------------------------------------

@dataclass
class TierREntry:
    holder: str
    base: str
    swap: str
    direction: str
    vanilla_token: str          # e.g. "Relative_EldestSon"
    label: str                   # e.g. "EldestSon"
    needed_word: str             # flipped label, e.g. "EldestDaughter"
    flipped_token_exists: bool
    must_mint: bool
    covered: bool
    covering_file: Optional[str]


def flip_label(label: str, direction: str) -> str:
    """label is the Relative_<X> suffix or a free-text guess. direction is
    'F->M' or 'M->F'. Returns the flipped <X> suffix using RELATIVE_FLIP."""
    pair = RELATIVE_FLIP.get(label)
    if not pair:
        return ""
    m_form, f_form = pair
    return m_form if direction == "F->M" else f_form


def compute_tier_r(content_dir: str, swaps: list[dict],
                    coverage_index: dict[str, list[CoverageVariant]]) -> list[TierREntry]:
    chars_path = os.path.join(content_dir, "Data", "Characters.json")
    chars_data = load_json(chars_path) or {}
    strings_chars_path = os.path.join(content_dir, "Strings", "Characters.json")
    strings_chars = load_json(strings_chars_path) or {}

    token_re = re.compile(r"\[LocalizedText Strings\\Characters:(Relative_\w+)\]")

    entries: list[TierREntry] = []
    for s in swaps:
        base, swap, direction = s["base"], s["swap"], s["direction"]
        for holder, cdata in chars_data.items():
            if not isinstance(cdata, dict):
                continue
            faf = cdata.get("FriendsAndFamily")
            if not isinstance(faf, dict):
                continue
            if base not in faf:
                continue
            raw_value = faf[base]
            if not isinstance(raw_value, str):
                continue
            m = token_re.search(raw_value)
            if m:
                vanilla_token = m.group(1)
                label = vanilla_token[len("Relative_"):]
            else:
                vanilla_token = ""
                label = raw_value.strip().lower()

            needed_label = flip_label(label, direction) if m else ""
            needed_word = WORD_FOR_TOKEN.get(needed_label, needed_label.lower() if needed_label else "(free-text -- hand-resolve)")
            flipped_token = f"Relative_{needed_label}" if needed_label else ""
            flipped_exists = bool(flipped_label_exists(strings_chars, flipped_token)) if flipped_token else False
            must_mint = bool(m) and not flipped_exists

            # covered: does any mod asset edit Data/Characters TargetField
            # [<holder>, FriendsAndFamily] entry <base>, via walk_logical_lines()?
            line_key = f"data/{holder}/FriendsAndFamily/{base}"
            covering_variants = coverage_index.get(line_key, [])
            covered = len(covering_variants) > 0
            covering_file = covering_variants[0].file if covering_variants else None

            entries.append(TierREntry(
                holder=holder, base=base, swap=swap, direction=direction,
                vanilla_token=vanilla_token or "(free-text)", label=label,
                needed_word=needed_word,
                flipped_token_exists=flipped_exists,
                must_mint=must_mint, covered=covered, covering_file=covering_file,
            ))
    return entries


def flipped_label_exists(strings_chars: dict, token: str) -> bool:
    return token in strings_chars


# ---------------------------------------------------------------------------
# Packet rendering
# ---------------------------------------------------------------------------

LONG_BASE_THRESHOLD = 600  # chars; above this, render CHANGES@ word-diffs instead of full EDIT@ text.


def render_mentions_md(mentions: list[Mention]) -> list[str]:
    """Terse per-line mentions: names + matched surface form only. Full swap
    facts are deduplicated into a single '## Swap facts' block at the top of
    each packet (see render_swap_facts_md) instead of being repeated per line."""
    if not mentions:
        return []
    return ["MENTIONS: " + "; ".join(
        f"{m.swap_base}→{m.swap_name} [{m.kind} \"{m.surface}\"]" for m in mentions
    )]


def render_swap_facts_md(swap_bases: set[str], swap_facts: dict[str, dict]) -> list[str]:
    """One '## Swap facts' section listing the full swaps.json facts for every
    swap base that appears anywhere in this packet (deduplicated, once)."""
    if not swap_bases:
        return []
    lines = ["## Swap facts", ""]
    for base in sorted(swap_bases):
        facts = swap_facts.get(base)
        if not facts:
            continue
        rel_str = "; ".join(
            f"{r['holder']}:{r['label']}→{r['needed']}"
            f"({'token' if r['has_token'] else 'MUST_MINT'},{r['kind']})"
            for r in facts.get("relatives", [])
        ) or "none"
        lines.append(
            f"- **{base}→{facts['swap']}** facts: direction={facts['direction']}; "
            f"species={facts['base_species']}→{facts['swap_species']} "
            f"(changes={facts['species_changes']}); "
            f"body={','.join(facts.get('swap_body_words', [])) or 'n/a'}; "
            f"relatives=[{rel_str}]; "
            f"tokens={','.join(facts.get('dynamic_tokens', [])) or 'n/a'}; "
            f"nicknames={','.join(facts.get('nicknames', [])) or 'none'}"
        )
    lines.append("")
    return lines


def render_changes_block(label: str, base_text: str, edit_text: str, swap_names: set[str]) -> list[str]:
    """Compact word-diff block for a covering variant of a long BASE (event
    script or any entry whose base text exceeds LONG_BASE_THRESHOLD). Avoids
    duplicating the entire resolved script per variant."""
    segments = word_diff(base_text, edit_text, swap_names)
    lines = [f"CHANGES@{label}:"]
    if not segments:
        lines.append("  (no text change — likely engine-only)")
        return lines
    for seg in segments:
        lines.append(f"  «{seg.old_text}» → «{seg.new_text}»")
    return lines


def render_record_md(rec: LineRecord, swap_names: set[str]) -> list[str]:
    covered_labels = sorted({(v.variant_label or "(base)") for v in rec.coverage})
    cov_str = ",".join(covered_labels) if covered_labels else "UNCOVERED"
    speaker_str = rec.speaker or "n/a"
    shared_str = " [shared]" if rec.shared else ""
    note_str = f" [{rec.source_note}]" if rec.source_note else ""
    lines = [
        f"### {rec.category}/{rec.subject} · {rec.entry}   "
        f"[speaker: {speaker_str}] [covered: {cov_str}]{shared_str}{note_str}",
        f"BASE: {rec.vanilla_base}",
    ]
    use_changes = rec.category == "event" or len(rec.vanilla_base) > LONG_BASE_THRESHOLD
    # base-variant override first (if present and non-empty), then others.
    for v in sorted(rec.coverage, key=lambda v: (v.variant_label or "")):
        label = v.variant_label or "base-override"
        if use_changes:
            lines += render_changes_block(label, rec.vanilla_base, v.edit_text, swap_names)
            lines.append(f"  _(src: {v.file})_")
        else:
            lines.append(f"EDIT@{label}: {v.edit_text}  _(src: {v.file})_")
    lines += render_mentions_md(rec.mentions)
    lines.append("")
    return lines


def write_md(path: str, title: str, body_lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n")
        fh.write("\n".join(body_lines))
        fh.write("\n")


# ---------------------------------------------------------------------------
# Packet assignment: each LineRecord goes to exactly one packet.
# ---------------------------------------------------------------------------

NON_SWAP_SPEAKING_SUBJECTS_DIALOGUE_ONLY = None  # computed dynamically from corpus


def assign_packet(rec: LineRecord) -> str:
    """Returns the packet basename (without .md) this record belongs to."""
    if rec.category == "dialogue":
        if rec.subject == "MarriageDialogue":
            return "shared-MarriageDialogue"
        if rec.subject.startswith("MarriageDialogue"):
            char = rec.subject[len("MarriageDialogue"):]
            return f"char-{char}"
        # plain Characters/Dialogue/<Name> (incl. "rainy" shared file)
        if rec.subject == "rainy":
            return "shared-rainy"
        return f"char-{rec.subject}"
    if rec.category == "event":
        return f"shared-event-{rec.subject}"
    if rec.category == "festival":
        return f"shared-festival-{rec.subject}"
    if rec.category == "strings":
        return f"shared-strings-{rec.subject}"
    if rec.category == "data":
        return f"shared-data-{rec.subject}"
    return "shared-misc"


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(content_dir: str, only: Optional[str] = None) -> tuple[int, int]:
    os.makedirs(OUT_DIR, exist_ok=True)

    default_path = os.path.join(I18N_DIR, "default.json")
    default_translations = load_json(default_path) or {}

    swaps = load_swaps()
    swap_facts = swaps_by_base(swaps)
    mention_index = build_mention_index(swaps)
    swap_names = load_swap_names()

    coverage_index = build_coverage_index(default_translations)

    records = enumerate_corpus(content_dir)

    # Attach coverage + mentions.
    for rec in records:
        rec.coverage = lookup_coverage(coverage_index, rec)
        mention_text = rec.vanilla_base + " " + " ".join(v.edit_text for v in rec.coverage)
        rec.mentions = scan_mentions(mention_text, mention_index)

    # Group into packets.
    packets: dict[str, list[LineRecord]] = {}
    for rec in records:
        packet_name = assign_packet(rec)
        packets.setdefault(packet_name, []).append(rec)

    if only:
        packets = {k: v for k, v in packets.items() if k == f"char-{only}" or only in k}

    total_lines = 0
    packet_meta = []  # (filename, count, swaps_covered, chars_covered)

    for packet_name in sorted(packets):
        recs = packets[packet_name]
        # group by entry within the packet for readability (spec: "Group by entry")
        recs_sorted = sorted(recs, key=lambda r: (r.entry, r.category, r.subject))
        body: list[str] = []
        swaps_seen: set[str] = set()
        for rec in recs_sorted:
            body += render_record_md(rec, swap_names)
            for m in rec.mentions:
                swaps_seen.add(m.swap_base)
        total_lines += len(recs)

        header = render_swap_facts_md(swaps_seen, swap_facts)

        fname = f"packet-{packet_name}.md"
        path = os.path.join(OUT_DIR, fname)
        write_md(path, f"Review packet: {packet_name}", header + body)
        packet_meta.append((fname, len(recs), sorted(swaps_seen)))

    # Tier R.
    tier_r = compute_tier_r(content_dir, swaps, coverage_index)
    tier_r_path = os.path.join(OUT_DIR, "tierR.json")
    with open(tier_r_path, "w", encoding="utf-8") as fh:
        json.dump([vars(t) for t in tier_r], fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    tier_r_md = ["| Holder | Base→Swap | Direction | Token | Needed | Flipped exists | MUST_MINT | Covered | Covering file |",
                 "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(tier_r, key=lambda t: (t.base, t.holder)):
        tier_r_md.append(
            f"| {t.holder} | {t.base}→{t.swap} | {t.direction} | {t.vanilla_token} | "
            f"{t.needed_word} | {t.flipped_token_exists} | "
            f"{'**MUST_MINT**' if t.must_mint else 'no'} | {t.covered} | "
            f"{t.covering_file or '-'} |"
        )
    write_md(os.path.join(OUT_DIR, "packet-tierR.md"), "Tier R: structured relational set", tier_r_md)

    # Index.
    index_lines = ["| Packet | Lines | Swaps mentioned |", "|---|---|---|"]
    for fname, count, swaps_seen in sorted(packet_meta):
        index_lines.append(f"| {fname} | {count} | {', '.join(swaps_seen) or '-'} |")
    index_lines.append(f"\n**Total packets:** {len(packet_meta)}  \n**Total lines:** {total_lines}\n")
    index_lines.append(f"\nSeparately: `tierR.json` / `packet-tierR.md` ({len(tier_r)} Tier-R relational rows).")
    write_md(os.path.join(OUT_DIR, "packet-INDEX.md"), "Review packet index", index_lines)

    return total_lines, len(packet_meta)


# ---------------------------------------------------------------------------
# Self-check: §3 anchors
# ---------------------------------------------------------------------------

def self_check(content_dir: str) -> bool:
    default_path = os.path.join(I18N_DIR, "default.json")
    default_translations = load_json(default_path) or {}
    swaps = load_swaps()
    coverage_index = build_coverage_index(default_translations)
    tier_r = compute_tier_r(content_dir, swaps, coverage_index)

    ok = True

    def find(base, holder, label=None):
        for t in tier_r:
            if t.base == base and t.holder == holder and (label is None or t.label == label):
                return t
        return None

    # Anchor 3.1: Kent -> Sam EldestSon present AND covered:false.
    t = find("Sam", "Kent", "EldestSon")
    print("\n[anchor 3.1] Kent->Sam EldestSon:", end=" ")
    if t and not t.covered:
        print(f"PASS (token={t.vanilla_token}, covered={t.covered})")
    else:
        print(f"FAIL (found={t})")
        ok = False

    # Anchor 3.2: Alex -> Alexis: George/Evelyn Grandson -> MUST_MINT (no Granddaughter token).
    for holder in ("George", "Evelyn"):
        t = find("Alex", holder, "Grandson")
        print(f"[anchor 3.2] {holder}->Alex/Alexis Grandson MUST_MINT:", end=" ")
        if t and t.must_mint and not t.flipped_token_exists:
            print(f"PASS (needed={t.needed_word})")
        else:
            print(f"FAIL (found={t})")
            ok = False

    # Anchor 3.3a: Emily/Haley -> Emil/Hayden: Sister -> no Relative_Brother -> MUST_MINT.
    for base, holder in (("Emily", "Haley"), ("Haley", "Emily")):
        t = find(base, holder, "Sister")
        print(f"[anchor 3.3] {holder}->{base} Sister MUST_MINT (no Relative_Brother):", end=" ")
        if t and t.must_mint and not t.flipped_token_exists:
            print(f"PASS (needed={t.needed_word})")
        else:
            print(f"FAIL (found={t})")
            ok = False

    # Anchor 3.3b: Penny -> Perry: Pam LittleBabyGirl -> no Relative_LittleBabyBoy -> MUST_MINT.
    t = find("Penny", "Pam", "LittleBabyGirl")
    print("[anchor 3.3] Pam->Penny/Perry LittleBabyGirl MUST_MINT (no Relative_LittleBabyBoy):", end=" ")
    if t and t.must_mint and not t.flipped_token_exists:
        print(f"PASS (needed={t.needed_word})")
    else:
        print(f"FAIL (found={t})")
        ok = False

    # Anchor 3.4: festival coverage recovered (coverage-detector blind-spot fix).
    # Data/Festivals/spring24 entry "Haley" is edited by the Hayden swap; the
    # mod resolves it to key data/spring24/Haley with a swap-Hayden variant.
    cov = coverage_index.get("data/spring24/Haley", [])
    labels = {v.variant_label for v in cov}
    print("[anchor 3.4] festival/spring24/Haley covered (swap-Hayden):", end=" ")
    if any(l and "swap-Hayden" in l for l in labels):
        print(f"PASS (labels={sorted(l for l in labels if l)})")
    else:
        print(f"FAIL (labels={sorted(str(l) for l in labels)})")
        ok = False

    # Anchor 3.5: MoviesReactions coverage recovered (Strings/MovieReactions edits
    # were mislabeled data/MoviesReactions by the enumerator). Harvey_dislike_
    # DuringMovie_2 is edited by the Hannah swap -> strings/MovieReactions/<entry>.
    cov = coverage_index.get("strings/MovieReactions/Harvey_dislike_DuringMovie_2", [])
    labels = {v.variant_label for v in cov}
    print("[anchor 3.5] MovieReactions/Harvey_dislike_DuringMovie_2 covered (swap-Hannah):", end=" ")
    if any(l and "swap-Hannah" in l for l in labels):
        print(f"PASS (labels={sorted(l for l in labels if l)})")
    else:
        print(f"FAIL (labels={sorted(str(l) for l in labels)})")
        ok = False

    print(f"\nSelf-check overall: {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content", default=DEFAULT_VANILLA_DIR,
                         help="Vanilla Content dir (default: ~/repos/Content_unpacked)")
    parser.add_argument("--self-check", action="store_true",
                         help="Run Tier-R anchor assertions and exit")
    parser.add_argument("--only", default=None,
                         help="Build just one character/asset packet (for iteration)")
    args = parser.parse_args()

    if not os.path.isdir(args.content):
        print(f"ERROR: vanilla content dir not found: {args.content}", file=sys.stderr)
        return 1

    if args.self_check:
        ok = self_check(args.content)
        return 0 if ok else 1

    total_lines, packet_count = build(args.content, only=args.only)
    print(f"\nBuilt {packet_count} packets, {total_lines} lines total, written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
