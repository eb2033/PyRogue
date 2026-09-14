# Beyond the Terminal — Research Notes

Research date: 2026-08-26. Scope: (A) agent "skills" worth installing to help build this, (B) options
for turning PythonRogue into a graphical 2D game, (C) shipping it as a `.exe`, (D) web builds,
(E) free art, (F) a concrete migration path for the current `main.py`.

---

## 0. TL;DR

- **Recommended path:** keep the game logic exactly as it is, split rendering behind a tiny interface,
  and add a **`tcod`** renderer alongside the existing `curses` one. `tcod` is the shortest distance
  from "ASCII in a terminal" to "real window with graphical tiles", and it replaces three things you
  were going to write by hand anyway (FOV, pathfinding, event handling).
- **If you want it to look like a normal indie game** (sprites, animation, particles, sound, mouse UI)
  rather than a tile grid, use **`pygame-ce`** instead. More work, higher ceiling.
- **For the `.exe`:** `PyInstaller --onedir` + a zip is the pragmatic default. `Nuitka` if you want one
  clean fast binary and can tolerate slow builds. Expect antivirus false positives with `--onefile`.
- **Cheaper than an `.exe`:** `pygbag` compiles a `pygame-ce` game to WebAssembly and it runs in a
  browser / on itch.io. No install, no AV warnings, works on phones. Only available on the pygame path.
- **Conflict to settle first:** `CLAUDE.md` says *standard library only, don't introduce `tcod` or
  `numpy`*. Every graphical option breaks that rule. See §6.1 — the split-renderer design lets the
  terminal build stay stdlib-pure while the graphical build takes dependencies.

---

## A. Agent skills for this project

"Skills" in the Claude Code sense — `SKILL.md` files that load task-specific instructions into an
agent's context. Anthropic shipped the plugin marketplace in May 2025; by March 2026 the official
marketplace had ~200 plugins, with several thousand more across community hubs. Browse with `/plugin`
inside Claude Code.

### A.1 The one that actually matches this project

**`gamedev-skills/awesome-gamedev-agent-skills`** — 68 skills + a router, Apache-2.0.

```bash
npx skills add gamedev-skills/awesome-gamedev-agent-skills
```

Relevant contents:

