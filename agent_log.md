# Agent Log — PythonRogue stretch-goal implementation

Session date: 2026-08-26. Goal: implement every baseline feature and every stretch goal from
`roguelike_reference.md` §8 / `CLAUDE.md`'s "Not yet implemented" list, testing each piece as it
was built, without pushing anything to a remote.

## 0. Starting state (surprise)

`CLAUDE.md` describes a single-file `main.py` skeleton, but the actual repo had already been
refactored into a `game/` (logic) + `render/` (curses/tcod boundary) package split, with a
`going_graphical.md` research doc explaining why (a future graphical `tcod` renderer). `CLAUDE.md`
itself was stale relative to that refactor. I kept the existing architecture (it's a strictly better
shape for adding the stretch goals — e.g. save/load only has to serialize `game/` objects, not
curses state) and updated `CLAUDE.md`'s Layout/Constraints/Current-state sections to match reality
at the end of the session, rather than reverting to the single-file description.

Not a git repository, so `EnterWorktree` was unavailable and I worked directly in the checkout, as
the background-job instructions say to do when that happens. Nothing has been pushed anywhere.

## 1. Recursive shadowcasting FOV (stretch #6)

**File:** `game/fov.py`. Replaced the old radius-only `update_visibility` (which lit tiles in a
circle regardless of walls) with the classic 8-octant recursive shadowcasting algorithm
(Björn Bergström's, as popularized by RogueBasin), operating on `game.tiles.is_transparent` so walls
now actually block sight. `update_visibility` keeps its old signature/behavior contract (clears
`visible`, folds newly-visible tiles into the persistent `seen` fog-of-war grid) so nothing else had
to change to consume it.

**Test:** `tests/test_game.py::FovShadowcastingTests` — three cases: an open room lights up to the
configured radius; a wall segment is itself lit but the tile directly behind it is dark while a tile
merely *beside* the wall stays lit (confirms it's real LOS, not just "any wall in the room blocks
everything"); `update_visibility` correctly persists `seen` after the player moves away. All three
passed on the first implementation.

## 2. Monsters (stretch #3)

**File:** `game/monster.py` (new). `Monster(Entity)` with `hp`/`power`/`alive`/`kind`, two types
(goblin, orc — table in `MONSTER_TYPES`). `take_turn(player, game_map)` matches the spec signature:
chases in a straight line within 8 tiles, wanders randomly otherwise, and — the one deliberate
deviation from the spec snippet — refuses to step onto the player's tile, returning `'attack'`
instead so `GameState` resolves damage in one place (see §4) rather than duplicating HP math in two
files. `spawn_monsters(rooms)` rolls 0-2 monsters per room, skipping the player's starting room.

**Test:** `MonsterTests` — chase-toward-player, adjacent-returns-'attack'-without-moving, and
spawn placement never lands in `rooms[0]`. Also exercised transitively by ~650 fuzz-simulation runs
(§7).

## 3. Items (stretch #4)

**File:** `game/item.py` (new). `Item(Entity)` — currently one kind, healing potions (`!`, cyan).
`apply(player, log)` runs the moment `GameState.try_move_player` detects the player stepped onto an
item's tile; the potion heals up to `max_hp` and records itself in `player.inventory` (a list, shown
as a count in the side panel — see §5). `spawn_items(rooms)` rolls a 50% chance per non-starting
room.

**Test:** `GameStateIntegrationTests::test_item_pickup_heals_and_fills_inventory` — hp increases,
inventory grows, the item entity is removed from `state.entities`.

## 4. Stairs, descend, combat, game state wiring (stretch #1, spec §6 combat)

**File:** `game/dungeon.py` — added `place_stairs(game_map, rooms)`, called once at world-gen and
again on every `next_level()`.

**File:** `game/state.py` — the bulk of the wiring:
- `try_move_player(dx, dy)`: walk into a wall → no-op; walk into a live monster → `attack()` instead
  of moving (bump-attack, no move onto the monster's tile); walk onto an item → apply it and remove
  it; otherwise move.
- `attack(attacker, defender)`: shared by both player-initiated and monster-initiated attacks.
  Subtracts `attacker.power`, logs a message, and on death sets `alive = False` (removal happens in
  `end_turn`, after all monsters have acted, so a monster can't act again post-mortem in the same
  turn).
- `end_turn()`: runs every non-player living entity's `take_turn`; a `'attack'` result triggers
  `attack(entity, player)`; then prunes dead entities and checks for player death → `game_over`.
- `try_descend()` / `next_level()`: only descends if the player's tile is literally `STAIRS_DOWN`;
  otherwise logs "There are no stairs here." and consumes no turn. Descending regenerates the
  dungeon, replaces monsters/items, resets both fog grids, and increments `depth`.
- `game_over` blocks movement/wait/descend actions but not `quit`/`save`/`load` — you can still save
  a dead run's log, or quit, once you've died.

**Test:** `GameStateIntegrationTests` — combat kill, monster-kills-player → `game_over` + "You
died.", descend-with-stairs regenerates the level and repositions the player, descend-without-stairs
is a no-op, game_over blocks movement but not quit. All passed.

Also fixed a **pre-existing bug**, unrelated to any single stretch goal but that the new automated
testing surfaced: `generate_dungeon`'s `min_size=8, max_size=12` room bounds hand
`random.randint(1, w - rw - 1)` a negative/inverted range and crash outright on any map smaller than
roughly 15×12 (e.g. `MAP_WIDTH=10`). Clamped room size to what actually fits in `(w, h)` and added a
single-room fallback so `rooms` is never empty. Confirmed via a 150-run fuzz sweep across three small
map sizes (10×8, 12×6, 20×10) — all failed before the fix, all passed after.

## 5. HP/inventory side panel (stretch #2)

**File:** `render/curses_render.py`. `_draw_panel` now shows depth, HP (turns the "low HP" color
when at or below a third of max), inventory count, the control legend, and the last 4 entries of
`state.messages` as a scrolling log. Added a `_draw_game_over` overlay ("YOU DIED — press q to
quit") drawn on top of the map when `state.game_over` is set. Monsters render in red (color pair 2,
already reserved for this in the original file), items in cyan (pair 3, likewise pre-reserved) —
both pairs existed in `COLOR_PAIRS` but were unused before this session.

**Test:** exercised via the PTY smoke test (§7) rather than a unit test — it's terminal-drawing code,
not game logic, and the project's own convention (`tests/test_game.py`'s docstring, and CLAUDE.md)
is that the renderer needs a real terminal and isn't unit-testable the same way.

## 6. Save/load (stretch #5)

**File:** `game/save.py` (new). Chose **JSON over pickle** deliberately: pickle deserializes
arbitrary objects and executes code on load, which is a real risk for a save file that (eventually)
might be shared/downloaded; JSON has no such hazard and the state here is simple enough to serialize
by hand. `state_to_dict`/`apply_dict` round-trip the map (as row-strings), both fog grids, the
player's stats/inventory, every other living entity (tagged `monster`/`item` with enough fields to
reconstruct a `Monster`/`Item`), the message log, depth, and `game_over`. Bound to `S`/`L` in
`render/curses_render.py` and `'save'`/`'load'` actions in `render/base.py`.

