# Out of the Terminal — PythonRogue as a Desktop `.exe`

Plan date: 2026-10-06. Successor to `going_graphical.md` (2026-08-26), which surveyed the options;
this file commits to one and breaks the work into parallel workstreams.

Goal, in one sentence: **a double-clickable `PyRogue.exe` that opens its own window, with the game
still written in Python end to end.**

---

## 0. The decision

| Question | Answer | Why, in short |
|---|---|---|
| Rendering engine | **`pygame-ce` 2.5.8** — new `render/pygame_render.py` | Real shipping track record, audio/mouse/sprites/web, one native wheel, no `numpy`. See §2. |
| What happens to `render/tcod_render.py` | Retired (deleted) at the end of Phase 1 | Its two selling points (FOV, pathfinding) were already written by hand in stdlib. See §2.3. |
| Packager | **PyInstaller 6.22.3, `--onedir --noupx --windowed`**, spec file committed | Industry-default for Python games; `--onedir` is the single biggest antivirus mitigation. |
| Nuitka | Evaluated after v1 ships, not before | Faster/cleaner binary, but slow builds + C toolchain; not worth blocking a first release. |
| Where the `.exe` is built | **GitHub Actions `windows-latest`** | PyInstaller cannot cross-compile. This repo develops on Arch Linux, so CI is not optional. |
| Terminal build | **Kept, forever** | It is the stdlib-only reference implementation and the thing CI can test cheaply. `--renderer curses` stays. |
| Primary distribution | itch.io (butler), zip + installer later | No store review, no cert required to get it into a friend's hands. Steam is a Phase 4 question. |

### 0.1 Dependency policy — the constraint this plan changes

`CLAUDE.md` currently says *standard library only* for everything under `game/` and
`render/curses_render.py`. That rule is **kept and narrowed, not dropped**:

- `game/**` — stdlib only. Still true after this work. No `pygame` import may ever appear there.
- `render/curses_render.py` — stdlib only. Unchanged.
- `render/pygame_render.py`, `render/ui.py`, `render/tileset.py` — **allowed `pygame-ce`.**
- `main.py` — loses its `python-dotenv` dependency (WS-B replaces it with ~15 lines of stdlib), so
  `python main.py` finally works outside the venv. Net dependency count for the terminal path: zero.

That is `going_graphical.md` §F.1's resolution, now binding. WS-G writes it into `CLAUDE.md`.

---

## 1. Verified environment facts (checked 2026-10-06 on this machine)

Do not re-derive these; they are measured, not assumed.

- Project interpreter is **Python 3.14.7** (`.venv/bin/python`). Installed: `python-dotenv`, `dotenv`,
  `joblib`, `curse`. No game dependencies yet.
- `pygame-ce 2.5.8` has a **cp314 wheel** and was installed into a throwaway venv and verified to
  render **headless** (`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`): `pygame.display.set_mode`,
  `pygame.font`, blit and flip all worked, SDL 2.32.10. **This is the keystone fact of the plan: the
  graphical renderer is unit-testable in CI, which the curses renderer never was.**
- `pyinstaller 6.22.3` declares `Requires-Python <3.16,>=3.8` and classifiers through 3.15 → 3.14 is
  supported.
- `tcod 21.2.1` ships a `cp310-abi3` wheel (so it would work), but requires `numpy>=1.21.4` + `cffi`.
- `nuitka 4.2.2` is **source-only** (no wheel) → needs a working C toolchain wherever it runs.
- `pygbag 0.9.3` is `py3-none-any` but its *in-browser* CPython targets 3.12/3.13; a web build would
  need a pinned 3.13 venv. Phase 4 only.
- `game/state.py:24` has `SAVE_PATH = 'savegame.json'` — **relative to the current working
  directory.** In a frozen app installed under `C:\Program Files\...` this fails or writes somewhere
  surprising. WS-B owns the fix.
- `.gitignore` contains `*.md`, so **this plan file is untracked by default** (`git check-ignore`
  confirms). Also, stale `__pycache__/*.pyc` files *are* tracked in git. Both are listed as cleanup
  items (§9, WS-E).

---

## 2. Research: how Python games actually get shipped

The question behind the plan was "what do indie games that use Python in their engine actually use,
and how did they do it?" Three answers, in descending order of how much they prove.

### 2.1 Ren'Py — the strongest proof that this is a solved problem

Ren'Py is **Python on top of `pygame_sdl2`**, open source, free for commercial use, currently at
8.5.3 (2026-05-15). Thousands of commercial titles ship on it — *Doki Doki Literature Club!*,
*Analogue: A Hate Story*, *Katawa Shoujo* — on Steam and itch.io, as ordinary `.exe` installs.

