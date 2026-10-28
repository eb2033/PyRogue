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
- [ ] **Browser zip licences**: `dist/PyRogue-web-<version>.zip` has `LICENSE`,
      `THIRD_PARTY_NOTICES.txt` and `licenses/` at its root (the build fails otherwise). After a
      pygbag or pygame-ce bump, re-check the component list (see **Browser build**).
- [ ] Linux zip: `unzip` then `./PyRogue/PyRogue` on a desktop with no Python dev setup.

## Browser build (itch.io)

A separate build from the desktop one: the same game under pygbag (CPython compiled to WebAssembly,
pygame-ce in the browser), uploaded to itch.io as an HTML5 project. `build_web.sh` / `build_web.ps1`
stage `build/web/` (`main.py` from `web/main.py`, plus `game/`, `render/`, `web/` and only the
assets the game loads: `tiles.json`, the Kenney sheets with their `License.txt`, `blood/`, and
`fonts/` with `OFL.txt`; no icons, no `ASSETS.md`), run `python -m pygbag --build --ume_block 0
--template packaging/web/index.tmpl build/web`, then `packaging/web/make_runtime.py` adds the runtime
(below) and writes `dist/PyRogue-web-<version>.zip`. The scripts fail if `web/main.py` is missing; the
Python step fails if the zip lacks `index.html`, `LICENSE`, `THIRD_PARTY_NOTICES.txt` or
`licenses/` at its root, is over 15 MB or 100 files, or if the
runtime it downloads is not the pinned one. The first build needs network access (pygbag's favicon, and
the runtime, cached afterwards in `build/web-runtime-cache/`); pygbag is pinned in
`requirements-dev.txt`.

```bash
./packaging/build_web.sh                      # -> dist/PyRogue-web-<version>.zip
powershell -File packaging\build_web.ps1      # the same on Windows
```

- **The zip carries its own runtime** (`rt/`, 10 files, 8.2 MB), so a player downloads about 8.3 MB from
  one host instead of 11.4 MB from `pygame-web.github.io` (pygbag's stock page). pygbag stays pinned at
  0.9.3 (CPython 3.12.12, pygame-ce 2.5.7); `make_runtime.py` checks every upstream file against a
  SHA-256 and asserts that each patch finds its target, so a changed upstream file fails the build.
  Why it is smaller and faster (measured, cold cache, 9 Mbit/s, 170 ms RTT; `web_build_plan.md` section 9):
  - `main.wasm` and `main.data` ship gzipped (`*.gz`) and are gunzipped in the page with
    `DecompressionStream`, so their size on the wire does not depend on whether the host compresses
    (nobody here could confirm what itch.io does with `.gz` files). A host that decodes them on the way
    out is fine too: the loader checks for the gzip magic. The glue script `main.js` and `cpythonrc.py` are gzipped the same way.
  - `main.data` (the stdlib) is repacked: upstream stores it LZ4-compressed, which gzip cannot shrink
    (4.5 MB gzipped); decoded, stripped of the unused 3.3 MB `FreeSerif.ttf` and of modules no session
    imports (`xml`, `multiprocessing`, `curses`, `sqlite3`, `pydoc`, `optparse`, `plistlib`,
    `pkg_resources`, the xterm parser) and gzipped it is 1.56 MB. The patched loader writes the files
    straight into the in-memory filesystem (no LZ4 recompression).
  - The xterm.js console and its sixel addon are not loaded (`data-os="snd,gui"`), and `print` still
    goes nowhere useful.
  - `packaging/web/prefetch.js` (inlined into `index.html`) starts every download at the first line of
    the page instead of down a chain of script loads, and holds back the pygame wheel and the app archive
    (needed only after the interpreter has booted) until the wasm and the stdlib are in, so they do not
    slow them down. It wraps `window.fetch` so pygbag's own later requests get those responses.
  - pygbag's package installer is pointed at `rt/` (`aio/pep0723.py` is patched inside the bundle), and
    a one-entry index serves the wheel; nothing is fetched from `pygame-web.github.io` at run time.
- **Unverified on itch.io itself:** all measurements are from headless Chromium 156 behind a Chrome
  DevTools network throttle against a local static server. Not tested: itch's own CDN (its latency,
  whether it uses HTTP/2, and whether it compresses `.js`/`.html`/`.json`: the page works either way,
  but an uncompressed `pythons.js` + `index.html` + `.json` is about 85 KB more), Safari and Firefox
  (`DecompressionStream('gzip')` needs Chrome 80, Safari 16.4 or Firefox 113), and phones.