**Test:** `SaveLoadTests::test_round_trip_preserves_state` — mutate HP/inventory/log, save to a
temp file, load into a *fresh* `GameState`, assert everything matches, including the exact map.
`test_load_missing_file_returns_none` covers the "no save yet" path. Also exercised end-to-end
through the real curses renderer in the PTY smoke test (§7) — saved, moved, loaded, confirmed the
"Game loaded." message renders in the log panel.

## 7. Testing strategy overall

This box has no TTY, so curses can't be driven interactively by hand here. Three layers of testing,
each catching different classes of bug:

1. **`tests/test_game.py`** (22 tests, `unittest`, stdlib only — no pytest installed in `.venv`).
   Deterministic, seeded, one file per concern (dungeon gen, movement, FOV, monsters, integration,
   save/load). Run: `.venv/bin/python -m unittest discover -s tests -v`. **Result: 22/22 pass.**

2. **Fuzz simulation** (ad hoc script, not checked in — it's a development tool, not a permanent
   regression test, since it doesn't assert anything `test_game.py` doesn't already assert more
   precisely; kept in the job's scratch dir). Ran 500 seeded `GameState(50, 20)` sessions of 300
   random actions each (all of move/wait/descend/save/load), plus 150 runs across three small map
   sizes (10×8, 12×6, 20×10), asserting every entity stays in-bounds and nothing raises. This is
   what caught the `generate_dungeon` small-map crash in §4. **Result: 0/650 failures** after the
   fix (150/150 failed before it).

3. **PTY smoke test** (ad hoc script, same reasoning as above — not checked in). Actually launches
   `main.py` under a real pseudo-terminal via Python's `pty` module, feeds it a sequence of
   keystrokes (movement in all four directions, wait, save, more movement, load, an out-of-place
   descend attempt, quit), and asserts: exit code 0, no `Traceback` in the captured output, and the
   process actually terminates (a `select()`-based reader with a hard deadline, so a hung game can't
   hang the test). This is the only layer that touches `render/curses_render.py` and the real
   `curses` calls (`initscr`, color pairs, `addch`/`addstr` bounds handling) rather than `GameState`
   directly. **Result: pass** — captured output shows the `@` moving, "Game saved."/"Game loaded."
   and "There are no stairs here." rendering correctly in the message log panel.

`savegame.json` written by the PTY smoke runs was deleted after each run so it doesn't linger as
stray state in the working tree.

## 7a. Follow-up: title screen, class select, Warrior/Archer (2026-08-26, same day)

Requested afterward, on top of the above: an intro menu with an ASCII "PyRogue" banner and
Start/Quit, then a class-selection screen (Warrior — unchanged bump-to-melee; Archer — WASD moves,
arrow keys fire an arrow in that direction).

**Design choice — menu logic split from curses drawing.** `render/menu.py`'s `Menu` class (index +
wraparound `move(delta)`) holds zero curses state, so it's unit-testable without a terminal, same
reasoning as the existing `game/`-stays-stdlib split. `render/curses_render.py`'s `_run_menu()` is
the only thing that touches `curses.getch()`/`addstr` for menus; it draws a `Menu` and translates
keys into `.move()`/confirm/quit. `render/banner.py`'s `render_banner(word)` builds the "PyRogue"
ASCII art from a small 5x5 block font *generated from data*, not hand-aligned line by line — a
hand-typed multi-line banner is exactly the kind of thing that silently goes crooked one character
at a time, so the font lives in a dict and layout is computed.

