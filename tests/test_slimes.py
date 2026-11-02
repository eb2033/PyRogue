"""Slimes (plan §5): sizes by floor, stats off the orc, splitting on death,
no gold from split-offs, the large slime's slow walk, arrow resistance, and
the renderer's green squares."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - stdlib-only checkout
    pygame = None

from game import monster as monster_mod
from game.actions import Action
from game.gold import GoldPile
from game.monster import (
    GIVE_UP_AFTER,
    RANGED_RESIST,
    SLIME_KINDS,
    Monster,
    slime_kind_for_depth,
    tier_for_depth,
)
from game.spawn import SPAWN_RULES, rules_for_depth
from game.state import GameState
from game.tiles import FLOOR, STAIRS_DOWN, WALL

SIZES = ('slime_small', 'slime_medium', 'slime_large')


def arena(char_class='warrior', seed=3):
    """An open floor with the player at (10, 10) and nothing else on it."""
    state = GameState(50, 20, char_class=char_class, seed=seed)
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    state.shopkeeper = None
    state.shop = None
    p = state.player
    p.x, p.y = 10, 10
    p.hp = p.max_hp = 1000
    state.entities = [p]
    state.update_fov()
    return state


def walled(state, floor):
    """Turn every tile but `floor` (and the player's) into wall."""
    keep = set(floor) | {(state.player.x, state.player.y)}
    for y, row in enumerate(state.game_map):
        for x in range(len(row)):
            if (x, y) not in keep:
                row[x] = WALL
    state.update_fov()


def add(state, entity):
    state.entities.append(entity)
    state.update_fov()
    return entity


def kill(state, target):
    state.player.power = 10_000
    with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
        return state.attack(state.player, target)


def slimes(state):
    return [e for e in state.entities if isinstance(e, Monster) and e.alive]


class SizeByFloorTests(unittest.TestCase):
    def test_kind_for_each_band_boundary(self):
        for depth, kind in (
            (1, 'slime_small'),
            (5, 'slime_small'),
            (6, 'slime_medium'),
            (10, 'slime_medium'),
            (11, 'slime_large'),
            (30, 'slime_large'),
        ):
            self.assertEqual(slime_kind_for_depth(depth), kind, depth)

    def test_spawn_rules_match_the_slime_bands(self):
        for depth in (1, 5, 6, 10, 11, 12, 25):
            rules = [r for r in rules_for_depth(depth) if r.kind in SLIME_KINDS]
            self.assertEqual(len(rules), 1, depth)
            rule = rules[0]
            self.assertEqual(rule.kind, slime_kind_for_depth(depth), depth)
            self.assertEqual((rule.weight, rule.count(depth), rule.spread), (1, 1, True))
        rules = [r for r in SPAWN_RULES if r.kind in SLIME_KINDS]
        self.assertEqual(
            [(r.kind, r.min_depth, r.max_depth) for r in rules],
            [('slime_small', 1, 5), ('slime_medium', 6, 10), ('slime_large', 11, None)],
        )
        self.assertEqual([(r.min_depth, r.kind) for r in rules], list(monster_mod.SLIME_BANDS))
        self.assertEqual(sorted(r.kind for r in rules), sorted(SIZES))

    def test_slimes_spawn_on_floors_1_to_4(self):
        seen = set()
        for seed in range(30):
            state = GameState(50, 20, seed=seed)
            seen |= {m.kind for m in state.entities if isinstance(m, Monster)}
        self.assertIn('slime_small', seen)


class StatsTests(unittest.TestCase):
    def test_hp_is_the_orc_that_spawns_there_times_the_size_factor(self):
        for depth in (1, 6, 9, 11):
            orc = Monster(0, 0, 'orc', depth).max_hp
            for kind, mult in (('slime_small', 0.5), ('slime_medium', 0.8), ('slime_large', 1.2)):
                slime = Monster(0, 0, kind, depth)
                self.assertEqual(slime.max_hp, max(1, round(orc * mult)), (kind, depth))
                self.assertEqual(slime.hp, slime.max_hp)
        self.assertEqual(Monster(0, 0, 'slime_small', 1).max_hp, 11)  # orc 22
        self.assertEqual(Monster(0, 0, 'slime_medium', 6).max_hp, 21)  # orc 26
        self.assertEqual(Monster(0, 0, 'slime_large', 11).max_hp, 56)  # orc 47

    def test_power_is_base_plus_tier(self):
        for depth in (1, 4, 6, 11, 20):
            tier = tier_for_depth(depth)
            for kind, base in zip(SIZES, (2, 3, 4), strict=True):
                self.assertEqual(Monster(0, 0, kind, depth).power, base + tier, (kind, depth))

    def test_no_defence_and_readable_names(self):
        for kind, name in zip(SIZES, ('small slime', 'medium slime', 'large slime'), strict=True):
            slime = Monster(0, 0, kind, 3)
            self.assertEqual(getattr(slime, 'defense', 0), 0)
            self.assertEqual(slime.name, name)
            self.assertTrue(slime.drops_gold)


class SplitTests(unittest.TestCase):
    def test_a_medium_splits_into_two_smalls_beside_it(self):
        state = arena()
        state.depth = 7
        medium = add(state, Monster(11, 10, 'slime_medium', 7))
        hit = kill(state, medium)
        self.assertTrue(hit.killed)
        kids = slimes(state)
        self.assertEqual([k.kind for k in kids], ['slime_small', 'slime_small'])
        for kid in kids:
            self.assertEqual(abs(kid.x - 11) + abs(kid.y - 10), 1)
            self.assertEqual(kid.max_hp, Monster(0, 0, 'slime_small', 7).max_hp)
            self.assertEqual(kid.hp, kid.max_hp)
            self.assertFalse(kid.drops_gold)
        self.assertNotEqual((kids[0].x, kids[0].y), (kids[1].x, kids[1].y))
        self.assertNotIn((10, 10), {(k.x, k.y) for k in kids})  # not on the player

    def test_a_large_splits_into_two_mediums_which_split_again(self):
        state = arena()
        state.depth = 12
        large = add(state, Monster(13, 10, 'slime_large', 12))
        kill(state, large)
        kids = slimes(state)
        self.assertEqual([k.kind for k in kids], ['slime_medium', 'slime_medium'])
        kill(state, kids[0])
        self.assertEqual(
            sorted(k.kind for k in slimes(state)),
            ['slime_medium', 'slime_small', 'slime_small'],
        )

    def test_a_small_dies_cleanly(self):
        state = arena()
        small = add(state, Monster(11, 10, 'slime_small', 1))
        kill(state, small)
        self.assertEqual(slimes(state), [])

    def test_splits_use_the_floors_depth(self):
        state = arena()
        state.depth = 9
        medium = add(state, Monster(12, 10, 'slime_medium', 6))
        kill(state, medium)
        for kid in slimes(state):
            self.assertEqual(kid.max_hp, Monster(0, 0, 'slime_small', 9).max_hp)
            self.assertEqual(kid.power, Monster(0, 0, 'slime_small', 9).power)

    def test_split_placement_in_a_corridor(self):
        # The slime at (5, 5), the player west of it, floor only where listed.
        cases = {
            # one free orthogonal neighbour first, then (7, 5) two tiles off
            'orthogonal first then within two': (
                'slime_medium',
                6,
                [(5, 5), (6, 5), (7, 5), (8, 5)],
                [(6, 5), (7, 5)],
            ),
            'fewer when boxed in': ('slime_large', 11, [(5, 5), (6, 5)], [(6, 5)]),
            'none when there is no room': ('slime_medium', 6, [(5, 5)], []),
            # the far side of a one-tile wall is within two tiles, but only through it
            'never through a wall': (
                'slime_medium',
                6,
                [(5, 5), (7, 4), (7, 5), (7, 6)],
                [],
            ),
        }
        for name, (kind, depth, floor, expected) in cases.items():
            with self.subTest(name):
                state = arena()
                state.player.x, state.player.y = 4, 5
                walled(state, floor)
                slime = add(state, Monster(5, 5, kind, depth))
                kill(state, slime)
                if name == 'fewer when boxed in':
                    self.assertEqual(
                        [(k.x, k.y, k.kind) for k in slimes(state)], [(6, 5, 'slime_medium')]
                    )
                else:
                    self.assertEqual(sorted((k.x, k.y) for k in slimes(state)), expected)

    def test_never_on_a_creature_the_stairs_or_a_pile(self):
        state = arena()
        state.player.x, state.player.y = 4, 5
        walled(state, [(5, 5), (6, 5), (5, 4), (5, 6), (7, 5)])
        goblin = add(state, Monster(6, 5, 'goblin'))
        state.game_map[4][5] = STAIRS_DOWN
        add(state, GoldPile(5, 6, 3))
        slime = add(state, Monster(5, 5, 'slime_medium', 6))
        kill(state, slime)
        kids = [m for m in slimes(state) if m is not goblin]
        # (7, 5) is two tiles off but only reachable through the goblin's
        # tile, which is walkable: it still counts as within reach.
        self.assertEqual([(k.x, k.y) for k in kids], [(7, 5)])

    def test_splits_drop_no_gold_but_a_spawned_slime_does(self):
        state = arena()
        medium = add(state, Monster(11, 10, 'slime_medium', 6))
        kill(state, medium)
        piles = [e for e in state.entities if isinstance(e, GoldPile)]
        self.assertEqual([(p.x, p.y) for p in piles], [(11, 10)])
        gold = piles[0].amount
        for kid in slimes(state):
            kill(state, kid)
        piles = [e for e in state.entities if isinstance(e, GoldPile)]
        self.assertEqual([(p.x, p.y, p.amount) for p in piles], [(11, 10, gold)])

    def test_the_kill_hit_is_the_parents_and_splits_record_no_hit(self):
        state = arena()
        medium = add(state, Monster(11, 10, 'slime_medium', 6))
        kill(state, medium)
        hits = state.hits()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0].defender, medium)
        self.assertTrue(hits[0].killed)
        for kid in slimes(state):
            self.assertIs(kid.split_from, medium)

    def test_splits_join_the_next_rounds_queue(self):
        state = arena()
        medium = add(state, Monster(11, 10, 'slime_medium', 6))
        medium.hp = 1
        state.player.power = 10_000
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            self.assertTrue(state.handle_action(Action.MOVE_E))  # bump: it dies
        kids = slimes(state)
        self.assertEqual(len(kids), 2)
        queued = state.controller.pending_monsters
        self.assertFalse(any(k in queued for k in kids))
        hp = state.player.hp
        state.end_turn()  # this round: the splits don't act
        self.assertEqual(state.player.hp, hp)
        # Next round they do.
        state.handle_action(Action.WAIT)
        self.assertTrue(all(k in state.controller.pending_monsters for k in kids))

    def test_a_split_in_the_monster_phase_acts_next_round(self):
        # A riposte kills a medium during the monsters' half: its splits act
        # in the next round like anything else.
        state = arena()
        medium = add(state, Monster(11, 10, 'slime_medium', 6))
        medium.hp = 1
        state.parry_armed = True
        state.player.power = 10_000
        state.end_turn()
        kids = slimes(state)
        self.assertEqual(len(kids), 2)
        state.handle_action(Action.WAIT)
        self.assertTrue(all(k in state.controller.pending_monsters for k in kids))