- **Licence notices:** the zip redistributes pygbag's prebuilt binaries (CPython and pygame-ce
  compiled to WebAssembly, with SDL2, SDL2_image/mixer/ttf, FreeType, HarfBuzz, libvorbis, zlib,
  bzip2, OpenSSL, SQLite, Expat and others linked in), so `make_runtime.py` also puts `LICENSE`,
  `packaging/web/THIRD_PARTY_NOTICES.txt` and `packaging/web/licenses/*.txt` (35 files) at the zip
  root, and fails if any is missing or if the notices and `licenses/` disagree. The scripts then run
  `make_runtime.py --verify dist/<zip>` on the finished file. `tests/test_web_notices.py` guards the
  table. The component list was compiled from the runtime's build recipes (pygame-web/python-wasm-sdk,
  pygbag, pygame-ce 2.5.7) and from version strings, symbols and source paths inside the binaries,
  not from an audit; rows say "may be present" or "version not verified" where that is all we know.
  In this browser build pygame-ce is the separate file `rt/cp312/pygame_ce-*.whl`, which is how the
  LGPL replacement clause is met (the notices say how). The extra files are harmless to itch.io
  (47 in all, limit 1000; only `index.html` is special).
- **Re-pinning:** when pygbag moves past 0.9.3, change `PYGBAG`, `WHEEL`, the hashes and the patch
  strings in `make_runtime.py` together, **re-check the component list and versions in
  `THIRD_PARTY_NOTICES.txt` (re-run the version-string inspection of `main.wasm` and the wheel's
  `.so`, add or drop rows and licence files)**, and re-run the smoke test below.
- **itch.io upload:** new project > kind of project: **HTML** > upload the zip > tick **This file
  will be played in the browser** > viewport **1280x720** > enable the **fullscreen button** > save.
  `index.html` must be at the zip root (the script checks).
- **Keyboard focus** in the itch iframe may need one click on the game first.
- **F11 does nothing in the browser**; use the itch fullscreen button.
- **`print` goes nowhere**: with the console dropped there is no in-page terminal. Use
  `platform.window.console.log(...)` to log to DevTools.
- **Never call `pygame.Window`, `display.toggle_fullscreen` or `Window.set_fullscreen` in web code.**
  Merely creating a `pygame.Window` (even via `from_display_module()`) raises an uncatchable JS
  "function signature mismatch" that kills the app. `hasattr(pygame, 'Window')` is True in the browser,
  so it is no guard.
- **Local test:** unzip `dist/PyRogue-web-<version>.zip` (or serve `build/web/build/web/`, which holds
  the same files) with any static server, e.g. `python -m http.server -d build/web/build/web 8000`, and
  open `http://localhost:8000`. (`python -m pygbag --port 8000` would serve pygbag's stock page and the
  CDN runtime, not this build.) The page plays on `localhost` and `127.0.0.1` alike.
- **Smoke test after touching `packaging/web/`:** load the page in Chromium, wait for the 1280x720
  canvas, press Enter twice, walk with `wasd`, and expect no console error except pygbag's
  `PyMain: BrowserFS not found`.

## Phase 4 (not now)

Nuitka `--standalone` comparison (size, start-up, AV hits) — report, don't switch, without a
decision. macOS `.app` + notarization needs an Apple developer account.
