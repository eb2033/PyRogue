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
.venv/bin/vulture                                  # production paths only; test-only API and false positives go in vulture_allowlist.py
```

The pygame suites run headless (they set `SDL_VIDEODRIVER=dummy` themselves) and skip cleanly
without pygame; `tests/test_properties.py` skips without hypothesis; the launch test in
`tests/test_frozen_smoke.py` skips unless `dist/PyRogue/` exists. Measured 2026-10-20 with
everything installed and a `dist/PyRogue/` present: **806 tests, all passing** (~56 s; the suite
was consolidated from 1083 tests on 2026-10-20 with no line or branch of coverage lost, and was
~105 s before corridor routing got faster and the statistical placement tests moved onto synthetic
`Rect` rooms); without
`dist/` the 2 launch tests skip.

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
  `crash.log` via `crashlog.write` *explicitly*, not through an excepthook (a
  windowed PyInstaller build may show its own error dialog and never run the hook), then
  re-raises.
- `game/`: all game logic, standard library only, `(x, y)` throughout.
  - `state.py`: `GameState`, the composition root and the one object `main.py` and `render/`
    talk to: the world's state, the event stream (`sound`, `recording_shot`, `events_since`,
    `hits`), the queries the renderer uses, `CLASS_STATS`, and thin methods that delegate to the
    rule modules below (same names and signatures as before the split, so callers never import
    those). The rule modules are free functions over the state, like `archery.py`, and use only
    its public attributes and methods:
    - `turns.py`: `TurnController` (`state.controller`), the turn controller: `handle_action`'s
      dispatch, `HANDLED_ACTIONS`, the player's half (`melee` and its queued strikes,
      `spend_turn`/restock), the monsters' half (`end_player_phase`, `step_monster_phase`) and
      `end_turn`. It owns the round's bookkeeping (monster queue, owed strikes, free turn).
    - `fight.py`: `attack` (the one place damage is dealt), `crit_chance`/`BASE_CRIT_CHANCE`,
      `dodged`, the parry (`arm_parry`, `parry_progress`, `riposte`, `PARRY_COOLDOWN`),
      `monster_melee`, `monster_shot`, `cleave`, a boss's `summon_goblins`. Patch crit and dodge
      here (`game.fight.BASE_CRIT_CHANCE`, `game.fight.dodge_chance`), not on `game.state`, which
      only re-exports them.
    - `moves.py`: `try_move_player` (walk, bump, open the shop), `arrive` (pick-ups),
      `reach_target` (the spear), the archer's hop (`prime_hop`, `hop`, `cancel_hop`).
    - `loot.py`: chests, shrines, `choose`/`skip_choice`, the shop (`buy`), `take_boon`, gold and
      arrow pick-ups, a dead monster's gold, the potion belt.
    - `floor.py`: `build_map`, `populate_level` (one `occupied` set through every spawner),
      `next_level`, `try_descend`, `DESCENT_HEAL_FRACTION`.
  - `dungeon.py`, `rect.py`, `tiles.py`: generation, `Rect`, tile chars and walkability.
  - `level.py`: **the one model of tile occupancy and blocking.** `BLOCKERS` maps each purpose
    (`MONSTER_MOVE`, `MONSTER_SHOT`, `ARROW`, `HOP`, `REACH`, `KNOCKBACK`, `SUMMON`) to the tags
    that block it, with the full table in the module docstring; every site asks
    `blocking_at(state, x, y, purpose)` (monster AI gets `blocker_tiles(...)` as sets). Also
    `occupant` (the creature on a tile), `room_tiles`/`free_tiles` for the spawners, and
    `draw_layer`, the renderer's paint order (piles, then chests/shrines, then creatures; an
    entity's kind is its class's `layer`, `game/entity.py`). Add a new "is this in the way" rule
    as a purpose row here, never as an ad hoc check at the call site.
  - `entity.py` (`Entity`, `Player`), `monster.py` (`Monster`, AI, tier scaling, the boss),
    `spawn.py` (who spawns where), `item.py` (items, gear, chests), `shrine.py` (shrines, boons
    and the shop's half boons), `gold.py` (`GoldPile`, drop and gold-chest amounts; the balance
    simulation that tuned them lives in `tests/test_gold.py`), `shop.py` (shop floors, offers, prices, the `Shopkeeper`), `sound.py` (sound slot
    names and the `SoundEvent` record), `damage.py` (damage reduction and rounding), `combat.py`
    (the event records `Hit`, `Arrow`, `Shot`, `Parry`; see **Events** under **The
    window**), `fov.py` (recursive shadowcasting), `rng.py` (the `Rng` type of every `rng`
    parameter; see **Randomness** under Conventions).
  - Platform layer: `paths.py` (`resource_path()` for anything bundled: `sys._MEIPASS` → exe dir →
    repo root; `user_data_dir()` for anything written: `%APPDATA%\PyRogue`,
    `~/Library/Application Support/PyRogue`, `$XDG_DATA_HOME/pyrogue` or `~/.local/share/pyrogue`,
    all overridden by `$PYROGUE_DATA_DIR`), `settings.py` (the stdlib `.env` reader, `env_int`),
    `crashlog.py`, `version.py` (`__version__`, the single source for the exe's file properties
    and release tags).
- `render/`: the window.
  - Pure, no pygame: `base.py` (re-exports `Action`, which lives in `game/actions.py`, and the `Renderer` interface:
    `draw`/`get_action`/`show_title_screen`/`choose_class`/`pause`/`close`), `menu.py` (menu
    selection state), `banner.py` (the ASCII "PyRogue" banner), `choice.py` (the text of the
    choose-one-of-three cards), `shop_text.py` (the shop screen's text), `palette.py` (`Entity.color` int → RGB, and the panel's ink
    colours), `camera.py` (combat zoom geometry, beats, hit shake).
  - pygame: `pygame_render.py` (`PygameRenderer`: window, event loop, map, effects, F11),
    `input_map.py` (key → `Action`), `ui.py` (`Layout`, the single source of truth for geometry;
    `Canvas` for grid text; `paint_panel` for the stats board, `paint_log` for the log board),
    `boards.py` (`BoardCache`: each board painted once onto its own Surface, rebuilt only when
    its key -- the layout plus `ui.panel_content` / `ui.log_content`, every value it shows --
    changes; every frame only blits them),
    `screens.py` (menus, the choice box, the shop overlay, the game-over banner, and their mouse
    hit-tests), `noticeboard.py` (a board's wood and page), `tileset.py` (`Tileset.glyph(char,
    color, size, dim)` → a tile Surface, or `None` meaning "draw the character"), `sound.py`
    (`SoundBoard`, which plays the `SoundEvent`s in `GameState.events`).
  - Module docstrings name a workstream owner (WS-A…WS-G) from `desktop_build_plan.md` §5. When
    several agents work in parallel, each edits only the files its workstream owns.
- `assets/`: three Kenney CC0 roguelike sheets (`assets/kenney/*/`, each with its `License.txt`),
  `tiles.json`, `blood/` (five CC0 blood decals for the boss arena), `fonts/` (JetBrains Mono,
  OFL), `icon.png`/`icon.ico` (generated from the `@` tile by `packaging/make_icon.py`). An
  optional `sounds/` (`<slot>.ogg` or `.wav`) is looked for but doesn't exist yet.
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
  `tileset.py`, `sound.py`) and inside `main.make_renderer`. CI's `stdlib-only` job enforces it, and every
  pygame test must skip cleanly without pygame. `requirements.txt` holds the only runtime
  dependency.
- **Every bundled file is read through `game.paths.resource_path()`; every written file goes
  under `game.paths.user_data_dir()`.** In an installed exe the CWD is neither where the assets
  are nor writable. Written files: `crash.log` and `warnings.log` (render-package warnings such as a tileset failure,
  routed there by `crashlog.route_warnings()` because a windowed build has no stderr).
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
  `@` player, `g` goblin, `o` orc, `s` goblin archer, `j` slime (all three sizes; uppercase for a boss of that kind; only `O`
  spawns today), `=` chest, `_` shrine, `$` gold pile, `P` shopkeeper. `!` `/` `[` (potion,
  weapon, armor) have tiles but items only appear inside chests or the shop; junk (`%`) never
  touches the map.
- **Walkability is a char comparison** (`is_walkable`: `!= '#'`), not a tile-type system. Doors
  are walkable but opaque (`is_transparent` treats `+` like a wall), so a room stays hidden from
  its corridor until the player stands in the doorway.
- **`Entity.distance_to` and `Entity.is_adjacent` use different metrics, on purpose.**
  `distance_to` is Chebyshev and only a loose "is that near me" check (chase range, the zoom's
  hold). `is_adjacent` is orthogonal (`|dx| + |dy| == 1`) and is the only thing that decides
  whether a melee blow can land. Everything moves 4-way; `distance_to(...) <= 1` for adjacency is
  the old bug that let monsters hit diagonally.
- **Colours are `Entity.color` ints** mapped to RGB by `render/palette.py`: 1 yellow (player, gold
  piles, gold chests), 2 red (monsters, danger), 3 gear chest (cyan), 4-7 the rarity ladder (`game/item.py`'s
  `RARITY_COLOR`: uncommon green, rare blue, epic magenta, common white), 8 potion chest (pink).
  On the panel's paper, `palette.ink(color)` gives the darker twin.
- **Map size** is `DEFAULT_WIDTH`/`DEFAULT_HEIGHT` (50x20) in `main.py`, overridden by
  `MAP_WIDTH`/`MAP_HEIGHT` and passed into `GameState(width, height, ...)`. That is the *base*
  size: each floor's map is bigger (`dungeon.map_size`, 79x32 on floor 1 from 50x20), and the
  window shows a view of it that follows the player (`camera.view_size`). Nothing under `game/`
  reads the environment.
- **Randomness: one generator per game.** `GameState(..., seed=None)` owns `self.rng =
  random.Random(seed)` and passes it to every roll of a running game: level generation
  (`generate_level`/`generate_dungeon`/`connect_rooms`), spawning, chests (spawn and contents),
  shrines and boons, shop rooms and offers, monster AI (`Monster.take_turn(..., rng=)`, the
  wander step), crits, dodges, damage rounding, summons and gold. The same seed and the same
  actions replay the same game, and a game never touches the global `random` module
  (`tests/test_rng.py`). Module functions keep an `rng: Rng = random` default for direct callers
  and tests; nothing in `GameState`'s flow may rely on it -- pass `self.rng`. In a test, seed a
  game with `GameState(..., seed=n)` (or `state.rng.seed(n)` mid-test) and force a roll with
  `mock.patch.object(state.rng, 'random', return_value=...)`; patching `random.random` no
  longer reaches the game. `main.py` builds each run with `seed=None`.
- **Settings** (`game/settings.py`): `KEY=VALUE` lines, `#` comments, optional quotes; a real
  environment variable always wins. Search order: `$PYROGUE_CONFIG` → `.env` next to the exe (or
  next to `main.py` from source) → `.env` in the CWD. `main.py` reads `MAP_WIDTH` (50),
  `MAP_HEIGHT` (20), `FOV_RADIUS` (6), `TURN_DELAY_MS` (110; `0` resolves a round instantly),
  `TILES` (1; `0` draws characters instead of tiles), `COMBAT_ZOOM` (1; `0` turns the zoom
  off) and `SOUND` (1; `0` turns audio off). `env_int` falls back to the default on an unparseable or out-of-range value (`main.py` bounds the map size, `FOV_RADIUS` and `TURN_DELAY_MS`). The checked-in `.env` sets
  `MAP_WIDTH=40` and `MAP_HEIGHT=20`, so a source run's base map is 40x20; the `.env` is not
  bundled, so the exe uses 50x20.

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
  1920x1080 (`ui.FIRST_WINDOW`) when that fits inside 85% of the desktop, else the largest 16:9
  size inside 85% of it (so never the whole desktop; a 1080p desktop gets 1632x918)
  (`ui.first_window_size`); on Windows the process is DPI-aware.
- **Map cells go through `_map_cell_rect`** (and, in tile mode, `layout.map_cell_to_pixel`, never
  `cell_to_pixel`): only those honour the combat zoom's projection.
- **The bundled font is the default** (`assets/fonts/JetBrainsMono-Regular.ttf`), so the game and
  the tests get the same metrics on every OS; system fonts (`ui.FONT_NAMES`) are only a fallback.
  Layout code must hold for fonts with tall line heights like this one.
- **Crash log:** an uncaught exception lands in `user_data_dir()/crash.log` (`main.py`'s
  `__main__`, see **Layout**). The windowed exe has no console, so look there first.
- **Packaging:** read `packaging/NOTES.md` before touching the spec or adding a data file.

## Tests

Families of near-identical cases (per rarity, weapon kind, depth, window size, mode, class) are
one test looping with `self.subTest(...)`, so a failure still names its case; add a case to the
loop rather than a new method.

| File | Covers |
|---|---|
| `test_slimes.py` | slimes: size bands, HP and power, splitting (placement, no gold from split-offs, next-round entry), the large slime's every-other-turn move, arrow resistance, the green squares |
| `test_terrain.py` | `dungeon.add_terrain`: reachability, room centres and doors kept clear, features never touching, 3 or 6 by room width, nothing spawning on terrain, seeded replay |
| `test_enemy_scaling.py` | goblin and goblin-archer pack ramps, the ranged monsters' 30% miss |
| `test_archer_changes.py` | archer melee and point-blank halving (first hit only), arrows that hit are used up |
| `test_new_weapons.py` | the fencing sword's riposte by rarity; the hand crossbow's hop-shot (deferred monster half, cooldown, arrows, death after the hop, through `main.run`) |
| `test_game.py` | `game/`: dungeon gen, doors, movement, adjacency, FOV, monster AI, spawn rules, collisions, chase give-up, turn phases, classes and the archer, gear, scaling, chests, potion belt, chest choice, combat events, crits and damage reduction, weapon types, boss enrage, goblin archers, shrines and boons |
| `test_gold.py` | `game/gold.py`: piles, drops, gold chests, pickup; `BalanceTest` (a full clear of floors 1-4 pays 120 ± 12 gold, chests 15-40% of it) |
| `test_shop.py` | `game/shop.py`: shop floors and room, offers, prices and rarity caps, half boons, buying |
| `test_shop_screen.py` | the shop's text, keys and overlay (glyph and tile mode, every window size) |
| `test_sound.py`, `test_sound_events.py` | `render/sound.py`'s `SoundBoard` (lazy mixer, silent on any failure, `SOUND=0`); which game events record which slot |
| `test_level.py` | `game/level.py`: every purpose row of the blocking table, spawn-time occupancy over 200 seeded floors (no chest/shrine on a creature or the stairs, no stacked creatures), monsters and knockback onto chests, summons, a dodged monster arrow at a door, draw order |
| `test_rng.py` | seeded reproducibility: two `GameState(seed=s)` games fed the same scripted moves, fights and descents stay identical; different seeds give different first maps; a game never touches the global `random` |
| `test_damage.py` | `game/damage.py`: reduction, mitigation, probabilistic rounding |
| `test_properties.py` | Hypothesis properties: solid border, reachability, doors, FOV, loot and scaling monotonicity, settings parsing, camera projection, log wrapping, random playthroughs |
| `test_loop.py` | `main.resolve_player_strikes` / `resolve_monster_phase` with a recording renderer: frame-by-frame order of a round, the rapier's beat |
| `test_camera.py` | `render/camera.py`: view geometry, the director's gate and hold, the spear's zoom, smooth zoom, hit shake |
| `test_pygame_render.py` | the renderer: events, fullscreen, game over, a scripted run through `main.run`, tile mode, hit shake and health bars, choice screens (chests and boons), the boss arena |
| `test_boards.py` | the cached boards: every displayed value, mutated, reaches the next frame exactly as an uncached paint draws it; resize, F11 and a refit rebuild them; a beat only blits; `_play` is paced by a `Clock` (glyph and tile mode) |
| `test_ui.py` | `Layout` (glyph, tile, stacked), the stats and log boards and their sections, message log, `Canvas` bold, menu hit-tests, paint smoke tests, game-over banner, noticeboard |
| `test_tileset.py` | fallbacks on missing/corrupt assets, a tile for every drawable char, chest colours, `ASSETS.md` provenance, the 10 MB budget |
| `test_menu.py` | `Menu` and the banner |
| `test_parity.py` | the window's key table reaches every `Action`; F11 never shadows a game key |
| `test_actions.py` | every `Action` is in `state.HANDLED_ACTIONS` or an explicit renderer-only set |
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
- `end_turn()` runs both halves back to back for tests. After a `handle_action` it resolves only
  what that action queued, as `main.run` would (nothing after a no-turn action); with no action
  since the last call it queues a fresh monster half. `cancel_monster_phase()` drops the queue
  when the level is thrown away (descending).
- **Hop-shot** (hand crossbow): a hop straight away from an adjacent monster sets
  `hop_half_owed` and ends no turn yet. If the next action is a shot, it fires and the monsters'
  half is queued once after both; otherwise `_deferred_hop` first resolves the hop's monster half
  all at once (nothing more after a fatal one), then the action runs as normal.
- **Split-offs** (slimes) join the *next* round's queue (`TurnController.deferred`,
  `defer_to_next_round`), not the one in progress.
- Turn-taking actions bump `state.turn` (the zoom's hold counts it). Waiting (`.`), bumping a wall
  and drinking take a turn; a refused move, a choice key, or `e` off the stairs do not.

### Classes and stats

- `CLASS_STATS`: **warrior** 60 HP / 4 power, **archer** 45 / 3. The warrior starts with a
  common plain weapon (Rusty Dagger, +1); the archer with a common longbow and common leather
  (`STARTING_WEAPON`, `STARTING_ARMOR`). Unknown classes fall back to warrior.
- Keys: WASD move, arrows `SHOOT_*`. For a warrior the arrows also move (bump to attack); for an
  archer they fire an arrow (`shoot_arrow`) that flies straight until a wall, a closed door (a
  monster standing in the doorway is still hit) or the first monster.
  Space or `.` wait, `e` descend (on `>`), `h` drink, `q` the class ability (the archer's hop, the
  warrior's parry), `1`/`2`/`3` choose and Space (on a choice screen) skips. In the shop
  `1`-`5` buy and Space leaves. `r` restarts and `q` quits only on the death screen.

### Damage, crits and gear (`game/damage.py`, `game/fight.py`, `game/item.py`)

- Damage: `raw = attacker.power`; `mitigate` removes `defense / (defense + DEFENSE_K)` of it
  (`DEFENSE_K = 10` gives 50% at 10 defence), never below 1.0; `round_damage` rounds
  probabilistically (2.3 → 3 with 30% chance), so averages hold.
- Crits: player only, `crit_chance` = `BASE_CRIT_CHANCE` (0.10) + the weapon's `crit_bonus` +
  boons, capped at 1.0. A crit multiplies raw damage by `CRIT_MULTIPLIER` (1.5) before defence
  and logs "Critical hit!".
- Rarity: common/uncommon/rare/epic. Rarity weights go linearly from 60/25/12/3 at depth 1 to
  10/25/35/30 at `MAX_SCALING_DEPTH` (20), then hold. Rolled when a chest is *opened*, at the
  current depth.
- Warrior weapons (weapon slot): damage bonus `GEAR_BONUS` 1/2/4/7 plus a per-type offset, and an
  effect: war axe (−1, +3/6/9/15 max HP), rapier (−2, strikes twice), great sword (+1, cleaves one more
  monster orthogonally adjacent to the player), sword & shield (0, +3/6/9/12 defence), dagger
  (−1, +5/10/15/20% crit), spear (0, reach 2: hits a visible monster two tiles away through a
  clear, door-free tile), fencing sword (−1, a parry's riposte hits for `riposte_mult` ×2.0/2.15/2.3/2.5
  of raw power instead of the crit's ×1.5; `fight.riposte`). The plain weapon line is only the warrior's starting weapon; it never
  drops. The archer's seven bows (`ARCHER_WEAPONS`) work the same way; each class only finds its own
  weapon types (`CLASS_WEAPONS`).
- Archer weapons: the hand crossbow (−1, `hop_shot`, no reload): a hop straight away from an
  orthogonally adjacent monster does not end the turn (see **Rounds**), and the existing post-hop
  crit applies to its combo shot. Arrows that hit a monster are used up (no pile); ammo comes back
  only from misses (which drop where they stop) and the restock (1 arrow per `RESTOCK_TURNS`, 3).
- Archer melee: a bump does ×0.5 (`ARCHER_MELEE_FACTOR`, `turns.py`); a shot whose first target is
  orthogonally adjacent ("point blank") counts as melee and the aim arrow, and each volley arrow
  at it, does ×0.5 (`POINT_BLANK_FACTOR`, `archery.py`) on that first hit only. Shots at two or
  more tiles, and warriors, are unchanged (a hop-then-shoot is full damage). Against an adjacent
  slime it stacks with `RANGED_RESIST`: 35%.
- Armor: heavy armor's `ARMOR_DEFENSE` 3/6/12/21 is a percentage damage reduction via
  `mitigate`; it stacks with the shield. Leather (`ARMOR_SPLIT['leather']`) trades defence for
  dodge, and is the only armor an archer finds. `gear_power` never drops below `MIN_POWER` (1). Equipping always replaces the old
  piece; power and defence are recomputed from scratch.

### Chests and the potion belt

- `spawn_chests`: never in `rooms[0]`, the shop room, on the stairs or on a monster (the floor's
  spawners share one `occupied` set: player, terrain walls and shopkeeper → monsters → chests and stairs → boss
  stairs → shrine; see `game/level.py`). Each other room gets a
  potion chest (pink) with 25%; at most one gear chest (cyan) per floor with 40%, **except floor
  1, which always gets one**, and at most one gold chest (yellow) with 70% (see **Gold and
  shops**).
- A gear chest offers `GEAR_CHEST_DROPS` (3) choices: each is junk ("Rusty scrap", 15%) or gear
  (armor is 20% of all drops, the rest weapons split evenly over the class's seven types). The choice is
  shown as three cards; `1`/`2`/`3` or a left click on a card takes one (`choose`), and Space or a click on the skip line
  takes nothing (`skip_choice`). Nothing else can happen until
  one of those, and neither takes a turn.
- A killed boss drops a boss chest: three rare/epic (75/25) gear choices, no junk.
- A potion chest's potion is drunk at once if hurt, else put on the **belt**: `BELT_SLOTS` (3)
  plus boons. `h` drinks slot 1 (heals `POTION_HEAL` 20/35/55/88 × boons); an empty belt logs "No
  potions", and full HP "You are already at full health."; neither drinks or takes a turn. Stepping onto a potion chest at full HP with a full belt is refused
  ("Your potion belt is full."): no move, no turn.

### Monsters and spawning (`game/monster.py`, `game/spawn.py`)

- Base stats (hp, power): goblin 11/2, orc 27/4, goblin archer 7/1 (slimes below). Every 3 floors is a tier:
  ×1.2 HP (compounding) and +1 power per tier. Regular orcs on floors 1-8 have 20% less HP
  (`EARLY_ORC_HP_MULT`). E.g. depth 1 orc 22/4; depth 4-6 goblin 13/3, orc 26/5; depth 7-9
  goblin 16/4, orc 31/6 (39/6 on floor 9).
- AI: 4-way only. A monster sees the player when its tile is in the player's FOV; it chases
  within 8 tiles (`CHASE_RANGE`), gives up after 3 blind turns (`GIVE_UP_AFTER`), else wanders.
  Monsters never share a tile (`level.MONSTER_MOVE`), but may walk onto chests, shrines and piles;
  the renderer always paints creatures over those. A chaser heads for the nearest tile in line with the player (same
  row or column, clear line) by a breadth-first search of up to 12 moves (`LANE_SEARCH_LIMIT`),
  and falls back to a greedy step when none is that close.
- Slimes (`slime_small`/`slime_medium`/`slime_large`, char `j`, named in the log via
  `MONSTER_NAMES`): small on floors 1-5, medium on 6-10, large from 11 (`SLIME_BANDS`). HP is
  the orc's at that depth × 0.5/0.8/1.2 (`SLIME_KINDS`), power 2/3/4 plus the tier bonus,
  defence 0. A dead medium or large slime splits into `SLIME_SPLIT_COUNT` (2) of the next size
  down (`fight.split_slime`): on free tiles next to it first, then within `SPLIT_RADIUS` (2)
  (`fight.split_tiles`, the `SUMMON` blocking rule, never through a wall; fewer if boxed in).
  Split-offs have `drops_gold` False and `split_from` set, and join the next round
  (`TurnController.deferred`, `defer_to_next_round`). A large slime steps only every
  `MOVE_EVERY` (2nd) turn it doesn't attack, but attacks every turn it is adjacent. Player
  arrows do `RANGED_RESIST` (0.7) of their damage to a slime.
- Goblin archer (`goblin_archer`): while it sees the player, it backs away within 2 tiles (`KEEP_AWAY`) and otherwise
  shoots along a clear row or column up to 5 tiles (`SHOOT_RANGE`); never through a wall, a door
  or another creature. Each of its shots misses `MISS_CHANCE` (30%, per ranged kind in
  `monster.py`), rolled in `fight.monster_shot` before the dodge; a miss takes the dodged-arrow
  path (no damage, no `Hit`, the arrow flies on, the attack sound still plays).
- `SPAWN_RULES`: **one enemy kind per room** (every room but `rooms[0]`), picked with equal
  weight from the rules for the depth: goblin packs, a lone orc through floor 8 and a spread pair
  after, goblin archers from floor 4, slimes by band (one per room). Packs ramp with depth (`spawn.py`): goblins 1/2/3/4/5 on floors 1-4/5-7/8-10/11-12/13+
  (`GOBLIN_PACK_STEPS`), archers 1/2/3 on 4-7/8-11/12+ (`ARCHER_PACK_STEPS`).
- Boss: every 8th floor (`is_boss_level`), one random non-start room is the **boss arena**
  (`state.boss_arena`): the boss (`O`, 2× HP and 1.5× power of that depth's orc: 78/9 on floor 8)
  at its centre, with `BOSS_ESCORTS` beside it (one orc on floor 8) and no regular pack. At half
  HP it enrages once and summons min(tier, 2) goblins within 3 tiles, on bare floor it could walk
  to without leaving that square (never through a wall into the next room).

### Shrines (`game/shrine.py`)

- On 40% of non-boss floors, at most one, in a room other than `rooms[0]` and the boss room, never
  on the stairs, a chest, a monster or the player.
- Walking onto one offers 3 different boons on the same choice screen as a chest (titled "Choose
  a boon"); the shrine is then gone. Boons last the run (`Player.boons`) and are derived where
  used, so none applies twice; max HP is added once and HP clamped to at least 1. Boons: Blood
  pact (+3 power, −15 max HP), Iron skin (+2 defence, −25% potion heal), Quick hands (+1 belt
  slot, −25% potion heal), Keen eye (+10% crit, −10 max HP), Stone heart (+15 max HP, −1 power).

### Gold and shops (`game/gold.py`, `game/shop.py`)

- **Gold** (`Player.gold`, shown on the stats board): a killed monster drops a `$` pile on its
  tile (`drop_amount`: `GOLD_PER_HP` × max HP + `GOLD_PER_POWER` × power, ×3 for a boss, ±20%),
  merged into a pile already there; walking (or an archer's hop) onto a pile picks it up
  (`pick_up_gold`). At most one **gold chest** (yellow `=`) per floor, with 70%, pays
  `3.2 × depth` ±20% plus 5-10 (`GOLD_CHEST_BONUS`) when opened. The constants are tuned so a full
  clear of floors 1-4 pays about 120 gold, chests about 36-37% of it (`GOLD_PER_HP` 0.234, `GOLD_PER_POWER` 0.609, retuned after terrain
  and slimes; `tests/test_gold.py`'s
  `BalanceTest`, through `gold.full_clear_gold_split`).
- **Shops** on every 4th floor (`is_shop_level`): a shopkeeper (`P`, not a `Monster`: it never
  moves or fights, and arrows fly past) stands at the centre of a room that isn't `rooms[0]`, the
  stairs room or the boss room; nothing else spawns there. Walking into it opens the shop
  (`state.shop_open`), as often as the player likes on that floor.
- Five offers, in key order: two different weapons for the player's class (rarity rolled like a
  chest's, capped at uncommon before floor 8 and rare from it: never epic), two half boons and a
  full heal. Prices: weapon `depth × 30 × {common 0.5, uncommon 1, rare 4/3}` (60/120 on floor 4, rare 320 on floor 8),
  half boon `depth × 13.3` (53 on floor 4), heal 5 per missing HP. `buy` takes no turn; a bought
  weapon equips at once (replacing the old one), bought weapons and boons are marked sold, and
  the heal stays. A refused buy (sold, too poor, full HP) logs why and costs nothing.
- **Half boons** (`shrine.half_boon`, `HALF_BOONS`): a shrine boon's benefit halved (at least 1)
  with no cost, keyed `<key>_half`, named "Lesser …", with `½` after the short name. Shrines never
  offer them; a player may hold both versions.

### Sound hooks (`game/sound.py`, `render/sound.py`)

- `GameState.sound(slot)` appends a `SoundEvent(serial, slot)` to `state.events` (the one event
  stream, see **Events**) at each hook (footsteps, door, melee by weapon weight, bow/crossbow
  shots (the fencing sword is light melee, the hand crossbow uses the crossbow slot), monster attacks by kind (slimes fall back to the goblin attack sound), chest open, descend, enemy alert, gold pickup: the 12 names in
  `sound.SLOTS`).
- The renderer's `SoundBoard` keeps its own cursor (`last_serial`) into the stream, skips every
  other record, and plays each new `SoundEvent` once (a redraw never replays it; the renderer
  resets the board when it sees a new `GameState`) from
  `assets/sounds/<slot>.ogg`, else `.wav`. It never raises: no file, a corrupt file or no audio
  device is silence, and the mixer is opened only when a slot first finds a file. **No sound
  files ship yet.** `SOUND=0` disables it; the renderer's default board is silent.

### Dungeon and FOV

- `generate_level` → `generate_dungeon`: a random target of 4-6 rooms, non-overlapping, 4-8
  tiles a side plus `room_growth(depth)` on every side (8-12 on floors 1-8, 10-14 on 9-16, 12-16
  from 17), on a map `map_size` enlarges to match; clamped to the map, up to `max_attempts` (300); a single interior room if nothing fits, so
  `rooms[0]`/`rooms[-1]` are always safe. Corridors come after every room is carved
  (`connect_rooms`, each room to the one before) via `route_corridor`'s cheapest 4-way path
  (`DOORWAY_COST` 20, `ROCK_COST` 3, `FLOOR_COST` 1), with the spec's L corridor as a fallback.
  It is Dijkstra over a flat per-call cost grid, tiles numbered `x * h + y` so heap ties break
  exactly as `(dist, (x, y))` did: the same path, byte for byte, as the old dict-and-closure
  version (`RouteCorridorTests` keeps that as its oracle). `generate_level` takes ~4 / 6 / 7 ms
  at depth 1 / 9 / 17 with terrain (was 14 / 33 / 40 before the faster router).
  `place_doors` puts a `+` in every one-tile gap in a room's wall. `add_terrain` then draws
  wall features inside every room but `rooms[0]`: 3 (`TERRAIN_FEATURES[0]`) in a room up to
  `TERRAIN_NARROW_ROOM` (12) wide, 6 in a wider one (floor 9 on), each an L of 3 or a line of 2-3.
  A feature must lie on floor in the room, keep the 3x3 round every room's centre clear (start,
  stairs, boss and shopkeeper stand there), not touch a door, not touch another feature, and
  leave everything reachable from `rooms[0]` reachable (a local connectivity check); it gets
  `TERRAIN_TRIES` (6) tries, then is skipped. `level.terrain_tiles` leads the spawners'
  `occupied` set, and `room_tiles`/`free_tiles` take an optional `game_map` that leaves terrain
  out. Stairs at `rooms[-1].center()`
  (on a boss floor, in the boss room); `e` on them builds the next floor.
- `game/fov.py`: recursive shadowcasting; `seen` keeps remembered cells, drawn dimmed.
  `update_visibility` touches only lit cells: it returns the set it lit, and given last call's set
  clears just those (`GameState.update_fov` keeps it, tied to the current `visible` grid).
  The FOV depends only on the map and the player's tile (monsters don't block sight), so it is
  computed once per player half (`end_player_phase`, a quickdraw's free shot) and on a new floor
  -- never after a monster's turn; `step_monster_phase`'s in-view test and monsters'
  `sees_player` read that one FOV. A monster round went 2.0 → 0.13 ms (depth 11, 7 monsters).

### The window (`render/`)

- **Title and class select:** the banner with Start/Quit, then Warrior/Archer with a description.
  Up/down or w/s, enter/space to pick, `q` quits (on the class select: back to the title —
  `choose_class` returns None); the mouse hovers and clicks in menus only.
  Gameplay is keyboard-only, except a click on a choice card.
- **Layout** (`ui.Layout`): glyph mode, or tile mode when the `Tileset` loads, with square tiles
  from `TILE_SIZES` (64…16) scaled nearest-neighbour. Two boards: the **stats board** right of the
  map with the **log board** under the map, or (`stacked`, when that gives bigger cells) the stats
  board under the map and the log board under it. Stats: `panel_x`/`panel_y`, `panel_rect()`,
  text at `text_x`/`text_y`; log: `log_x`/`log_y`/`log_cols`, `log_rect()`, `log_page_rect()`,
  text at `log_text_x`/`log_text_y`.
- **Stats board** (`ui.paint_panel` on `noticeboard.py`'s wooden board and parchment page,
  `PANEL_COLS` = 34, fixed rows `HEADER_ROW`…`CONTROLS_TOP`): class and depth, HP with a bar (red
  at or below a third), ATK/DEF (+ dodge), items (+ arrows), gold; GEAR (weapon and armor, two
  rows each, in rarity ink); BELT, a row of boxes (the first outlined while the belt holds a
  potion); BOONS once one is held (short names, wrapped over up to two rows); CONTROLS, a
  key/action table for the class.
- **Log board** (`ui.paint_log`): a 'LOG' header and a word-wrapped log of 4-12 lines
  (`Layout.log_lines()`, as many as the window's rows allow).
- **Cached boards** (`render/boards.py`, 2026-10-18): both boards are drawn from their content
  (`ui.panel_content`, `ui.log_content`) onto offscreen Surfaces, rebuilt only when that content
  or the layout changes (`_relayout` also calls `invalidate()`); every frame, beat and pan only
  blits them. A new value on a board must go into `PanelContent`, or it will go stale -- paint it
  *from* the content. On the main thread on purpose (pygame fonts aren't thread-safe). Frame time
  (dummy driver) went 6.7 → 1.1 ms at 1080p and 11-14 → 4.5-5.6 ms at 4K, 34-38 → 0
  `font.render` calls a frame; `_play` waits with `Clock.tick(BEAT_FPS)` (60) instead of
  paint + 16 ms, so beats run at ~60 fps instead of 31-47.
- **Shop overlay** (`screens.paint_shop`): a box centred on the map, as big as its text needs and
  clamped to the window (in glyph mode it covers part of the boards): the title, the player's
  gold, five offer rows (rarity ink for a weapon, the boon colour, plain ink for the heal, whether
  or not the player can afford it; an unaffordable offer's price, `shop_text.price_text`, in
  `INK_DANGER`; a sold offer all grey) and the hint.
- **Tiles:** `assets/tiles.json` maps each char to a stack of sheet cells (`layers`, optional
  `backdrop` or `tint` in the entity's colour). Bosses get their own entry (helmet, bigger
  weapon); in glyph mode a boss is brighter, bold and underlined. A char with no tile falls back
  to its glyph. Slimes have no tile yet: they are drawn as green squares centred in the cell,
  sized by kind (`SLIME_CELL_FRACTION` 0.45/0.65/0.85), in tile and glyph mode alike
  (`tests/test_tileset.py` exempts `j` from the every-char-has-a-tile check).
  `_before_hits` hides split-offs until the blow that kills their parent has landed. The fencing
  sword uses the `'skinny'` swing, like the rapier.
- **Boss arena:** the arena's 3x3 centre is drawn as darker stone, and blood decals from
  `assets/blood/` are scattered over its floor, laid out the same every frame.
- **Combat zoom** (`render/camera.py`, warriors only, `COMBAT_ZOOM=0` disables): with a monster in
  melee range (`zoom_opponents()`, which for a spear also includes its reach targets, so it zooms
  a step earlier), the map pans in so the player and that monster sit centred with 2 squares round
  them. It never zooms in on a monster the player just stepped away from (the fleeing gate); once
  in, it holds while any visible monster is within 3 tiles and for 2 more turns after, and zooms
  out at once when no monster is in view or the player dies.
- **Events** (`game/combat.py`, `game/sound.py`): one ordered stream, `GameState.events`, of
  typed records with one serial counter: `Hit(serial, attacker, defender, damage, killed, x, y,
  crit)` for a melee blow, `Shot(serial, arrows)` for a shot (player or goblin archer; each
  `Arrow(path, hits)`, the aim arrow first; `shot.path`/`shot.hits` are the aim arrow's),
  `Parry(serial, monster, player, x, y, riposte)` for a blow an armed parry nullified, and
  `SoundEvent(serial, slot)`. A `Shot` *owns* its Hits (they are not in the stream themselves;
  `GameState.recording_shot()` takes the Shot's serial and place before any arrow flies), and a
  `Parry` names its riposte's `Hit`, which follows it. The list is always in serial order, is
  cleared when the player acts, and the serial counts for the whole run (a new `GameState` starts
  over). Readers: `events_since(cursor)` (what is new), `events_of(kind)`, `hits()` (every Hit,
  Shots' included, in serial order). `attack()` returns its Hit (None if dodged). Each consumer
  keeps its own cursor and never replays an event: the camera `Director` (`_cursor`; a new
  Director per run, `_forget_run`) and the `SoundBoard` (`last_serial`).
- **Beats:** `Director.plan` walks the new events in stream order: a `Shot` becomes its `Flight`s
  and `Impact`s, a `Parry` the monster's `Swing`, a `Guard` and (after the riposte's beats) a
  `ParryText`, a melee `Hit` a `Swing` and an `Impact`; then a `Pan`. An impact flashes the struck cell red, raises a `-N` damage number (a crit's is double
  size, yellow, black-outlined), shakes the map (180 ms; a crit 280 ms and harder) and jolts the
  struck sprite and its health bar inside its cell. Impacts always play out; a queued key cuts a
  pan or step short.
- **Enemy health bars** above each visible monster: green above half, amber down to a quarter, red
  below; a boss's spans the cell. They are the last thing painted on the map (over sprites, the
  player's ability bar, swings, arrows, impacts and the shield; before the hit shake, so they jolt
  with it). With the player straight above a monster, its bar sits inside the monster's cell, just
  under the player's ability bar.
- **Walk tilt:** an entity that just stepped leans 15°, alternating left and right, for 110 ms.
- **Gold piles** are drawn under whatever stands on them (in glyph mode, not at all while
  something does), and a kill's pile appears only once the blow that drops it has landed.
- **Game over:** a "YOU DIED" banner across the top of the map; `r` restarts, `q` quits.

### Browser build (planned, not started)

A browser version for itch.io is planned as a **separate build**. No browser code exists yet.
Don't change the main build, its loop or its dependencies for it.