What they did: Ren'Py has a **built-in "Build Distribution"** step that emits a cross-platform zip
*and* a Windows installer, rolling images/audio into archive files. Lessons we copy directly:

1. The shipped artifact is a **folder with a launcher `.exe`**, not a single self-extracting binary.
2. **Assets live in archives/data dirs next to the binary**, resolved relative to the install root —
   never relative to the CWD (our `savegame.json` bug, §1).
3. Build is a **project-level committed configuration**, not a command someone remembers to type.
   → WS-E commits `packaging/pyrogue.spec`, not a CLI invocation in a README.

### 2.2 pygame proper — a real, if modest, commercial history

- **Frets on Fire** (Unreal Voodoo) — pygame; won Assembly 2006, millions of downloads.
- **Galcon / Galcon 2** (Phil Hassey) — pygame, sold commercially, originally frozen with
  py2exe/py2app (the PyInstaller of its day).
- **Dangerous High School Girls in Trouble!** (Mousechief) — pygame, sold on Steam, Writers Guild
  nominee, Casual Games Association "Most Innovative Game".
- **7 Grand Steps** (Mousechief) — pygame, IGF 2013 finalist.
- Modern practice, per pygame community and itch.io threads: **PyInstaller** to freeze, `pynsist` if
  you want an installer, and **SteamworksPy** (Python bindings to the Steamworks C++ SDK, maintained,
  last touched 2026-05) if you want achievements. Steamworks integration is never required to ship.

### 2.3 python-tcod — great library, no shipping record

Searched specifically for commercially released roguelikes built on `python-tcod`/libtcod. Found
tutorials (rogueliketutorials.com, RogueBasin), sample repos, and hobby projects — **no commercial
Steam release**. That's not a knock on the library; it is the canonical teaching tool. But it is a
weak foundation for "ship a product", and the two concrete things it was recommended for in
`going_graphical.md` §B.1 are **already done by hand here**:

- Recursive shadowcasting FOV: implemented, in stdlib, in `game/fov.py`.
- Pathfinding: deliberately *not* wanted — `game/monster.py`'s naive 4-way chase is the spec's
  behaviour and `CLAUDE.md` documents the stall-behind-a-wall case as intended.

So tcod's remaining value is "grid console with a tilesheet", which pygame-ce does by blitting a
surface per cell — about 20 lines — while also giving audio, mouse, free-form sprites, particle/juice
headroom, and the only credible browser path. And it does it without pulling `numpy` (a ~40 MB
addition to the bundle and a second native dependency to freeze).

**Therefore this plan reverses `going_graphical.md` §0's recommendation.** That file stays as the
research record; this one is the decision.

### 2.4 Panda3D / others, for completeness

Panda3D is a C++ engine with Python as the authoring language — Disney's *Toontown Online* and
*Pirates of the Caribbean Online*, KingsIsle's *Wizard101*. Proof that Python-authored games scale to
commercial MMOs, irrelevant to a 2D grid roguelike. Similarly: *EVE Online* (Stackless Python),
*Civilization IV* and *Battlefield 2* (Python as the scripting layer over a C++ engine). The pattern
across all of them — **Python owns the game logic, a C library owns the window** — is exactly the
architecture this repo already has via the `Renderer` interface.

### 2.5 The antivirus problem (unchanged from `going_graphical.md` §C.2, restated as a rule)

PyInstaller's `--onefile` bootloader unpacks-then-executes, which is byte-for-byte the behaviour of a
malware dropper; Defender/Norton/McAfee/Kaspersky/Avast all flag legitimate builds. Nuitka's
`--onefile` has the same issue. Rules for this project:

1. **Never ship `--onefile`.** `--onedir` (PyInstaller) / `--standalone` (Nuitka) only.
2. **Always `--noupx`.** UPX compression is itself a detection trigger.
3. Check the artifact on VirusTotal before any public release; report false positives.
4. Code signing (~$200–500/yr) is the only real fix and is a Phase 4 / "if we charge money" decision.

---

## 3. Target architecture