| Skill | Why it matters here |
|---|---|
| `roguelike` | Genre skill: grid/turn movement, procedural dungeons, permadeath, FOV, loot. Direct hit. |
| `procedural-gen` | Dungeon generation beyond room-and-corridor (BSP, cellular automata, drunkard's walk). |
| `pygame-core` | pygame-ce 2.5.7: game loop, `Surface`/`Rect`, sprites/groups, events. The only Python-engine skill in the set. |
| `game-feel` | Screen shake, hit-stop, input buffering — the difference between "moves" and "feels good". |
| `camera-systems` | Needed the moment the map is bigger than the window. |
| `level-design` | Pacing, difficulty curve, room purpose. |
| `game-ui-ux` | HP bars, inventory panels, message log. |

The format is portable — the same files load in Cursor, Codex, Gemini CLI, Copilot, etc., so this
isn't a lock-in decision.

Caveat: there is **no `tcod` skill** in the set. If you go the tcod route, the genre skills
(`roguelike`, `procedural-gen`) still apply but the engine-specific one won't.

### A.2 Others worth a look

- **`Donchitos/Claude-Code-Game-Studios`** — 49 agents + 72 workflow skills mirroring a studio
  hierarchy. Almost certainly overkill for a single-file roguelike; noted for completeness.
- **`travisvn/awesome-claude-skills`** — curated index; good for finding general-purpose skills
  (docs, testing, refactoring) rather than game ones.
- **`claudemarketplaces.com/skills/category/game-dev`** — browsable game-dev category.
- **`daymade/claude-code-skills`** — general dev-workflow skills marketplace.

### A.3 Skills you'd write yourself

Given this repo already has `roguelike_reference.md` acting as a spec, the highest-value custom skill
is a thin one that says *"read `roguelike_reference.md` §N before touching feature N, and respect the
`(y,x)` vs `(x,y)` convention"*. That's the project's actual recurring failure mode per `CLAUDE.md`,
and no off-the-shelf skill knows about it.

---

## B. Going graphical — the four real options

All four give you a real window with graphics. Ordered by distance from where you are now.

### B.1 `python-tcod` — **recommended**

The successor to libtcod, the library the entire roguelike-tutorial ecosystem is built on. Version
21.2.1 as of July 2026.

**What you get:**
- SDL-backed window, hardware accelerated.
- `tcod.tileset.load_tilesheet()` — load a PNG tilesheet and draw *graphical tiles* instead of
  characters. Still a grid, but each cell is a sprite. This is the "looks like a game" upgrade with
  ~zero restructuring.
- Also loads BDF and TrueType fonts if you want to stay text-y but pretty.
- **FOV algorithms built in** — including recursive shadowcasting, which is item #6 on your
  not-yet-implemented list and described in `CLAUDE.md` as "the largest jump in complexity". You'd
  delete `update_visibility` and call `tcod.map.compute_fov` instead.
- **Pathfinding built in** (Dijkstra / A*) — needed the moment monsters chase the player.
- Event handling for keyboard, mouse, joystick, controller.

**Why it fits:** your world model is already a 2D char grid indexed `[y][x]`. tcod's console is a 2D
grid indexed the same way. The port is mostly a find-and-replace on the drawing and input layer.

**Cost:** one dependency (which pulls in `numpy` — tcod's console is numpy-backed). Both of the things
`CLAUDE.md` explicitly forbids, in one package.

**Tutorial:** rogueliketutorials.com's "Yet Another Roguelike Tutorial" (Python 3 + tcod v2) — 13 parts
from `@`-on-screen through equipment and difficulty scaling. It is the canonical path and it maps
almost 1:1 onto your stretch-goal list.

### B.2 `pygame-ce` — the "real 2D game" option

Community Edition; the actively maintained fork and the one everything downstream now targets.

**What you get:** free-form sprite rendering (no grid), smooth movement and animation, sound and
music, mouse-driven UI, particles, shaders via `pygame.gfxdraw` / OpenGL interop. Plus it's the only
path to a browser build (§D).

**Cost:** you write FOV, pathfinding, and the grid/tile abstraction yourself — nothing roguelike-shaped
is included. Bigger rewrite: turn-based grid logic has to be reconciled with a real-time frame loop.

**Choose this if** the goal is a game that doesn't *look* like a roguelike port — animated sprites,
juice, sound. Choose tcod if the goal is a better-looking roguelike.

### B.3 `arcade`

Modern OpenGL-based, nicer API than pygame, built-in tilemap support (Tiled `.tmx`), good docs.
pythonarcade even maintains a roguelike sample repo. Smaller ecosystem than pygame; no wasm story.
A reasonable middle option, but it doesn't beat tcod at roguelikes or pygame at reach.

### B.4 `raylib` bindings (`pyray` / `raylib-python-cffi`)

Thin bindings over the C library. Fast, batteries-included (shapes, textures, audio, 3D), very clean
API. Weakest Python-side ecosystem of the four and the least roguelike prior art. Mentioned because
it packages well and performs well, not because it's the obvious pick here.

### Comparison

| | tcod | pygame-ce | arcade | raylib |
|---|---|---|---|---|
| Port effort from current code | **Low** | High | Medium-high | High |
| FOV / pathfinding included | **Yes** | No | No | No |
| Graphical tiles | Yes (grid) | Yes (free-form) | Yes (free-form) | Yes |
| Animation / sound | Limited | **Best** | Good | Good |
| Browser build | No | **Yes (pygbag)** | No | Partial |
| Roguelike tutorials/community | **Best** | Good | Some | Minimal |
| Deps pulled in | tcod + numpy | pygame-ce | arcade + pyglet | raylib cffi |

---

## C. Shipping a `.exe`

### C.1 The tools

**PyInstaller** — most widely used. Analyses imports, bundles a CPython interpreter + your code.
Two modes:
- `--onedir` (default): a folder with the `.exe` plus DLLs and data. **Prefer this.**
- `--onefile`: single `.exe` that unpacks itself to a temp dir at startup. Convenient, but slower to
  launch and the self-extraction pattern is exactly what antivirus heuristics flag.

**Nuitka** — compiles Python to C, then to a native binary. No bundled interpreter. Genuinely faster
runtime, cleaner single-file output, fewer AV problems. Costs: long build times, C toolchain required,
occasionally fiddly with C-extension-heavy deps. The better choice if you're distributing something
you'd call finished.

**Briefcase (BeeWare)** — packages for Windows/macOS/Linux/iOS/Android from one config, and produces
proper installers (MSI, `.app`, `.deb`) rather than a loose folder. Worth it if you care about
multi-platform installers; heavier setup than the other two.

**cx_Freeze** — the third classic. Simpler than PyInstaller, less magic, smaller community. Fine, but
no reason to pick it over PyInstaller today.

### C.2 The antivirus problem — read this before you ship

PyInstaller's bootloader has been on antivirus threat lists for years, so *safe* apps get flagged by
association. This is a real distribution problem, not a theoretical one: users get "Windows protected
your PC" and delete your game.

Mitigations, in order of effectiveness:
1. **Use `--onedir`, not `--onefile`.** Biggest single win.
2. **Code-sign the executable.** Signed binaries are trusted far more. Costs money (~$100-400/yr for a
   cert) but it's the actual fix.
3. **Disable UPX compression** (`--noupx`). UPX is itself a common trigger.
4. **Build the PyInstaller bootloader from source** so your binary's bootloader isn't byte-identical to
   the one on the blocklists.
5. Check the result on VirusTotal before release; submit false-positive reports to the vendors that
   flag it.

Nuitka sidesteps most of this by producing an ordinary compiled binary.

### C.3 Bundling assets

Once there are tilesheets and sounds, they must be shipped alongside the binary:

```bash
pyinstaller --onedir --noupx \
  --add-data "assets;assets" \      # Windows uses ';'  (Linux/macOS use ':')
  --name PythonRogue \
  main.py
```

And in code, resolve paths through the bundle root rather than `__file__`:

```python
import sys, pathlib

def asset_path(*parts):
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    return base.joinpath("assets", *parts)
```

`sys._MEIPASS` is the temp extraction dir PyInstaller sets at runtime; the fallback covers running
from source. Forgetting this is the #1 cause of "works locally, crashes as an exe".

### C.4 Can the *current* curses version be an exe?

Yes, with caveats. `curses` isn't in the Windows stdlib — you'd need `pip install windows-curses`, and
PyInstaller can bundle it. But the result is a **console** application: it opens a terminal window,
inherits terminal-sized rendering, and looks like a script someone ran rather than a game. Fine for
internal distribution, weak as a thing you hand to a friend. This is the strongest practical argument
for §B: the exe only feels like a *game* once there's a real window behind it.

---

## D. The web option (worth considering before the exe)

**`pygbag`** packages a `pygame-ce` app to WebAssembly so it runs in a browser — desktop and mobile,
no install, no antivirus warnings, shareable as a URL.

```bash
pip install pygbag
python3 -m pygbag --archive path/to/game/main.py
# produces ./build/web.zip  → upload as an itch.io project of kind "HTML"
```

Requirements and gotchas:
- **`pygame-ce` is required** — the original `pygame` doesn't work with pygbag.
- Your main loop must become `async` — `import asyncio`, make `main()` a coroutine, `await asyncio.sleep(0)`
  each frame, and run it with `asyncio.run(main())`. That's the "2-3 lines" adjustment people mention.
- Python 3.11 support was dropped; current wheels target 3.12/3.13 (pygbag 0.9+).
- Blocking calls (`input()`, synchronous file I/O, `time.sleep`) don't work in the browser.

**This only exists on the pygame path.** If reach matters more than fidelity, that pushes the §B
decision toward `pygame-ce` — a web build plus a PyInstaller build from one codebase covers far more
people than an `.exe` alone.

---

## E. Free art (all usable commercially)

- **Kenney** (kenney.nl) — 40,000+ CC0 assets, no attribution required. The **Roguelike/RPG pack**
  (~1,700 tiles) is the direct match. The "Tiny" series (Tiny Dungeon, Tiny Town) is excellent for
  16×16 top-down. **Start here.**
- **Urizen 1-Bit Tileset** (itch.io) — 5,500+ 12×12 tiles, fantasy/modern/sci-fi/horror. Enormous
  coverage, single coherent style, and 1-bit art sidesteps the "programmer picks colors" problem.
- **Hexany's Roguelike Tiles** (itch.io) — 16×16 monochrome, clean and small.
- **itch.io asset collections** — filter by 1-bit / 16×16 / roguelike; check each pack's license
  individually (CC0 vs CC-BY vs "free for non-commercial" all appear).

A note on tile size with tcod: the tile size must relate to the font/tilesheet cell size — it can't be
*smaller*, but it can be an integer multiple. A 16×16 sheet can render at 16×16, 32×32, 48×48, etc.
Pick 16×16 art and scale up; it stays crisp with nearest-neighbour filtering.

---

## F. Concrete migration path for `main.py`

### F.1 Settle the dependency constraint first

`CLAUDE.md` currently says: *"Standard library only for game logic (`curses` + `random`) … don't
introduce game dependencies like `tcod` or `numpy`."* Every option above violates that.

The resolution that keeps both goals: **the constraint applies to game logic, not to rendering.** Keep
dungeon generation, entities, turn resolution, and combat in stdlib-only modules. Let the *renderer*
be swappable, and let the graphical renderer take dependencies. The terminal build then still runs on
a bare Python install with zero internet, exactly as intended, and the graphical build is a second
front end over identical logic. `CLAUDE.md` should be updated to say this explicitly.

### F.2 The refactor, in order

**Step 1 — split the file.** `main.py` is 130 lines and does everything. Break it up now, while it's
cheap:

```
game/
  rect.py          # Rect
  entity.py        # Entity, later Monster, Item
  dungeon.py       # generate_dungeon, carve_*, make_empty_map
  fov.py           # update_visibility  (later: swap for tcod.map.compute_fov)
  state.py         # GameState: map, entities, visible, seen, turn logic
render/
  curses_render.py # draw_with_fog + input mapping  (stdlib only)
  tcod_render.py   # the new one
main.py            # picks a renderer, runs the loop
```

**Step 2 — define the renderer interface.** Three methods is enough:

```python
class Renderer:
    def draw(self, state) -> None: ...
    def get_action(self) -> str | None:   # 'move_n', 'quit', 'descend', ...
    def close(self) -> None: ...
```

Crucially, `get_action` returns a **semantic action**, not a keycode. Today `main()` compares raw
`ord('w')` values; that logic can't be shared between curses and SDL. Once input is semantic, the
game loop becomes renderer-agnostic and never changes again.

**Step 3 — fix the coordinate convention while you're in there.** `CLAUDE.md` calls the `(y,x)` /
`(x,y)` mismatch "the most common source of bugs here". It exists because curses' API forces row-first.
Confine that inversion to `curses_render.py` — game logic should be `(x, y)` everywhere, with the
renderer doing the flip at the boundary. This is the single highest-value cleanup in the codebase and
it costs almost nothing right now.

**Step 4 — add `tcod_render.py`.** Same three methods, drawing to a `tcod.Console` with a loaded
tilesheet. At this point you have both builds from one codebase and can compare them side by side.

**Step 5 — trade hand-written systems for library ones.** With tcod present:
- `update_visibility` → `tcod.map.compute_fov(transparency, (x, y), radius, algorithm=tcod.FOV_SHADOW)`.
  This deletes stretch goal #6 (recursive shadowcasting) outright and fixes the known placeholder that
  walls don't block vision.
- Monster chase behaviour → `tcod.path.AStar` / `SimpleGraph`, rather than writing pathfinding.

**Step 6 — package.** `PyInstaller --onedir --noupx --add-data` with the `_MEIPASS` path helper from
§C.3. Test the built exe on a machine that has never had Python installed — that's where missing-DLL
and missing-asset bugs surface.

### F.3 What this buys you

The stretch-goal list in `CLAUDE.md` — stairs, HP panel, monsters, items, save/load, shadowcasting —
is unchanged by any of this, except that #6 becomes a library call and monster AI gets pathfinding for
free. Everything else is still yours to write, in stdlib Python, exactly as the reference specifies.
The renderer split is the only structural change, and it's worth doing whether or not you ever ship a
graphical build.

---

## Appendix: if "skills" meant *in-game* skills

Reading the request the other way — character abilities rather than agent tooling — the standard
roguelike approaches, roughly by complexity:

1. **Consumable-driven** (original Rogue): no skill system; scrolls, potions and wands *are* the
   abilities. Zero new architecture — items are already stretch goal #4. Cheapest path to variety.
2. **Class + fixed kit** (NetHack, DCSS backgrounds): pick a class at start, get a small fixed ability
   set. Needs a `Player` subtype with an `abilities` list and a targeting mode in the input layer.
3. **Use-based skill growth** (DCSS): skills level from usage — swing a sword, sword skill rises.
   Emergent and self-balancing, but needs per-action bookkeeping and careful tuning.
4. **Point-buy / talent tree** (ToME, modern roguelites): levelling grants points spent on a tree.
   Most player-facing depth, most UI work — needs a full menu system, which is a real project on top
   of a terminal renderer and a much easier one on a graphical renderer with mouse support.

For this codebase, (1) then (2) is the natural order: items exist in the spec already, and a class kit
is a small addition on top. Save (3)/(4) until after monsters, items and save/load are in — a skill
system with nothing to use it against isn't testable.

The `roguelike` and `game-ui-ux` skills from §A.1 both cover this ground.

---

## Sources

**Agent skills**
- [awesome-gamedev-agent-skills (68 skills, Apache-2.0)](https://github.com/gamedev-skills/awesome-gamedev-agent-skills)
- [Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios)
- [awesome-claude-skills (curated index)](https://github.com/travisvn/awesome-claude-skills)
- [Claude Code Marketplaces — game-dev category](https://claudemarketplaces.com/skills/category/game-dev)
- [daymade/claude-code-skills](https://github.com/daymade/claude-code-skills)
- [Claude Code Plugin Marketplace & Skills Guide (2026)](https://www.alexcloudstar.com/blog/claude-code-plugin-marketplace-skills-2026/)
- [Best Claude Code Plugins (2026): 11 Tested](https://buildtolaunch.substack.com/p/best-claude-code-plugins-tested-review)

**tcod / roguelike development**
- [python-tcod documentation (21.2.1)](https://python-tcod.readthedocs.io/en/latest/)
- [Yet Another Roguelike Tutorial — Python 3 + tcod v2](https://rogueliketutorials.com/tutorials/tcod/v2/)
- [Complete Roguelike Tutorial extras — RogueBasin](https://www.roguebasin.com/index.php/Complete_Roguelike_Tutorial,_using_Python+libtcod,_extras)
- [HexDecimal/roguelike-tutorial](https://github.com/HexDecimal/roguelike-tutorial)
- [pythonarcade/roguelike](https://github.com/pythonarcade/roguelike)

**Packaging**
- [PyInstaller vs Nuitka vs cx_Freeze — Sparx Engineering](https://sparxeng.com/blog/software/python-standalone-executable-generators-pyinstaller-nuitka-cx-freeze)
- [Nuitka vs PyInstaller — CodersLegacy](https://coderslegacy.com/nuitka-vs-pyinstaller/)
- [Python to EXE without PyInstaller — Finxter](https://blog.finxter.com/python-to-exe-without-pyinstaller-a-comprehensive-guide/)
- [Fixing antivirus false positives with PyInstaller — PythonGUIs](https://www.pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller/)
- [PyInstaller issue #6754 — onefile AV false positives](https://github.com/pyinstaller/pyinstaller/issues/6754)

**Web builds**
- [pygbag — python and pygame wasm](https://github.com/pygame-web/pygbag)
- [Publishing to itch.io — pygame wasm wiki](https://pygame-web.github.io/wiki/publishing/itch.io/)
- [Pygbag wiki](https://pygame-web.github.io/wiki/pygbag/)

**Assets**
- [Kenney — Roguelike/RPG pack (CC0)](https://kenney.nl/assets/roguelike-rpg-pack)
- [Best Free 2D Sprites, Pixel Art and Tilesets (2026)](https://app.cinevva.com/guides/free-2d-sprites-tilesets)
- [itch.io — 1-bit tileset collection](https://itch.io/c/2064578/1-bit)