**Design choice — arrow keys are `SHOOT_*`, not `MOVE_*`, at the renderer boundary.** Previously
arrow keys and WASD both produced `move_*` actions. Now `curses_render.py` maps arrows to new
`Action.SHOOT_N/S/E/W` values unconditionally — the renderer still doesn't know what class the
player is, consistent with the "GameState knows nothing about curses, renderer knows nothing about
classes" split described at the top of `state.py`. `GameState.handle_action` decides what a shoot
action *means*: for a warrior it's simply forwarded to the same `try_move_player` movement/bump-
attack path as before (so warriors keep working exactly like they did pre-menu, arrows-move-you
included); for an archer it calls the new `shoot_arrow(dx, dy)`, which walks the line in that
direction until it hits a wall (message, turn consumed, no damage) or the first monster in its path
(routed through the existing shared `attack()` so ranged and melee combat log/kill/death logic is
one code path, not two).

**Class stats:** warrior 25 HP / 4 power, archer 18 HP / 3 power (`CLASS_STATS` in `game/state.py`)
— archer trades durability for the ranged option. `player.char_class` defaults to `'warrior'` and
falls back to it for any unrecognized string, so `GameState(...)` is still safe to call without a
class for anything that doesn't go through the menu (all the existing tests, the fuzz harness).
Added to save/load (`game/save.py`) with `.get('char_class', 'warrior')` on load, so old save files
without the field still load.

**`main.py` reordering:** the renderer now has to exist *before* `GameState` does (it needs curses
running to draw the menus), so `main()` now builds the renderer, calls `show_title_screen()` (return
False → quit without ever constructing a `GameState`) then `choose_class()`, and only then builds
`GameState(..., char_class=...)` and enters the normal run loop.

**Tests, three layers again:**

1. `tests/test_menu.py` (new, 7 tests) — `Menu` wraparound in both directions, starts at index 0,
   rejects an empty option list; `render_banner` produces `FONT_HEIGHT` equal-width rows, is
   case-insensitive, and raises `KeyError` on a letter not in the font (rather than silently
   producing garbage).
2. `tests/test_game.py` — added `ClassAndArcherTests` (8 tests): default class is warrior, an
   unknown class string falls back to warrior, warrior/archer stats actually differ, a warrior's
   `shoot_*` action just moves the player, an archer's arrow kills a monster three tiles away
   without moving the player, an arrow with nothing in its path logs a wall-hit and doesn't raise,
   an archer's `shoot_*` action never moves the player, and `char_class` survives a save/load
   round-trip. **37/37 tests pass** (22 from before this feature + 8 new class tests + 7 new menu
   tests).
3. **Fuzz simulation**, extended to run both classes through all move/shoot/wait/descend/save/load
   actions, 300 seeded sessions × 300 steps each on the default map plus 180 runs across three small
   map sizes. **0/780 failures.**