```
main.py                     renderer selection + the (unchanged) renderer-agnostic loop
game/                       stdlib only, (x, y), no pygame — unchanged by this work
  paths.py        [NEW]     resource_path() / user_data_dir() / save_path()  (WS-B)
  crashlog.py     [NEW]     excepthook -> user_data_dir()/crash.log         (WS-B)
  settings.py     [NEW]     stdlib .env/ini reader, replaces python-dotenv  (WS-B)
render/
  base.py                   Action + Renderer interface — additive changes only
  menu.py, banner.py        pure, curses-free — REUSED AS-IS by the pygame screens
  curses_render.py          untouched, stays stdlib-only
  pygame_render.py [NEW]    the window: draw/get_action/pause/close          (WS-A)
  input_map.py    [NEW]     pygame key -> Action table                       (WS-A)
  tileset.py      [NEW]     atlas loader, char -> Surface, graceful fallback (WS-C)
  ui.py           [NEW]     panel/HUD/overlays drawn into a Surface          (WS-D)
  screens.py      [NEW]     title / class-select / game-over in-window       (WS-D)
assets/           [NEW]     tilesheet(s), font, icon, tiles.json, ASSETS.md  (WS-C)
packaging/        [NEW]     pyrogue.spec, build.ps1, build.sh, version_info  (WS-E)
.github/workflows [NEW]     ci.yml (test matrix) + release.yml (tag -> zips) (WS-F)
tests/                      existing 82 tests stay green; new headless suites (WS-G)
```

Three invariants every workstream must respect:

1. **`game/` never imports `pygame`.** If a workstream needs game-side data it doesn't have, it adds
   a read-only accessor, not a rendering concern inside `game/`.
2. **`Action` values are frozen.** New actions may be *added* (e.g. `FULLSCREEN`); existing strings
   never change, or `tests/test_loop.py` and the curses path break.
3. **`main.py`'s loop shape is frozen** for v1: `draw` → blocking `get_action` → `handle_action` →
   `resolve_monster_phase`. A real-time animation loop is Phase 4 and needs its own plan.

### 3.1 The one genuinely hard technical problem

`CursesRenderer.get_action()` is `stdscr.getch()` — it blocks. In an OS window, *blocking without
pumping the event queue makes Windows grey out the title bar and mark the app "Not Responding."*

The fix is not to restructure the game loop. It is to implement the block *as* an event loop:

```python
def get_action(self):
    while True:
        event = pygame.event.wait()                 # blocks, but keeps the queue drained
        if event.type == pygame.QUIT:
            return Action.QUIT
        if event.type == pygame.WINDOWEXPOSED or event.type == pygame.VIDEORESIZE:
            self._relayout(event)                   # recompute cell size
            self._redraw_last_frame()                # window stays live while idle
            continue
        if event.type == pygame.KEYDOWN:
            action = self.lookup(event)
            if action is not None:
                return action                        # unmapped keys are ignored, as in curses
```

This keeps `main.run()`, `resolve_monster_phase()`, `GameState`, and all 82 existing tests exactly as
they are. It is WS-A's first deliverable and its most important one. Caching the last drawn frame
(so idle redraws are cheap) is part of it.

---

## 4. Phases (the gates)

| Phase | Outcome | Gate to call it done |
|---|---|---|
| **P0 — Policy & stubs** | `pygame-ce` in `.venv`, `CLAUDE.md` dependency rule updated, every new module exists as a signature-only stub with a trivial passing test | `python -m unittest discover -s tests` green; every workstream can `import` what it depends on |
| **P1 — Window parity** | `--renderer pygame` plays a complete run in a real window, drawing the same glyphs, same panel items, same keys. No art yet. | A full run (title → class → descend → death) in-window; 82 + new tests green; curses path byte-identical in behaviour |
| **P2 — Shippable exe** ← *the actual ask* | `PyRogue-win64.zip` from CI: `--onedir`, no console, icon, saves in `%APPDATA%`, crash log on failure | Download the CI artifact on a Windows box with no Python, double-click, play, save, quit, reopen, load |
| **P3 — Looks like a game** | 16×16 tileset, HUD with HP bar and longer log, mouse-clickable menus, window scaling/fullscreen | Side-by-side against P1 shows tiles, not glyphs; still keyboard-complete |
| **P4 — Optional reach** | Nuitka build comparison, pygbag web build (pinned 3.13), audio, animation/game-feel, Steam/SteamworksPy, code signing | Each is its own decision; none blocks P2 |

**P2 does not wait for P3.** Shipping a crisp glyph-grid window as v0.1.0 is a real deliverable; art
lands in v0.2.0.

---

## 5. Workstreams (areas of responsibility)

Seven streams. Each lists **files it exclusively owns** — the mechanism that lets these run in
parallel without clobbering each other. If you need a change in a file you don't own, ask the owner;
don't edit it. Shared files have exactly one owner, named below.

