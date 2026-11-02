"""game/level.py: one model of who stands where and what stops what.

The purpose table (level.BLOCKERS) is the rule; these tests pin each row
against the sites that use it, and the spawners' shared occupancy set
against seeded floors.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import archery, level, shop
from game.combat import Shot
from game.gold import GoldPile
from game.item import Chest, Item
from game.monster import Monster
from game.quiver import ArrowPile
from game.shrine import Shrine
from game.state import GameState
from game.tiles import DOOR, FLOOR, WALL


def arena(char_class='warrior'):
    """An open floor with the player at (10, 10) and nothing else on it."""
    state = GameState(50, 20, char_class=char_class, seed=3)
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    state.shopkeeper = None
    state.shop = None
    state.player.x, state.player.y = 10, 10
    state.entities = [state.player]
    state.update_fov()
    return state


def add(state, entity):
    state.entities.append(entity)
    state.update_fov()
    return entity


def creature_tiles(state):
    tiles = [(state.player.x, state.player.y)]
    tiles += [(e.x, e.y) for e in state.entities if isinstance(e, Monster) and e.alive]
    if state.shopkeeper is not None:
        tiles.append((state.shopkeeper.x, state.shopkeeper.y))
    return tiles


def fixture_tiles(state):
    return [(e.x, e.y) for e in state.entities if isinstance(e, (Chest, Shrine))]


class SeededFloorsTest(unittest.TestCase):
    """The spawners share one occupancy set: over 200 seeded floors (depths
    1-10, boss floor 8 and shop floors included) no chest or shrine is on a
    creature, and no two creatures share a tile."""

    def test_no_chest_or_shrine_on_a_creature_or_the_stairs_and_no_creatures_stacked(self):
        overlaps = []
        for seed in range(20):
            state = GameState(50, 20, seed=seed)
            while True:
                creatures = creature_tiles(state)
                self.assertEqual(len(creatures), len(set(creatures)), (seed, state.depth))
                fixtures = fixture_tiles(state)
                overlaps += [(seed, state.depth, t) for t in fixtures if t in creatures]
                self.assertEqual(len(fixtures), len(set(fixtures)), (seed, state.depth))
                for x, y in fixtures:
                    self.assertNotEqual(state.game_map[y][x], '>', (seed, state.depth))
                if state.depth >= 10:
                    break
                state.next_level()
        self.assertEqual(overlaps, [])


class PurposeTableTest(unittest.TestCase):
    """blocking_at, one purpose at a time."""

    def setUp(self):
        self.state = arena()
        s = self.state
        s.game_map[10][14] = DOOR
        s.game_map[10][15] = WALL
        self.goblin = add(s, Monster(12, 10, 'goblin'))
        self.chest = add(s, Chest(10, 12, kind='potion'))
        self.shrine = add(s, Shrine(10, 13))
        self.pile = add(s, GoldPile(10, 14, 5))
        self.arrows = add(s, ArrowPile(10, 15))
        self.keeper = shop.Shopkeeper(8, 10)
        s.shopkeeper = self.keeper
        s.entities.append(self.keeper)

    def blocked(self, purpose):
        """{what: blocks?} for one purpose."""
        s = self.state
        tiles = {
            'floor': (11, 10),
            'wall': (15, 10),
            'door': (14, 10),
            'monster': (12, 10),
            'player': (10, 10),
            'shopkeeper': (8, 10),
            'chest': (10, 12),
            'shrine': (10, 13),
            'gold': (10, 14),
            'arrows': (10, 15),
        }
        return {what: level.blocking_at(s, x, y, purpose) for what, (x, y) in tiles.items()}

    def test_blocked_tiles_for_each_purpose(self):
        everything = {
            'floor',
            'wall',
            'door',
            'monster',
            'player',
            'shopkeeper',
            'chest',
            'shrine',
            'gold',
            'arrows',
        }
        expected = {
            level.MONSTER_MOVE: {'wall', 'monster', 'player', 'shopkeeper'},
            level.MONSTER_SHOT: {'wall', 'door', 'monster', 'player', 'shopkeeper'},
            # an arrow passes the shopkeeper and fixtures, but not an empty door
            level.ARROW: {'wall', 'door'},
            level.HOP: {'wall', 'door', 'monster', 'player', 'shopkeeper', 'chest', 'shrine'},
            level.REACH: {'wall', 'door', 'monster', 'player', 'shopkeeper'},
            level.KNOCKBACK: {'wall', 'monster', 'player', 'shopkeeper'},
            level.SUMMON: everything - {'floor'},  # needs bare floor
        }
        for purpose, blocked in expected.items():
            with self.subTest(purpose=purpose):
                got = self.blocked(purpose)
                self.assertEqual(set(got), everything)
                self.assertEqual({k for k, v in got.items() if v}, blocked)

    def test_arrow_enters_a_door_with_a_monster_in_it(self):
        s = self.state
        self.goblin.x = 14
        self.assertFalse(level.blocking_at(s, 14, 10, level.ARROW))

    def test_off_the_map_blocks_everything_and_dead_or_ignored_monsters_do_not(self):
        for purpose in level.BLOCKERS:
            self.assertTrue(level.blocking_at(self.state, -1, 5, purpose))
            self.assertTrue(level.blocking_at(self.state, 5, 500, purpose))
        self.assertFalse(
            level.blocking_at(self.state, 12, 10, level.MONSTER_MOVE, ignore=self.goblin)
        )
        self.goblin.alive = False
        self.assertFalse(level.blocking_at(self.state, 12, 10, level.MONSTER_MOVE))

    def test_occupant(self):
        s = self.state
        self.assertIs(level.occupant(s, 12, 10), self.goblin)
        self.assertIs(level.occupant(s, 10, 10), s.player)
        self.assertIs(level.occupant(s, 8, 10), self.keeper)
        self.assertIsNone(level.occupant(s, 10, 12), 'a chest is not a creature')
        self.assertIsNone(level.occupant(s, 11, 10))

    def test_blocker_tiles_is_the_entity_part_of_the_rule(self):
        s = self.state
        self.assertEqual(
            level.blocker_tiles(s, level.MONSTER_MOVE, ignore=self.goblin), {(10, 10), (8, 10)}
        )
        self.assertEqual(
            level.blocker_tiles(s, level.HOP),
            {(10, 10), (12, 10), (8, 10), (10, 12), (10, 13)},
        )
        self.assertEqual(
            level.blocker_tiles(s, level.MONSTER_SHOT, ignore=self.goblin), {(10, 10), (8, 10)}
        )

    def test_free_tiles(self):
        from game.rect import Rect

        room = Rect(2, 2, 2, 1)  # x, y, w, h: carved floor x 2..3, y 2
        self.assertEqual(level.room_tiles(room), [(2, 2), (3, 2)])
        self.assertEqual(level.free_tiles(room, {(2, 2)}), [(3, 2)])


class MonstersAndFixturesTest(unittest.TestCase):
    """Only creatures block creatures: a monster may walk (or be knocked)
    onto a chest or shrine, as it always could. The renderer paints it on
    top (draw_layer); only spawning keeps chests off creatures."""

    def test_a_chaser_steps_onto_a_chest(self):
        state = arena()
        # A corridor: the goblin at (13, 10), a chest between it and the player.
        for y in (9, 11):
            for x in range(9, 16):
                state.game_map[y][x] = WALL
        chest = add(state, Chest(12, 10, kind='gear'))
        goblin = add(state, Monster(13, 10, 'goblin'))
        state.handle_action('wait')
        state.end_turn()
        self.assertEqual((goblin.x, goblin.y), (chest.x, chest.y))

    def test_a_chest_does_not_break_a_goblin_archers_line(self):
        state = arena()
        add(state, Chest(12, 10, kind='gear'))
        shooter = add(state, Monster(14, 10, 'goblin_archer'))
        occupied = level.blocker_tiles(state, level.MONSTER_SHOT, ignore=shooter)
        self.assertTrue(shooter.clear_shot(state.player, state.game_map, occupied))

    def test_knockback_crosses_a_chest_and_a_doorway_and_stops_before_a_monster(self):
        state = arena('archer')
        goblin = add(state, Monster(13, 10, 'goblin'))
        add(state, Chest(14, 10, kind='gear'))
        add(state, Monster(16, 10, 'goblin'))
        archery._knock_back(state, goblin, 1, 0, 3)
        self.assertEqual((goblin.x, goblin.y), (15, 10))
        state = arena('archer')
        state.game_map[10][14] = DOOR
        goblin = add(state, Monster(13, 10, 'goblin'))
        archery._knock_back(state, goblin, 1, 0, 2)
        self.assertEqual((goblin.x, goblin.y), (15, 10))


class SummonPlacementTest(unittest.TestCase):
    def boss_state(self):
        state = arena()
        state.depth = 8  # tier 2: two goblins
        boss = add(state, Monster(20, 10, 'orc', depth=8, is_boss=True))
        state.player.x, state.player.y = 40, 15
        return state, boss

    def summoned(self, state, boss):
        return [e for e in state.entities if isinstance(e, Monster) and e is not boss]

    def test_summons_never_land_on_a_chest_shrine_or_pile(self):
        for seed in range(30):
            state, boss = self.boss_state()
            # Wall the boss into a 3x1 strip with everything but one tile taken.
            for y in range(7, 14):
                for x in range(17, 24):
                    state.game_map[y][x] = WALL
            for x in range(18, 23):
                state.game_map[10][x] = FLOOR
            add(state, Chest(18, 10, kind='gear'))
            add(state, GoldPile(19, 10, 3))
            add(state, ArrowPile(21, 10))
            state.rng.seed(seed)
            state._summon_goblins(boss)
            self.assertEqual([(m.x, m.y) for m in self.summoned(state, boss)], [(22, 10)])

    def test_summons_never_appear_through_a_wall(self):
        for seed in range(30):
            state, boss = self.boss_state()
            # A wall at x = 21 splits the radius: only the boss's side counts.
            for y in range(1, 19):
                state.game_map[y][21] = WALL
            state.rng.seed(seed)
            state._summon_goblins(boss)
            summoned = self.summoned(state, boss)
            self.assertEqual(len(summoned), 2)
            for m in summoned:
                self.assertLess(m.x, 21, seed)


class MonsterArrowTest(unittest.TestCase):
    def test_a_dodged_arrow_stops_before_a_closed_door(self):
        state = arena()
        state.game_map[10][6] = DOOR
        add(state, Monster(13, 10, 'goblin_archer'))
        with mock.patch('game.fight.dodge_chance', return_value=100):
            state.end_turn()
        (shot,) = state.events_of(Shot)
        self.assertEqual(shot.path[-1], (7, 10))


class DrawOrderTest(unittest.TestCase):
    def test_draw_layer_puts_creatures_over_fixtures_over_piles(self):
        state = arena()
        goblin = Monster(12, 10, 'goblin')
        things = [
            goblin,
            Chest(12, 10, kind='gear'),
            GoldPile(12, 10, 1),
            Shrine(12, 11),
            state.player,
            ArrowPile(13, 10),
            shop.Shopkeeper(1, 1),
            Item(0, 0, 'potion', 'common'),
        ]
        ordered = sorted(things, key=level.draw_layer)
        layers = [level.draw_layer(e) for e in ordered]
        self.assertEqual(layers, sorted(layers))
        self.assertEqual(
            [type(e).__name__ for e in ordered[-3:]], ['Monster', 'Player', 'Shopkeeper']
        )
        self.assertEqual({type(e).__name__ for e in ordered[3:5]}, {'Chest', 'Shrine'})


if __name__ == '__main__':
    unittest.main()
