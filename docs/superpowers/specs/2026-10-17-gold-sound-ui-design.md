# Gold, sound hooks and a split panel — design

2026-10-17. Three independent pieces of work for the windowed (pygame) build of PyRogue, built in
this order: **UI → sound hooks → gold**. Each lands as its own reviewable chunk with its own tests.
Base: `main` at `0866938` (release 0.2.1).

Decisions marked **(user)** were made by the user in conversation and are not open for the builder
to change. Decisions marked **(call)** are the designer's sensible defaults: the builder may revise
one if the code makes it awkward, but should say so.

## Why

- **UI:** the side panel reads as one undifferentiated column. HP, stats, gear, the potion belt,
  controls and the message log run together with no separation, so the player can't find things
  at a glance mid-fight, and the belt in particular is easy to miss.
- **Sound:** the user will source sounds and redo the art next. The game needs named places to
  drop a sound in *now*, so that later work is just adding files.
- **Gold:** a currency with somewhere to spend it, adding a reason to fight and clear floors and a
  periodic shopping beat. It is deliberately *not* a build-control system.

## Constraints (all three)

- `CLAUDE.md` rules hold: `game/` stays standard-library only and speaks `(x, y)`; pygame is only
  imported by `render/pygame_render.py`, `input_map.py`, `ui.py`, `screens.py`, `tileset.py`.
  New pygame-using modules under `render/` are fine if nothing on the stdlib path imports them.
- Every bundled file is read via `game.paths.resource_path()` and listed in `assets/ASSETS.md`
  with source and licence (`tests/test_tileset.py` enforces it; 10 MB budget, ~0.5 MB used).
- The full suite, ruff, pyright (0 errors) and vulture must stay clean. Panel parity tests
  (`tests/test_parity.py`, the panel tests in `tests/test_ui.py`) and the panel row constants in
  `render/ui.py` will change with the UI work; update them, don't delete their intent.
- There is no save/load (removed in `c3525b4`, before 0.2.1; `CLAUDE.md`'s notes on it are
  stale). A run is played in one sitting, so none of this work needs persisting.
- Releases go through PRs into `main`. Each piece updates `CHANGELOG.md` and the `CLAUDE.md`
  "Current state" notes.

---

## 1. UI: split the panel

### Decided (user)

- **Two boards, layout B.** The existing noticeboard stays on the right of the map and holds
  stats, gear, belt and controls. The **message log moves to its own board**, a wide strip
  *under the map*, spanning the map's width.
- The stats board is divided into **sections, each with its own header**: class & depth with HP
  (bar) and ATK/DEF; gear; belt; controls.
- **Controls are a table**: a key column and an action column, one binding per row.
- **The potion belt is a single row of slot boxes**: each shows its heal in its rarity colour,
  empty slots show "—", and the slot `h` drinks next is **outlined**. No second row.
- A mockup of the approved layout is in the brainstorm session (`panel-split-v2.html`); it is a
  guide to arrangement, not pixel-exact.

### Confirmed defaults

- Archer controls table: `wasd` move, `arrows` shoot; warrior: `wasd/arrows` move. Both then list
  `space` wait, `e` descend, `h` drink, `q` ability (whatever the current bindings are; the table is
  generated from the same source as today's lines).
- Shrine boons stay on the stats board as their own section, shown only once one is held.
- The log strip shows as many lines as its height allows, word-wrapped to its width (existing
  `log_rows` behaviour, wider).
- Stacked (tall/narrow) layouts: stats board under the map, then the log strip at the very bottom.
- Board art (wood frame, parchment page) is kept; the log strip gets its own frame.
- Glyph mode (`TILES=0`) gets the same split.
- Gold (section 3) will add a `Gold n` entry to the stats section; leave room for it.

### Left to the builder

How the log strip's height is chosen against the map's (the existing `Layout` already picks the
largest tile/font that fits; the log strip is one more region in that fit), exact section
spacing, the outline style, and how the panel row constants are restructured.

---

## 2. Sound hooks

### Decided (user)

- **Hook points only. No audio files ship in this work.**
- Named sound slots, one per event:

  | Slot | When |
  |---|---|
  | `attack_heavy` | player melee attack with war axe, great sword, sword & shield, spear, or the starting sword |
  | `attack_light` | player melee attack with dagger or rapier |
  | `attack_bow` | player shot with longbow, volley bow, sling, hunter's bow, quickdraw; **also the goblin archer's shot** |
  | `attack_crossbow` | player shot with the heavy crossbow |
  | `monster_attack_goblin` | a goblin attacks |
  | `monster_attack_orc` | an orc attacks |
  | `door` | the player steps into a doorway |
  | `descend` | the player descends the stairs |
  | `chest_open` | a chest is opened |
  | `enemy_alert` | a monster first notices the player |
  | `gold_pickup` | the player picks up gold (section 3) |
  | `footsteps` | the player moves one tile |

- Everything else (shop sounds, music, volume settings, more monster/world sounds) comes later.

### Confirmed defaults

- Doors in this game never open; they are walkable, opaque `+` tiles. `door` fires when the
  player **steps onto** a door tile.
- `enemy_alert` fires when a monster switches from not-chasing to chasing the player; once per
  monster until it loses track of the player, and at most once per turn however many notice.
- Attack slots fire on the swing/shot, hit or miss.
- A boss uses its kind's slot. `footsteps` is the player only, every tile moved (not on a bump
  attack, not when the move is blocked).

### Architecture (call)

- `game/` stays sound-free: it **records events** (a list of slot names on `GameState`, cleared
  when the player acts, the same pattern as `state.combat_events` / `game.combat.Hit`).