> **Day-0 rule for every stream: land your stub first.** A module with the final signatures,
> `NotImplementedError` bodies (or trivial correct ones), and one passing test — committed before you
> start the real work. Everyone else is blocked on your *signature*, not your implementation.

---

### WS-A — Renderer core: the window, input, and the loop

**Owns:** `render/pygame_render.py`, `render/input_map.py`, `render/base.py` *(additive only)*,
`main.py` *(sole owner — other streams request changes here)*.

**Depends on stubs from:** WS-B (`game/paths.py`), WS-C (`render/tileset.py`), WS-D
(`render/ui.py`, `render/screens.py`).

**Tasks**

1. `PygameRenderer(Renderer)` implementing all seven interface methods (`draw`, `get_action`,
   `show_title_screen`, `choose_class`, `pause`, `close`) against a resizable window.
2. **The responsive blocking `get_action()`** of §3.1 — the critical path. Handle `QUIT` →
   `Action.QUIT`, resize/expose → relayout + redraw + keep waiting, unmapped keys → ignore.
3. `render/input_map.py`: a single table mirroring `curses_render.KEY_ACTIONS` exactly —
   `w/a/s/d` → `MOVE_*`, arrows → `SHOOT_*`, `.` wait, `e` descend, `S` save, `L` load, `q` quit.
   Add `F11` → fullscreen toggle (new `Action`, or handle internally — renderer's choice, but if it
   becomes an `Action` it must be additive and `GameState` must ignore it harmlessly).
4. Glyph-grid draw: one cell per map char, bundled monospace bitmap font, cell size derived from
   window size (integer scale, nearest-neighbour, letterboxed — never fractional).
5. Colour table: map `Entity.color` ints **1–7** to RGB, mirroring `curses_render.COLOR_PAIRS`
   (1 yellow player, 2 red, 3 cyan chest, 4 green uncommon, 5 blue rare, 6 magenta epic, 7 white
   common). Fog of war: `visible` → full brightness (curses `A_BOLD`), `seen` → ~40% brightness
   (`A_DIM`). Boss (`entity.is_boss`) → brighter + underline equivalent.
6. `pause(ms)` via `pygame.time.delay` **while still draining the event queue**, so the monster phase
   animates without freezing the window; `TURN_DELAY_MS=0` must still collapse to instant.
7. Register `'pygame'` in `main.make_renderer`. Keep `curses` the default through P2; flip the
   default to `pygame` in P3 (one-line change, called out in the PR).
8. Delete `render/tcod_render.py` and its `'tcod'` choice at the end of P1.

**Acceptance**

- A complete run is playable in-window, keyboard-identical to the terminal build.
- `SDL_VIDEODRIVER=dummy` construct-draw-close smoke test passes (WS-G writes it; you keep it green).
- `.venv/bin/python main.py` (curses) behaves exactly as before; all 82 existing tests green.
- Resizing the window mid-game does not crash, does not distort the grid, and redraws immediately.

---

### WS-B — Runtime platform layer: paths, config, crash logging, frozen mode