4. **PTY smoke test**, extended with three scenarios driven through the *real* curses UI: (a)
   navigate the title menu down to Quit and confirm — asserts the string "Choose your class" never
   appears in the output, i.e. quitting from the title never constructs a class-select screen or a
   `GameState`; (b) Start → Archer → move with WASD → fire an arrow in all four directions → quit —
   asserts "loose an arrow" (the shot-fired log line) actually appears in the captured terminal
   output; (c) Start → Warrior (default) → press all four arrow keys → quit, confirming they don't
   crash a warrior's turn loop. **All 3 pass.**

**A test-harness bug worth recording, not a game bug:** the first pass of the PTY scenarios sent
raw `\x1b[A`-style (CSI) arrow-key escape sequences and all three scenarios "passed" — but only
because passing meant "no traceback," and CSI sequences are literally the wrong bytes for
`TERM=xterm`. `infocmp xterm | grep kcu` shows this terminfo maps arrows to SS3 sequences (`\EOA`,
`\EOB`, `\EOC`, `\EOD`), so curses never recognized the arrow presses at all — they were dropped as
unbound characters, meaning the archer-shoot scenario had silently tested nothing. Fixed the harness
to send `\x1bOA`/etc., which is what made the "loose an arrow" assertion actually meaningful. Kept
here because it's a trap anyone else scripting curses input against a pty will hit the same way.

## 7b. Follow-up: gear system, rarity tiers, difficulty scaling, bosses (2026-08-26, same day)

Requested afterward: diversify items with a gear system, a dedicated right-panel gear section,
monsters getting stronger every 3 floors (1.2x hp, +1 attack), and a boss every 8th floor (2x hp,
1.5x damage of a regular enemy) with a guaranteed rare drop. Items now split Common → Uncommon →
Rare → Epic.

**Gear design (`game/item.py`).** Two new item kinds alongside the existing potion: `weapon`
(bonus power) and `armor` (bonus defense — a new stat). All three kinds are now rarity-tiered
(`RARITIES = ['common','uncommon','rare','epic']`, spawn-weighted 60/25/12/3). Rarity drives both a
flat stat table (`GEAR_BONUS`: 1/2/4/7) and a name (`GEAR_NAMES`) and — reusing the existing
`Entity.color`-is-a-curses-pair-number convention the codebase already used for players/monsters —
a color: pairs 4-7 in `render/curses_render.py`'s `COLOR_PAIRS` are green/blue/magenta/white for
uncommon/rare/epic/common. Potions got pulled into the same tiering rather than staying a single
flat heal (`POTION_HEAL`: 8/14/22/35 by rarity) — the ask was to diversify *items*, and a single
never-upgrading potion would have been the odd one out next to tiered gear.

**Equip model.** Gear auto-equips on pickup (same "walk over it, it applies immediately" pattern as
potions — no separate use/equip step, consistent with how items already worked here), replacing
whatever was in that slot; the old piece is discarded rather than dropped back to the floor (no
inventory-management ask was made, so kept minimal). `player.base_power` (from `CLASS_STATS`,
unaffected by gear) and `player.power` (`base_power + weapon.bonus`, recomputed on every equip
rather than stacked) are tracked separately so re-equipping a weapon can't accidentally compound.
`player.defense` works the same way for armor. `GameState.attack()` now computes
`damage = max(1, attacker.power - defender.defense)` — the `max(1, ...)` floor means heavy armor
can't make a player literally unhittable, just tankier.

**Gear panel.** `render/curses_render.py`'s `_draw_panel` gained a `-- gear --` section (rows
6-8, between HP/inventory and the controls legend) showing equipped weapon/armor with their bonus
and rarity, colored by rarity — the "section on the right dedicated to gear details" from the ask.
Also added an `ATK n  DEF n` line so the effect of gear is visible as numbers, not just names.

**Difficulty scaling (`game/monster.py`).** `tier_for_depth(depth) = (depth - 1) // 3` buckets every
3 floors into a tier; `scale_stats(base_hp, base_power, depth)` applies `1.2 ** tier` to hp
(compounding — tier 2 is 1.2x *tier 1's* hp, not 1.2x base twice-over as a flat 2.4x, since `1.2**2`
already *is* the compounded value) and `+1 * tier` flat to power, matching "1.2x hp and +1 attack"
read as *per tier* rather than a one-time bump. `spawn_monsters(rooms, depth)` now threads depth
through so every regular monster on a level is scaled for that level's tier.

