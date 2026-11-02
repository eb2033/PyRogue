# Small Changes Plan (2026-10-19)

**Status:** agreed, not started. Every decision below is the user's or was approved by them; items marked *(implementer's call)* are left to whoever builds it.

**Base:** the working tree on `worktree-gold-sound-ui` (v0.2.1 plus this session's work, uncommitted).

## Global constraints

- `game/` stays standard-library only and never imports `render/`.
- Seeded replay holds: the same seed and actions give the same game (`tests/test_rng.py`). New rolls go through `state.rng`; seeded fixtures that shift are updated, and each such change is listed in the task report.
- Gold balance: a full clear of floors 1–4 pays 120 ± 12 gold (`tests/test_gold.py`). Terrain (§4) and slimes (§5) both change floors 1–4, so re-run the balance test after each and retune `GOLD_PER_HP` / `GOLD_PER_POWER` in `game/gold.py` if it leaves the window. Report the new means.
- Test-first for each behaviour. Full suite, `ruff check`, `ruff format --check`, `pyright` and `vulture` clean after each task.
- Update `CLAUDE.md` (Current state, Keys, Tests table) and the `CHANGELOG.md` Unreleased section for every player-visible change, including the room-size change already made (rooms 10–14 on floors 9–16, 12–16 from 17).
- No commits or pushes until the user says so.

---

## 1. Archer melee does half damage

- An archer's bump-attack uses `factor=0.5` on raw power (`game/turns.py` `melee` → `game/fight.py` `attack`).
- A **point-blank arrow** counts as melee and is halved too: a shot whose first monster is orthogonally adjacent to the archer when it fires. That covers the aim arrow in `game/archery.py` `_fly` and the volley's extra arrows in `_point_blank`.
- A shot at a monster two or more tiles away is unchanged. After a hop the target is usually no longer adjacent, so a hop-then-shoot does full damage (kiting is rewarded).
- Warriors are unaffected.

**Files:** `game/turns.py`, `game/archery.py`, tests.

**Tests:** an archer bump does half a warrior-style bump at the same power (seeded crit/rounding); an adjacent shot does half a two-tile shot; a two-tile shot is unchanged; a volley at an adjacent target is halved per arrow; a warrior bump is unchanged.

---

## 2. Space is the only skip

- `render/choice.py`: `HINT` becomes `'press 1, 2 or 3; space skips'`; the skip lines become `'[Space] Skip: leave the chest'` and `'[Space] Skip: leave the shrine'`.
- `render/input_map.py`: remove `'4': Action.SKIP` from `CHAR_ACTIONS`, so key 4 does nothing outside the shop. Space (on a choice screen) and a click on the skip line still skip.
- **Shop:** key 4 still buys the shop's 4th offer (`SHOP_CHAR_ACTIONS`). *Confirm with the user before implementing;* removing it there too would leave the 4th offer buyable only by mouse.
- Remove the tests that assert key 4 skips (e.g. `tests/test_parity.py` `test_4_skips_a_choice_and_space_skips_only_on_the_choice_screen`, keeping its Space assertions), and update tests asserting the old strings.
- `CLAUDE.md` Keys line and Chests section: drop "`4`".

**Files:** `render/choice.py`, `render/input_map.py`, `tests/test_parity.py`, choice-screen tests, `CLAUDE.md`.

---

## 3. More enemies; ranged monsters miss

### 3a. Goblin packs grow to 5
`game/spawn.py` `goblin_pack_size`: 1 on floors 1–4, 2 on 5–7, 3 on 8–10, 4 on 11–12, 5 from 13 (`GOBLIN_PACK_MAX = 5`).

### 3b. Goblin archer packs grow to 3
From their first floor (4): 1 on floors 4–7, 2 on 8–11, 3 from 12. Spread still applies (never adjacent).

### 3c. Ranged monsters miss 30%
- Every ranged monster kind (`RANGED_KINDS`; today the goblin archer) misses 30% of shots. The chance is data per kind in `game/monster.py`, not a hard-coded check.
- Rolled on `state.rng` in `game/fight.py` `monster_shot`, before the player's dodge roll. A miss is handled exactly like a dodged arrow: no damage, no `Hit`, and the arrow flies on past the player. The attack sound still plays.

**Files:** `game/spawn.py`, `game/monster.py`, `game/fight.py`, tests (pack-size tables at every boundary, no archer before floor 4, a forced miss leaves HP unchanged and records no Hit, a forced hit still damages).

---

## 4. Terrain walls in rooms

- New step `add_terrain(game_map, rooms, rng)` in `game/dungeon.py`, called by `generate_level` after doors. Because it is inside `generate_level`, the gold balance simulation picks it up automatically.
- Features: an L-shape (3 tiles), or a straight wall of 2 or 3 tiles, drawn as `WALL`.
- **Count:** 3 features in a room up to 12 tiles wide, 6 in a wider room. In practice that is 3 on floors 1–8 and 6 from floor 9. `rooms[0]` (the player's start) gets none.
- **Placement rules.** A feature is placed only if all of these hold, else it is retried a few times and then skipped:
  - It lies inside the room's floor area.
  - It is clear of the 3×3 around **every room's centre**. That is where the player starts, and where the stairs, the boss and the shopkeeper stand. Those roles are picked after generation, so this rule protects them without knowing which room is which.
  - It doesn't touch a door: no feature tile is orthogonally adjacent to a `+`.
  - It doesn't touch another feature: no tile within one tile (diagonals included) of another feature.
  - Every walkable tile reachable before it is still reachable from `rooms[0]`'s centre afterwards (flood fill).
- Walls already block sight and movement, so FOV and monster movement need no changes. Monsters, chests and shrines spawn on the remaining floor tiles through the existing occupancy rules (`game/level.py`).
- Known side effect to watch in playtest: the monster chase is still a simple 4-way step, so a monster lined up behind terrain with the player can stall. This is already documented in `game/monster.py`.

**Files:** `game/dungeon.py`, `CLAUDE.md` (Dungeon section), tests.

**Tests** (seeded levels at depths 1, 5, 9, 17):
- every walkable tile is reachable from the start;
- no terrain is within the 3×3 of a room centre, next to a door, or on the stairs;
- features don't touch each other;
- `rooms[0]` has none;
- the 3-versus-6 count by room width;
- the room count is unchanged.

---

## 5. Slimes

### 5a. Kinds and sizes
- Three kinds: `slime_small`, `slime_medium`, `slime_large`.
- Floors 1–5 spawn small slimes, floors 6–10 medium, and 11 onwards large.

### 5b. Stats
- **HP:** an orc's HP at the same depth (after tier scaling and the early-orc reduction, i.e. the orc that would actually spawn there) times 0.5 (small), 0.8 (medium) or 1.2 (large).
- **Power:** base 2 / 3 / 4, plus the normal +1 per tier.
- **Defence:** 0.

### 5c. Splitting
- When a medium dies it splits into two smalls; a large splits into two mediums. Splits use the depth of the floor they're on.
- Split slimes appear on free walkable tiles: orthogonally next to the dead slime first, then within two tiles. They use the `SUMMON` rule in `game/level.py`, so never through a wall. If there's no room, fewer appear.
- Split slimes drop **no gold**. Only a slime placed by the spawner drops gold (a flag on the monster).
- Split slimes join the next round's monster queue, not the current one.

### 5d. Behaviour
- Large slimes move one tile every two turns. They skip every other move but still attack every turn when adjacent, and the skip must not upset the chase and give-up counters.
- Player arrows do 70% damage to every slime size: a data field `ranged_resist` on the kind, applied as a factor in the arrow path. It stacks with §1's point-blank halving, giving 35% for an adjacent shot.

### 5e. Spawning
One `SpawnRule` per size band, weight 1, a pack of 1 per room, spread.

### 5f. Looks
- No tiles yet; the user will supply pixel art later.
- The renderer draws each slime as a **green square** centred in its cell, sized by kind: about 45% of the cell for small, 65% for medium, 85% for large *(exact sizes: implementer's call)*. Same in tile and glyph mode. Health bars and hit effects work as for any monster.
- Use a placeholder glyph char for game logic, e.g. `j`. Exempt it from `tests/test_tileset.py`'s "every drawable char has a tile" check with a comment.

**Files:** `game/monster.py`, `game/spawn.py`, `game/fight.py` (split on death, no gold for splits), `game/archery.py` (ranged resistance), `render/pygame_render.py` (squares), `tests/test_tileset.py`, tests.

**Tests:**
- size by floor at every band boundary;
- HP is orc × 0.5 / 0.8 / 1.2 at depths 1, 6 and 11;
- a medium dies into two smalls, a large into two mediums, a small cleanly;
- splits land only on free reachable tiles, and fewer when boxed in;
- splits drop no gold;
- a large moves once per two turns but attacks every turn;
- arrows do 70% damage to a slime (seeded, compared with a goblin);
- a renderer test that a slime cell is painted green at the expected size;
- the gold balance re-run (see Global constraints).

---

## 6. Two new weapons

Both use the existing offset table (`WEAPON_DAMAGE_OFFSET` in `game/item.py`): **−1**. Each joins its class's weapon list, so it drops from chests and appears in shops. Each needs names for all four rarities, a `WEAPON_EFFECTS` entry and an `ITEM_CHARS` row (`/`). Seeded fixtures that roll weapon kinds will shift.

### 6a. Warrior: fencing sword
- Its parry riposte hits harder: ×2.0 at common, ×2.15 uncommon, ×2.3 rare, ×2.5 epic.
- The normal riposte is ×1.5 (`CRIT_MULTIPLIER`).
- Data: `WEAPON_EFFECTS['fencing_sword'] = {'riposte_mult': {...}}`. `fight.riposte` uses the weapon's value when it has one, else `CRIT_MULTIPLIER`.
- **Tests:** a fencing-sword riposte deals the right multiple at each rarity (seeded rounding); every other weapon's riposte is unchanged.

### 6b. Archer: hand crossbow
- No reload. Its effect is the **hop-shot**: with it equipped, a hop that moves the archer directly away from an orthogonally adjacent monster doesn't end the turn.
  - **The next action is a shot:** the shot fires and *then* the turn ends, so monsters act once, after both.
  - **The next action isn't a shot:** the hop's deferred monster turn resolves first (all at once, not animated step by step), then the new action runs as a normal turn. So the hop never becomes free movement.
- The hop keeps its cooldown (`HOP_COOLDOWN`), and the shot uses an arrow as usual.
- A hop with no adjacent monster to move away from is an ordinary hop.

**Files:** `game/item.py`, `game/turns.py` (the deferred turn after a hop), `game/moves.py` (the "moved away" check), `game/archery.py`, tests.

**Tests:**
- hop away then shoot: monsters act once, after the shot, and not between;
- hop away then walk: monsters act after the hop and again after the walk;
- a hop not away from an adjacent monster is ordinary;
- the cooldown still applies;
- the shot consumes an arrow;
- other bows' hops are unchanged.

---

## 7. Arrows that hit are used up

- An arrow that strikes at least one monster leaves no pile (`game/archery.py` `_fly` / `_drop_arrow`, and the volley's extras per arrow).
- An arrow that hits nothing still drops where it stops, as today.
- Ammo now returns only from misses and the passive restock (1 arrow every `RESTOCK_TURNS` = 3 turns, quiver 12). If that's too stingy in playtest, the knob is `RESTOCK_TURNS` in `game/quiver.py`.

**Tests:** a hit arrow leaves no pile; a miss leaves one on its stop tile; a longbow arrow through two monsters leaves nothing; a volley leaves piles only for its missing arrows.

---

## Order of work

1. §1 archer melee and point-blank, §2 space-only skip, §7 arrows used up. Small, independent.
2. §3 enemy scaling and the ranged miss.
3. §4 terrain, then a gold balance re-run.
4. §5 slimes, then a gold balance re-run.
5. §6 fencing sword and hand crossbow.

## Decided (for reference)

- Goblin ramp 1/2/3/4/5 over floors 1–4 / 5–7 / 8–10 / 11–12 / 13+, and archers 1/2/3 over 4–7 / 8–11 / 12+.
- Ranged monsters miss 30%.
- Space is the only skip (the shop's key 4 is pending confirmation).
- Terrain: 3 or 6 features, room centres and doors kept clear.
- Slime HP 0.5 / 0.8 / 1.2 × orc, power 2 / 3 / 4, no gold from splits, drawn as green squares for now.
- Fencing sword riposte ×2.0 → ×2.5. The hand crossbow defers the hop's turn to the shot.
- Point-blank arrows halved; arrows that hit are used up.