**Owns:** `game/paths.py`, `game/crashlog.py`, `game/settings.py` *(all new, stdlib only)*, plus
narrowly-scoped edits to `game/state.py` (the `SAVE_PATH` line only) and `game/save.py` (accept a
path, don't invent one). Config wiring in `main.py` goes **through WS-A**.

**Why this is its own stream:** it is the difference between "an exe that runs" and "an exe that
works when installed in Program Files" — and none of it needs pygame, so it can start on day 0 and
finish before the renderer does.

**Tasks**

1. `game/paths.py`, stdlib only:
   ```python
   def is_frozen() -> bool           # sys.frozen (PyInstaller) or "__compiled__" (Nuitka)
   def resource_path(*parts) -> Path # sys._MEIPASS / exe dir / repo root, in that order
   def user_data_dir() -> Path       # %APPDATA%\PyRogue | ~/Library/Application Support/PyRogue
                                     # | $XDG_DATA_HOME/pyrogue | ~/.local/share/pyrogue
   def save_path() -> Path           # user_data_dir()/savegame.json
   def log_path() -> Path            # user_data_dir()/crash.log
   ```
   `user_data_dir()` creates the directory (`mkdir(parents=True, exist_ok=True)`).
2. Move the save file there. `game/state.py`'s module-level `SAVE_PATH` constant becomes a call to
   `paths.save_path()` **at save/load time**, not import time (so tests can redirect it).
   One-time migration: if a legacy `./savegame.json` exists and the new location doesn't, copy it.
3. `game/settings.py`: ~15 lines of stdlib `KEY=VALUE` parsing to **replace `python-dotenv`**, with
   the same precedence (real env var wins over file) and the same `env_int` fallback-on-garbage
   behaviour. Search order: `PYROGUE_CONFIG` env var → file next to the exe/`main.py` → `.env` in
   CWD → defaults. Then `main.py` drops `from dotenv import load_dotenv` entirely.
4. `game/crashlog.py`: install a `sys.excepthook` that appends a timestamped traceback to
   `log_path()`. **This is mandatory, not polish** — `--windowed` discards stderr, so without it a
   crash in the shipped game is a window that silently vanishes. Bonus: show the user a dialog
   (`pygame.display.message_box` where available) pointing at the log path.
5. Document (for WS-E) every path the frozen app reads or writes.

**Acceptance**

- `tests/test_paths.py` (WS-G co-writes): resolution is correct with `sys._MEIPASS` faked, with
  `sys.frozen` faked, and when running from source; `user_data_dir()` honours `XDG_DATA_HOME` and
  `APPDATA` when those are faked.
- Save/load works when the CWD is read-only.
- Forcing an exception produces a `crash.log` with a full traceback.
- `python main.py` works **outside** the venv (no `python-dotenv` anywhere on the terminal path).

---

### WS-C — Art direction and the tile pipeline

**Owns:** `assets/**` (tilesheets, bundled font, icon sources, `tiles.json`), `assets/ASSETS.md`,
`render/tileset.py`.

**Tasks**

1. Pick and vendor a **CC0** 16×16 set — Kenney's Roguelike/RPG pack (~1,700 tiles, no attribution
   required) is the default; Urizen 1-bit is the alternative if we want a monochrome look. **Record
   provenance and licence for every file in `assets/ASSETS.md` before committing any art.** No
   "free for non-commercial" assets, ever — that forecloses a paid release.
2. `assets/tiles.json`: data-driven mapping from game char → atlas cell, covering every glyph the
   game can draw today: `#` wall, `.` floor, `+` door, `>` stairs, `@` player, `=` chest, `!` potion,
   `/` weapon, `[` armor, lowercase monster letters, uppercase boss variants. Unknown char → explicit
   fallback. Keep it data, not code, so adding a monster is a JSON edit.
3. `render/tileset.py`:
   ```python
   class Tileset:
       def __init__(self, path: Path | None, cell: int = 16, scale: int = 2)
       @property
       def available(self) -> bool            # False if assets are missing/unreadable
       def glyph(self, char: str, color: int = 0) -> "pygame.Surface | None"
   ```
   `glyph()` returning `None` means "no tile — caller draws the character instead". **The
   missing-asset path must never raise**: a build with no `assets/` must degrade to the P1 glyph
   renderer and log once. That is what keeps WS-A unblocked while art is still being chosen.
   Cache per `(char, color)`; nearest-neighbour upscale; rarity tint applied via the same 1–7 colour
   ints WS-A uses.
4. Window/exe icon: a 256/48/32/16 multi-size `.ico` for Windows plus a `.png` for the SDL window
   icon. Hand the paths to WS-E.
5. Keep the bundled monospace font decision with WS-A, but vendor the file here (licence recorded) so
   the exe doesn't depend on a system font being present — `SysFont('monospace', ...)` is not a
   guarantee on Windows.

**Acceptance**

- `Tileset` loads headless (`SDL_VIDEODRIVER=dummy`) and returns a `Surface` of the expected size for
  every char in `tiles.json`.
- Deleting `assets/` leaves the game fully playable in glyph mode.
- `ASSETS.md` accounts for every file, with licence and source URL.
- Total asset payload under 10 MB.

---

### WS-D — In-window UI: panel, HUD, and the menu screens

**Owns:** `render/ui.py`, `render/screens.py`.

**Reuses, without modifying:** `render/menu.py` (pure selection state) and `render/banner.py` (the
5×5 block font) — both are already curses-free, which is exactly why they were split out.

**Tasks**

1. `render/ui.py` — the side panel, re-done for pixels. Must reach **parity** with
   `curses_render._draw_panel`: title, `Class - Depth`, HP (red at ≤ ⅓ max), `ATK`/`DEF`, item count,
   the `-- gear --` block with rarity-coloured weapon/armor lines, class-dependent control list, and
   the message log. Then improve: a real HP **bar**, and more log lines than the terminal's 4 (pixels
   are cheap — make the count a constant, not a magic number).
