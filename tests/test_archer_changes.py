"""Archer melee and point-blank arrows do half damage; arrows that hit are used up."""

import unittest
from unittest import mock

from game.actions import Action
from game.monster import Monster
from game.quiver import ArrowPile
from game.state import GameState
from game.tiles import FLOOR
from tests.test_game import ArcherArena


def _warrior_arena():
    state = GameState(50, 20, char_class='warrior', seed=5)
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    p = state.player
    p.x, p.y = 10, 10
    p.hp = p.max_hp = 1000
    state.entities = [p]
    return state


class HalfDamageTests(ArcherArena):
    def setUp(self):
        super().setUp()
        self.state.player.power = 20

    def test_archer_bump_does_half_a_warrior_bump(self):
        m = self.monster(11, 10)
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            self.state.handle_action(Action.MOVE_E)
        w = _warrior_arena()
        w.player.power = 20
        wm = Monster(11, 10, 'goblin')
        wm.hp = wm.max_hp = 1000
        wm.defense = 0
        w.entities.append(wm)
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            w.handle_action(Action.MOVE_E)
        self.assertEqual(wm.max_hp - wm.hp, 20)
        self.assertEqual(m.max_hp - m.hp, 10)

    def test_adjacent_shot_is_half_a_two_tile_shot(self):
        near = self.monster(11, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(near.max_hp - near.hp, 10)
        self.state.entities.remove(near)
        far = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(far.max_hp - far.hp, 20)

    def test_pierced_far_monster_takes_full_damage(self):
        self.equip('longbow', 'uncommon', power=20)
        near, far = self.monster(11, 10), self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.hits()], [near, far])
        self.assertEqual([h.damage for h in self.state.hits()], [10, 20])

    def test_volley_at_adjacent_target_is_halved_per_arrow(self):
        self.equip('volley_bow', power=20)
        m = self.monster(11, 10)
        self.state.shoot_arrow(1, 0)
        hits = self.state.hits()
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits[0].damage, 10)
        factor = self.state.player.weapon.spread_factor
        for h in hits[1:]:
            self.assertLessEqual(h.damage, int(10 * factor) + 1)
        self.assertLess(m.max_hp - m.hp, 40)


class UsedUpArrowTests(ArcherArena):
    def test_hit_arrow_leaves_no_pile_and_miss_drops_at_stop_tile(self):
        self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(self.piles(), {})
        self.state.entities = [e for e in self.state.entities if not isinstance(e, Monster)]
        self.state.shoot_arrow(1, 0)
        self.assertEqual(self.piles(), {(48, 10): 1})

    def test_pierce_through_two_leaves_nothing(self):
        self.equip('longbow', 'uncommon')
        self.monster(12, 10)
        self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(self.piles(), {})

    def test_volley_leaves_a_pile_only_for_its_missing_aim_arrow(self):
        self.equip('volley_bow')
        self.state.shoot_arrow(1, 0)
        self.assertEqual(self.piles(), {(48, 10): 1})
        self.state.entities = [e for e in self.state.entities if not isinstance(e, ArrowPile)]
        self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(self.piles(), {})


if __name__ == '__main__':
    unittest.main()
