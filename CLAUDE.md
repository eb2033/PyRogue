# PythonRogue

A terminal roguelike built from `roguelike_reference.md` — an offline reference that doubles as the
project spec. Read that file before adding a feature: it defines the intended approach for dungeon
generation, FOV, entities, and the stretch-goal roadmap.

## Running

```bash
.venv/bin/python main.py                    # terminal (curses, the default)
.venv/bin/python main.py --renderer pygame  # OS window (needs pygame-ce, installed in .venv)
```

`tests/test_game.py`, `tests/test_menu.py` and `tests/test_loop.py` cover `game/` logic, the pure
menu/banner helpers, and the main loop's monster-phase driving
(`.venv/bin/python -m unittest discover -s tests -v`). There is no build step, and no automated test
touches the curses renderer itself (it needs a real terminal) — verify rendering/input changes by
running the game.

## Layout

- `main.py` — entry point only. Picks a renderer (`--renderer`/`RENDERER` env, default `curses`),
  shows the title screen and class-select screen, builds a `GameState`, and runs a renderer-agnostic
  loop (`draw` / `get_action` / `handle_action`, then `resolve_monster_phase`). That last step is
  what makes the monster half of a round watchable — see **Rounds** below.
- `game/` — all game logic, standard library only, speaks `(x, y)` throughout. `state.py` owns turn
  resolution (`GameState`, including the archer's ranged attack); `dungeon.py`, `rect.py`, `tiles.py`
  are dungeon generation; `entity.py`, `monster.py`, `item.py` are the entity hierarchy; `fov.py` is
  field of view; `save.py` is JSON save/load.
- `render/` — the renderer boundary. `base.py` defines `Action` (semantic keys, including `SHOOT_*`
  for the arrow keys) and the `Renderer` interface (`draw`/`get_action`/`show_title_screen`/
  `choose_class`/`pause`/`close`); `curses_render.py` is the terminal renderer (stdlib only, the only file
  that speaks `(y, x)`); `menu.py` is the pure (curses-free) menu-selection state; `banner.py` builds
  ASCII-art banner text from a small block font; `pygame_render.py` is the windowed renderer
  (pygame-ce, glyph grid, panel/menu parity with curses — the `desktop_build_plan.md` §3.1 spike, see
  **Windowed renderer** below) with its key table in `input_map.py`; `tcod_render.py` is a not-yet-implemented graphical
  scaffold (see `going_graphical.md`) — it has no menu/class methods since it never gets past
  `__init__` without the `tcod` package installed.
- `tests/test_game.py`, `tests/test_menu.py`, `tests/test_loop.py` — headless `unittest` suites:
  `game/` logic (dungeon gen, FOV, combat, adjacency, turn phases, classes, items, save/load); the
  pure menu/banner helpers; and `main.resolve_monster_phase` driven with a recording stand-in
  renderer, which asserts the frame-by-frame ordering of a round. Run with
  `.venv/bin/python -m unittest discover -s tests -v`. There is intentionally no test for the
  curses renderer's drawing/getch itself — it needs a real terminal (or a pty — see `agent_log.md`'s
  note on the `TERM=xterm` arrow-key SS3-vs-CSI trap if you script one).
- `roguelike_reference.md` — the spec/reference. Section numbers below refer to it.
- `going_graphical.md` — research notes (2026-08-26) on an eventual graphical build. Its §0
  recommendation of `tcod` is **superseded** by `desktop_build_plan.md`; the rest (packaging,
  antivirus, assets, web builds) still stands.
- `desktop_build_plan.md` — the plan (2026-10-06) for taking the game out of the terminal and
  shipping it as a `.exe`: `pygame-ce` renderer, PyInstaller `--onedir` built on a Windows CI
  runner, split into seven workstreams with exclusive file ownership so agents can run in parallel.
  **Read this before starting any graphical or packaging work.** Nothing in it is implemented yet —
  the repo is still terminal-only.
- `.env` — read via `python-dotenv`. `main.py` looks for `MAP_WIDTH`, `MAP_HEIGHT`, `FOV_RADIUS`,
  `RENDERER` and `TURN_DELAY_MS`, each with a code default (50 / 20 / 6 / `curses` / 110); the
  checked-in `.env` only sets `MAP_WIDTH=40` and `MAP_HEIGHT=20`, so an actual run is a **40x20**
  map. `env_int` falls back to the default on an unparseable value rather than crashing.
  `TURN_DELAY_MS=0` collapses the monster phase back to instant, which is handy for testing.

## Constraints

- **Standard library only** for everything under `game/` and for `render/curses_render.py`
  (`curses` + `random`). The reference exists so the terminal build runs with zero internet and zero
  installs; don't introduce dependencies there.
- `main.py` is the one terminal-path file with a dependency: `python-dotenv` (`from dotenv import
  load_dotenv`), installed in `.venv`. It is imported unconditionally, so a bare `python main.py`
  outside the venv fails at import — run it as `.venv/bin/python main.py`.