2. A `Layout` object: given the window size and the map's `(width, height)` in cells, compute the map
   rect, panel rect, and cell pixel size. **Single source of truth for geometry** — WS-A asks
   `Layout` where things go rather than computing offsets itself. This is the contract that keeps the
   two streams from fighting over the same pixels.
3. `render/screens.py` — title screen (reusing `render_banner('PyRogue')`), class-select with the
   existing descriptions, and the game-over overlay, all drawn into a Surface and driven by `Menu`.
   Keyboard parity (`w`/`s`/arrows/enter/`q`) is **mandatory**; mouse hover + click is a welcome
   addition on top, never a replacement.
4. DPI / scaling sanity: legible at 1280×720 through 4K. Integer-scale a virtual canvas rather than
   re-laying-out at every size.

**Acceptance**

- A written parity checklist against `_draw_panel`, every item ticked.
- Title → class → play → death → quit, entirely in-window, keyboard-only.
- No `curses` import; no game-logic decisions (read `GameState`, never mutate it).

---

### WS-E — Packaging: the executable itself

**Owns:** `packaging/pyrogue.spec`, `packaging/build.ps1`, `packaging/build.sh`,
`packaging/version_info.txt`, `packaging/hooks/**`, `requirements.txt`, `requirements-dev.txt`,
and `.gitignore` *(sole owner)*.

**Can start on day 0 — and should.** Freeze *today's curses build* first as a pipeline dry run; it
produces a console exe nobody wants to play, but it proves the spec file, the data bundling, and the
smoke test before the pygame renderer exists. Pipeline bugs then surface in isolation instead of
tangled up with renderer bugs.

**Tasks**

1. `requirements.txt` → `pygame-ce==2.5.8` (pinned). `requirements-dev.txt` →
   `pyinstaller==6.22.3`. Nothing else unless justified in the PR.
2. `packaging/pyrogue.spec`, committed (not a remembered CLI line, per §2.1 lesson 3):
   - `--onedir`, `--noupx`, `--windowed`/`--noconsole`, `--name PyRogue`, `--icon` from WS-C.
   - `datas` bundling `assets/` → resolved at runtime **only** through `game.paths.resource_path`.
   - `excludes`: `tkinter`, `numpy`, `unittest`, `test`, `pydoc`, `curses` *(for the pygame-only
     build — keep a second spec or a flag if we ever ship the terminal build as an exe)*.
   - `version_info.txt` for Windows file properties (product name, version, company, copyright).
3. `build.ps1` (Windows) and `build.sh` (Linux) wrappers: clean `build/`/`dist/`, run PyInstaller
   against the spec, then zip `dist/PyRogue/` as `PyRogue-<platform>-<version>.zip` with `LICENSE`
   and a short `README.txt` included.
4. **Repo hygiene that affects the bundle:** `__pycache__/*.pyc` files are currently *tracked in
   git* (`git ls-files` shows them). `git rm -r --cached` them and add `__pycache__/`, `*.pyc`,
   `build/`, `dist/`, `*.spec~`, `.venv/` to `.gitignore`. Also decide the `*.md` rule (§9) with the
   user — today every doc in this repo, including this plan, is ignored.
5. Budgets, measured and reported in the PR: cold-start time (target < 2 s) and unzipped size
   (target < 120 MB, expect ~60–80 MB with pygame-ce + no numpy).
6. Write `packaging/NOTES.md`: the AV rules from §2.5, why `--onedir`, how to add a data file, and
   what to check before a release.
7. **Phase 4 only:** a Nuitka `--standalone` build for comparison (size, start-up, AV) — report, do
   not switch, without a decision.

**Acceptance**

- `./packaging/build.sh` on Linux produces a runnable `dist/PyRogue/PyRogue` (glyph or tiles).
- The CI Windows build produces a zip whose exe launches with **no console window**.
- Launching the exe from a shell with `PYTHONPATH`/`PYTHONHOME` cleared and the venv off `PATH`
  works — the standard proxy for "a machine that never had Python".
- Deliberately breaking an asset path produces a `crash.log` (WS-B), not a silent disappearance.

---

### WS-F — CI, release automation, and distribution