**Boss (`game/monster.py`, `game/state.py`).** `is_boss_level(depth) = depth % 8 == 0`.
`spawn_boss(rooms, depth)` scales off the orc template (the tougher of the two regular kinds) at
that depth's tier via the same `scale_stats`, then applies 2x hp / 1.5x power on top and uppercases
its map glyph (`O` instead of `o`) — `GameState._spawn_level_monsters()` appends exactly one boss
whenever `is_boss_level` is true, on top of the normal regular-monster spawn (a boss floor isn't
empty of regular monsters, just additionally has a boss). `render/curses_render.py` draws bosses
bold+underlined so they're visually distinct from a regular monster of the same letter. On boss
death, `GameState.attack()` checks `defender.is_boss` and calls `game.item.boss_drop()`, which
forces rarity to rare (75%) or epic (25%) — "guaranteed rare drop" read as a rarity floor rather
than literally always exactly 'rare', so an epic is a pleasant surprise rather than something the
system has to avoid.

**Tests, three layers again:**

1. `tests/test_game.py` — added `GearTests` (6) and `DifficultyScalingTests` (7), plus a save/load
   round-trip test for equipped gear. Covers: invalid rarity rejected, potion heal scales with
   rarity, equipping updates power without stacking on a swap, armor's damage-reduction floor of 1,
   tier bucketing at the 3-floor boundaries, `scale_stats` compounding correctly, a spawned
   monster's actual stats matching the formula, `is_boss_level` on/off the 8-floor cadence, a boss's
   stats matching 2x/1.5x off the scaled reference monster, exactly one boss appearing on (and only
   on) a boss level, and a killed boss dropping exactly one rare-or-epic item. **51/51 tests pass**
   (37 before this feature + 14 new).
2. **Fuzz simulation**, extended to 300 sessions of 1500 steps each (both classes, on the default
   map) asserting `power >= 1`, `defense >= 0`, and every entity's `max_hp >= 1` throughout, plus a
   separate 200-seed sweep that force-jumps to depths 8/16/24/32 via `next_level()` and asserts
   exactly one boss exists on each, then kills it and asserts the drop. **0/500 failures.**