- `render/pygame_render.py` and `render/input_map.py` may import `pygame-ce` (plan §0.1); nothing
  on the terminal path imports them, and `tests/test_pygame_render.py` skips cleanly without pygame.
- `render/tcod_render.py` is the other deliberate exception — it's allowed to depend on `tcod` (and
  what it pulls in) precisely because it's isolated behind the `Renderer` interface and never
  imported by the terminal path. It's still an unimplemented scaffold, and
  `desktop_build_plan.md` §0 schedules it for deletion in favour of a `pygame-ce` renderer: the two
  things tcod was chosen for (FOV, pathfinding) are already written by hand in `game/`, and no
  commercially released game appears to use `python-tcod`, while pygame and Ren'Py have a real
  shipping record.
- **The dependency rule is per-directory, and that is what makes a graphical build possible**
  (`desktop_build_plan.md` §0.1, not yet implemented): `game/**` and `render/curses_render.py` stay
  stdlib-only forever; a future `render/pygame_render.py` / `ui.py` / `tileset.py` may import
  `pygame-ce`; and `main.py` is meant to *lose* its `python-dotenv` dependency (replaced by a
  stdlib settings reader), which would make the whole terminal path dependency-free.
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
  (unopened; `!`/`/`/`[` potion/weapon/armor only exist transiently once one is opened).
- **Walkability** is a char comparison (`!= '#'`), not a tile-type system.
- **Colors** go through `curses.init_pair(n, fg, bg)` and are stored on entities as an int
  (`Entity.color`), rendered with `curses.color_pair(...)`. Pair 1 is yellow-on-black (the player);
  pairs 4-7 are the gear-rarity ladder (`game/item.py`'s `RARITY_COLOR` picks the number).
- Map dimensions are `DEFAULT_WIDTH`/`DEFAULT_HEIGHT` constants in `main.py`, overridden by the
  `MAP_WIDTH`/`MAP_HEIGHT` env vars via `env_int`, and passed explicitly into `GameState(width,
  height, ...)`. `GameState` keeps them as `self.width`/`self.height`; nothing under `game/` reads
  the environment or a module global for size.

## Current state

All of spec §3–§7 and all six §8 stretch goals are implemented:
- `Rect` with `center()` / `intersects()` (§3)
- Room-and-corridor dungeon generation (§3): `generate_dungeon` rolls a random target room count in
  `[min_rooms, max_rooms]` (default 4-6) and keeps placing non-overlapping rooms (`min_size=4,
  max_size=8`, the spec's own range) until it hits that target or exhausts `max_attempts`; on
  either the 50x20 code default or the 40x20 the checked-in `.env` produces, this reliably lands at
  4-6 rooms (verified over 400 generations each). Room size is clamped to whatever actually
  fits in `(w, h)`, and generation falls back to a single interior room if nothing fits — so
  `rooms[0]`/`rooms[-1]` are always safe to use even on tiny maps. Every corridor gets a door
  (`+`) dropped at each point it crosses a room boundary (`_place_doors` in `game/dungeon.py`);
  `tiles.is_transparent` treats `+` as opaque like a wall (`!=` `+` and `!=` `#`), so a room's
  interior stays hidden from its corridor/neighbors until the player is in the doorway or past it
  — `is_walkable` still allows walking through it, only line-of-sight is affected.
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
  file). `S` saves to `savegame.json`, `L` loads. Round-trips map, fog, player, class, and live
  entities.

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
and a heal amount for potions (`POTION_HEAL`: 8/14/22/35). Gear auto-equips on pickup, replacing
whatever was in that slot (no inventory/drop management — picking up a second weapon just swaps).
Rarity also picks the item's on-map color (pairs 4-7 in `render/curses_render.py`, green/blue/
magenta/white for uncommon/rare/epic/common) — the render side panel has a dedicated `-- gear --`
section showing the equipped weapon/armor's name, bonus, and rarity in that color.

**Chests, not bare items, spawn on the floor** (`game/item.py`'s `Chest`, `=` on the map, cyan):
`spawn_chests(rooms)` rolls 50/50 per room — skipping `rooms[0]`, the player's start — and places
a chest instead of a raw `Item`. A chest holds nothing until opened
(`GameState.open_chest`, triggered by walking onto it, same as items used to auto-apply) — kind and
rarity are rolled fresh at that moment via `roll_kind`/`roll_rarity`, against the *current depth*,
not the depth it was spawned at. `rarity_weights_for_depth` interpolates linearly from the depth-1
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
expected. Not yet verified on Windows itself — that's the P2 CI build.

Test coverage: `tests/test_game.py` (68 tests) + `tests/test_menu.py` (7) + `tests/test_loop.py`
(7) + `tests/test_pygame_render.py` (11, headless via `SDL_VIDEODRIVER=dummy`) = 93 unit tests, plus ad hoc fuzz/PTY smoke testing during development — see `agent_log.md` for
what was run and why.

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