**Owns:** `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `CHANGELOG.md`,
`game/version.py` *(single source of the version string, read by WS-E's spec and the title screen)*.

**Tasks**

1. `ci.yml` on push/PR: matrix `{ubuntu-latest, windows-latest} × {3.12, 3.13, 3.14}`, install
   `requirements*.txt`, run `python -m unittest discover -s tests -v` with
   `SDL_VIDEODRIVER=dummy`/`SDL_AUDIODRIVER=dummy` exported. Headless is the whole point of §1's
   verification — use it.
2. `release.yml` on tag `v*`: build on `windows-latest` (required — PyInstaller cannot cross-compile)
   and `ubuntu-latest`, upload both zips plus a `SHA256SUMS` file to a GitHub Release.
3. Version single-sourced in `game/version.py`; the tag must match it (fail the build if it doesn't).
4. itch.io: `butler push dist/PyRogue <user>/pyrogue:windows` (and `:linux`) behind a repo secret,
   wired as an opt-in release step. itch is the primary channel for v0.1.0 — no review queue, no
   certificate, and the AV story is better than emailing a zip.
5. A release checklist in `CHANGELOG.md`: VirusTotal scan, fresh-machine launch, save/load round-trip
   across versions, the exact `.env`/settings defaults the build ships with.

**Acceptance**

- A PR shows green checks across the whole matrix.
- `git tag v0.1.0 && git push --tags` yields downloadable, checksummed zips with no manual steps.
- A documented, repeatable "how to cut a release" path that doesn't involve this machine.

---

### WS-G — QA, parity testing, and documentation (incl. the context update)

**Owns:** `tests/test_pygame_render.py`, `tests/test_paths.py`, `tests/test_parity.py`,
`tests/test_frozen_smoke.py`, plus `CLAUDE.md`, `README.md`, `agent_log.md` *(sole owner of all
three — everyone else requests doc changes through this stream, which is how `agent_log.md` §7c.1's
concurrent-edit problem is avoided this time)*.

**Tasks**

1. `tests/test_pygame_render.py` — headless (`SDL_VIDEODRIVER=dummy`, set in the module before
   importing pygame): construct the renderer, `draw()` a real `GameState`, `close()`. Assert no
   exception, and sample the pixel at the player's cell to prove something was actually drawn. Skip
   cleanly (`unittest.skipUnless`) if `pygame` isn't installed, so the stdlib-only terminal checkout
   still has a green suite.
2. `tests/test_parity.py` — the highest-value new test: assert `curses_render.KEY_ACTIONS` and
   `input_map`'s table **cover the same set of `Action` values**, and that no `Action` is unreachable
   in either renderer. This is the test that catches "the pygame build forgot the save key" during a
   refactor, which no amount of manual play reliably catches.
3. `tests/test_paths.py` — with WS-B, per that stream's acceptance criteria.
4. `tests/test_frozen_smoke.py` — skipped unless `dist/PyRogue/` exists; launches the frozen binary
   with a dummy video driver and a short timeout, asserts a clean exit and no `crash.log`.
5. Keep the existing 82 tests green and the counts in `CLAUDE.md` accurate.
6. **The context update** (deliverable in its own right):
   - `CLAUDE.md`: new **Constraints** wording for the per-directory dependency policy (§0.1);
     `render/pygame_render.py` and friends added to **Layout**; the `python-dotenv` removal noted;
     saves now in a per-user directory; `--renderer pygame` added to **Running**; the
     `render/tcod_render.py` bullet replaced; a pointer to this plan file next to the
     `going_graphical.md` pointer.
   - `going_graphical.md`: a short header note that §0's tcod recommendation is **superseded** by
     this file, with the §2.3 reasoning. Don't rewrite the research; date the override.
   - `README.md`: how to download and run the exe, and how to run from source.
   - `agent_log.md`: a new `## 10` section in the existing voice — what was built, what broke, and
     what was deliberately left out.

**Acceptance**

- Full suite green on both OSes and all three Python versions in CI.
- `CLAUDE.md` describes the repo as it actually is after P2 — a fresh agent reading only `CLAUDE.md`
  can build and package the game without reading this plan.

---

## 6. Parallelism map

```
day 0 ──┬── WS-B  paths/config/crashlog ........ no pygame needed, start now
        ├── WS-E  freeze today's curses build ... proves the pipeline early
        ├── WS-C  pick + vendor assets, ASSETS.md
        ├── WS-F  ci.yml on the existing test suite
        └── WS-A  stub + §3.1 get_action spike ... the one real unknown
                        │
P1 gate ────────────────┴── WS-A window parity (needs B's resource_path,
                            C's Tileset stub, D's Layout + screens)
                        ┌── WS-D  ui.py / screens.py against the Layout contract
                        └── WS-G  headless + parity tests as soon as A's stub lands
P2 gate ──── WS-E spec against the real pygame build + WS-F release.yml
                            ↓
P3 ───────── WS-C real tiles + WS-D HUD polish (independent of each other)
P4 ───────── Nuitka / pygbag / audio / Steam — separate decisions
```

