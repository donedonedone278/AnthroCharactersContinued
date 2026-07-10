# Double-check all 1.6 character sprites
- Missing haley sprite (rock rejuvenation) /assets/Characters/Haley.png. ddd fixed it by copying from winter.
- Shane passed out sprite is missing a tail. assets/LooseSprites/Cursors/Cursors_prarie_king_and_random_stuff.png
- One of Albert's flower dance sprites makes him look to the right for a frame. 
- Albert playing the drums - both sprites are identical when they could have a slight headbang.

# Dialogue


# Alexis genderswap art (report to Gav)
- The mod reflavors Alexis from a "gridball" (football) player into a "hoopball"
  (basketball) player in her dialogue, but the thrown-ball sprite is still the
  vanilla football. The projectile shown in Beach event 20 (`specificTemporarySprite
  joshFootball`) needs a basketball variant — likely lives in LooseSprites/Cursors.
- Town event 2481135 (Alex 4-heart "Dusty steak") reuses one of Alex's
  football-throw animation frames (frames 24-26; vanilla `animate Alex ... 24 25 25
  26`) for the steak moment (`showFrame Alex 26`). Because Alexis's throw frames are
  drawn as a hoopball throw rather than a gridball throw, the steak scene reads a
  little odd. Purely cosmetic — wants an art pass on those frames if we want it clean.

# SVE
Governor
Marlon
Morris
Gunther
Henchman

# Translations
