# PythonRogue

A terminal roguelike built from `roguelike_reference.md` — an offline reference that doubles as the
project spec. Read that file before adding a feature: it defines the intended approach for dungeon
generation, FOV, entities, and the stretch-goal roadmap.

## Running

```bash
.venv/bin/python main.py                    # terminal (curses, the default from source)
.venv/bin/python main.py --renderer pygame  # OS window (needs pygame-ce); F11 toggles fullscreen
./packaging/build.sh                        # frozen Linux build -> dist/PyRogue/ + a zip
```

Setting up a checkout (or a fresh worktree — `.venv` is gitignored, so each needs its own):
`python -m venv .venv && .venv/bin/pip install -r requirements.txt`. `requirements-dev.txt`
(PyInstaller) is only for packaging. The terminal build itself needs **no** packages: `python3
main.py` works with a bare system Python.

Tests: `.venv/bin/python -m unittest discover -s tests -v`. The pygame suites run headless (they set
`SDL_VIDEODRIVER=dummy` themselves) and skip cleanly when pygame isn't installed;
`tests/test_frozen_smoke.py`'s launch test skips unless `dist/PyRogue/` exists. CI
(`.github/workflows/ci.yml`) runs the suite on Ubuntu + Windows × Python 3.12/3.13/3.14, a
nothing-installed job that guards the stdlib-only terminal path, and a `frozen-build` job that
freezes the game on Windows and Linux, smoke-tests it, and keeps the zips as artifacts for 7 days —
that job is the only place the Windows exe gets built before a release. `frozen-build` runs only for
pushes to `main`, tags, and manual runs ("Run workflow" on the Actions tab); other branches and PRs
get the tests alone. No automated test touches
the curses renderer itself (it needs a real terminal) — verify curses rendering/input changes by
running the game.

## Layout

