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