3. **PTY smoke test**: the existing menu-driven scenarios still pass unmodified (title→quit,
   Start→Archer→shoot→quit, Start→Warrior→arrows→quit). Added a new scenario that starts a game and
   confirms `-- gear --`, `Wpn:`, `Arm:`, `ATK`, `DEF`, and the empty-slot `(none)` text all render
   through the real curses panel with no crash — this is what catches a layout mistake (the panel
   grew by 4 rows to fit the new gear section; a terminal-size miscalculation would show up here,
   not in the unit tests, since `_put_str`'s bounds-check would just silently clip text rather than
   raise). **Pass.** (Didn't script an actual pickup through the PTY — gear spawn location is random
   and scripting "explore until an item happens to be found" blind, without seeing the screen, isn't
   reliable; the equip *logic* itself is fully covered by `GearTests`, and this smoke test confirms
   the rendering plumbing and color-pair registration for the new pairs don't crash.)

One incidental fix along the way: an old pre-menu-system PTY smoke script (from the previous
session, testing move/save/load directly) still "passes" post-menu — it just never gets past the
title screen anymore, since its `wsad` keystrokes now navigate the Start/Quit menu instead of
moving a player. It exits cleanly via its trailing `q`, so it doesn't report a false failure, but it
no longer tests what it originally tested. Superseded by `pty_menu_smoke.py`, which explicitly
presses Enter to get through the menus first; left as-is otherwise since it's a scratch file, not
part of the repo.

## 7c. Follow-up: chests instead of bare items, depth-scaled loot, descend key change
(2026-08-26, same day)

Requested: floor loot should spawn as an openable chest that rolls the item table when opened
rather than appearing as an already-identified item, loot quality should improve the deeper the run
goes, and the descend key should change. **This request also explicitly flagged that another agent
was concurrently working on level design (dungeon generation) in the same repo, with no git to
merge against — coordination notes are their own subsection below (§7c.1) since that constraint
shaped how this was done, not just what.**

**Chests (`game/item.py`).** New `Chest(Entity)`, glyph `=`, reusing the previously-orphaned cyan
color pair 3 (freed up when the rarity system took over pairs 4-7 for actual items). A chest carries
no kind/rarity at spawn time — `spawn_chests(rooms)` replaces the old `spawn_items(rooms)` call
sites in `GameState.__init__`/`next_level` one-for-one. Opening one (`GameState.open_chest`, called
from `try_move_player` the moment the player's tile matches a chest's, same trigger point the old
bare-item pickup used) calls `Chest.open(depth)`, which rolls a kind (`roll_kind` — same 50/25/25
potion/weapon/armor split as before) and a rarity (`roll_rarity(depth)`) *at that moment*, then
returns a normal `Item` that gets `.apply()`'d immediately, identical to how items already worked.
Net effect: what's on the floor is a mystery until you walk up to it, and — because the roll happens
at open time, not spawn time — a chest you noticed early but only got back to several floors later
rolls against the *later, better* table, not the one from when it first appeared.

**Depth-scaled rarity (`game/item.py`).** Deliberately *not* reusing `monster.py`'s
`tier_for_depth`/3-floor-bucket concept — the ask ("the further you go, the better it should be")
reads as a continuous trend, not a stepped one like the monster difficulty ask was, and tying loot
quality to the same tier buckets as monster difficulty would couple two systems that don't need to
know about each other. Instead, `rarity_weights_for_depth(depth)` linearly interpolates from the
depth-1 weights (`RARITY_WEIGHTS_SHALLOW`, same 60/25/12/3 as before) toward a deliberately
loot-heavy table (`RARITY_WEIGHTS_DEEP`: 10/25/35/30) as depth approaches `MAX_SCALING_DEPTH` (20),
then holds flat past that — uncapped linear growth would eventually make "epic" the *only* realistic
roll on a long run, which stops feeling like a rarity system at all. A boss's chest
(`spawn_boss_chest`, `guaranteed_min_rarity='rare'`) skips this table entirely and always rolls
rare/epic (75/25) — "guaranteed rare drop" read the same way as last time: a rarity floor, not a
literal always-exactly-'rare' pin, so an epic boss drop is a nice surprise rather than a case the
system has to actively prevent.

**Descend key (`render/curses_render.py`).** Changed from `>` to `e`. Reasoning, since none was
specified in the request: `>` needs shift on most keyboard layouts, and reads confusingly sitting
right next to the *stairs tile glyph* on screen, which is also `>` — a keybinding and a map symbol
happening to be the same character invites the assumption they're the same concept, when they're
actually independent (`game/tiles.py`'s `STAIRS_DOWN = '>'` is unrelated to and untouched by this
change; only the `KEY_ACTIONS` entry in `curses_render.py` moved). `e` ("enter" the stairs) sits
right next to the wasd movement block and needs no shift. The old binding was removed outright
rather than kept as a second alias — the request said "change," and keeping a dead alias around
would just be a trap for whoever reads the key table next.

**Tests, three layers again:**

1. `tests/test_game.py` — added `ChestTests` (6): `spawn_chests` places chests (not items) and
   skips the starting room; a regular chest's `.open()` always returns a valid kind/rarity across a
   range of depths; a boss chest's `.open()` ignores depth and always returns rare/epic; the rarity
   weight table actually shifts toward better loot with depth and holds flat past
   `MAX_SCALING_DEPTH`; a large-sample statistical check that `roll_rarity` at max depth produces
   more epics than at depth 1; and that `open_chest` removes the chest and grows inventory. Also
   updated three **pre-existing** tests that broke because they simulated the old world — placing a
   bare `Item` directly on the map and expecting `try_move_player` to auto-pick it up, which is now
   chest-only: `test_item_pickup_heals_and_fills_inventory` → rewritten against a `Chest`; two
   `GearTests` (`test_potion_heal_scales_with_rarity`, `test_equip_weapon_updates_power`) → switched
   to calling `Item.apply()` directly, since what they actually test is the apply/equip logic, not
   the world pickup trigger. The boss-drop test and its save/load counterpart were also updated to
   expect a `Chest` with `guaranteed_min_rarity='rare'` rather than a bare rare/epic `Item`.
   **58/58 tests pass** (51 before this feature + 6 chest tests + 1 new chest save/load test).
2. **Fuzz simulation**: 300 sessions (both classes, 1200 steps) with the descend key change baked in
   (actions are still dispatched as semantic strings like `'descend'`, not raw keys, so this
   exercises `GameState` regardless of which physical key the renderer binds to it) asserting every
   `Chest`'s `guaranteed_min_rarity` is `None` or `'rare'` throughout; plus 100 seeds force-jumping
   through boss floors 8/16/24, confirming each boss drops exactly one `guaranteed_min_rarity='rare'`
   chest (had to fix the fuzz script itself here — an early version grabbed the *first* `Chest` found
   rather than specifically the boss's, occasionally picking up a coincidental regular chest already
   on that level and failing; not a game bug). **0/400 failures** after the fuzz-script fix.
3. **PTY smoke test**, real curses UI: confirmed `>` is now inert (spamming it near the stairs
   neither descends nor errors, and movement keeps working afterward) and a longer mixed
   move/wait/`e` session runs clean with the concurrent dungeon-generation changes (§7c.1) also live.
   Re-ran the existing menu/gear-panel PTY scenarios too, unmodified, to confirm nothing regressed.
   **All pass.**

### 7c.1. Working alongside a concurrent level-design agent, with no git

This repo has no `.git` (confirmed at the very start of this session — see §0), so there was no
merge/branch mechanism available; "don't overwrite each other" had to mean discipline about which
files got touched and how, not tooling. Concretely:

- **Stayed out of `game/dungeon.py`, `game/rect.py`, and (mostly) `game/tiles.py` entirely** — those
  are the level-design agent's files. Confirmed this was the right call: partway through this work,
  `game/dungeon.py` was observed mid-edit (a docstring describing door-based room generation with a
  function body that hadn't caught up to it yet — a snapshot of their in-progress save, not a bug),
  and later had grown further (adding `_room_at`, `_corridor_path`, `_place_doors`, a
  `min_rooms`/`max_rooms` target-based generation loop) by the time this work finished. `game/
  tiles.py` also changed on their end (doors block sight now). None of this needed touching for
  chests/rarity/keybinding, so it wasn't touched.
- **Checked file mtimes before editing anything shared** (`game/state.py`, `game/save.py`,
  `render/curses_render.py`, `CLAUDE.md`) rather than assuming the last-known content was still
  current, and re-read fresh before each edit. Used targeted `Edit` (old_string/new_string) calls
  instead of full-file rewrites on every shared file, specifically so a concurrent change landing in
  the same file wouldn't get silently clobbered by an unrelated full overwrite.
- **One transient false failure from this**: `tests/test_game.py::DungeonGenerationTests::
  test_rooms_are_carved_floor` failed once (`room center == '+' not '.'`) while `dungeon.py` was
  mid-save on the other agent's end, then passed cleanly on the next run once their edit landed.
  Didn't touch that test or `dungeon.py` in response — it isn't this session's code, and the failure
  was a race against a save-in-progress, not a real regression.
- **`CLAUDE.md` was being edited by both agents.** The other agent had already added an accurate
  paragraph about their door/room-count generation work by the time this session got back to
  documentation. Left that paragraph completely alone and made small, surgical `Edit` calls
  elsewhere in the file — fixing the now-stale "`>`" reference in the stairs bullet, updating the
  `Item(Entity)` bullet to reflect chests, adding a chest/depth-scaling paragraph, and bumping the
  test count — rather than reading the file once and writing back a full replacement, which risks
  discarding whatever the other agent adds between the read and the write.

## 8. What's still explicitly out of scope

- `render/tcod_render.py` remains an unimplemented scaffold. It's not one of the six `CLAUDE.md`
  stretch goals — it's a separate, self-initiated research thread (`going_graphical.md`) about an
  eventual graphical build, and pulling in `tcod`/`numpy` would violate the stdlib-only constraint
  the terminal build is designed to preserve. Left untouched.
- No new gameplay content beyond what the spec's stretch goals ask for (e.g. no scrolls, no
  equipment, no multiple potion types) — the brief was to complete the listed goals, not expand
  scope beyond them.

## 9. Files touched

New (initial pass): `game/monster.py`, `game/item.py`, `game/save.py`, `tests/test_game.py`,
`agent_log.md`.
New (menu/class follow-up): `render/menu.py`, `render/banner.py`, `tests/test_menu.py`.
Modified (menu/class + gear/scaling/boss follow-ups, then chest/depth-loot/descend-key
follow-up): `game/fov.py`, `game/dungeon.py` (only in the earlier pass — untouched in the
chest/key follow-up, see §7c.1), `game/state.py`, `game/save.py`, `game/item.py`,
`game/monster.py`, `render/base.py`, `render/curses_render.py`, `main.py`, `tests/test_game.py`,
`CLAUDE.md` (Layout/Constraints/Current-state sections, to match the package-split reality and
list the now-completed stretch
goals, the menu/class system, the gear/scaling/boss system, and the chest/depth-loot system plus
the descend-key change).

As requested, this was left for interactive play-testing by the user rather than "final" sign-off
here — the automated layers above only prove it doesn't crash and the logic is correct, not that it
*feels* right to play.

## 10. Planning session: out of the terminal, into a `.exe` (2026-10-06)

No game code changed in this session. The brief was to produce a plan for running the game outside a
terminal as a Windows `.exe`, keeping it Python, informed by what indie games that use Python
actually ship with. Output: `desktop_build_plan.md`, plus context updates to `CLAUDE.md` and a
supersede header on `going_graphical.md`.

**What the research changed.** `going_graphical.md` §0 recommended `tcod`. This plan reverses that in
favour of `pygame-ce`, and the reversal is the main substantive finding:

- The two things tcod was picked for — built-in FOV and pathfinding — have since been *written by
  hand*, in stdlib, in `game/fov.py` (recursive shadowcasting) and `game/monster.py` (the naive 4-way
  chase, which `CLAUDE.md` documents as deliberate, not a gap). tcod's library value had already been
  spent by the time the graphical build came up again.
- Searching for commercially released games built on `python-tcod` turned up tutorials
  (rogueliketutorials.com, RogueBasin) and hobby repos, and **no shipped titles**. pygame has a
  modest but real one (Frets on Fire; Galcon; Dangerous High School Girls in Trouble!, sold on Steam;
  7 Grand Steps), and Ren'Py — Python on `pygame_sdl2`, with a built-in "Build Distribution" step —
  carries thousands of commercial releases including Doki Doki Literature Club!. Panda3D (Toontown
  Online, Pirates of the Caribbean Online, Wizard101) and EVE Online/Civ IV/Battlefield 2 show the
  same architecture this repo already has: Python owns the logic, a C library owns the window.
- tcod also pulls `numpy`; pygame-ce is one native wheel and no second native dependency to freeze.

**What was verified on this machine rather than assumed** (all of it is §1 of the plan):

- `pygame-ce 2.5.8` has a cp314 wheel, and in a throwaway venv on this project's **Python 3.14.7** it
  initialised, created a display, rendered text and flipped **headless** under
  `SDL_VIDEODRIVER=dummy`. That is the keystone fact — the graphical renderer is testable in CI,
  which the curses renderer never was (`§7` and `§7a` above are the history of working around that).
- `pyinstaller 6.22.3` declares `Requires-Python <3.16,>=3.8`. `tcod 21.2.1` is `cp310-abi3` but
  needs `numpy`+`cffi`. `nuitka 4.2.2` is source-only (C toolchain required). `pygbag 0.9.3`'s
  in-browser interpreter is 3.12/3.13, so a web build would need a pinned venv.
- `game/state.py:24`'s `SAVE_PATH = 'savegame.json'` is CWD-relative, which breaks in an installed
  app; the plan gives that to a workstream with a `user_data_dir()` + one-time migration.
- `.gitignore`'s `*.md` means **every doc in this repo is untracked**, including the new plan, and
  stale `__pycache__/*.pyc` files *are* tracked. Both flagged for the user rather than changed
  unilaterally.

**Shape of the plan.** Phases P0 stubs → P1 window parity (same glyphs, same keys, no art) → P2
shippable exe ← the actual ask → P3 tiles/HUD → P4 optional (Nuitka, pygbag, audio, Steam). Seven
workstreams (renderer core, runtime platform/paths, art pipeline, in-window UI, packaging, CI/release,
QA+docs), each with **exclusive file ownership** and a day-0 "land your stub first" rule — a direct
response to §7c.1 above, where two agents editing `CLAUDE.md` and `game/dungeon.py` concurrently cost
a transient false test failure and some careful merge work. This time the doc files have a single
owner and the interface signatures are fixed before the implementations start.

**The one real technical risk, called out as a gate.** `CursesRenderer.get_action()` is a blocking
`getch()`. Blocking in an OS window without draining the event queue is what makes Windows grey the
title bar and mark the app "Not Responding". The plan's answer is to implement the block *as* a
`pygame.event.wait()` loop (handling quit/resize/expose, ignoring unmapped keys, redrawing the cached
last frame while idle), which leaves `main.run()`, `resolve_monster_phase()` and all 82 existing tests
untouched. If that spike fails, the "don't touch the game loop" premise is wrong and the plan gets
revisited before any UI work starts — so it is P1's gate, not a detail.

**Deliberately not decided here.** Engine confirmation (the tcod reversal is the user's call to
ratify), art direction (Kenney CC0 colour vs Urizen 1-bit), the `*.md` gitignore question, and
whether v0.1.0 gets an itch.io page or just a zip. All four are listed as open questions in the plan
rather than resolved by assumption.
