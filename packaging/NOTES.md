# Packaging notes

How PyRogue becomes a double-clickable folder. Owned by WS-E (spec, build scripts) and WS-F
(release workflow). The spec, not this file, is the source of truth — this explains why it looks
the way it does.

## Files

| File | What it does |
|---|---|
| `pyrogue.spec` | The PyInstaller build. Committed config, never a remembered CLI line. |
| `build.sh` / `build.ps1` | Clean `build/` + `dist/`, run the spec, copy `LICENSE` + `README.txt` into the bundle, run `collect_licenses.py` (third-party notices + `licenses/`), zip it as `dist/PyRogue-<platform>-<version>.zip`. Keep the two in step. |
| `version_info.py` | Reads `game/version.py` (the only place the version lives) and generates the Windows file-properties resource at build time. `--print-version` prints just the version for scripts/CI. |
| `make_zip.py` | Zips the bundle with one top-level `PyRogue/` folder. Shared by both build scripts. |
| `README.txt` | The player-facing readme that ships inside the zip. |
| `../tests/test_frozen_smoke.py` | Launches `dist/PyRogue/` headless; skipped when there is no build. |
| `../.github/workflows/release.yml` | Tag `v*` → both zips + `SHA256SUMS` on a GitHub Release (+ itch.io). Manual run → zips as workflow artifacts only. |
| `../.github/workflows/ci.yml` `frozen-build` | Builds and smoke-tests both platforms on every push/PR. |

```bash
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./packaging/build.sh                          # Linux  -> dist/PyRogue/PyRogue
powershell -File packaging\build.ps1          # Windows -> dist\PyRogue\PyRogue.exe
.venv/bin/python -m unittest tests.test_frozen_smoke -v
```

PyInstaller cannot cross-compile: the Linux box only builds the Linux bundle. The Windows exe is
built by GitHub Actions — run the `release` workflow by hand (Actions → release → Run workflow) to
get one without tagging, or grab the `frozen-build` artifact from any CI run.

## Antivirus rules (desktop plan §2.5) — non-negotiable

1. **Never `--onefile`.** The onefile bootloader unpacks itself to a temp dir and then executes
   what it unpacked — byte-for-byte a malware dropper. Defender, Norton, McAfee, Kaspersky and
   Avast all flag legitimate onefile builds. The spec has no onefile path; don't add one.
2. **Always `upx=False`.** UPX-packed executables are an AV trigger on their own. Both `EXE` and
   `COLLECT` set it; `tests/test_frozen_smoke.py` fails if `upx=True` ever appears in the spec.
3. **VirusTotal before every public release** (checklist below). Report false positives to the
   vendor rather than "fixing" them with packers or obfuscation.
4. Code signing (~$200–500/yr) is the only real fix for SmartScreen's "unknown publisher" warning.
   That's a Phase 4 / "if we charge money" decision; `README.txt` tells players how to get past it.

## Why onedir

Besides AV: start-up is fast (nothing to unpack on every launch — measured ~0.15–0.26 s to window
on Linux), files can be patched individually, and pygame-ce/SDL stay separate, replaceable shared
libraries, which is what the LGPL asks of a program that links them. The cost is a folder instead of
a single file — which is what itch.io and every Ren'Py game ship anyway. Players must keep
`PyRogue.exe` next to `_internal/`.

## Current build facts (2026-10-12, Linux, Python 3.14.7, PyInstaller 6.22.3)

- Unzipped `dist/PyRogue/`: **~40 MB**; zip **~17 MB** (budget: < 120 MB). Biggest items:
  `pygame_ce.libs` (SDL + codecs, 13 MB), `libpython3.14` (6 MB), OpenSSL (7 MB, pulled in by the
  stdlib — a candidate to trim if size ever matters).
- Start-up: window created ~0.15–0.26 s after launch (budget: < 2 s). Windows numbers come from CI
  and a real machine; Defender scanning makes the very first launch slower.
- Excluded on purpose: `tkinter`, `numpy`, `unittest`, `test`, `pydoc`, `doctest`, `curses`
  (the curses renderer is deleted; the game is pygame-only), `tcod`, `render.tcod_render`, `pygame.tests`/`examples`/`docs`.

## Things the exe currently relies on from other workstreams

- **python-dotenv (WS-B).** `main.py` still imports `dotenv`, so the bundle includes it (PyInstaller
  finds it by import scan; nothing in the spec names it). Once `game/settings.py`'s `load()` replaces
  it, drop `python-dotenv` from `requirements.txt` and confirm `dotenv` is gone from the bundle
  (`pyi-archive_viewer --list build/pyrogue/PYZ-00.pyz | grep dotenv`).