- The pygame renderer consumes them: a new `render/sound.py` maps slot → file, loads
  `assets/sounds/<slot>.(ogg|wav)` through `resource_path()` if present, and plays it. **A missing
  file is silent**, and so is a machine where the mixer fails to initialise (headless CI, no audio
  device) — sound must never be able to crash or block the game.
- Sounds play in step with what's on screen: an event is played when the frame that shows it is
  drawn (e.g. a monster's attack with the monster-phase frame that shows it, not all at the end of
  the round).
- `assets/sounds/` may be absent or empty; when files arrive, each gets an `ASSETS.md` row.
- A setting `SOUND=0` (via `game.settings`, like `TILES`) turns sound off. (call)

### Left to the builder

The event type's exact shape, where in `GameState` each event is recorded, mixer settings, and
how the renderer ties events to frames.

---

## 3. Gold and shops

### Decided (user)

**Gold income**
- Defeated enemies **drop a gold pile on the ground**; the player picks it up by walking over it.
- Drop size scales with the enemy's **threat, health and the floor**: orcs drop more than goblins,
  goblins more than goblin archers. Each drop is randomised **±20%** around its base.
- **Gold chests**: a third chest kind, spawning **more often than gear chests and less often
  than potion chests**. Opening one gives gold.
- **Balance target:** a player who fully clears floors 1–4 (kills every enemy, opens every chest,
  including all of floor 4 before walking back to the shopkeeper) has **about 100 gold** on
  average, *counting both drops and gold chests*. (At floor-4 prices that is most of a weapon, or ~2 boons.)

**Shops**
- On **every 4th floor (4, 8, 12, …)** a shop is generated in **its own room**, with a **human
  shopkeeper** standing in the middle. Walking into the shopkeeper opens the shop.
- The player may **buy as many offers as they can afford**, and can walk away and **come back any
  time while on that floor**. A bought offer is gone; the heal is always available.
- Offers:
  - **Two weapons of different types**, rolled at random. Rarity **rolls normally** (the usual
    depth table) and is then **capped**: at most **Uncommon on floor 4**, at most **Rare from
    floor 8 on**. The shop **never** sells Epic (purple) or anything above.
    Price: **floor × 10 × 3 × rarity multiplier**, where the multiplier is **Uncommon 1, Common
    0.5** (floor 4: Uncommon 120, Common 60) and **Rare 2** (call: the user didn't price Rare;
    this extends the same doubling — floor 8 Rare: 480).
  - **Two random boons, benefit only, no cost, at half the benefit.** "Half" means half the
    number: +3 power becomes +2 (rounded). Price: **floor × 10 × 1.33** (floor 4: 53).
  - **Heal**: price **missing HP × 5**.
- Not in scope (user rejected): offering shrines/gold shrines, chest rerolls, buying a specific
  boon, any other build-control spending.

### Confirmed defaults

- Shop weapons are for the player's class (`item.class_weapons`).
- Half a benefit rounds **half up, minimum 1**: +3 power → +2, +2 defence → +1, +1 belt slot → +1,
  +10% crit → +5%, +15 max HP → +8. (call)
- Heal is all-or-nothing: a full heal for the full price. It is not offered (or shown disabled) at
  full HP. (call)
- Floors 8, 16, … are also boss floors and get **both** the boss and the shop.
- Shop screen: a new screen listing all five offers with prices and the player's gold; number
  keys buy, Space/Esc leaves. Unaffordable offers are visibly greyed out. (call)
- Gold shows on the stats board.
- Prices are rounded to whole gold (floor × 13.3 → 53, 106, 160, …). (call)
- Gold is not shown on the death screen or used as a score for now; it only matters for
  spending. (call)

### Gold balance (call, builder tunes)

- Base drop per enemy is a function of its scaled hp and power at that depth (so threat and depth
  both raise it and the orc > goblin > goblin archer ordering falls out of `MONSTER_TYPES`), times
  a uniform factor in [0.8, 1.2]. Bosses drop proportionally more.
- Gold chest frequency sits between today's gear chest (40% per floor, at most one) and potion
  chests (25% per room, ~1 per floor). A gold chest's amount scales with depth.
- **Acceptance test:** a seeded simulation of many full clears of floors 1–4 (counting every
  enemy's drop and every gold chest the generator places) averages 100 gold ± 10%. The constants
  are tuned until it does, and the test pins them.

### Shop room and shopkeeper (call)

- The shop room is one of the floor's rooms, not `rooms[0]` (start) and not the stairs room; no
  monsters, chests or shrine spawn in it. The shopkeeper stands at its centre and never moves or
  fights; walking into it opens the shop rather than attacking.
- The shopkeeper tile is a human built from the bundled Kenney characters sheet
  (`assets/kenney/roguelike-characters`) via `assets/tiles.json`, with a new map char reserved
  for it (glyph fallback for `TILES=0`). No new art files are needed.
- Shop boons go into the same `Player.boons` mechanism as shrine boons, so stats keep being
  derived rather than stored; a half-strength shop boon must be distinguishable from the full
  shrine boon of the same name (e.g. its own key). Holding both is allowed.

### Left to the builder

The gold-pile entity and char, the shopkeeper char, the exact gold formulas and constants (subject
to the acceptance test), the shop screen's layout (reuse `render/choice.py` / `screens.py` patterns
where they fit), and and nothing else.

---

## Out of scope

Real sound files and music; art redesign; any curses/terminal changes (window-only work);
build-control spending; changes to release/packaging beyond listing new assets.