class LargeSlimeWalkTests(unittest.TestCase):
    def chase(self, kind, turns):
        state = arena()
        slime = Monster(16, 10, kind, 11)
        moves = 0
        for _ in range(turns):
            before = (slime.x, slime.y)
            slime.take_turn(state.player, state.game_map, sees_player=True, rng=state.rng)
            moves += (slime.x, slime.y) != before
        return slime, moves

    def test_large_moves_once_every_two_turns_others_every_turn_large_attacks_every_turn(self):
        _, moves = self.chase('slime_large', 6)
        self.assertEqual(moves, 3)
        for kind in ('slime_small', 'slime_medium'):
            _, moves = self.chase(kind, 4)
            self.assertEqual(moves, 4, kind)
        state = arena()
        slime = Monster(11, 10, 'slime_large', 11)
        for _ in range(4):
            self.assertEqual(
                slime.take_turn(state.player, state.game_map, rng=state.rng), 'attack'
            )

    def test_resting_does_not_upset_the_give_up_count(self):
        state = arena()
        slime = Monster(16, 10, 'slime_large', 11)
        slime.take_turn(state.player, state.game_map, sees_player=True, rng=state.rng)
        self.assertTrue(slime.chasing)
        for turn in range(1, GIVE_UP_AFTER + 1):
            slime.take_turn(state.player, state.game_map, sees_player=False, rng=state.rng)
            if turn < GIVE_UP_AFTER:
                self.assertTrue(slime.chasing, turn)
                self.assertEqual(slime.lost_sight, turn)
        self.assertFalse(slime.chasing)
        self.assertEqual(slime.lost_sight, 0)


