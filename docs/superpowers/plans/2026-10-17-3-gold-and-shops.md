# Gold and Shops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gold dropped by enemies and found in gold chests, spent at a shopkeeper who appears in his own room every 4th floor selling two weapons, two half-strength cost-free boons, and a heal.

**Architecture:** Game rules in new stdlib modules `game/gold.py` (piles, drop and chest amounts) and `game/shop.py` (the shop's offers, prices, the shopkeeper entity); half-strength boons join `game/shrine.py`'s table. `GameState` wires them in (kills drop piles, walking picks up, walking into the shopkeeper opens the shop, number keys buy). The window gets a shop overlay in `render/screens.py` with its text in a new stdlib `render/shop_text.py`, a shop key layer in `render/input_map.py`, and tiles for `$` and `P`.

**Tech Stack:** Python 3.12+, pygame-ce, unittest.

**Spec:** `docs/superpowers/specs/2026-10-17-gold-sound-ui-design.md` §3.

**Depends on:** plan 1 (`ui.GOLD_ROW`) and plan 2 (`GameState.sound('gold_pickup')`), both already implemented in this working tree.

## Global Constraints

- `game/` standard-library only; take a `rng: Rng = random` parameter on anything that rolls (the codebase's pattern, `game/rng.py`).
- Prices, verbatim from the spec: weapon `depth × 10 × 3 × {'common': 0.5, 'uncommon': 1, 'rare': 2}[rarity]`; boon `depth × 10 × 1.33`; heal `missing HP × 5`. Round to whole gold with `round()`. Floor 4: common weapon 60, uncommon 120, boon 53.
- Shop floors: `depth % 4 == 0` (4, 8, 12, …). Weapon rarity rolls with `roll_rarity(depth, rng)` then is capped: at most `'uncommon'` when `depth < 8`, at most `'rare'` from 8. Never `'epic'`.
- Gold drops ±20% (uniform factor in `[0.8, 1.2]`). Orc > goblin > goblin archer at equal depth.
- Gold chest frequency strictly between gear chests (0.4 per floor, at most one) and potion chests (0.25 per room, ~1 per floor).
- Balance: full clears of floors 1–4 (every enemy's drop + every gold chest the generator places, including the boss-free floor 4 in full) average **100 gold ± 10%**.
- Same test/lint commands as plan 1. **Do not commit or push.**

## Review Focus

1. A monster dying on a tile that already has a gold pile (or arrows, or the stairs): piles merge, the stairs still work, the arrows stay. Test: `test_two_kills_on_one_tile_make_one_pile`, `test_pile_on_stairs_still_descends`.
2. Chasing monsters following the player into the shop room must never step onto the shopkeeper. Test: `test_monsters_never_step_onto_the_shopkeeper`.
3. Buying with too little gold, buying a sold-out slot, or healing at full HP: no change, a log line, no turn. Test: `test_cannot_buy_what_you_cannot_afford`, `test_sold_offer_cannot_be_bought_again`, `test_heal_at_full_hp_is_refused`.
4. A floor with too few rooms for a separate shop room: no shop, no crash. Test: `test_shop_floor_with_two_rooms_has_no_shop`.
5. The shop overlay at the smallest window size: painted inside the window, no raise. Test: `test_shop_overlay_fits_small_windows`.

---

### Task 1: Gold piles, drops, gold chests, and the panel row

**Files:**
- Create: `game/gold.py`
- Modify: `game/item.py` (Chest kinds/colour ~280-296, `Chest.__init__`/`offers_choice`/`open` ~498-531, `spawn_chests` ~544-561), `game/state.py` (`Player`/init gold, `attack` death branch ~918-930, `try_move_player` ~555-562, `_belt_refuses` ~582-589, `open_chest` ~724-750, `gold_at` helper next to `arrows_at` ~1170), `render/ui.py` (`GOLD_ROW` painting), `render/pygame_render.py` (piles excluded from `_occupied` like arrows ~724), `assets/tiles.json` (`$`), `tests/test_tileset.py` (`drawable_chars` gains `'$'`)
- Test: `tests/test_gold.py` (new), `tests/test_ui.py`, `tests/test_tileset.py`

**Interfaces:**
- Produces (`game/gold.py`):
  - `GOLD_CHAR = '$'`, `GOLD_COLOR = 1` (yellow).
  - `class GoldPile(Entity)`: `__init__(self, x, y, amount: int)`; attributes `amount: int`, `kind = 'gold'`, name `'gold'`.
  - `drop_amount(monster, rng: Rng = random) -> int` — `max(1, round(base × rng.uniform(0.8, 1.2)))`, `base = GOLD_PER_HP × monster.max_hp + GOLD_PER_POWER × monster.power`, × `BOSS_GOLD_MULT` for a boss. Constants are placeholders Task 2 tunes.
  - `chest_amount(depth: int, rng: Rng = random) -> int` — `max(1, round(GOLD_CHEST_PER_DEPTH × depth × rng.uniform(0.8, 1.2)))`.
  - `GOLD_CHEST_CHANCE_PER_FLOOR` (at most one gold chest per floor; must stay in `(0.4, 1.0)`).
- Produces (`game/item.py`): `CHEST_KINDS` gains `'gold'` only for spawning (keep `roll_kind`'s 50/50 potion/gear for kind-less chests); `GOLD_CHEST_COLOR = 1`; `Chest.offers_choice` is True only for `'gear'`; `spawn_chests(rooms, rng, depth, exclude=())` places at most one gold chest per floor with `GOLD_CHEST_CHANCE_PER_FLOOR`, never in `rooms[0]`, the stairs tile, or a room in `exclude` (used by Task 3's shop room; potion and gear chests honour `exclude` too).
- Produces (`GameState`/`Player`): `player.gold: int = 0`; `gold_at(x, y) -> GoldPile | None`; `pick_up_gold(pile)` adds `pile.amount`, removes the pile, logs `'You pick up {n} gold.'`, and calls `self.sound('gold_pickup')`. A killed non-player `Monster` drops `drop_amount(defender)` at `(defender.x, defender.y)` — merged into an existing pile there. Walking onto a pile (normal move; a hop's landing tile) picks it up. `_belt_refuses` checks `chest.kind == 'potion'` (a gold chest is never refused). `open_chest` on a `'gold'` chest adds `chest_amount(self.depth)` and logs `'The chest holds {n} gold.'`.
- Produces (`render/ui.py`): `GOLD_ROW` always shows `f'Gold {player.gold}'` in `palette.ink(GOLD_COLOR)`; add `INK_COLORS[1] = (150, 110, 0)` to `render/palette.py` so yellow reads as a dark gold ink on the paper.
- `assets/tiles.json`: a `"$"` entry using a coin/gold-pile cell from the existing `rpg` sheet (find one by viewing `assets/kenney/roguelike-rpg-pack/roguelikeSheet_transparent.png` with the Read tool); no new image files.

- [ ] **Step 1: Write the failing tests** (`tests/test_gold.py`):

```python
def test_orc_drops_more_than_goblin_more_than_archer(self):
    rng = FixedRng(uniform=1.0)  # or mock rng.uniform -> 1.0
    for depth in (1, 4, 8):
        o, g, a = (
            gold.drop_amount(Monster(0, 0, k, depth), rng)
            for k in ('orc', 'goblin', 'goblin_archer')
        )
        self.assertGreater(o, g)
        self.assertGreater(g, a)


def test_drop_varies_within_20_percent(self):
    m = Monster(0, 0, 'orc', 4)
    lo = gold.drop_amount(m, FixedRng(uniform=0.8))
    hi = gold.drop_amount(m, FixedRng(uniform=1.2))
    mid = gold.drop_amount(m, FixedRng(uniform=1.0))
    self.assertAlmostEqual(lo / mid, 0.8, delta=0.1)
    self.assertAlmostEqual(hi / mid, 1.2, delta=0.1)


def test_deeper_monsters_drop_more(self): ...
def test_boss_drops_more_than_its_kind(self): ...
def test_killing_a_monster_leaves_a_pile_where_it_died(self): ...
def test_two_kills_on_one_tile_make_one_pile(self): ...
def test_walking_onto_a_pile_picks_it_up_and_plays_gold_pickup(
    self,
): ...  # player.gold increased by amount; pile gone; 'gold_pickup' in [e.slot for e in state.sound_events]
def test_pile_on_stairs_still_descends(self): ...
def test_gold_chest_gives_gold_and_no_choice(self): ...  # state.pending_choice is None afterwards
def test_gold_chest_opens_at_full_hp_with_full_belt(self): ...
def test_gold_chest_rate_between_gear_and_potion(self):
    # 2000 seeded spawn_chests over generated levels (game.dungeon.generate_level(40, 20, depth)):
    # mean gear < mean gold < mean potion per floor
    ...


def test_spawn_chests_honours_exclude(self): ...
```

In `tests/test_ui.py`: `test_gold_row_shows_the_players_gold` (set `player.gold = 37`, paint, `GOLD_ROW` has ink) and update plan 1's `test_gold_row_and_boons_are_blank_without_gold_or_boons` so gold 0 still shows `Gold 0` (the row is always painted now) — boons rows stay blank. In `tests/test_tileset.py`: `'$'` in `drawable_chars()`, and `test_gold_chest_is_yellower_than_a_gear_chest` mirroring the potion-chest test.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_gold tests.test_ui tests.test_tileset 2>&1 | tail -15`
Expected: ImportError on `game.gold`.

- [ ] **Step 3: Implement** per Interfaces.

- [ ] **Step 4: Full suite + linters**

Run: `.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3 && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pyright && .venv/bin/vulture`
Expected: `OK`, all clean.

---

### Task 2: Balance — tune to 100 gold over floors 1–4

**Files:**
- Modify: `game/gold.py` (constants only)
- Test: `tests/test_gold.py` (`BalanceTest`)

**Interfaces:**
- Produces: `gold.expected_full_clear_gold(floors: int = 4, runs: int = 400, seed: int = 0) -> float` — a pure simulation in `game/gold.py`: for each run and each depth `1..floors`, generate the level exactly as `GameState` does (`game.dungeon.generate_level(base_w, base_h, depth)` with the default 50x20 base and the `.env`'s 40x20 — run both and require both in range), `spawn_level(rooms, depth, rng)` for the monsters, `spawn_chests(rooms, rng, depth=depth)` for the gold chests; sum `drop_amount` for every monster (bosses included; ignore the depth-8 boss's summons) and `chest_amount` for every gold chest; return the mean per run. Uses its own `random.Random(seed)`.

- [ ] **Step 1: Write the failing test**

```python
def test_full_clear_of_floors_1_to_4_is_about_100_gold(self):
    for base in ((50, 20), (40, 20)):
        mean = gold.expected_full_clear_gold(floors=4, runs=400, seed=1, base=base)
        self.assertTrue(90 <= mean <= 110, (base, mean))


def test_gold_chests_are_a_minority_of_income(self):
    # chests 15-35% of the total, so kills stay the main source (designer's call)
    ...
```

(Add the `base=(w, h)` keyword to the signature.)

- [ ] **Step 2: Run** — expect FAIL with the placeholder constants.
- [ ] **Step 3: Tune** `GOLD_PER_HP`, `GOLD_PER_POWER`, `BOSS_GOLD_MULT` (≈ 3), `GOLD_CHEST_PER_DEPTH`, `GOLD_CHEST_CHANCE_PER_FLOOR` (≈ 0.6–0.7) until both pass; record the measured means in a comment above the constants.
- [ ] **Step 4: Run** the test and the full suite → `OK`.

---

### Task 3: Shop rules — offers, prices, half boons, the shop room, buying

**Files:**
- Create: `game/shop.py`
- Modify: `game/shrine.py` (half boons; `held_boons`), `game/state.py` (`_populate_level` ~242-262, `try_move_player`, `handle_action` shop branch, `_occupied_except` ~1091, `hop`), `game/spawn.py:spawn_level` (`exclude=()`), `game/shrine.py:place_shrine` (honour the excluded room via its `occupied`/a new `exclude` arg), `render/base.py` (`Action.CHOOSE_4`, `Action.CHOOSE_5`), `game/state.py:CHOOSE_INDEX` (`'choose_4': 3, 'choose_5': 4`)
- Test: `tests/test_shop.py` (new)

**Interfaces:**
- Produces (`game/shrine.py`):
  - `half_boon(boon: Boon) -> Boon` — key `f'{boon.key}_half'`, name `f'Lesser {boon.name.lower()}'`, `short = boon.short + '½'`, `cost = ''`; each **positive** numeric benefit halved rounding half up, minimum 1 for ints (`power`, `defense`, `max_hp`, `belt`) and `crit` halved exactly (0.10 → 0.05); negative fields set to 0; `heal` set to 1.0 if it is below 1.0 (a cost) else halved toward 1.0. `benefit` text regenerated (`'+2 power'`, `'+1 defence'`, `'+1 belt slot'`, `'+5% crit'`, `'+8 max HP'`).
  - `HALF_BOONS = {b.key: b for b in (half_boon(x) for x in _TABLE)}`; `ALL_BOONS = {**BOONS, **HALF_BOONS}`; `held_boons` and `boon_total` read `ALL_BOONS`; `roll_boons` still draws only from `BOONS`.
  - Expected half values: blood_pact power 2 / max_hp 0; iron_skin defense 1 / heal 1.0; quick_hands belt 1 / heal 1.0; keen_eye crit 0.05 / max_hp 0; stone_heart max_hp 8 / power 0.
- Produces (`game/shop.py`):
  - `SHOP_INTERVAL = 4`; `is_shop_level(depth: int) -> bool` (`depth % 4 == 0`).
  - `SHOPKEEPER_CHAR = 'P'`, `SHOPKEEPER_COLOR = 7`; `class Shopkeeper(Entity)` (name `'shopkeeper'`, `alive = True`, no `take_turn`).
  - `WEAPON_PRICE_MULT = {'common': 0.5, 'uncommon': 1, 'rare': 2}`; `weapon_price(depth, rarity) -> int`; `boon_price(depth) -> int`; `heal_price(player) -> int` (= `(max_hp - hp) * 5`).
  - `rarity_cap(depth) -> str` (`'uncommon'` below 8, else `'rare'`); `cap_rarity(rarity, depth) -> str`.
  - `@dataclass class Offer: kind: str  # 'weapon' | 'boon' | 'heal'`, `item: Item | None`, `boon: Boon | None`, `price: int`, `sold: bool = False`.
  - `@dataclass class Shop: offers: list[Offer]` — always 5 offers in key order: weapon, weapon, boon, boon, heal (the heal's `price` is ignored; `heal_price(player)` is used live).
  - `roll_shop(depth: int, char_class: str, held_boons=(), rng: Rng = random) -> Shop` — two **different** weapon kinds from `item.class_weapons(char_class)`, each `Item(0, 0, kind, cap_rarity(roll_rarity(depth, rng), depth))`; two different `half_boon`s from `BOONS` (any; holding the full or half version doesn't exclude it).
  - `pick_shop_room(rooms, boss_room, rng) -> Rect | None` — a random room from `rooms[1:-1]` that isn't `boss_room`; `None` if there is none (≤ 2 rooms).
- Produces (`GameState`):
  - `self.shop: Shop | None` (this floor's), `self.shopkeeper: Shopkeeper | None`, `self.shop_open: bool`.
  - `_populate_level`: on a shop floor, pick the room after the boss room; spawn monsters, chests and the shrine with that room excluded; put the `Shopkeeper` at its centre; roll the shop. Off shop floors (and when no room) all three are None/False.
  - Walking into the shopkeeper (`try_move_player`, before the monster check) sets `shop_open = True`, logs `'The shopkeeper shows you his wares.'`, the player doesn't move; returns True (takes the turn like a bump; monsters still get their half).
  - `handle_action` while `shop_open`: `CHOOSE_1..5` → `buy(index)`; `'skip'` → `shop_open = False` (log `'You leave the shop.'`); everything else ignored; none take a turn.
  - `buy(index: int) -> bool`: refuses with a log line and no change if sold, unaffordable, or (heal) HP is full; weapon → `offer.item.apply(self.player, self.log)` (equips, replacing), boon → `take_boon(offer.boon, source='shop')`; heal → HP to max. Deducts the price, marks the offer sold (not the heal), returns True.
  - `take_boon(boon, source='shrine')`: the `'The shrine crumbles to dust.'` line only for `source == 'shrine'`; a shop boon logs `'You buy the {name}: {benefit}.'`.
  - `_occupied_except` includes the shopkeeper's tile; `hop` stops before it; `monster_at` unchanged (arrows fly past the shopkeeper).

- [ ] **Step 1: Write the failing tests** (`tests/test_shop.py`):

```python
def test_shop_floors(self):
    self.assertEqual([d for d in range(1, 17) if shop.is_shop_level(d)], [4, 8, 12, 16])


def test_prices(self):
    self.assertEqual(shop.weapon_price(4, 'uncommon'), 120)
    self.assertEqual(shop.weapon_price(4, 'common'), 60)
    self.assertEqual(shop.weapon_price(8, 'rare'), 480)
    self.assertEqual(shop.boon_price(4), 53)
    self.assertEqual(shop.boon_price(8), 106)
    p = Player(...)
    p.max_hp, p.hp = 60, 41
    self.assertEqual(shop.heal_price(p), 95)


def test_weapons_capped_and_never_epic(self):
    for seed in range(300):
        s = shop.roll_shop(4, 'warrior', rng=random.Random(seed))
        rarities = {o.item.rarity for o in s.offers if o.kind == 'weapon'}
        self.assertTrue(rarities <= {'common', 'uncommon'})
    for depth in (8, 20, 40):
        for seed in range(300):
            s = shop.roll_shop(depth, 'warrior', rng=random.Random(seed))
            self.assertNotIn('epic', {o.item.rarity for o in s.offers if o.kind == 'weapon'})


def test_weapons_roll_normally_below_the_cap(self):
    # at depth 4 over 300 seeds both common and uncommon appear
    ...


def test_two_different_class_weapons(self): ...  # archer -> ARCHER_WEAPONS kinds, distinct
def test_two_different_half_boons(self): ...
def test_half_boon_values(self):
    h = shrine.HALF_BOONS
    self.assertEqual((h['blood_pact_half'].power, h['blood_pact_half'].max_hp), (2, 0))
    self.assertEqual((h['iron_skin_half'].defense, h['iron_skin_half'].heal), (1, 1.0))
    self.assertEqual(h['quick_hands_half'].belt, 1)
    self.assertAlmostEqual(h['keen_eye_half'].crit, 0.05)
    self.assertEqual((h['stone_heart_half'].max_hp, h['stone_heart_half'].power), (8, 0))


def test_shrines_never_offer_half_boons(self): ...
def test_shop_floor_has_shopkeeper_in_an_empty_room(self):
    # GameState advanced to depth 4 (call next_level 3 times with a seed): shopkeeper at a room centre,
    # no Monster/Chest/shrine inside that room, room is not rooms[0] or the stairs room
    ...


def test_shop_floor_8_has_boss_and_shop(self): ...
def test_shop_floor_with_two_rooms_has_no_shop(
    self,
): ...  # pick_shop_room([r0, r1], None, rng) is None
def test_walking_into_shopkeeper_opens_shop_without_moving(self): ...
def test_buy_weapon_equips_and_charges(self): ...
def test_buy_boon_adds_half_boon_and_charges(
    self,
): ...  # power +2 for blood_pact_half, no max_hp loss
def test_heal_costs_missing_hp_times_5_and_stays_available(self): ...
def test_heal_at_full_hp_is_refused(self): ...
def test_cannot_buy_what_you_cannot_afford(self): ...
def test_sold_offer_cannot_be_bought_again(self): ...
def test_shop_actions_take_no_turn(self): ...  # state.turn unchanged across buys and skip
def test_leaving_and_coming_back(self): ...  # skip closes; bump again reopens with sold flags kept
def test_monsters_never_step_onto_the_shopkeeper(
    self,
): ...  # goblin chasing through the shopkeeper's tile, 50 rounds
def test_descending_clears_the_shop(self): ...
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m unittest tests.test_shop 2>&1 | tail -15` → ImportError on `game.shop`.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Full suite + linters** (as Task 1) → `OK`, clean. `tests/test_parity.py` will fail until Task 4 adds keys for `CHOOSE_4`/`CHOOSE_5` — acceptable only within this task; Task 4 must restore it.

---

### Task 4: Shop overlay, shop keys, shopkeeper tile

**Files:**
- Create: `render/shop_text.py` (stdlib only, like `render/choice.py`)
- Modify: `render/input_map.py` (`SHOP_CHAR_ACTIONS`, `lookup(event, choosing=False, shopping=False)`), `render/pygame_render.py` (`get_action` ~1377-1382 passes `shopping=state.shop_open`; `_paint_game` ~755 paints the overlay when `state.shop_open`; mouse hover/click like the choice screen is **not** required), `render/screens.py` (`paint_shop(canvas, state)`), `assets/tiles.json` (`"P"`: a human from the `chars` paper-doll sheet — body + clothes, no weapon, distinct from `@`/`&`), `tests/test_tileset.py` (`drawable_chars` gains `'P'`), `tests/test_parity.py` (`pygame_actions()` includes `SHOP_CHAR_ACTIONS.values()`)
- Test: `tests/test_shop_screen.py` (new; pygame, skips without it)

**Interfaces:**
- Consumes: Task 3's `GameState.shop`, `shop_open`, `Offer`, `heal_price`, `Action.CHOOSE_4/5`.
- Produces:
  - `input_map.SHOP_CHAR_ACTIONS = {'1': CHOOSE_1, '2': CHOOSE_2, '3': CHOOSE_3, '4': CHOOSE_4, '5': CHOOSE_5, ' ': SKIP}`; applied by `lookup(..., shopping=True)` before `CHAR_ACTIONS`. Outside the shop `'4'` is still `SKIP` and `'5'` does nothing.
  - `shop_text.TITLE = 'Shop'`, `shop_text.HINT = 'press 1-5 to buy; space leaves'`, `shop_text.gold_line(player) -> str` (`'Your gold: {n}'`), `shop_text.offer_lines(number: int, offer: Offer, player) -> list[str]`: weapon `[f'[{n}] {item.name} ({rarity})', f'+{bonus} atk   {price} gold']` (reuse the stat text `render/choice.py` already builds for a weapon card), boon `[f'[{n}] {boon.name}', f'{boon.benefit}   {price} gold']`, heal `[f'[{n}] Heal to full', f'{heal_price} gold']` or `'(at full HP)'`; a sold offer's second line is `'sold'`. `shop_text.affordable(offer, player) -> bool`.
  - `screens.paint_shop(canvas, state)`: a framed box over the map like `paint_choice` (same colours: `palette.BACKGROUND` box, `PAGE_EDGE` border, parchment rows), title, gold line, five offer rows inked in the item's rarity ink / boon colour / plain ink, unaffordable or sold rows in `palette.SEEN`, hint at the bottom. Fits inside the window at every `SIZES` entry (shrinks to the map rect, then the window).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_shop_screen.py
def test_shop_keys_only_while_shopping(self):
    four = key_event('4')
    five = key_event('5')
    self.assertEqual(input_map.lookup(four), Action.SKIP)
    self.assertIsNone(input_map.lookup(five))
    self.assertEqual(input_map.lookup(four, shopping=True), Action.CHOOSE_4)
    self.assertEqual(input_map.lookup(five, shopping=True), Action.CHOOSE_5)
    self.assertEqual(input_map.lookup(key_event(' '), shopping=True), Action.SKIP)


def test_offer_lines(self): ...  # sold -> 'sold'; heal at full HP -> '(at full HP)'; prices shown
def test_paint_shop_draws_inside_the_map(self): ...
def test_shop_overlay_fits_small_windows(self):
    for tiles in (False, True):
        for size in SIZES + [(320, 240)]:
            ...  # paint_shop at that size: every painted pixel inside the window, no raise


def test_unaffordable_offer_is_greyed(self): ...
def test_renderer_opens_overlay_and_routes_keys(
    self,
): ...  # post KEYDOWN '5' with state.shop_open -> get_action returns CHOOSE_5
```

`tests/test_tileset.py`: `'P'` in `drawable_chars()`. `tests/test_parity.py`: the every-Action test passes with `CHOOSE_4`/`CHOOSE_5` reachable through `SHOP_CHAR_ACTIONS`.

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Full suite + linters** → `OK`, clean.
- [ ] **Step 5: Look at it.** Headless-render a depth-4 `GameState` with the shop open (give the player 130 gold so some rows are affordable, some not) at 1920x1080 and 1280x720, save PNGs to `$CLAUDE_JOB_DIR/tmp/`, view them with Read, and check the shopkeeper tile and `$` tile on the map look right. Fix anything off.
- [ ] **Step 6: Do not commit** (user instruction).
