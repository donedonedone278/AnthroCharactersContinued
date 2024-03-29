# Hello
This project is a fairly standard Content Patcher mod. If you already
know about VSCode and git, go check out the [Content Patcher mod developer
documentation](https://github.com/Pathoschild/StardewMods/blob/develop/ContentPatcher/docs/author-guide.md). It should make the structure
of this project make a lot more sense.


## Seaching Stardew's Dialogue
Problem: You want to quickly find certain words or phrases accross all of Stardew's in-game text.

Solution: Unpack your game's Content and import it into VSCode for easy searching.

Instructions:
1. Download and run [StardewXNBHack](https://github.com/Pathoschild/StardewXnbHack?tab=readme-ov-file#usage) to extract Stardew's content into a Content (Unpacked) folder. I recommend moving the Content (Unpacked) folder onto your Desktop or something accessible.
2. Download and run [VSCode](https://code.visualstudio.com/). This is a fancy text editor developed by Microsoft.
3. In VSCode, go to File -> Open Folder... -> then find your Content (Unpacked) folder. Select it, then hit "Select Folder" in the bottom right.
4. You're done. To search all files, use the magnifying glass button on the left side of the screen.
  - If you'd like to exclude non-English files from your search, click the three dots, then under "files to exclude" enter \*.\*.\*

## Seaching AnthroCharacters' Dialogue
Problem: You want to see all the dialogue that is changed in AnthroCharacters.

Solution: Download AnthroCharacters and open it in VSCode

Limitation: This won't neatly show you what the text said originally, only what it changed to. 

1. Either download the latest release of AnthroCharacters from Nexus or from [this github link](https://github.com/donedonedone278/AnthroCharacters/releases). If downloading from github, click "Source code (zip)" under Assets on the latest release.
2. Unzip the folder somewhere easily accessible (like your Desktop or Documents)
3. In VSCode, go to File -> New Window...
4. In the new window, go to File -> Open Folder... -> then find your AnthroCharacters filder. Select it, then hit "Select Folder" in the bottom right.
5. You're done. To search all files, use the magnifying glass button on the left side of the screen. Most of the character dialogue changes are going to be in assets/genderswap_dialogue.json (for now). 

If we want to make the characters individually genderswappable, we'll have to break out the changes by who each change refers to. While that's not difficult, it is extra effort. I'll hold off until we're sure it's worth it.