class ArrowResistTests(unittest.TestCase):
    def shot(self, kind, x):
        state = arena(char_class='archer', seed=5)
        target = add(state, Monster(x, 10, kind, 1))
        target.hp = target.max_hp = 1000
        state.player.power = 20
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            state.shoot_arrow(1, 0)
        return 1000 - target.hp

    def test_every_slime_resists_arrows_by_30_percent(self):
        for kind in SIZES:
            self.assertEqual(RANGED_RESIST[kind], 0.7)
        self.assertEqual(self.shot('goblin', 13), 20)
        for kind in SIZES:
            self.assertEqual(self.shot(kind, 13), 14, kind)
        self.assertEqual(set(RANGED_RESIST), set(SLIME_KINDS))
        self.assertIs(monster_mod.RANGED_RESIST, RANGED_RESIST)

    def test_stacks_with_point_blank(self):
        self.assertEqual(self.shot('goblin', 11), 10)
        for kind in SIZES:
            self.assertEqual(self.shot(kind, 11), 7, kind)

    def test_melee_is_not_resisted(self):
        state = arena()
        slime = add(state, Monster(11, 10, 'slime_small', 1))
        slime.hp = slime.max_hp = 1000
        state.player.power = 20
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            state.handle_action(Action.MOVE_E)
        self.assertEqual(1000 - slime.hp, 20)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class SlimeLookTests(unittest.TestCase):
    """Each slime is a green square centred in its cell, sized by kind."""

    def renderer(self, tiles):
        from game.paths import resource_path
        from render import camera
        from render.pygame_render import PygameRenderer
        from render.tileset import Tileset

        tileset = Tileset(resource_path('assets')) if tiles else None
        r = PygameRenderer(40, 20, tileset=tileset, combat_zoom=False)
        r._set_mode((1600, 900), pygame.RESIZABLE)
        r._relayout()
        r.director = camera.Director(zoom=False)
        r.zoom_ms = r.follow_ms = 0
        self.addCleanup(r.close)
        return r

    def check(self, tiles):
        from render.pygame_render import SLIME_CELL_FRACTION, SLIME_COLORS

        r = self.renderer(tiles)
        state = arena()
        for kind, (x, y) in zip(SIZES, ((12, 10), (14, 10), (10, 13)), strict=True):
            add(state, Monster(x, y, kind, 11))
        r.draw(state)
        screen = r.canvas.surface
        for (kind, frac), m in zip(SLIME_CELL_FRACTION.items(), slimes(state), strict=True):
            cell = r._map_cell_rect(m.x, m.y)
            side = round(min(cell.size) * frac)
            centre_row = [
                tuple(screen.get_at((x, cell.centery)))[:3] for x in range(cell.left, cell.right)
            ]
            green = sum(1 for c in centre_row if c in SLIME_COLORS)
            self.assertAlmostEqual(green, side, delta=2, msg=(kind, tiles))
            self.assertIn(tuple(screen.get_at(cell.center))[:3], SLIME_COLORS)
            # The cell's corner pixel is not slime.
            self.assertNotIn(tuple(screen.get_at((cell.left, cell.bottom - 1)))[:3], SLIME_COLORS)
        fracs = list(SLIME_CELL_FRACTION.values())
        self.assertEqual(fracs, sorted(fracs))
        self.assertEqual(list(SLIME_CELL_FRACTION), list(SIZES))

    def test_green_squares_in_tile_and_glyph_mode(self):
        for tiles in (True, False):
            with self.subTest(tiles=tiles):
                self.check(tiles=tiles)

    def test_a_split_killed_by_the_same_shot_waits_for_its_parents_blow(self):
        # A piercing arrow kills a medium and then the fresh small behind it:
        # before the parent's impact no small slime is drawn, not even as the
        # ghost of the second hit; after it, the small is (until it is struck).
        r = self.renderer(tiles=True)
        state = arena(char_class='archer', seed=1)
        state.player.weapon.pierce = 3
        medium = add(state, Monster(12, 10, 'slime_medium', 6))
        medium.hp = 1
        state.game_map[9][12] = WALL  # the only room for a split: behind it
        state.game_map[11][12] = WALL
        state.update_fov()
        state.player.power = 10_000
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            state.handle_action(Action.SHOOT_E)
        hits = state.hits()
        self.assertIs(hits[0].defender, medium)
        killed_kids = [h for h in hits[1:] if getattr(h.defender, 'split_from', None) is medium]
        self.assertTrue(killed_kids and all(h.killed for h in killed_kids))
        drawn = r._before_hits(state, state.visible_entities(), hits)
        kinds = [e.kind for e in drawn if isinstance(e, Monster)]
        self.assertNotIn('slime_small', kinds)
        self.assertIn('slime_medium', kinds)
        drawn = r._before_hits(state, state.visible_entities(), hits[1:])
        self.assertIn('slime_small', [e.kind for e in drawn if isinstance(e, Monster)])

    def test_splits_appear_only_once_the_killing_blow_lands(self):
        r = self.renderer(tiles=True)
        state = arena()
        medium = add(state, Monster(11, 10, 'slime_medium', 6))
        hit = kill(state, medium)
        drawn = r._before_hits(state, state.visible_entities(), [hit])
        self.assertFalse([e for e in drawn if getattr(e, 'split_from', None) is medium])
        self.assertTrue(any(e.kind == 'slime_medium' for e in drawn if isinstance(e, Monster)))


if __name__ == '__main__':
    unittest.main()