- **`.env` is not shipped.** The frozen game uses the code defaults (50x20 map), not the repo's
  `.env` (40x20). If the release should ship different defaults, decide that explicitly and add the
  file next to the exe in the build scripts — it's a release checklist item, not an accident.
- **Crash log (WS-B).** Must go to `game.paths.user_data_dir()`, never the CWD or the
  install folder.

## Adding a data file

1. Put it under `assets/` (WS-C owns that directory). The spec bundles all of `assets/` as
   `<bundle>/_internal/assets/` whenever the folder exists — no spec change needed for new files in
   it.
2. Read it **only** through `game.paths.resource_path('assets', ...)`. Never `open('assets/...')`,
   never a path relative to `__file__` or the CWD: in the frozen build the CWD is wherever the
   player launched from, and the files live under `sys._MEIPASS`.
3. A data file outside `assets/` needs a `datas.append((src, dest_dir))` line in `pyrogue.spec`
   *and* a `resource_path` call that matches `dest_dir`.
4. A Python module imported dynamically (by string, `importlib`, plugin discovery) needs an entry in
   `hiddenimports`. Ordinary imports, including ones inside functions, are found automatically.
5. Rebuild, then check it is really there: `ls dist/PyRogue/_internal/assets` and run the smoke
   test. A missing file should produce a `crash.log` (WS-B), never a silent exit.

The app icon: drop `assets/icon.ico` (or `packaging/icon.ico`) and the spec picks it up.

## Windows crash dialog and the smoke test

A windowed (`console=False`) Windows build that dies with an unhandled exception shows PyInstaller's
modal "Unhandled exception" dialog. Setting `disable_windowed_traceback=True` doesn't remove the
dialog, it only replaces the traceback with a "disabled" message, so the spec keeps the traceback.
The catch: a dialog keeps the crashed process alive, so "still running after N seconds" would read
as success. `test_frozen_smoke.py` therefore also checks, on Windows, that the process owns no
visible window (under SDL's dummy driver the game itself opens none). Better still would be for
`main.py` to catch and log exceptions itself (`game.crashlog`), so the bootloader never sees them.

## Release checklist

Cutting a release (no step needs this machine):

1. Move `CHANGELOG.md`'s *Unreleased* notes under a new `## [x.y.z] - YYYY-MM-DD` heading.
2. Set `__version__ = 'x.y.z'` in `game/version.py`. Commit.
3. `git tag vx.y.z && git push --tags`. `release.yml` fails fast if the tag and `game/version.py`
   disagree, builds both platforms, runs the frozen smoke test, and publishes the zips +
   `SHA256SUMS`. A version with letters in it (`0.2.0rc1`) becomes a GitHub pre-release.
4. itch.io (optional): set the `BUTLER_API_KEY` secret and the `ITCH_PROJECT` repo variable
   (`<itch-user>/pyrogue`); tagged releases then push channels `windows` and `linux`. No secret, no
   push — the job just skips.

Before announcing it:

- [ ] **VirusTotal**: upload the Windows zip (and `PyRogue.exe` on its own). Note detections in the
      release; report false positives to the vendors.
- [ ] **Fresh-machine launch**: a Windows box (or VM) that never had Python. Unzip to a normal user
      folder *and* to `C:\Program Files\PyRogue` (read-only install dir). Double-click: window
      opens, **no console window**, title screen responds to keys and to the close button.
- [ ] **Crash path**: a broken build (e.g. a renamed asset) leaves `%APPDATA%\PyRogue\crash.log`.
- [ ] **Settings defaults**: record which map size / FOV / turn delay the build ships with (see the
      `.env` note above).
- [ ] **Licences**: the zip has `LICENSE`, `README.txt`, `THIRD_PARTY_NOTICES.txt` and `licenses/`
      (added by `collect_licenses.py`). If `requirements.txt` moved to a new pygame-ce, check
      `NoticesTest` passed on *both* OSes in CI — it only sees the libraries of the OS it runs on.
- [ ] Linux zip: `unzip` then `./PyRogue/PyRogue` on a desktop with no Python dev setup.

## Phase 4 (not now)

Nuitka `--standalone` comparison (size, start-up, AV hits) — report, don't switch, without a
decision. macOS `.app` + notarization needs an Apple developer account.
