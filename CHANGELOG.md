# Changelog

All notable changes to PyRogue. Versions follow `game/version.py`; a `vX.Y.Z` tag that doesn't
match it fails the release build. `release.yml` uses the section for the tagged version as the
GitHub Release notes.

## [Unreleased]

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
