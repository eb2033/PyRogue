"""Gold piles, drops and gold chests (game/gold.py)."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import gold
from game.dungeon import generate_level
from game.item import GEAR_CHEST_CHANCE_PER_FLOOR, Chest, spawn_chests
from game.level import terrain_tiles
from game.monster import Monster
from game.rect import Rect
from game.shop import is_shop_level, pick_shop_room
from game.sound import SoundEvent
from game.spawn import pick_boss_room, spawn_level
from game.state import GameState
from game.tiles import FLOOR, STAIRS_DOWN


class FixedRng(random.Random):
    """An rng whose uniform() always answers the same number."""

    def __init__(self, uniform):
        super().__init__()
        self._uniform = uniform

    def uniform(self, a, b):
        return self._uniform


def synthetic_rooms(rng):
    """A floor's worth of rooms without generating a level: 4-6 (as
    generate_dungeon rolls) non-overlapping rooms of 4-8 tiles a side, in a
    row. spawn_chests only looks at the rooms, so this is all it needs."""
    rooms, x = [], 1
    for _ in range(rng.randint(4, 6)):
        w, h = rng.randint(4, 8), rng.randint(4, 8)
        rooms.append(Rect(x, rng.randint(1, 4), w, h))
        x += w + rng.randint(2, 5)
    return rooms


def arena(seed=3):
    state = GameState(50, 20, seed=seed)
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    p = state.player
    p.x, p.y = 10, 10
    p.hp = p.max_hp = 1000
    p.power = 1000
    state.entities = [p]
    state.update_fov()
    return state


def slots(state):
    return [e.slot for e in state.events_of(SoundEvent)]


def in_room(chest, room):
    return room.x1 <= chest.x < room.x2 and room.y1 <= chest.y < room.y2


def kill_adjacent(state, kind='goblin', at=(11, 10)):
    m = Monster(at[0], at[1], kind)
    state.entities.append(m)
    state.update_fov()
    state.attack(state.player, m)
    return m


class DropAmountTests(unittest.TestCase):
    def test_drops_order_by_kind_depth_and_boss(self):
        rng = FixedRng(1.0)
        for depth in (1, 4, 8):
            o, g, a = (
                gold.drop_amount(Monster(0, 0, k, depth), rng)
                for k in ('orc', 'goblin', 'goblin_archer')
            )
            self.assertGreater(o, g)
            self.assertGreater(g, a)
        amounts = [gold.drop_amount(Monster(0, 0, 'orc', d), rng) for d in (1, 4, 7, 10)]
        self.assertEqual(amounts, sorted(amounts))
        self.assertLess(amounts[0], amounts[-1])
        boss = Monster(0, 0, 'orc', 8, is_boss=True)
        plain = Monster(0, 0, 'orc', 8)
        self.assertGreater(gold.drop_amount(boss, rng), gold.drop_amount(plain, rng))

    def test_drop_varies_within_20_percent(self):
        m = Monster(0, 0, 'orc', 4)
        lo = gold.drop_amount(m, FixedRng(0.8))
        hi = gold.drop_amount(m, FixedRng(1.2))
        mid = gold.drop_amount(m, FixedRng(1.0))
        self.assertAlmostEqual(lo / mid, 0.8, delta=0.1)
        self.assertAlmostEqual(hi / mid, 1.2, delta=0.1)
        for seed in range(50):
            n = gold.drop_amount(m, random.Random(seed))
            self.assertTrue(lo <= n <= hi)

    def test_a_drop_is_at_least_one(self):
        m = Monster(0, 0, 'goblin_archer', 1)
        m.max_hp, m.power = 0, 0
        self.assertEqual(gold.drop_amount(m, FixedRng(0.8)), 1)

    def test_chest_amount_grows_with_depth_and_bonus_adds_5_to_10_gold(self):
        rng = FixedRng(1.0)
        self.assertLess(gold.chest_amount(1, rng), gold.chest_amount(5, rng))
        self.assertGreaterEqual(gold.chest_amount(1, FixedRng(0.8)), 1)
        lo, hi = gold.GOLD_CHEST_BONUS
        self.assertEqual((lo, hi), (5, 10))
        for depth in (1, 4, 9):
            old = max(1, round(gold.GOLD_CHEST_PER_DEPTH * depth))
            extras = set()
            for seed in range(200):
                rng = FixedRng(1.0)
                rng.seed(seed)
                extras.add(gold.chest_amount(depth, rng) - old)
            self.assertEqual(extras, set(range(lo, hi + 1)), depth)


class PileTests(unittest.TestCase):
    def test_killing_a_monster_leaves_a_pile_where_it_died(self):
        state = arena()
        m = kill_adjacent(state)
        pile = state.gold_at(m.x, m.y)
        self.assertIsNotNone(pile)
        self.assertGreater(pile.amount, 0)

    def test_the_player_dying_drops_nothing(self):
        state = arena()
        state.player.hp = 0
        state.attack(Monster(11, 10, 'goblin'), state.player)
        self.assertEqual([e for e in state.entities if isinstance(e, gold.GoldPile)], [])

    def test_two_kills_on_one_tile_make_one_pile(self):
        state = arena()
        kill_adjacent(state)
        first = state.gold_at(11, 10).amount
        kill_adjacent(state)
        piles = [e for e in state.entities if isinstance(e, gold.GoldPile)]
        self.assertEqual(len(piles), 1)
        self.assertGreater(piles[0].amount, first)

    def test_walking_onto_a_pile_picks_it_up_and_plays_gold_pickup(self):
        state = arena()
        state.entities.append(gold.GoldPile(11, 10, 25))
        state.events.clear()
        state.handle_action('move_e')
        self.assertEqual(state.player.gold, 25)
        self.assertIsNone(state.gold_at(11, 10))
        self.assertIn('gold_pickup', slots(state))
        self.assertIn('You pick up 25 gold.', state.messages)
        # an archer's hop landing on a pile picks it up too
        state = arena()
        state.entities.append(gold.GoldPile(12, 10, 7))
        self.assertTrue(state.hop(1, 0))
        self.assertEqual(state.player.gold, 7)
        self.assertIsNone(state.gold_at(12, 10))

    def test_pile_on_stairs_still_descends(self):
        state = arena()
        state.game_map[10][11] = STAIRS_DOWN
        state.entities.append(gold.GoldPile(11, 10, 5))
        state.handle_action('move_e')
        self.assertEqual(state.player.gold, 5)
        state.handle_action('descend')
        self.assertEqual(state.depth, 2)
        self.assertEqual(state.player.gold, 5)  # the gold comes along


class GoldChestTests(unittest.TestCase):
    def chest_state(self):
        state = arena(4)
        state.entities.append(Chest(11, 10, kind='gold'))
        return state

    def test_gold_chest_gives_gold_and_no_choice(self):
        state = self.chest_state()
        state.handle_action('move_e')
        self.assertGreater(state.player.gold, 0)
        self.assertIsNone(state.pending_choice)
        self.assertIsNone(state.chest_at(11, 10))
        self.assertTrue(any(m.startswith('The chest holds ') for m in state.messages))

    def test_gold_chest_opens_at_full_hp_with_full_belt(self):
        state = self.chest_state()
        state.belt[:] = [object()] * 20
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertTrue(state.try_move_player(1, 0))
        self.assertGreater(state.player.gold, 0)
        self.assertEqual(state.player.x, 11)

    def test_gold_chest_rate_between_gear_and_potion(self):
        rng = random.Random(11)
        totals = {'gear': 0, 'gold': 0, 'potion': 0}
        layouts, spawns = 200, 10
        for i in range(layouts):
            depth = 2 + i % 8  # floor 1 always has its gear chest
            rooms = synthetic_rooms(rng)
            for _ in range(spawns):
                for c in spawn_chests(rooms, rng, depth):
                    totals[c.kind] += 1
        gear, gold_, potion = (totals[k] / (layouts * spawns) for k in ('gear', 'gold', 'potion'))
        self.assertLess(gear, gold_)
        self.assertLess(gold_, potion)
        self.assertAlmostEqual(gear, GEAR_CHEST_CHANCE_PER_FLOOR, delta=0.05)

    def test_at_most_one_gold_chest_per_floor_off_start_and_stairs(self):
        rng = random.Random(2)
        for _ in range(300):
            rooms = synthetic_rooms(rng)
            chests = spawn_chests(rooms, rng, 3)
            golds = [c for c in chests if c.kind == 'gold']
            self.assertLessEqual(len(golds), 1)
            for c in golds:
                self.assertNotEqual((c.x, c.y), rooms[-1].center())
                self.assertFalse(in_room(c, rooms[0]))

    def test_spawn_chests_honours_exclude(self):
        rng = random.Random(5)
        for _ in range(300):
            rooms = synthetic_rooms(rng)
            banned = rooms[1]
            for c in spawn_chests(rooms, rng, 3, exclude=(banned,)):
                self.assertFalse(in_room(c, banned))

    def test_offers_choice_only_for_gear_and_kindless_chests_are_potion_or_gear(self):
        self.assertTrue(Chest(0, 0, kind='gear').offers_choice)
        self.assertFalse(Chest(0, 0, kind='gold').offers_choice)
        self.assertFalse(Chest(0, 0, kind='potion').offers_choice)
        kinds = {Chest(0, 0, rng=random.Random(i)).kind for i in range(50)}
        self.assertEqual(kinds, {'potion', 'gear'})


def full_clear_gold_split(
    floors: int = 4, runs: int = 400, seed: int = 0, base: tuple[int, int] = (50, 20)
) -> tuple[float, float]:
    """(kill gold, chest gold): the mean per run from fully clearing floors
    1..`floors` -- every monster's drop and every gold chest -- over `runs`
    seeded simulated runs on a `base`-sized map. Levels are built the way
    GameState builds them. Used by the balance tests only."""
    # One generator for everything, as GameState has: the global random
    # module is never read or reseeded.
    rng = random.Random(seed)
    kills = chests = 0
    for _ in range(runs):
        for depth in range(1, floors + 1):
            game_map, rooms = generate_level(base[0], base[1], depth, rng)
            # As game.floor.populate_level: the shop room (on a shop
            # floor) gets no monsters and no chests.
            boss_room = pick_boss_room(rooms, depth, rng)
            shop_room = pick_shop_room(rooms, boss_room, rng) if is_shop_level(depth) else None
            exclude = (shop_room,) if shop_room is not None else ()
            # One occupancy set through both spawners (game/level.py).
            occupied = {rooms[0].center()} | terrain_tiles(game_map, rooms)
            monsters, _ = spawn_level(
                rooms, depth, rng, exclude=exclude, boss_room=boss_room, occupied=occupied
            )
            kills += sum(gold.drop_amount(m, rng) for m in monsters)
            chests += sum(
                gold.chest_amount(depth, rng)
                for chest in spawn_chests(
                    rooms, rng, depth=depth, exclude=exclude, occupied=occupied
                )
                if chest.kind == 'gold'
            )
    return kills / runs, chests / runs


def expected_full_clear_gold(
    floors: int = 4, runs: int = 400, seed: int = 0, base: tuple[int, int] = (50, 20)
) -> float:
    """Mean total gold from a full clear of floors 1..`floors` (see
    full_clear_gold_split)."""
    return sum(full_clear_gold_split(floors, runs, seed, base))


class BalanceTest(unittest.TestCase):
    BASES = ((50, 20), (40, 20))
    RUNS = 150  # per base; 400 runs would take about a minute

    @classmethod
    def setUpClass(cls):
        cls.split = {
            base: full_clear_gold_split(floors=4, runs=cls.RUNS, seed=1, base=base)
            for base in cls.BASES
        }

    def test_full_clear_of_floors_1_to_4_is_about_120_gold_and_chests_are_a_minority(self):
        # Chests 15-40% of the total, so kills stay the main source (measured
        # about 36-37% with terrain-aware placement).
        for base, (kills, chests) in self.split.items():
            self.assertAlmostEqual(kills + chests, 120, delta=12, msg=str(base))
            share = chests / (kills + chests)
            self.assertTrue(0.15 <= share <= 0.40, (base, share))

    def test_simulation_is_reproducible_and_leaves_global_random_alone(self):
        random.seed(5)
        before = random.getstate()
        first = expected_full_clear_gold(runs=5, seed=3)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(first, expected_full_clear_gold(runs=5, seed=3))


if __name__ == '__main__':
    unittest.main()