- `main.py` — entry point only. Loads settings (`game.settings.load()`, before anything reads the
  environment), picks a renderer (`--renderer`/`RENDERER`; default `curses` from source, `pygame`
  in a frozen build — the exe has no console and doesn't bundle curses), shows the title and
  class-select screens, builds a `GameState`, and runs a renderer-agnostic loop (`draw` /
  `get_action` / `handle_action`, then `resolve_monster_phase`). That last step is what makes the
  monster half of a round watchable — see **Rounds** below. Its `__main__` block appends any
  uncaught exception to `crash.log` via `crashlog.write` *explicitly* (not `crashlog.install()`'s
  excepthook — a `--windowed` PyInstaller build may show its own error dialog and never run the
  hook), then re-raises.
- `game/` — all game logic, standard library only, speaks `(x, y)` throughout. `state.py` owns turn
  resolution (`GameState`, including the archer's ranged attack); `dungeon.py`, `rect.py`, `tiles.py`
  are dungeon generation; `entity.py`, `monster.py`, `item.py` are the entity hierarchy; `fov.py` is
  field of view; `save.py` is JSON save/load (atomic: temp file + `os.replace`). Platform layer:
  `paths.py` — `resource_path()` for anything bundled (`sys._MEIPASS` → exe dir → repo root; never
  a CWD-relative path) and `user_data_dir()` for anything written (`%APPDATA%\PyRogue`,
  `~/Library/Application Support/PyRogue`, `$XDG_DATA_HOME/pyrogue` or `~/.local/share/pyrogue`;
  `$PYROGUE_DATA_DIR` overrides all of them — tests and portable installs use it); `settings.py` —
  the stdlib `.env` reader that replaced `python-dotenv`; `crashlog.py`; `version.py`
  (`__version__`, the single source for the exe's file properties and release tags).
- `render/` — the renderer boundary. `base.py` defines `Action` (semantic keys, including `SHOOT_*`
  for the arrow keys) and the `Renderer` interface (`draw`/`get_action`/`show_title_screen`/
  `choose_class`/`pause`/`close`); `curses_render.py` is the terminal renderer (stdlib only, the only file
  that speaks `(y, x)`); `menu.py` is the pure (curses-free) menu-selection state; `banner.py` builds
  ASCII-art banner text from a small block font. The pygame front end (see **Windowed renderer**
  below) is split by desktop-plan workstream: `pygame_render.py` (window, event loop, map cells,
  F11) + `input_map.py` + `palette.py` (Entity.color int → RGB) are WS-A; `ui.py` (`Layout` — the
  single source of truth for geometry — `Canvas` for grid text, `paint_panel`) and `screens.py`
  (paint-only menu/game-over frames; the menu *event loop* stays in `pygame_render.py`) are WS-D;
  `tileset.py` (`Tileset.glyph(char, color, size, dim)` → a tile Surface, or `None` meaning "draw
  the character"; reads `assets/tiles.json`) and `assets/` are WS-C.
- `assets/` — bundled art: three Kenney CC0 roguelike sheets (`assets/kenney/*/`, each with its
  `License.txt`), `tiles.json` (game char → a stack of sheet cells — a goblin is body + clothes +
  dagger from the characters pack's paper-doll kit; `backdrop`/`tint` colour an item or chest by
  its `Entity.color`), and `icon.png`/`icon.ico` (generated from the `@` tile by
  `packaging/make_icon.py`). **`assets/ASSETS.md` must list every file with its source and
  licence** — `tests/test_tileset.py` enforces it, and the 10 MB budget.
- `packaging/` — `pyrogue.spec` is the committed source of truth for the PyInstaller build
  (**onedir and `upx=False`, never onefile** — antivirus; `console=False`; excludes curses/tkinter/
  numpy/unittest; bundles `assets/` only if it exists). `build.sh` / `build.ps1` clean, build, and zip
  via `make_zip.py`; `version_info.py` generates the Windows file properties from `game/version.py`.
  `NOTES.md` has the AV rules, how to add a data file, and the release checklist.
  **Third-party notices:** `THIRD_PARTY_NOTICES.txt` (component, licence, source) and `licenses/`
  (each project's licence text, fetched from its official repo) are copied into every bundle by
  `collect_licenses.py`, which also adds the building Python's own `LICENSE.txt`.
  `tests/test_frozen_smoke.py`'s `NoticesTest` fails if pygame-ce ever bundles a native library the
  notices don't cover — after a pygame-ce upgrade, add a row and its licence file.
- `.github/workflows/release.yml` — on a `v*` tag (which must match `game/version.py`): builds both
  zips, smoke-tests them, publishes a GitHub Release with `SHA256SUMS` and the matching
  `CHANGELOG.md` section. Pushes to itch.io only if a `BUTLER_API_KEY` secret is set (plus an
  `ITCH_PROJECT` repo variable). `workflow_dispatch` builds artifacts without releasing.
- `requirements.txt` (`pygame-ce`, pinned — the only runtime dependency, and only for the window),
  `requirements-dev.txt` (`pyinstaller` + hooks, pinned), `CHANGELOG.md`.
- `tests/` — headless `unittest` suites. `test_game.py` (`game/` logic: dungeon gen, FOV, combat,
  adjacency, turn phases, classes, items, save/load), `test_menu.py` (menu/banner helpers),
  `test_loop.py` (`main.resolve_monster_phase` with a recording stand-in renderer, asserting the
  frame-by-frame ordering of a round), `test_pygame_render.py` (renderer, events, fullscreen,
  game over, a full scripted run through `main.run`, default-renderer choice, tile mode),
  `test_ui.py` (`Layout` in both modes, paint smoke tests), `test_tileset.py` (fallback on
  missing/corrupt assets, every drawable char has a tile, chest colours, `ASSETS.md` provenance),
  `test_parity.py` (both renderers' key tables
  reach every `Action`), `test_paths.py` / `test_settings.py` / `test_crashlog.py` (platform
  layer), `test_main.py` (`main.py` as a subprocess: config loading, crash logging),
  `test_frozen_smoke.py` (launches `dist/PyRogue/` if it exists). There is intentionally no test
  for the curses renderer's drawing/getch itself — it needs a real terminal (or a pty — see
  `agent_log.md`'s note on the `TERM=xterm` arrow-key SS3-vs-CSI trap if you script one).
- **The next three docs are private: gitignored and untracked, on purpose.** They exist only in the
  primary checkout, not in a git worktree or a fresh clone. If you're working in a worktree and
  can't find one, read it from the primary checkout: the first path `git worktree list` prints.
  Don't `git add -f` them (the repo is public).
- `roguelike_reference.md` — the spec/reference. Section numbers below refer to it.
- `going_graphical.md` — research notes (2026-08-26) on an eventual graphical build. Its §0
  recommendation of `tcod` is **superseded** by `desktop_build_plan.md`; the rest (packaging,
  antivirus, assets, web builds) still stands.
- `desktop_build_plan.md` — the plan (2026-10-06) for taking the game out of the terminal and
  shipping it as a `.exe`: `pygame-ce` renderer, PyInstaller `--onedir` built on a Windows CI
  runner, split into seven workstreams with exclusive file ownership so agents can run in parallel.
  **Read this before starting any graphical or packaging work.** §4.1 records the status. Done: the
  §3.1 spike, P0, P1 (window parity), and P2's build pipeline — P2 is only *done* once a Windows
  exe from CI has been launched on a real Windows machine — WS-C's tiles, and P3's HUD, mouse
  menus and bundled font (2026-10-13). P3 is done; the P2 Windows launch is the open gate. If you are one of several agents, edit only the files your workstream owns (§5) — and
  `CLAUDE.md` belongs to WS-G.
- `.env` — read by `game/settings.py` (`KEY=VALUE`, `#` comments, optional quotes; a real
  environment variable always wins). Search order: `$PYROGUE_CONFIG` → `.env` next to the exe (or
  next to `main.py` from source) → `.env` in the CWD. `main.py` looks for `MAP_WIDTH`,
  `MAP_HEIGHT`, `FOV_RADIUS`, `RENDERER`, `TURN_DELAY_MS` and `TILES`, each with a code default (50 /
  20 / 6 / curses-or-pygame / 110 / 1); the checked-in `.env` only sets `MAP_WIDTH=40` and `MAP_HEIGHT=20`, so
  a source run is a **40x20** map — but the `.env` is **not** bundled into the exe, which therefore
  uses the 50x20 code default. `env_int` falls back to the default on an unparseable value rather
  than crashing. `TURN_DELAY_MS=0` collapses the monster phase back to instant, which is handy for
  testing. `TILES=0` makes the window draw characters instead of tiles. `COMBAT_ZOOM=0` (default
  1) turns off the window's melee zoom.

## Constraints

- **Standard library only** for everything under `game/`, for `render/curses_render.py`
  (`curses` + `random`), and for `main.py`. The reference exists so the terminal build runs with
  zero internet and zero installs; don't introduce dependencies there. CI's nothing-installed job
  enforces it.
- **The dependency rule is per-directory, and that is what makes a graphical build possible**
  (`desktop_build_plan.md` §0.1): `render/pygame_render.py`, `input_map.py`, `ui.py`, `screens.py`
  and `tileset.py` may import `pygame-ce` (`palette.py` happens not to); nothing on the terminal
  path imports them, and every pygame test skips cleanly without it. tcod was evaluated and
  dropped (`render/tcod_render.py` is deleted): the two things it was chosen for (FOV, pathfinding)
  are already written by hand in `game/`, and no commercially released game appears to use
  `python-tcod`, while pygame and Ren'Py have a real shipping record.
- **Every bundled file is read through `game.paths.resource_path()` and every written file goes
  under `game.paths.user_data_dir()`.** In an installed exe the CWD is neither where the assets are
  nor writable. Saves (`savegame.json`, written atomically) and `crash.log` live in the user data
  dir; an old `./savegame.json` is copied there once, never deleted.
- `curses` ships with Python on Linux/macOS. Windows needs `pip install windows-curses`.
- Prefer adding a new file under `game/` or `render/` over growing an existing one — the package
  split (vs. the spec's single-file skeleton) is intentional; see `going_graphical.md` for why.

## Conventions

- **Coordinates are `(y, x)` in curses calls, `(x, y)` in game logic.** `stdscr.addstr(y, x, text)`
  and `stdscr.addch(y, x, ch)` take row first; `Entity`, `Rect.center()`, and `move(dx, dy)` use
  x-first. This mismatch is the most common source of bugs here.
- **Map is a 2D list of chars**, indexed `game_map[y][x]`, built by `make_empty_map(w, h, fill='#')`.
- **Tile chars**: `#` wall, `.` floor, `+` door, `>` stairs down, `@` player, lowercase letters for
  monsters (uppercase for a boss version of the same kind, e.g. `o`/`O` for orc), `=` chest
  (unopened — pink holds a potion, cyan holds gear; `!`/`/`/`[` potion/weapon/armor only exist transiently once one is opened).
- **Walkability** is a char comparison (`!= '#'`), not a tile-type system.
- **Colors** go through `curses.init_pair(n, fg, bg)` and are stored on entities as an int
  (`Entity.color`), rendered with `curses.color_pair(...)`. Pair 1 is yellow-on-black (the player);
  pairs 4-7 are the gear-rarity ladder (`game/item.py`'s `RARITY_COLOR` picks the number); pair 8
  is the pink potion chest.
- Map dimensions are `DEFAULT_WIDTH`/`DEFAULT_HEIGHT` constants in `main.py`, overridden by the
  `MAP_WIDTH`/`MAP_HEIGHT` env vars via `env_int`, and passed explicitly into `GameState(width,
  height, ...)`. `GameState` keeps them as `self.width`/`self.height`; nothing under `game/` reads
  the environment or a module global for size.

## Current state

All of spec §3–§7 and all six §8 stretch goals are implemented:
- `Rect` with `center()` / `intersects()` (§3)
- Room-and-corridor dungeon generation (§3): `generate_dungeon` rolls a random target room count in
  `[min_rooms, max_rooms]` (default 4-6), keeps placing non-overlapping rooms (`min_size=4,
  max_size=8`, the spec's own range) until it hits that target or exhausts `max_attempts`; on
  either the 50x20 code default or the 40x20 the checked-in `.env` produces, this reliably lands at
  4-6 rooms (verified over 400 generations each). Room size is clamped to whatever actually
  fits in `(w, h)`, and generation falls back to a single interior room if nothing fits — so
  `rooms[0]`/`rooms[-1]` are always safe to use even on tiny maps. **Corridors come after every
  room is carved** (`connect_rooms`, joining each room to the one placed before it — so no room can
  land with its wall along an existing corridor), and each is the cheapest 4-way path from
  `route_corridor`: crossing a wall costs `DOORWAY_COST`, rock `ROCK_COST`, existing floor or an
  existing doorway `FLOOR_COST`, and it may never walk *along* a wall, step through a ring corner,
  or open a wall tile next to an existing doorway in the same wall. The spec's L-shaped corridor is
  only a fallback if routing fails (never seen in 2000 maps; ~8 ms a map). Doors (`+`) go *in the
  doorway*: `place_doors` then walks each room's wall ring (`wall_sides(room)`, corners excluded)
  and puts a door on every single-tile gap, flanked by wall on both sides — never on the room's own
  floor (the old bug: doors sat on the room's edge tile, which let sight around them). Thanks to the
  routing, every opening is such a gap; `place_doors` would still leave a wider one open, since one
  door can't close it. Two rooms two tiles apart get a door in each wall (`++`).
  `tiles.is_transparent` treats `+` as opaque like a wall, so a room stays hidden from its corridor
  until the player steps into the doorway — `is_walkable` still allows walking through it.
  `DoorPlacementTests` checks placement, that no opening is wider than one tile, that every room is
  reachable, and that a closed doorway hides the room.
- `Entity` with collision-checked `move` (§4)
- Recursive shadowcasting FOV (§5, stretch #6): `game/fov.py`'s `compute_fov` — walls block sight;
  `update_visibility` folds the result into the `seen` fog-of-war grid. Replaced the old radius-only
  placeholder entirely.
- WASD/arrow movement, `.` wait, `q` quit, main loop in `main.py` (§7)
- Stairs (stretch #1): `dungeon.place_stairs` marks `rooms[-1].center()` with `>`; `GameState.
  try_descend` / `next_level` regenerate the dungeon and reset the player, monsters, chests, and fog
  when the player presses `e` while standing on it. (Was `>` originally; changed because it needed
  shift on most layouts and read confusingly next to the stairs tile glyph, which is still `>` —
  that's the map symbol, unrelated to the keybinding.)
- HP/inventory side panel (stretch #2): `render/curses_render.py`'s `_draw_panel` (drawn at
  `x = state.width + 2`) shows class + depth, HP (red via pair 2 at or below a third of max),
  `ATK`/`DEF`, inventory count, a `-- gear --` block, a class-dependent control list, and the last
  `MESSAGE_LOG_LINES` (4) entries of `state.messages` (appended by `GameState.log`).
- `Monster(Entity)` (stretch #3, `game/monster.py`): `hp`/`power`/`alive`/`take_turn(player,
  game_map)`. Chases within 8 tiles (`distance_to <= CHASE_RANGE`), wanders otherwise, and returns
  `'attack'` rather than moving when it is already orthogonally adjacent — `GameState`'s monster
  phase resolves the damage via `GameState.attack`, which the player's bump-attack, the archer's
  arrow, and monster attacks all share. `spawn_monsters` rolls `choice([0, 0, 1, 1, 2])` per room,
  skipping `rooms[0]`. Movement is **4-way only** (`ORTHOGONAL_STEPS`, plus `(0, 0)` when
  wandering); `_chase_step` closes the larger gap first and falls back to the other axis when that
  step is walled off. It is still the spec's naive chase, not pathfinding: a monster lined up with
  the player on one axis has no fallback axis, so a wall directly between them stalls it until the
  player moves.
- `Item(Entity)` (stretch #4, `game/item.py`): potions (`!`), weapons (`/`), and armor (`[`). These
  no longer spawn directly on the floor — see the chest system below — but `Item.apply(player, log)`
  is still what actually heals/equips, wherever the item comes from.
- Save/load (stretch #5, `game/save.py`): JSON, not pickle (no arbitrary-code-exec risk from a save
  file). `S` saves to `savegame.json` in the per-user data dir (see **Constraints**), `L` loads.
  Round-trips map, fog, player, class, and live entities. A failed or corrupt save/load is reported
  in the message log ("Save failed: …" / "Load failed: …") instead of crashing.

Beyond the spec's own stretch goals, there's also a title screen (ASCII "PyRogue" banner via
`render/banner.py`, Start/Quit via `render/menu.py`) and a class-select screen. **Warrior**: melee
only, walk into an enemy to hit it — identical to the original single-class combat. **Archer**:
lower HP/power (`CLASS_STATS` in `game/state.py`) but WASD is movement-only and the arrow keys fire
an arrow (`GameState.shoot_arrow`) that travels in a straight line and damages the first monster it
hits, or hits a wall harmlessly. Arrow keys are `Action.SHOOT_*` at the renderer boundary regardless
of class — `GameState.handle_action` is what decides a warrior's `SHOOT_*` is just a move (so a
warrior's arrow-keys-also-move behavior from before classes existed is unchanged) while an archer's
fires. `player.char_class` defaults to, and unrecognized values fall back to, `'warrior'`.

**Rounds are two halves, resolved one entity at a time.** `handle_action` resolves the *player's*
half and then calls `end_player_phase`, which only refreshes FOV and queues the monsters that owe a
turn — it deliberately resolves none of them. The caller then drives `step_monster_phase()` until it
returns False. Each call resolves monsters until one does something the player can see (an attack,
or a move inside FOV) and returns True so the caller can hold that frame; monsters acting out of
sight are folded into the same call, so crossing an empty dungeon costs no extra frames.
`main.resolve_monster_phase` is the driver: it draws *before* each step and calls `renderer.pause`
after a visible one, so the first frame shows the player's own blow landing with the reply still
pending, and each later frame adds exactly one monster's answer. Two consequences worth knowing:

- **A death ends the round immediately.** `_player_just_died` cancels the queue, so monsters further
  down the list never swing at a corpse. Previously every monster acted against the pre-round world,
  so three adjacent goblins all landed hits on a player who died to the first of them, and the HP
  bar went well past zero.
- **`visible_entities()` filters on `alive`.** The renderer now draws mid-round, so a monster killed
  during the player's half has to leave the screen at once rather than at the end of the round.

`GameState.end_turn()` still runs both halves back to back for tests and any headless caller;
`cancel_monster_phase()` drops the queue when the level it refers to is thrown away (descending,
loading a save).

**Gear and rarity** (`game/item.py`): every item — potion, weapon, armor — is tiered Common →
Uncommon → Rare → Epic (`RARITIES`, spawn-weighted 60/25/12/3 via `roll_rarity`). Rarity sets a flat
stat (`GEAR_BONUS`: 1/2/4/7) for weapons (`player.power = player.base_power + bonus`) and armor
(`player.defense = bonus`, subtracted from incoming damage with a floor of 1 in `GameState.attack`),
and a heal amount for potions (`POTION_HEAL`: 8/14/22/35). Gear auto-equips on pickup only if
its bonus beats what is already in that slot; an equal or worse piece is left behind with a log
line (no inventory/drop management).
Rarity also picks the item's on-map color (pairs 4-7 in `render/curses_render.py`, green/blue/
magenta/white for uncommon/rare/epic/common) — the render side panel has a dedicated `-- gear --`
section showing the equipped weapon/armor's name, bonus, and rarity in that color.

**Chests, not bare items, spawn on the floor** (`game/item.py`'s `Chest`, `=` on the map, pink or cyan):
`spawn_chests(rooms)` rolls 50/50 per room — skipping `rooms[0]`, the player's start — and places
a chest instead of a raw `Item`. A chest's *kind* is rolled at spawn (`roll_kind`) so the map can
show it: potion chests are pink (`POTION_CHEST_COLOR`, pair 8 — xterm-256 colour 213, magenta on an
8-colour terminal), gear chests stay cyan (pair 3). Its *rarity* is rolled only when it is opened
(`GameState.open_chest`, triggered by walking onto it) via `roll_rarity`, against the *current
depth*, not the depth it was spawned at. Saves store the kind; a chest from an older save gets one
rolled on load. `rarity_weights_for_depth` interpolates linearly from the depth-1
weights toward a much better table by `MAX_SCALING_DEPTH` (20), then holds steady past that, so "the
deeper you go the better the loot" is continuous rather than tied to the monster-scaling 3-floor
tiers. A boss's chest (`spawn_boss_chest`) ignores that table entirely and always rolls rare or epic
(75/25) regardless of depth — the spec-follow-up's "guaranteed rare drop."

**Difficulty scaling and bosses** (`game/monster.py`): `tier_for_depth` buckets every 3 floors;
`scale_stats` compounds 1.2x hp and +1 flat power per tier onto a monster's base stats. Every 8th
floor (`is_boss_level`) also spawns exactly one boss (`spawn_boss`, on top of the normal monster
spawn, not instead of it) at 2x hp / 1.5x power of that depth's scaled orc, drawn bold+underlined.
A killed boss always drops a guaranteed-rare-or-better chest (see above) — `GameState.attack`.

**Windowed renderer** (`render/pygame_render.py`, plan §3.1 spike — done 2026-10-12): `main.py`'s
loop is unchanged. `get_action` blocks in `pygame.event.wait()` rather than a sleep, so expose/
resize/close are serviced while the player thinks (verified on i3/X11: ~2% of a core idle, live
repaint on resize mid-`get_action`). `pause(ms)` pulls only window events off the queue and leaves
key presses queued, so typing ahead during the monster phase behaves like curses' `getch`. A window
close seen in a menu or pause is remembered and delivered as `Action.QUIT` by the next
`get_action`. Layout picks the largest font size whose `cols x rows` grid fits the window and
letterboxes it (crisp text, no scaling); tiling WMs resize the window at creation, which is
expected. **F11** toggles borderless fullscreen; it is handled inside the renderer (never an
`Action`), so it works in menus, mid-game and on the death screen. It uses
`pygame.Window.from_display_module().set_fullscreen()` because, on i3/X11,
`display.toggle_fullscreen()` hangs and `set_mode(..., FULLSCREEN)` destroys and recreates the OS
window; that call is deprecated in pygame-ce 2.4+ (its warning is silenced) — fine while
`requirements.txt` pins pygame-ce, revisit on upgrade. Bosses are drawn brighter, bold and
underlined, matching curses. Verified in a real window on Linux; on Windows only via CI's
headless tests so far.

**Tiles** (WS-C, 2026-10-13): when the `Tileset` loads, `ui.Layout(..., tiles=True)` gives the map
its own grid of square cells (`layout.tile` px, picked from `TILE_SIZES` = 64…16 in steps of 4, scaled nearest-neighbour — the largest that
leaves the panel a font of at least 12) at `layout.map_origin`, beside the text panel at
`panel_x`/`panel_y`; draw map cells through `layout.map_cell_to_pixel`, never `cell_to_pixel`.
The text grid then spans the whole window, so menus centre in it. Remembered cells are the tile
multiplied darker (`dim=True`); bosses are told apart by their own `tiles.json` entry (a helmet and
a bigger weapon), not by bold/underline. A char with no entry falls back to its glyph centred in
the tile. The first window is sized to 85% of the desktop. Glyph mode (`TILES=0`, or no assets) is
unchanged.

**P3 window polish** (2026-10-13, two agents in worktrees, merged by a coordinator):
- **Noticeboard** (2026-10-13, `render/noticeboard.py`): the panel is drawn as a framed wooden board
  with a parchment page hanging from a nail, cached per size. Text on it is ink: `palette.INK`,
  `INK_DANGER` and `palette.ink(color)` (the rarity ladder's darker twins — common is plain ink,
  since white vanishes on paper). The paper under the text is one flat colour (`palette.PAGE`) so
  tests can tell ink from paper. Text starts at `layout.text_x`/`text_y` (`PANEL_PAD_X`/`_TOP`
  inside the board); `page_rect()`/`text_rect()` give the page and its text area. The board is
  `PANEL_COLS = 34` wide with gear slots split over two rows — every column it takes is map width,
  and this is what gives 40 px tiles at 1080p, 32 at 900p, 24 at 720p.
- **Panel** (`render/ui.py`): an HP bar on the HP row (red at or below a third, like the text), and
  a message log of `MIN_LOG_LINES` (4) up to `LOG_LINES` (12) lines — `Layout.log_lines()` derives
  the count from the rows the panel has, and `ui.log_rows()` word-wraps messages to the panel width
  (a message is shown whole or not at all). `tests/test_ui.py`'s `PanelParityTest` is the parity
  checklist against `curses_render._draw_panel`, run in four layouts.
- **Tall/narrow windows:** `Layout.stacked` puts the panel *under* the map when that gives a bigger
  font (glyph mode) or tile (tile mode); every other `Layout` name keeps its meaning.
- **`Canvas.put`/`put_str`/`text_surface` take `bold=`**; bosses are drawn through it.
- **Game-over banner:** `screens.game_over_rect` puts a framed box at the end of the map (top or
  bottom) farther from the player, split over two lines on a map narrower than the text.
- **Mouse in menus only:** hover moves the highlight and a left click selects, via
  `screens.option_at(layout, menu, banner_lines, pixel)`, which shares `paint_menu`'s geometry.
  `_wait_input(mouse=True)` is the menu wait; `get_action` uses `_wait_key()`, which skips mouse
  events — gameplay stays keyboard-only, and `pause` still leaves keys queued.
- **Bundled font:** `assets/fonts/JetBrainsMono-Regular.ttf` (SIL OFL 1.1) is `ui.Layout`'s default
  font (`ui.BUNDLED_FONT`), so the game *and the tests* use the same metrics on every OS;
  `ui.FONT_NAMES` (system fonts) is only the fallback when it's missing. Layout tests used to run on
  whatever system font CI had (Consolas on Windows) and broke there; the layout code must hold for
  fonts with tall line heights like this one (see `_place_stacked_tiles`: the panel never overlaps
  the map, even if it has to run off the bottom).

Test coverage: `test_game.py` (80 tests) + `test_menu.py` (7) + `test_loop.py` (7) +
`test_pygame_render.py` (46) + `test_ui.py` (55) + `test_tileset.py` (12) + `test_camera.py` (14) +
`test_parity.py` (4) +
`test_paths.py` (28) + `test_settings.py` (18) + `test_crashlog.py` (7) + `test_main.py` (2) +
`test_frozen_smoke.py` (7) = 287 unit tests, plus ad hoc fuzz/PTY smoke testing during development — see `agent_log.md` for
what was run and why.

**Combat zoom** (2026-10-13, `render/camera.py`, window only): when a monster is orthogonally
adjacent (`GameState.melee_opponents()`), the map zooms in so the player and that monster sit at the
centre of the map area with 2 squares (`camera.MARGIN`) round them, and zooms back out when the fight
ends or the player dies. Warriors only (`camera.ZOOM_CLASSES`) — the archer is left out for now.
It is *staged*: `GameState.attack` appends a `game.combat.Hit` (with an ever-growing `serial`) to
`state.combat_events` (cleared when the player acts), and `camera.Director.plan(state)` turns what
is new since the last frame into beats — `Impact(hit)` for each visible blow, then `Pan(start, end)`
if the view must move. `PygameRenderer.draw` plays each beat via `_play(ms, paint)` (`IMPACT_MS`
flash + rising damage, `ZOOM_MS` eased pan) before showing the frame, so a killing blow lands
zoomed-in before the camera pulls out. `_play` services the window like `pause` and never takes
keys; a queued key cuts the beat short, so animation never delays input. A new effect is a new beat
type plus a player — `main.py`'s loop and curses are untouched. Views are in map cells and not
clamped to the map (off-map is dark), `camera.project` fits one into `layout.map_rect()` with
whole-pixel cells; map cells must go through `_map_cell_rect`, which honours the projection.
Mid-pan tile sizes are scaled from the source tile each frame rather than cached (`_tile`).

## Gotchas

- `addstr`/`addch` raise on the terminal's bottom-right cell, and off-screen writes raise too.
  `CursesRenderer._put` / `_put_str` already bounds-check against `getmaxyx()` and swallow
  `curses.error`, and `_put_str` truncates to the window width — draw through those helpers rather
  than calling `addch`/`addstr` directly, or the guard is lost.
- **`Entity.distance_to` and `Entity.is_adjacent` use different metrics, on purpose.**
  `distance_to` is Chebyshev (`max(|dx|, |dy|)`) and is only a loose "is that near me" radius check
  (chase range, FOV-ish distances). `is_adjacent` is orthogonal (`|dx| + |dy| == 1`) and is the only
  thing that may decide whether an attack can land. Using `distance_to(...) <= 1` for adjacency is
  the bug that let monsters hit diagonally from squares the 4-way player could not hit back from.
- `Entity.move` does not bounds-check, so the map border must stay solid `#`. Dungeon generation
  keeps rooms inside `range(1, w - rw - 1)` for this reason.
- If the terminal is left broken after a crash, run `reset`.
- Scripting keyboard input against curses via a pty (e.g. for a smoke test): terminfo maps arrow
  keys differently per `$TERM`. For `TERM=xterm`, `infocmp xterm | grep kcu` shows they're SS3
  sequences (`\EOA` for up, etc.), *not* the `\E[A`-style CSI sequences a real xterm sends after
  `smkx` — curses silently drops the wrong ones as unbound characters instead of erroring, so a test
  can pass for the wrong reason. See `agent_log.md` §7a for how this was caught.
