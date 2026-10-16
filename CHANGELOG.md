# Changelog

All notable changes to PyRogue. Versions follow `game/version.py`; a `vX.Y.Z` tag that doesn't
match it fails the release build. `release.yml` uses the section for the tagged version as the
GitHub Release notes.

## [Unreleased]

## [0.2.1] - 2026-10-16

A playable fix-up on top of 0.2.0: a Windows window that opens at full size, and a round of
archer and combat changes from playtesting.

### Added
- Skip a chest or shrine choice with key 4 or Space: a bad roll no longer forces a worse weapon.
- The archer's Q primes a hop, and the next movement key picks its direction. It no longer needs
  an enemy nearby.
- The archer sees two tiles further than the warrior.

### Changed
- Chasing monsters line up with you (in your row or column, with a clear line) before closing in,
  so they can't sit beside an arrow's lane and go untargeted.
- Holding a movement key doesn't keep walking while an enemy is on screen.
- The window opens at 1920x1080 (or the largest 16:9 size that fits a smaller desktop), on every
  platform. On Windows the process is DPI-aware, so display scaling doesn't shrink the window.

## [0.2.0] - 2026-10-16

A second playable build: a new archer class, a parry for the warrior, shrines, a boss that calls
for help, and bigger, more varied floors.

### Added
- The archer: a bow-carrying class with six bows (longbow, heavy crossbow, volley bow, sling,
  hunter's bow, quickdraw shortbow), each with its own mechanic. Arrows are recoverable from a
  quiver of 12 that restocks one arrow every three turns. Q hops two tiles back from a nearby
  monster, with a four-turn cooldown, and the next shot after a hop always crits.
- Leather armour, which gives defence and dodge. Archers only find leather armour.
- The warrior's Q arms a parry. The next monster hit that lands is nullified and returns the
  warrior's crit damage. It has a four-turn cooldown, shown by a bar under the warrior.
- Goblin archers from floor 4: ranged goblins that keep their distance and shoot along a clear
  row or column.
- Shrines (about 40% of non-boss floors): step onto one to take a permanent boon with a cost, such
  as Blood pact (+3 power, -15 max HP) or Quick hands (a fourth belt slot, potions heal less).
- A potion belt: potions found at full health are kept in three slots, and `h` drinks the first.
- The boss can enrage at half health and summon goblins. Its arena has a darker centre and blood
  spatters, and the stairs down are always in the boss room.
- Melee swings for every blow, drawn in code and shaped by the weapon. The struck sprite shakes,
  and enemies have health bars.
- Resting on the stairs: each descent heals 20% of max HP.
- Death screen: R restarts from the title screen.
- Floors grow with depth: rooms and the map get bigger, and the window follows the player.

### Changed
- Space waits a turn. Q is the class ability key and no longer quits; quit is on the death screen.
- Early orcs (floors 1 to 8) have 20% less HP, so the first gear drops matter less.
- Heavy armour gives defence only; leather trades some defence for dodge.
- Ranged weapons were rebalanced, and an archer starts with a longbow.
- The curses terminal build and save/load are gone. PyRogue is the window only.

### Removed
- The terminal (curses) version. PyRogue is now the window only; `--renderer` and the `RENDERER`
  setting are gone, and `windows-curses` is no longer needed anywhere.
- Save and load (`Shift+S` / `Shift+L`). A run is meant to be played in one sitting; an old
  `savegame.json` is simply ignored. `crash.log` still goes to the user data folder.

### Fixed
- A corridor could turn through the corner of one room's wall into the room next to it, leaving
  two doors side by side where one should have been flanked by wall.

### Development
- CI lints and checks formatting with ruff, type-checks with pyright and looks for unused code
  with vulture; Hypothesis property tests hunt for edge cases in dungeon generation, FOV, loot,
  settings and whole random playthroughs. Dependabot opens weekly update PRs for the pinned
  Python packages and GitHub Actions.

## [0.1.0] - 2026-10-13

The first desktop release: PyRogue in its own window, as a download that needs no Python.

### Added
- The game in its own window (pygame-ce), with Kenney's CC0 pixel-art tiles. The map scales with
  the window (40 px tiles at 1080p, 28 px on a 1366x768 laptop); F11 toggles fullscreen and
  `TILES=0` draws letters instead of tiles. The terminal version still works, with no installs.
- The stats panel is a wooden noticeboard with the stats inked on a page hanging from it: an HP bar,
  gear in its rarity colour, and a longer message log that wraps. In a tall or narrow window it
  moves under the map.
- Combat zoom in the window: when an enemy steps into melee range the map zooms in on you and it,
  with two squares of map around the fight, and zooms back out when the fight is over. Blows flash
  red with the damage rising off the target. Pressing a key skips the animation. Warrior only for
  now; `COMBAT_ZOOM=0` turns it off.
- Mouse support in the menus (hover and click). The game itself stays keyboard-only.
- Potion chests are pink and gear chests cyan, so you can tell them apart before opening them.
- Downloads for Windows and Linux (`PyRogue-<platform>-0.1.0.zip`), with an icon, saves in your
  user data folder, a `crash.log` if anything goes wrong, and `THIRD_PARTY_NOTICES.txt` plus a
  `licenses/` folder for every bundled library. The window uses a bundled font (JetBrains Mono,
  SIL OFL), so it looks the same everywhere.

### Changed
- Doors sit in the doorway, the one-tile gap in a room's wall, so a closed door really hides the
  room behind it. Corridors are routed so every opening into a room is such a doorway.
- Weapons and armour only replace what you're wearing when they're better; a worse piece is left
  behind.
- The game-over banner sits at the end of the map away from the player, instead of over them.

### For developers
- Release automation: pushing a `v*` tag builds both zips on GitHub Actions and publishes them with
  a `SHA256SUMS` file (itch.io upload is wired up but off). Tests run on every push and PR; the
  frozen Windows and Linux builds run on pushes to `main`, tags, and manual runs.

## Release checklist

The full list, with the reasons, is in `packaging/NOTES.md`. In short:

1. Move the *Unreleased* notes under `## [x.y.z] - YYYY-MM-DD`; set `game/version.py` to `x.y.z`.
2. `git tag vx.y.z && git push --tags` — CI builds, checks, and publishes.
3. Before announcing:
   - VirusTotal scan of the Windows zip / exe.
   - Fresh-machine launch on Windows with no Python installed: no console window, keys work.
   - Save/load round-trip, including a save from the previous release; saves land in the per-user
     data folder.
   - Note the settings defaults (map size, FOV, turn delay) the build ships with.
