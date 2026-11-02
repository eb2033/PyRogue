"""Bigger goblin and goblin archer packs, and ranged monsters that miss."""

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import monster as monster_module
from game.combat import Hit, Shot
from game.monster import RANGED_KINDS, Monster
from game.rect import Rect
from game.spawn import SPAWN_RULES, goblin_pack_size, spawn_pack
from game.spawn import goblin_archer_pack_size as archer_pack_size
from game.state import GameState
from game.tiles import FLOOR


class PackSizeTests(unittest.TestCase):
    def test_goblin_pack_boundaries(self):
        table = {1: 1, 4: 1, 5: 2, 7: 2, 8: 3, 10: 3, 11: 4, 12: 4, 13: 5, 14: 5, 99: 5}
        for depth, size in table.items():
            self.assertEqual(goblin_pack_size(depth), size, depth)

    def test_archer_pack_boundaries_and_rule(self):
        table = {4: 1, 7: 1, 8: 2, 11: 2, 12: 3, 30: 3}
        for depth, size in table.items():
            self.assertEqual(archer_pack_size(depth), size, depth)
        rule = next(r for r in SPAWN_RULES if r.kind == 'goblin_archer')
        self.assertEqual(rule.min_depth, 4)
        self.assertTrue(rule.spread)

    def test_archer_packs_never_touch(self):
        rule = next(r for r in SPAWN_RULES if r.kind == 'goblin_archer')
        for seed in range(40):
            pack = spawn_pack(Rect(1, 1, 10, 10), rule, 12, random.Random(seed))
            self.assertEqual(len(pack), 3)
            for a in pack:
                for b in pack:
                    if a is not b:
                        self.assertGreaterEqual(max(abs(a.x - b.x), abs(a.y - b.y)), 2)


class RangedMissTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(50, 20, seed=3)
        s = self.state
        for y in range(1, 19):
            for x in range(1, 49):
                s.game_map[y][x] = FLOOR
        p = s.player
        p.x, p.y = 10, 10
        p.hp = p.max_hp = 1000
        self.archer = Monster(14, 10, 'goblin_archer')
        s.entities = [p, self.archer]
        s.update_fov()

    def test_miss_chance_is_data_for_every_ranged_kind(self):
        for kind in RANGED_KINDS:
            self.assertEqual(monster_module.MISS_CHANCE[kind], 0.3)

    def test_a_forced_miss_does_no_damage_and_the_arrow_flies_past(self):
        s = self.state
        with mock.patch.object(s.rng, 'random', return_value=0.0):
            s._monster_shot(self.archer)
        self.assertEqual(s.player.hp, 1000)
        self.assertEqual(s.hits(), [])
        self.assertEqual([e for e in s.events if isinstance(e, Hit)], [])
        shot = s.events_of(Shot)[-1]
        self.assertEqual(shot.arrows[0].hits, ())
        self.assertLess(shot.arrows[0].path[-1][0], 10)
        self.assertIn('attack_bow', [e.slot for e in s.events if hasattr(e, 'slot')])

    def test_a_forced_hit_still_damages(self):
        s = self.state
        with (
            mock.patch.object(s.rng, 'random', return_value=0.99),
            mock.patch('game.fight.dodge_chance', return_value=0),
        ):
            s._monster_shot(self.archer)
        self.assertLess(s.player.hp, 1000)
        self.assertEqual(len(s.hits()), 1)
        # a kind without a miss chance never misses
        goblin = Monster(11, 10, 'goblin')
        with mock.patch.object(s.rng, 'random', return_value=0.0):
            s._monster_shot(goblin)
        self.assertEqual(len(s.hits()), 2)

    def test_miss_rate_is_about_thirty_percent(self):
        s = self.state
        s.rng.seed(1)
        misses = 0
        n = 2000
        for _ in range(n):
            s.player.hp = 1000
            before = len(s.hits())
            s._monster_shot(self.archer)
            misses += len(s.hits()) == before
        self.assertAlmostEqual(misses / n, 0.3, delta=0.04)


if __name__ == '__main__':
    unittest.main()
