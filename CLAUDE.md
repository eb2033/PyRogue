# PythonRogue

A turn-based roguelike in a pygame-ce window, shipped as a frozen PyInstaller build for Windows and
Linux. It started from `roguelike_reference.md`, an offline spec (see **Private docs**). The game
logic under `game/` is standard library only; the window lives under `render/`.

## Running

```bash
.venv/bin/python main.py      # the game, in a window; F11 toggles borderless fullscreen
./packaging/build.sh          # frozen Linux build -> dist/PyRogue/ + dist/PyRogue-linux-<version>.zip
./packaging/build.ps1         # the same on Windows (pwsh)
```

There is no `--renderer` option and no terminal build: the game is the window only.

Setting up a checkout (or a fresh worktree; `.venv` is gitignored):

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # pygame-ce, pinned
.venv/bin/pip install -r requirements-test.txt     # hypothesis, for tests/test_properties.py
.venv/bin/pip install -r requirements-lint.txt     # ruff, pyright, vulture
.venv/bin/pip install -r requirements-dev.txt      # pyinstaller + hooks, for packaging only
```

Tests and checks (config in `pyproject.toml`, the same commands CI's `lint` job runs):

```bash
.venv/bin/python -m unittest discover -s tests     # add -v for names
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/vulture                                  # false positives go in vulture_allowlist.py
```

The pygame suites run headless (they set `SDL_VIDEODRIVER=dummy` themselves) and skip cleanly
without pygame; `tests/test_properties.py` skips without hypothesis; the launch test in
`tests/test_frozen_smoke.py` skips unless `dist/PyRogue/` exists. Measured 2026-10-15 with
everything installed and a built `dist/`: **522 tests, all passing** (~34 s).

## CI and releases

`.github/workflows/ci.yml`, on every push and PR (and "Run workflow" on the Actions tab):

- **lint** (Ubuntu, Python 3.14): `ruff check`, `ruff format --check --diff`, `pyright`,
  `vulture`. Every step runs even if an earlier one failed.
- **test**: `python -m unittest discover -s tests -v` on Ubuntu + Windows × Python 3.12/3.13/3.14,
  with SDL's dummy video/audio drivers.
- **stdlib-only**: nothing installed; imports `main`, `game.state`, `game.paths`,
  `game.settings`, `game.crashlog`, `game.version`, then runs the whole suite (pygame and
  hypothesis tests must skip, not fail).
- **frozen-build** (after lint and test; only for pushes to `main`, tags and manual runs): freezes
  the game on Windows and Linux, runs `tests.test_frozen_smoke`, and keeps the zips as artifacts
  for 7 days. It is the only place the Windows exe gets built before a release.

`.github/workflows/release.yml`, on a `v*` tag (which must match `game/version.py`) or manual
dispatch: builds and smoke-tests both zips, then (tags only) publishes a GitHub Release with
`SHA256SUMS` and the matching `CHANGELOG.md` section. It pushes to itch.io only if a
`BUTLER_API_KEY` secret (plus an `ITCH_PROJECT` repo variable) is set. The release checklist is in
`CHANGELOG.md` and `packaging/NOTES.md`.

## Layout

- `main.py`: entry point. `settings.load()` first, then `make_renderer` (imports pygame there, so
  `import main` stays stdlib-only), the title and class-select menus, a `GameState`, and `run()`:
  `draw` / `get_action` / `handle_action`, then `resolve_player_strikes` and
  `resolve_monster_phase` (see **Rounds**). Its `__main__` block appends an uncaught exception to
  `crash.log` via `crashlog.write` *explicitly*, not through `crashlog.install()`'s excepthook (a
  windowed PyInstaller build may show its own error dialog and never run the hook), then
  re-raises.
- `game/`: all game logic, standard library only, `(x, y)` throughout.
  - `state.py`: `GameState`, turn resolution, combat (`attack`, `melee`, crits), chests, the
    potion belt, shrines, `CLASS_STATS`.
  - `dungeon.py`, `rect.py`, `tiles.py`: generation, `Rect`, tile chars and walkability.
  - `entity.py` (`Entity`, `Player`), `monster.py` (`Monster`, AI, tier scaling, the boss),
    `spawn.py` (who spawns where), `item.py` (items, gear, chests), `shrine.py` (shrines, boons),
    `damage.py` (damage reduction and rounding), `combat.py` (the `Hit` record), `fov.py`
    (recursive shadowcasting), `rng.py` (the `Rng` type for seeded rolls).
  - Platform layer: `paths.py` (`resource_path()` for anything bundled: `sys._MEIPASS` → exe dir →
    repo root; `user_data_dir()` for anything written: `%APPDATA%\PyRogue`,
    `~/Library/Application Support/PyRogue`, `$XDG_DATA_HOME/pyrogue` or `~/.local/share/pyrogue`,
    all overridden by `$PYROGUE_DATA_DIR`), `settings.py` (the stdlib `.env` reader, `env_int`),
    `crashlog.py`, `version.py` (`__version__`, the single source for the exe's file properties
    and release tags).
- `render/`: the window.
  - Pure, no pygame: `base.py` (`Action`, the semantic key names, and the `Renderer` interface:
    `draw`/`get_action`/`show_title_screen`/`choose_class`/`pause`/`close`), `menu.py` (menu
    selection state), `banner.py` (the ASCII "PyRogue" banner), `choice.py` (the text of the
    choose-one-of-three cards), `palette.py` (`Entity.color` int → RGB, and the panel's ink
    colours), `camera.py` (combat zoom geometry, beats, hit shake).
  - pygame: `pygame_render.py` (`PygameRenderer`: window, event loop, map, effects, F11),
    `input_map.py` (key → `Action`), `ui.py` (`Layout`, the single source of truth for geometry;
    `Canvas` for grid text; `paint_panel`), `screens.py` (menus, the choice box, the game-over
    banner, and their mouse hit-tests), `noticeboard.py` (the panel's board and page),
    `tileset.py` (`Tileset.glyph(char, color, size, dim)` → a tile Surface, or `None` meaning
    "draw the character").
  - Module docstrings name a workstream owner (WS-A…WS-G) from `desktop_build_plan.md` §5. When
    several agents work in parallel, each edits only the files its workstream owns.
- `assets/`: three Kenney CC0 roguelike sheets (`assets/kenney/*/`, each with its `License.txt`),
  `tiles.json`, `blood/` (five CC0 blood decals for the boss arena), `fonts/` (JetBrains Mono,
  OFL), `icon.png`/`icon.ico` (generated from the `@` tile by `packaging/make_icon.py`).
  **`assets/ASSETS.md` must list every file with its source and licence**, CC0 or equivalent only;
  `tests/test_tileset.py` enforces the listing and a 10 MB budget for `assets/`.
- `packaging/`: `pyrogue.spec` is the source of truth for the PyInstaller build (**onedir,
  `upx=False`, never onefile**; `console=False`; excludes tkinter, numpy, unittest, curses and
  tcod; bundles `assets/`). `build.sh` / `build.ps1` clean, build and zip via `make_zip.py`;
  `version_info.py` writes the Windows file properties; `README.txt` is the player readme.
  `THIRD_PARTY_NOTICES.txt` and `licenses/` are copied into every bundle by
  `collect_licenses.py`, which also adds the building Python's `LICENSE.txt`.
  `tests/test_frozen_smoke.py`'s `NoticesTest` fails if pygame-ce bundles a native library the
  notices don't cover: after a pygame-ce upgrade, add a row and its licence file.
  `NOTES.md` has the antivirus rules, how to add a data file, and the release checklist.
- `tests/`: headless `unittest` suites (see **Tests**).
- Also tracked: `README.md`, `CHANGELOG.md`, `agent_log.md` (a log of what earlier agents ran and
  why), `docs/screenshot.png`, `.github/dependabot.yml`.

### Private docs

`roguelike_reference.md` (the original spec; section numbers in code comments refer to it),
`going_graphical.md` (research notes on going graphical) and `desktop_build_plan.md` (the plan
that took the game into a window and a `.exe`: workstreams, §4.1 status, §5 file ownership) are
**gitignored and untracked on purpose** (the repo is public). They exist only in the primary
checkout, not in a worktree or a fresh clone; from a worktree, read them from the first path `git
worktree list` prints. Don't `git add -f` them. They predate the removal of the terminal renderer
and saves, so where they disagree with the code, the code wins.

## Constraints

- **Standard library only for `game/` and for `main.py`'s imports.** pygame-ce is imported only
  under `render/` (by `pygame_render.py`, `input_map.py`, `ui.py`, `screens.py`, `noticeboard.py`,
  `tileset.py`) and inside `main.make_renderer`. CI's `stdlib-only` job enforces it, and every
  pygame test must skip cleanly without pygame. `requirements.txt` holds the only runtime
  dependency.
- **Every bundled file is read through `game.paths.resource_path()`; every written file goes
  under `game.paths.user_data_dir()`.** In an installed exe the CWD is neither where the assets
  are nor writable. Today the only written file is `crash.log`.
- **Packaging stays onedir with `upx=False`** (`packaging/NOTES.md`, "Antivirus rules"; the
  onefile bootloader and UPX both trip antivirus). `tests/test_frozen_smoke.py` fails if
  `upx=True` appears in the spec.
- Prefer a new file under `game/` or `render/` over growing an existing one.

## Conventions

- **Coordinates are `(x, y)` in game logic.** `Entity`, `Rect.center()` and `move(dx, dy)` are
  x-first; pixels and layout belong to the renderer.
- **The map is a 2D list of chars**, indexed `game_map[y][x]`, built by `make_empty_map(w, h,
  fill='#')`.
- **Tile chars** (`game/tiles.py` and friends): `#` wall, `.` floor, `+` door, `>` stairs down,
  `@` player, `g` goblin, `o` orc, `s` goblin slinger (uppercase for a boss of that kind; only `O`
  spawns today), `=` chest, `_` shrine. `!` `/` `[` (potion, weapon, armor) have tiles but items
  only appear inside chests; junk (`%`) never touches the map.
- **Walkability is a char comparison** (`is_walkable`: `!= '#'`), not a tile-type system. Doors
  are walkable but opaque (`is_transparent` treats `+` like a wall), so a room stays hidden from
  its corridor until the player stands in the doorway.
- **`Entity.distance_to` and `Entity.is_adjacent` use different metrics, on purpose.**
  `distance_to` is Chebyshev and only a loose "is that near me" check (chase range, the zoom's
  hold). `is_adjacent` is orthogonal (`|dx| + |dy| == 1`) and is the only thing that decides
  whether a melee blow can land. Everything moves 4-way; `distance_to(...) <= 1` for adjacency is
  the old bug that let monsters hit diagonally.
- **Colours are `Entity.color` ints** mapped to RGB by `render/palette.py`: 1 player, 2 red
  (monsters, danger), 3 gear chest (cyan), 4-7 the rarity ladder (`game/item.py`'s
  `RARITY_COLOR`: uncommon green, rare blue, epic magenta, common white), 8 potion chest (pink).
  On the panel's paper, `palette.ink(color)` gives the darker twin.
- **Map size** is `DEFAULT_WIDTH`/`DEFAULT_HEIGHT` (50x20) in `main.py`, overridden by
  `MAP_WIDTH`/`MAP_HEIGHT` and passed into `GameState(width, height, ...)`. Nothing under `game/`
  reads the environment.
- **Settings** (`game/settings.py`): `KEY=VALUE` lines, `#` comments, optional quotes; a real
  environment variable always wins. Search order: `$PYROGUE_CONFIG` → `.env` next to the exe (or
  next to `main.py` from source) → `.env` in the CWD. `main.py` reads `MAP_WIDTH` (50),
  `MAP_HEIGHT` (20), `FOV_RADIUS` (6), `TURN_DELAY_MS` (110; `0` resolves a round instantly),
  `TILES` (1; `0` draws characters instead of tiles) and `COMBAT_ZOOM` (1; `0` turns the zoom
  off). `env_int` falls back to the default on an unparseable value. The checked-in `.env` sets
  `MAP_WIDTH=40` and `MAP_HEIGHT=20`, so a source run is 40x20; the `.env` is not bundled, so the
  exe uses 50x20.

## Gotchas

- **`Entity.move` does not bounds-check**, so the map border must stay solid `#`.
  `generate_dungeon` places rooms at x in `[1, w - rw - 1]` (and the same for y) for this reason.
- **The window must never block in a sleep.** `get_action` waits in `pygame.event.wait()`, which
  also wakes for expose/resize/close, so the window repaints and is never "Not Responding".
  `pause(ms)` and animation beats (`_play`) pull only window events off the queue and leave key
  presses queued, so typing ahead works. A window close seen in a menu or a pause is remembered
  and delivered as `Action.QUIT` by the next `get_action`.
- **F11 is handled inside the renderer, never an `Action`**, so it works in menus, mid-game and
  on the death screen. It uses `pygame.Window.from_display_module().set_fullscreen()` because on
  i3/X11 `display.toggle_fullscreen()` hangs and `set_mode(..., FULLSCREEN)` recreates the OS
  window; that call is deprecated in pygame-ce 2.4+ (the warning is silenced), fine while
  `requirements.txt` pins pygame-ce.
- Tiling window managers resize the window at creation; `Layout.fit` copes. The first window is
  85% of the desktop (`ui.DESKTOP_SHARE`).
- **Map cells go through `_map_cell_rect`** (and, in tile mode, `layout.map_cell_to_pixel`, never
  `cell_to_pixel`): only those honour the combat zoom's projection.
- **The bundled font is the default** (`assets/fonts/JetBrainsMono-Regular.ttf`), so the game and
  the tests get the same metrics on every OS; system fonts (`ui.FONT_NAMES`) are only a fallback.
  Layout code must hold for fonts with tall line heights like this one.
- **Crash log:** an uncaught exception lands in `user_data_dir()/crash.log` (`main.py`'s
  `__main__`, see **Layout**). The windowed exe has no console, so look there first.
- **Packaging:** read `packaging/NOTES.md` before touching the spec or adding a data file.

## Tests

| File | Covers |
|---|---|
| `test_game.py` | `game/`: dungeon gen, doors, movement, adjacency, FOV, monster AI, spawn rules, collisions, chase give-up, turn phases, classes and the archer, gear, scaling, chests, potion belt, chest choice, combat events, crits and damage reduction, weapon types, boss enrage, slingers, shrines and boons |
| `test_damage.py` | `game/damage.py`: reduction, mitigation, probabilistic rounding |
| `test_properties.py` | Hypothesis properties: solid border, reachability, doors, FOV, loot and scaling monotonicity, settings parsing, camera projection, log wrapping, random playthroughs |
| `test_loop.py` | `main.resolve_player_strikes` / `resolve_monster_phase` with a recording renderer: frame-by-frame order of a round, the rapier's beat |
| `test_camera.py` | `render/camera.py`: view geometry, the director's gate and hold, the spear's zoom, smooth zoom, hit shake |
| `test_pygame_render.py` | the renderer: events, fullscreen, game over, a scripted run through `main.run`, tile mode, hit shake and health bars, choice screens (chests and boons), the boss arena |
| `test_ui.py` | `Layout` (glyph, tile, stacked), message log, `Canvas` bold, menu hit-tests, paint smoke tests, game-over banner, noticeboard, panel |
| `test_tileset.py` | fallbacks on missing/corrupt assets, a tile for every drawable char, chest colours, `ASSETS.md` provenance, the 10 MB budget |
| `test_menu.py` | `Menu` and the banner |
| `test_parity.py` | the window's key table reaches every `Action`; F11 never shadows a game key |
| `test_paths.py`, `test_settings.py`, `test_crashlog.py` | the platform layer |
| `test_main.py` | `main.py` as a subprocess: config loading before the window, crash logging |
| `test_frozen_smoke.py` | the spec (onedir, no UPX), version resource, third-party notices; launches `dist/PyRogue/` if it exists |

Nothing tests what the window looks like to a person; check rendering changes by running the game.

## Current state

### Rounds

A round has two halves, resolved one step at a time so each blow can be seen.

- **Player half.** `handle_action` applies the action. A melee hit goes through `melee`; a
  rapier's second strike is *queued* (`strike_pending`), not swung at once. `main.
  resolve_player_strikes` draws the first hit (its impact beat plays), holds the frame for
  `TURN_DELAY_MS`, then calls `step_strike` to roll the next one. The last strike calls
  `end_player_phase`, which refreshes FOV and queues the monsters that owe a turn, resolving none
  of them. `resolve_player_phase` lands every queued strike at once for headless callers.
- **Monster half.** `main.resolve_monster_phase` draws *before* each `step_monster_phase()` and
  pauses after a visible step (an attack, or a move in view); monsters acting out of sight fold
  into the same call, so crossing an empty dungeon costs no frames.
- **A death ends the round at once** (`_player_just_died` cancels the queue), and
  `visible_entities()` filters on `alive`, so a monster killed mid-round leaves the screen at once.
- `end_turn()` runs both halves back to back for tests. `cancel_monster_phase()` drops the queue
  when the level is thrown away (descending).
- Turn-taking actions bump `state.turn` (the zoom's hold counts it). Waiting (`.`), bumping a wall
  and drinking take a turn; a refused move, a choice key, or `e` off the stairs do not.

### Classes and stats

- `CLASS_STATS`: **warrior** 60 HP / 4 power, **archer** 45 / 3. Both start with a common plain
  weapon (Rusty Dagger, +1). Unknown classes fall back to warrior.
- Keys: WASD move, arrows `SHOOT_*`. For a warrior the arrows also move (bump to attack); for an
  archer they fire an arrow (`shoot_arrow`) that flies straight until a wall or the first monster.
  `.` wait, `e` descend (on `>`), `h` drink, `1`/`2`/`3` choose, `q` quit.

### Damage, crits and gear (`game/damage.py`, `game/state.py`, `game/item.py`)

- Damage: `raw = attacker.power`; `mitigate` removes `defense / (defense + DEFENSE_K)` of it
  (`DEFENSE_K = 10` gives 50% at 10 defence), never below 1.0; `round_damage` rounds
  probabilistically (2.3 → 3 with 30% chance), so averages hold.
- Crits: player only, `crit_chance` = `BASE_CRIT_CHANCE` (0.10) + the weapon's `crit_bonus` +
  boons, capped at 1.0. A crit multiplies raw damage by `CRIT_MULTIPLIER` (1.5) before defence
  and logs "Critical hit!".
- Rarity: common/uncommon/rare/epic. Rarity weights go linearly from 60/25/12/3 at depth 1 to
  10/25/35/30 at `MAX_SCALING_DEPTH` (20), then hold. Rolled when a chest is *opened*, at the
  current depth.
- Weapons (weapon slot): damage bonus `GEAR_BONUS` 1/2/4/7 plus a per-type offset, and an effect:
  war axe (−1, +3/6/9/15 max HP), rapier (−2, strikes twice), great sword (+1, cleaves one more
  monster orthogonally adjacent to the player), sword & shield (0, +3/6/9/12 defence), dagger
  (−1, +5/10/15/20% crit), spear (0, reach 2: hits a visible monster two tiles away through a
  clear, door-free tile). The plain weapon line is only the starting weapon; it never drops.
- Armor: `ARMOR_DEFENSE` 3/6/12/21, a percentage damage reduction via `mitigate`; it stacks with
  the shield. `gear_power` never drops below `MIN_POWER` (1). Equipping always replaces the old
  piece; power and defence are recomputed from scratch.

### Chests and the potion belt

- `spawn_chests`: never in `rooms[0]` or on the stairs. Each other room gets a potion chest (pink)
  with 25%; at most one gear chest (cyan) per floor with 40%, **except floor 1, which always gets
  one**.
- A gear chest offers `GEAR_CHEST_DROPS` (3) choices: each is junk ("Rusty scrap", 15%) or gear
  (armor is 20% of all drops, the rest weapons split evenly over the six types). The choice is
  shown as three cards; `1`/`2`/`3` or a left click on a card takes one (`choose`). There is no
  cancel, nothing else can happen until one is taken, and choosing takes no turn.
- A killed boss drops a boss chest: three rare/epic (75/25) gear choices, no junk.
- A potion chest's potion is drunk at once if hurt, else put on the **belt**: `BELT_SLOTS` (3)
  plus boons. `h` drinks slot 1 (heals `POTION_HEAL` 20/35/55/88 × boons); an empty belt logs "No
  potions" and takes no turn. Stepping onto a potion chest at full HP with a full belt is refused
  ("Your potion belt is full."): no move, no turn.

### Monsters and spawning (`game/monster.py`, `game/spawn.py`)

- Base stats (hp, power): goblin 11/2, orc 27/4, goblin slinger 7/1. Every 3 floors is a tier:
  ×1.2 HP (compounding) and +1 power per tier, e.g. depth 4-6 goblin 13/3, orc 32/5; depth 7-9
  goblin 16/4, orc 39/6.
- AI: 4-way only. A monster sees the player when its tile is in the player's FOV; it chases
  within 8 tiles (`CHASE_RANGE`), gives up after 3 blind turns (`GIVE_UP_AFTER`), else wanders.
  Monsters never share a tile. The chase is greedy, not pathfinding: a wall directly between a
  monster and a lined-up player stalls it.
- Slinger: while it sees the player, it backs away within 2 tiles (`KEEP_AWAY`) and otherwise
  shoots along a clear row or column up to 5 tiles (`SHOOT_RANGE`); never through a wall, a door
  or another creature.
- `SPAWN_RULES`: **one enemy kind per room** (every room but `rooms[0]`), picked with equal
  weight from the rules for the depth: goblin packs (1 on floors 1-5, 2 on 6-10, 3 from 11),
  a lone orc through floor 8 and a spread pair after, a lone slinger from floor 4.
- Boss: every 8th floor (`is_boss_level`), one random non-start room is the **boss arena**
  (`state.boss_arena`): the boss (`O`, 2× HP and 1.5× power of that depth's orc: 78/9 on floor 8)
  at its centre, with `BOSS_ESCORTS` beside it (one orc on floor 8) and no regular pack. At half
  HP it enrages once and summons min(tier, 2) goblins within 3 tiles.

### Shrines (`game/shrine.py`)

- On 40% of non-boss floors, at most one, in a room other than `rooms[0]` and the boss room, never
  on the stairs, a chest, a monster or the player.
- Walking onto one offers 3 different boons on the same choice screen as a chest (titled "Choose
  a boon"); the shrine is then gone. Boons last the run (`Player.boons`) and are derived where
  used, so none applies twice; max HP is added once and HP clamped to at least 1. Boons: Blood
  pact (+3 power, −15 max HP), Iron skin (+2 defence, −25% potion heal), Quick hands (+1 belt
  slot, −25% potion heal), Keen eye (+10% crit, −10 max HP), Stone heart (+15 max HP, −1 power).

### Dungeon and FOV

- `generate_dungeon`: a random target of 4-6 rooms (4-8 tiles a side, clamped to the map),
  non-overlapping, up to `max_attempts` (300); a single interior room if nothing fits, so
  `rooms[0]`/`rooms[-1]` are always safe. Corridors come after every room is carved
  (`connect_rooms`, each room to the one before) via `route_corridor`'s cheapest 4-way path
  (`DOORWAY_COST` 20, `ROCK_COST` 3, `FLOOR_COST` 1), with the spec's L corridor as a fallback.
  `place_doors` puts a `+` in every one-tile gap in a room's wall. Stairs at `rooms[-1].center()`;
  `e` on them builds the next floor.
- `game/fov.py`: recursive shadowcasting; `seen` keeps remembered cells, drawn dimmed.

### The window (`render/`)

- **Title and class select:** the banner with Start/Quit, then Warrior/Archer with a description.
  Up/down or w/s, enter/space to pick, `q` quits; the mouse hovers and clicks in menus only.
  Gameplay is keyboard-only, except a click on a choice card.
- **Layout** (`ui.Layout`): glyph mode, or tile mode when the `Tileset` loads, with square tiles
  from `TILE_SIZES` (64…16) scaled nearest-neighbour. The panel sits right of the map, or under it
  (`stacked`) when that gives bigger cells.
- **Panel** (`ui.paint_panel` on `noticeboard.py`'s wooden board and parchment page, `PANEL_COLS`
  = 34): class and depth, HP with a bar (red at or below a third), ATK/DEF, item count, weapon and
  armor (two rows each, in rarity ink), the belt slots, boons, controls, and a word-wrapped log of
  4-12 lines (`Layout.log_lines()`).
- **Tiles:** `assets/tiles.json` maps each char to a stack of sheet cells (`layers`, optional
  `backdrop` or `tint` in the entity's colour). Bosses get their own entry (helmet, bigger
  weapon); in glyph mode a boss is brighter, bold and underlined. A char with no tile falls back
  to its glyph.
- **Boss arena:** the arena's 3x3 centre is drawn as darker stone, and blood decals from
  `assets/blood/` are scattered over its floor, laid out the same every frame.
- **Combat zoom** (`render/camera.py`, warriors only, `COMBAT_ZOOM=0` disables): with a monster in
  melee range (`zoom_opponents()`, which for a spear also includes its reach targets, so it zooms
  a step earlier), the map pans in so the player and that monster sit centred with 2 squares round
  them. It never zooms in on a monster the player just stepped away from (the fleeing gate); once
  in, it holds while any visible monster is within 3 tiles and for 2 more turns after, and zooms
  out at once when no monster is in view or the player dies.
- **Beats:** `Director.plan` turns new `state.combat_events` (`Hit`s) into `Impact` beats, then a
  `Pan`. An impact flashes the struck cell red, raises a `-N` damage number (a crit's is double
  size, yellow, black-outlined), shakes the map (180 ms; a crit 280 ms and harder) and jolts the
  struck sprite and its health bar inside its cell. Impacts always play out; a queued key cuts a
  pan or step short.
- **Enemy health bars** above each visible monster: green above half, amber down to a quarter, red
  below; a boss's spans the cell.
- **Walk tilt:** an entity that just stepped leans 15°, alternating left and right, for 110 ms.
- **Game over:** a "YOU DIED" banner across the top of the map; `q` quits.

### Browser build (planned, not started)

A browser version for itch.io is planned as a **separate build**. No browser code exists yet.
Don't change the main build, its loop or its dependencies for it.
