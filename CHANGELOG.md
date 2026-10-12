# Changelog

All notable changes to PyRogue. Versions follow `game/version.py`; a `vX.Y.Z` tag that doesn't
match it fails the release build. `release.yml` uses the section for the tagged version as the
GitHub Release notes.

## [Unreleased]

### Added
- Windowed renderer (`--renderer pygame`, pygame-ce): the game in its own OS window.
- Desktop packaging: a PyInstaller `--onedir` build (`packaging/pyrogue.spec`,
  `packaging/build.sh`, `packaging/build.ps1`) producing `PyRogue-windows-<version>.zip` and
  `PyRogue-linux-<version>.zip`.
- Release automation: pushing a `v*` tag builds both zips on GitHub Actions and publishes them with
  a `SHA256SUMS` file; optional itch.io upload via butler. Every CI run also builds and
  smoke-tests the frozen game on Windows and Linux.

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