Hard dependencies (everything else is soft):

- WS-A's §3.1 spike **gates P1**. If a responsive blocking `get_action()` can't be made to work, the
  whole "don't touch the game loop" premise is wrong and we re-plan before anyone writes UI code.
- WS-E's P2 build **requires** WS-B's `resource_path`. That's why WS-B starts on day 0.
- WS-D needs the `Layout` contract agreed with WS-A on day 0 (a 20-line stub, not a design doc).
- Nothing in P1–P2 requires final art. The glyph fallback is the mechanism.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation / owner |
|---|---|---|---|
| Window greys out / "Not Responding" while waiting for input | High if naive | Fatal to feel | §3.1 event-driven blocking wait; WS-A day-0 spike |
| `--windowed` build crashes silently (no stderr) | High | Unshippable | `game/crashlog.py` is mandatory, not polish; WS-B |
| Saves fail when installed under Program Files | High | Data loss | `user_data_dir()` + one-time migration; WS-B |
| Antivirus flags the exe | Medium | Users delete the game | `--onedir`, `--noupx`, never `--onefile`, VirusTotal pre-check; WS-E §2.5 |
| Assets not found in the frozen build | High first attempt | Crash on launch | *All* asset access through `resource_path`; frozen smoke test; WS-B/E/G |
| Can't build Windows exe from this Linux box | Certain | Blocks release | CI on `windows-latest` from day 0; WS-F |
| Scope creep into animation / real-time loop | Medium | Slips P2 indefinitely | Invariant 3 (§3): loop shape frozen for v1; animation is P4 |
| Curses build quietly rots | Medium | Loses the stdlib reference | CI runs both; `test_parity.py` enforces input equivalence; WS-G |
| Art licence contamination | Low | Blocks any paid release | CC0 only, `ASSETS.md` provenance required pre-commit; WS-C |
| Python 3.14 wheel gaps for a future dep | Low | Annoying | Verified for pygame-ce/PyInstaller (§1); pin 3.13 if pygbag is ever attempted |
| Doc edit collisions across streams | Medium | Lost work (happened before, §7c.1) | WS-G is the sole owner of all three doc files |

---

## 8. Explicitly out of scope for P1–P2

- Animation, tweening, screen shake, particles — needs the real-time loop; P4 with its own plan.
- Audio. pygame-ce gives it to us for free, but "free to call" isn't "free to design"; P3/P4.
- Mouse-driven *gameplay* (click to move, click to target). Mouse in menus is fine.
- Any new gameplay content. This project is about the window and the exe; `game/` logic changes are
  out of scope unless a workstream's acceptance criteria name them.
- macOS build and notarization. The CI job can emit a `.app`, but notarization needs an Apple
  developer account — P4.
- Steam. Technically fine (SteamworksPy exists, §2.2), but it's a store decision, not an engineering
  one.
- Web build. `pygbag` wants a 3.13 interpreter and an `async` main loop; attractive, but it is a
  second port of the loop and belongs after the desktop build ships.

---

## 9. Open questions for the user

1. **Engine confirmation.** This plan reverses `going_graphical.md`'s tcod recommendation in favour of
   `pygame-ce` (§2.3). If you'd rather keep tcod — e.g. you specifically want the grid-console look —
   say so before P1; WS-A's work is the part that changes.
2. **Art direction:** Kenney colour tiles (friendly, generic) vs Urizen 1-bit (coherent, stark, and
   it sidesteps picking a palette). Affects WS-C only, and only at P3.
3. **`.gitignore` and `*.md`.** Every doc in this repo — `CLAUDE.md`, `going_graphical.md`,
   `agent_log.md`, and this file — is currently ignored, so **this plan is untracked.** Options:
   `git add -f` it, or add `!CLAUDE.md`-style exceptions, or drop the `*.md` rule. Recommendation:
   negate the rule for the handful of docs that *are* the project's memory.
4. **Distribution ambition for v0.1.0:** itch.io page (recommended), or just a zip you hand around?
   That decides whether WS-F wires up butler now or later.

---

## 10. Quick reference — commands this plan introduces

```bash
# development
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python main.py                       # terminal (unchanged)
.venv/bin/python main.py --renderer pygame     # window

# tests (headless, both renderers)
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/python -m unittest discover -s tests -v

# local build
./packaging/build.sh                           # Linux -> dist/PyRogue/
powershell -File packaging/build.ps1           # Windows -> dist/PyRogue/PyRogue.exe

# release
git tag v0.1.0 && git push --tags              # CI builds + publishes the zips
```
