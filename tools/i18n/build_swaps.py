"""
Stage-0 generator for the exhaustive dialogue review (see
claude-documentation/plans/exhaustive-dialogue-review.md).

Emits tools/i18n/swaps.json: the 12 genderswaps, each with the facts a Stage-2
reviewer needs to judge a line that references the swapped character:

  - toggle            CP config key that activates the swap ("<Base> to <New>")
  - direction         "M->F" or "F->M"
  - base / swap       the two character names
  - nicknames         non-engine display nicknames / wordplay (base side)
  - dynamic_tokens    the {{<token>}} names content.json flips for this swap
                      (pulled live from content.json -- these already exist as
                      flipping tokens; a reviewer cross-checks coverage against
                      them)
  - relatives         §2 relationship map: who refers to the char relationally,
                      the vanilla kinship label, the flipped word needed, whether
                      a vanilla Relative_* token exists (else text must be minted),
                      and notes (free-text / gap)
  - romance_assets    vanilla targets carrying this char's romance/marriage text
  - base_species / swap_species / species_changes
  - swap_body_words   the swap's correct body-word vocabulary (species-map.md)

The §2 map, species, nicknames and romance assets are curated constants here
(sourced from the plan + reference/species-map.md); only dynamic_tokens are
derived from content.json so they stay in sync as tokens are added.

Run:  python3 tools/i18n/build_swaps.py   (writes tools/i18n/swaps.json)
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CONTENT = os.path.join(REPO, "content.json")
OUT = os.path.join(HERE, "swaps.json")


# Per-swap curated facts. relatives entries:
#   holder       -- the NPC whose dialogue / FriendsAndFamily carries the reference
#   label        -- vanilla kinship word/token
#   needed       -- the flipped word the swap requires
#   has_token    -- a vanilla Relative_* token exists for `needed` (repoint) vs.
#                   must mint text (False)
#   kind         -- "structured" (Data/Characters FriendsAndFamily) or "free-text"
#   note         -- caveats / known gaps (e.g. the un-edited Kent label)
SWAPS = {
    "Abigail to Albert": {
        "direction": "F->M", "base": "Abigail", "swap": "Albert",
        "nicknames": ["Abby"],
        "base_species": "Dragon", "swap_species": "Dragon", "species_changes": False,
        "swap_body_words": ["scales", "horns", "wings", "claws", "fangs", "tail", "snout"],
        "relatives": [
            {"holder": "Pierre", "label": "Daughter", "needed": "Son",
             "has_token": True, "kind": "structured", "note": ""},
            {"holder": "Caroline", "label": "daughter", "needed": "son",
             "has_token": True, "kind": "free-text",
             "note": "structured entry empty; 'my daughter' appears in dialogue"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueAbigail",
                           "Data/EngagementDialogue:Abigail0/Abigail1"],
    },
    "Emily to Emil": {
        "direction": "F->M", "base": "Emily", "swap": "Emil",
        "nicknames": [],
        "base_species": "Cat", "swap_species": "Parrot", "species_changes": True,
        "swap_body_words": ["feathers", "beak", "wings", "talons"],
        "relatives": [
            {"holder": "Haley", "label": "Sister", "needed": "brother",
             "has_token": False, "kind": "structured",
             "note": "no vanilla Relative_Brother token -- must mint text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueEmily",
                           "Data/EngagementDialogue:Emily0/Emily1"],
    },
    "Haley to Hayden": {
        "direction": "F->M", "base": "Haley", "swap": "Hayden",
        "nicknames": [],
        "base_species": "Cat", "swap_species": "Eagle", "species_changes": True,
        "swap_body_words": ["feathers", "beak", "talons", "wings"],
        "relatives": [
            {"holder": "Emily", "label": "Sister", "needed": "brother",
             "has_token": False, "kind": "structured",
             "note": "no vanilla Relative_Brother token -- must mint text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueHaley",
                           "Data/EngagementDialogue:Haley0/Haley1"],
    },
    "Leah to Liam": {
        "direction": "F->M", "base": "Leah", "swap": "Liam",
        "nicknames": [],
        "base_species": "Fox", "swap_species": "Bear", "species_changes": True,
        "swap_body_words": ["fur", "paws", "claws", "broad muzzle", "rounded ears"],
        "relatives": [],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueLeah",
                           "Data/EngagementDialogue:Leah0/Leah1"],
    },
    "Maru to Marcus": {
        "direction": "F->M", "base": "Maru", "swap": "Marcus",
        "nicknames": [],
        "base_species": "Rabbit", "swap_species": "Rabbit", "species_changes": False,
        "swap_body_words": ["fur", "paws", "long upright ears", "whiskers"],
        "relatives": [
            {"holder": "Robin", "label": "Daughter", "needed": "Son",
             "has_token": True, "kind": "structured", "note": ""},
            {"holder": "Sebastian", "label": "HalfSister", "needed": "HalfBrother",
             "has_token": True, "kind": "structured", "note": ""},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueMaru",
                           "Data/EngagementDialogue:Maru0/Maru1"],
    },
    "Penny to Perry": {
        "direction": "F->M", "base": "Penny", "swap": "Perry",
        "nicknames": [],
        "base_species": "Sheep", "swap_species": "Bull", "species_changes": True,
        "swap_body_words": ["hide", "horns", "hooves", "snout", "tail"],
        "relatives": [
            {"holder": "Pam", "label": "LittleBabyGirl", "needed": "little baby boy",
             "has_token": False, "kind": "structured",
             "note": "no vanilla LittleBabyBoy token -- must mint text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialoguePenny",
                           "Data/EngagementDialogue:Penny0/Penny1"],
    },
    "Elliott to Ellen": {
        "direction": "M->F", "base": "Elliott", "swap": "Ellen",
        "nicknames": [],
        "base_species": "Lion", "swap_species": "Horse", "species_changes": True,
        "swap_body_words": ["coat", "fur", "mane", "hooves", "long muzzle", "tail"],
        "relatives": [],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueElliott",
                           "Data/EngagementDialogue:Elliott0/Elliott1"],
    },
    "Shane to Shauna": {
        "direction": "M->F", "base": "Shane", "swap": "Shauna",
        "nicknames": [],
        "base_species": "Lizard", "swap_species": "Lizard", "species_changes": False,
        "swap_body_words": ["scales", "claws", "tail", "snout"],
        "relatives": [
            {"holder": "Marnie", "label": "Nephew", "needed": "Niece",
             "has_token": True, "kind": "structured", "note": ""},
            {"holder": "Jas", "label": "(guardian)", "needed": "(guardian)",
             "has_token": False, "kind": "free-text",
             "note": "Jas refers to Shane; check her dialogue/events"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueShane",
                           "Data/EngagementDialogue:Shane0/Shane1"],
    },
    "Sebastian to Sabrina": {
        "direction": "M->F", "base": "Sebastian", "swap": "Sabrina",
        "nicknames": ["Sebby"],
        "base_species": "Wolf", "swap_species": "Wolf", "species_changes": False,
        "swap_body_words": ["fur", "paws", "claws", "fangs", "snout", "tail"],
        "relatives": [
            {"holder": "Robin", "label": "Son", "needed": "Daughter",
             "has_token": True, "kind": "structured", "note": ""},
            {"holder": "Maru", "label": "HalfBrother", "needed": "HalfSister",
             "has_token": True, "kind": "structured", "note": ""},
            {"holder": "Demetrius", "label": "stepson", "needed": "stepdaughter",
             "has_token": False, "kind": "free-text", "note": "free-text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueSebastian",
                           "Data/EngagementDialogue:Sebastian0/Sebastian1"],
    },
    "Sam to Samantha": {
        "direction": "M->F", "base": "Sam", "swap": "Samantha",
        "nicknames": ["Sammy", "Samson"],
        "base_species": "Cheetah", "swap_species": "Cheetah", "species_changes": False,
        "swap_body_words": ["fur", "paws", "claws", "spots", "whiskers", "tail"],
        "relatives": [
            {"holder": "Jodi", "label": "EldestSon", "needed": "eldest daughter",
             "has_token": False, "kind": "structured",
             "note": "no vanilla EldestDaughter token -- must mint text"},
            {"holder": "Kent", "label": "EldestSon", "needed": "eldest daughter",
             "has_token": False, "kind": "structured",
             "note": "ANCHOR §3.1: Kent's label NOT edited (gap) -- both parents tag Sam"},
            {"holder": "Vincent", "label": "big brother", "needed": "big sister",
             "has_token": False, "kind": "free-text", "note": "free-text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueSam",
                           "Data/EngagementDialogue:Sam0/Sam1"],
    },
    "Harvey to Hannah": {
        "direction": "M->F", "base": "Harvey", "swap": "Hannah",
        "nicknames": [],
        "base_species": "Goat", "swap_species": "Deer", "species_changes": True,
        "swap_body_words": ["fur", "hooves", "antlers", "big ears", "muzzle"],
        "relatives": [],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueHarvey",
                           "Data/EngagementDialogue:Harvey0/Harvey1"],
    },
    "Alex to Alexis": {
        "direction": "M->F", "base": "Alex", "swap": "Alexis",
        "nicknames": [],
        "base_species": "Dog", "swap_species": "Dog", "species_changes": False,
        "swap_body_words": ["fur", "paws", "snout", "fluffy mane"],
        "relatives": [
            {"holder": "George", "label": "Grandson", "needed": "granddaughter",
             "has_token": False, "kind": "structured",
             "note": "no vanilla Granddaughter token -- must mint text"},
            {"holder": "Evelyn", "label": "Grandson", "needed": "granddaughter",
             "has_token": False, "kind": "structured",
             "note": "no vanilla Granddaughter token -- must mint text"},
        ],
        "romance_assets": ["Characters/Dialogue/MarriageDialogueAlex",
                           "Data/EngagementDialogue:Alex0/Alex1"],
    },
}


def dynamic_tokens_by_toggle(content_path: str) -> dict[str, list[str]]:
    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)
    by_toggle: dict[str, set[str]] = defaultdict(set)
    for tok in content.get("DynamicTokens", []):
        when = tok.get("When")
        name = tok.get("Name")
        if not when or not name or len(when) != 1:
            continue
        (key, val), = when.items()
        if key in SWAPS and val is True:
            by_toggle[key].add(name)
    return {k: sorted(v) for k, v in by_toggle.items()}


def main() -> None:
    tokens = dynamic_tokens_by_toggle(CONTENT)
    out = {"_doc": "Stage-0 swap facts for the exhaustive dialogue review. "
                    "Generated by tools/i18n/build_swaps.py; dynamic_tokens are "
                    "pulled live from content.json.",
           "swaps": []}
    for toggle, facts in SWAPS.items():
        entry = {"toggle": toggle}
        entry.update(facts)
        # MarriageLine is the shared spouse token, not specific to one swap;
        # keep only the per-character flipping tokens.
        entry["dynamic_tokens"] = [t for t in tokens.get(toggle, [])
                                   if t != "MarriageLine"]
        out["swaps"].append(entry)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT} ({len(out['swaps'])} swaps)")


if __name__ == "__main__":
    main()
