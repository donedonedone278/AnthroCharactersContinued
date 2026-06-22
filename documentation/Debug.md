# Shane passed out
debug ebi 3910674
# Penny spa event
debug ebi 38
# Leah 2 heart event
debug ebi 50
# Hayden cows event
debug ebi 14
# Rock Rejuvination
debug ebi 150938
# Desert festival
debug season spring
debug day 15
go to sleep
debug warp desert

# Change time
debug addhour
debug time <time>
debug season <season>
debug day <day>

# ---------------------------------------------------------------------------

## Verifying dialogue & string changes with `patch export` (no event needed)

You usually do NOT need to trigger the actual in-game event, wedding, or festival
to confirm a dialogue/string patch is correct. Content Patcher adds console
commands (typed into the SMAPI window) that inspect patched assets directly:

- `patch summary` — lists every patch, current token values, and whether each
  patch's `When` conditions match right now. Use it to confirm the right
  conditional branch is active for your config (e.g. which marriage-line patch
  matched).
- `patch export <AssetName>` — writes the fully-patched asset (all mods applied)
  to a file and prints the path; open it and read the exact final values.
- `patch update` — forces a token/condition re-check after changing config
  mid-session.

**General principle for testing any EditData / string change:** set the relevant
config, load a save, then `patch export` the target asset and read the result —
far faster and more reliable than reproducing the in-game moment. Example
(verify Lewis's marriage pronouncement for the current config, no wedding needed):

```
patch export Strings/StringsFromCSFiles
```

then check `Utility.cs.5371 / 5373 / 5375 / 5377` in the exported file. Other handy
targets: `Characters/Dialogue/<Name>`, `Data/Events/<Location>`,
`Strings/StringsFromMaps`, `Strings/StringsFromCSFiles`. (Note: some tokens only
resolve once a save is loaded, so load a save before exporting.)

# ---------------------------------------------------------------------------

## Dialogue baseline

This mod's overridden vanilla text (`Characters/Dialogue/*`, `Data/Events/*`,
`Strings/*`) is synced to Stardew Valley **1.6.15** — see
`tools/i18n/dialogue_baseline.txt`. The base game occasionally ships
typo/grammar/wording fixes to lines we override, so periodically re-check
our overrides against current vanilla text.

To re-run the check: `python3 tools/i18n/vanilla_diff.py --mode current`
(needs an unpacked vanilla `Content` dir, default `~/repos/Content_unpacked`;
override with `--vanilla-content`). It writes a Markdown report to
`claude-documentation/reports/vanilla-diff-<baseline>.md` listing every line
where our override no longer matches vanilla, ranked (heuristically) by
likely-upstream-fix vs likely-our-own-edit — a human still reviews each one.
When a future pass has both an old and a new vanilla snapshot, use
`--mode oldnew --old-content <dir> --new-content <dir>` instead for a
clean, low-noise old-vs-new vanilla diff, then bump
`tools/i18n/dialogue_baseline.txt` to the new version.