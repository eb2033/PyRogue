"""The fencing sword (warrior) and the hand crossbow (archer).

The fencing sword's parry riposte hits harder than the usual crit
multiplier (WEAPON_EFFECTS['fencing_sword']['riposte_mult']). The hand
crossbow has no reload; its effect is the hop-shot: a hop directly away from
an orthogonally adjacent monster doesn't end the turn, so a shot right after
it lands before the monsters answer (they act once, after both), and any
other action first resolves the hop's deferred monster half.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pygame
except ImportError:  # pragma: no cover - stdlib-only checkout
    pygame = None

import main
from game.combat import Shot
from game.fight import CRIT_MULTIPLIER
from game.item import (
    ARCHER_WEAPONS,
    CLASS_WEAPONS,
    GEAR_STATS,
    ITEM_CHARS,
    RARITIES,
    WARRIOR_WEAPONS,
    WEAPON_DAMAGE_OFFSET,
    Item,
    gear_power,
)
from game.monster import Monster
from game.moves import HOP_COOLDOWN
from game.state import GameState
from game.tiles import FLOOR, WALL
from render.base import Action, Renderer
from render.choice import stat_text

FENCING_RIPOSTE = {'common': 2.0, 'uncommon': 2.15, 'rare': 2.3, 'epic': 2.5}


def _open_arena(char_class):
    state = GameState(20, 20, char_class=char_class, seed=0)
    # The floor's map keeps its size (the window draws all of it): walled
    # off, with an open 18x18 room in the corner.
    for y, row in enumerate(state.game_map):
        for x in range(len(row)):
            row[x] = FLOOR if 1 <= x <= 18 and 1 <= y <= 18 else WALL
    p = state.player
    p.x, p.y = 10, 10
    p.hp = p.max_hp = 1000
    p.defense = 0
    state.entities = [p]
    return state


def _monster(state, x, y, power=1, hp=1000):
    mon = Monster(x, y, 'goblin')
    mon.hp = mon.max_hp = hp
    mon.power = power
    mon.defense = 0
    state.entities.append(mon)
    return mon


def _equip(state, kind, rarity='common'):
    Item(0, 0, kind, rarity).apply(state.player, state.log)


class WeaponDataTests(unittest.TestCase):
    def test_both_join_their_class_list_with_offset_minus_one(self):
        self.assertIn('fencing_sword', WARRIOR_WEAPONS)
        self.assertIn('hand_crossbow', ARCHER_WEAPONS)
        self.assertNotIn('fencing_sword', CLASS_WEAPONS['archer'])
        self.assertNotIn('hand_crossbow', CLASS_WEAPONS['warrior'])
        for kind in ('fencing_sword', 'hand_crossbow'):
            self.assertEqual(WEAPON_DAMAGE_OFFSET[kind], -1)
            self.assertEqual(ITEM_CHARS[kind], '/')
            for rarity in RARITIES:
                item = Item(0, 0, kind, rarity)
                self.assertTrue(item.name)
                self.assertEqual(item.bonus, GEAR_STATS['weapon'][rarity] - 1)

    def test_effects(self):
        for rarity, mult in FENCING_RIPOSTE.items():
            self.assertEqual(Item(0, 0, 'fencing_sword', rarity).riposte_mult, mult)
            self.assertTrue(Item(0, 0, 'hand_crossbow', rarity).hop_shot)
            self.assertEqual(Item(0, 0, 'hand_crossbow', rarity).reload, 0)
        self.assertFalse(Item(0, 0, 'longbow', 'epic').hop_shot)
        self.assertFalse(Item(0, 0, 'rapier', 'epic').riposte_mult)
        # and the choice cards name them
        self.assertIn('riposte x2.5', stat_text(Item(0, 0, 'fencing_sword', 'epic')))
        self.assertIn('hop-shot', stat_text(Item(0, 0, 'hand_crossbow', 'common')))


class FencingRiposteTests(unittest.TestCase):
    def _parried(self, kind, rarity):
        """A warrior with `kind` arms a parry; the adjacent goblin's blow is
        riposted. Returns (riposte Hit, the player's power)."""
        state = _open_arena('warrior')
        _equip(state, kind, rarity)
        state.player.base_power = 20
        state.player.power = gear_power(state.player)
        _monster(state, 9, 10, power=5)
        state.update_fov()
        self.assertTrue(state.handle_action(Action.ABILITY))
        state.end_turn()
        (hit,) = state.hits()
        self.assertIs(hit.attacker, state.player)
        self.assertFalse(hit.crit)
        return hit, state.player.power

    def test_fencing_riposte_multiple_at_each_rarity(self):
        for rarity, mult in FENCING_RIPOSTE.items():
            with self.subTest(rarity=rarity):
                # Defence 0: the riposte is raw power x the multiplier,
                # rounded either way by the seeded roll.
                hit, power = self._parried('fencing_sword', rarity)
                raw = power * mult
                self.assertIn(hit.damage, (int(raw), int(raw) + (raw % 1 > 0)))

    def test_fencing_riposte_exact_with_rounding_pinned(self):
        for rarity, mult in FENCING_RIPOSTE.items():
            for roll, up in ((0.0, True), (0.999, False)):
                with self.subTest(rarity=rarity, roll=roll):
                    state = _open_arena('warrior')
                    _equip(state, 'fencing_sword', rarity)
                    state.player.base_power = 21
                    state.player.power = gear_power(state.player)
                    _monster(state, 9, 10, power=5)
                    state.update_fov()
                    self.enterContext(mock.patch.object(state.rng, 'random', return_value=roll))
                    state.handle_action(Action.ABILITY)
                    state.end_turn()
                    (hit,) = state.hits()
                    raw = state.player.power * mult
                    expected = int(raw) + (1 if up and raw % 1 > 1e-9 else 0)
                    self.assertEqual(hit.damage, expected)

    def test_other_weapons_riposte_is_unchanged(self):
        for kind in ['weapon'] + [k for k in WARRIOR_WEAPONS if k != 'fencing_sword']:
            with self.subTest(kind=kind):
                state = _open_arena('warrior')
                _equip(state, kind, 'epic')
                state.player.base_power = 20
                state.player.power = gear_power(state.player)
                _monster(state, 9, 10, power=5)
                state.update_fov()
                self.enterContext(mock.patch.object(state.rng, 'random', return_value=0.0))
                state.handle_action(Action.ABILITY)
                state.end_turn()
                hits = [h for h in state.hits() if h.attacker is state.player]
                raw = state.player.power * CRIT_MULTIPLIER
                expected = int(raw) + (1 if raw % 1 else 0)
                self.assertEqual(hits[0].damage, expected)


class HandCrossbowHopShotTests(unittest.TestCase):
    """An archer at (10, 10) with a hand crossbow and a tough goblin west of
    her, adjacent. Hopping east moves her directly away from it."""

    def _arena(self, kind='hand_crossbow', monster_at=(9, 10)):
        state = _open_arena('archer')
        _equip(state, kind)
        mon = _monster(state, *monster_at) if monster_at else None
        state.update_fov()
        return state, mon

    def hop(self, state, direction=Action.MOVE_E):
        self.assertFalse(state.handle_action(Action.ABILITY))
        return state.handle_action(direction)

    def test_hop_away_then_shoot_monsters_act_once_after_the_shot(self):
        state, mon = self._arena()
        assert mon is not None
        self.assertTrue(self.hop(state))
        self.assertEqual((state.player.x, state.player.y), (12, 10))
        # The hop ended no turn: no monster half yet, and end_turn runs none.
        self.assertFalse(state.monster_phase_pending())
        state.end_turn()
        self.assertEqual((mon.x, mon.y), (9, 10))
        hp = mon.hp
        self.assertTrue(state.handle_action(Action.SHOOT_W))
        self.assertLess(mon.hp, hp)  # the shot landed before it moved
        self.assertEqual((mon.x, mon.y), (9, 10))
        self.assertTrue(state.monster_phase_pending())
        state.end_turn()
        self.assertEqual((mon.x, mon.y), (10, 10))  # exactly one step
        # And the next turn is an ordinary one.
        state.handle_action(Action.WAIT)
        state.end_turn()
        self.assertEqual((mon.x, mon.y), (11, 10))

    def test_hop_away_then_walk_monsters_act_after_the_hop_and_after_the_walk(self):
        state, mon = self._arena()
        assert mon is not None
        self.hop(state)
        self.assertEqual((mon.x, mon.y), (9, 10))
        self.assertTrue(state.handle_action(Action.MOVE_S))
        # The hop's deferred half resolved before the walk ...
        self.assertEqual((mon.x, mon.y), (10, 10))
        self.assertEqual((state.player.x, state.player.y), (12, 11))
        # ... and the walk's own half is queued as usual.
        self.assertTrue(state.monster_phase_pending())
        state.end_turn()
        self.assertEqual(abs(mon.x - 10) + abs(mon.y - 10), 1)

    def test_hop_away_then_a_no_turn_action_still_resolves_the_hop(self):
        state, mon = self._arena()
        assert mon is not None
        self.hop(state)
        state.handle_action(Action.CHOOSE_1)  # means nothing here: no turn
        state.end_turn()
        self.assertEqual((mon.x, mon.y), (10, 10))  # the hop's half, once
        state.handle_action(Action.SHOOT_W)  # an ordinary shot now
        state.end_turn()
        self.assertEqual(abs(mon.x - 10) + abs(mon.y - 10), 1)

    def test_a_refused_shot_after_the_hop_resolves_the_hop(self):
        state, mon = self._arena()
        assert mon is not None
        self.hop(state)
        state.player.quiver = 0
        self.assertFalse(state.handle_action(Action.SHOOT_W))
        self.assertEqual(state.messages.count('No arrows left.'), 1)  # logged once
        state.end_turn()
        self.assertEqual((mon.x, mon.y), (10, 10))

    def _deadly_hop(self):
        """A hop-shot hop that lands the archer (1 HP) next to a killer at
        (12, 11): the hop's owed monster half will kill her."""
        state, _ = self._arena()
        killer = _monster(state, 12, 11, power=5000)
        state.player.hp = 1
        self.enterContext(mock.patch.object(state.rng, 'random', return_value=0.99))
        self.hop(state)
        self.assertEqual((state.player.x, state.player.y), (12, 10))
        self.assertTrue(state.player.is_adjacent(killer))
        return state

    def test_q_after_a_deadly_hop_shows_the_death_screen_and_does_not_quit(self):
        state = self._deadly_hop()
        self.assertFalse(state.handle_action(Action.ABILITY))
        self.assertTrue(state.game_over)
        self.assertTrue(state.running)  # the death screen is still to come
        self.assertFalse(state.restart_requested)
        # On the death screen, q quits as usual.
        self.assertFalse(state.handle_action(Action.ABILITY))
        self.assertFalse(state.running)

    def test_any_action_after_a_deadly_hop_does_nothing_more(self):
        for action in (Action.MOVE_N, Action.WAIT, Action.SKIP, Action.DRINK):
            with self.subTest(action=action):
                state = self._deadly_hop()
                self.assertFalse(state.handle_action(action))
                self.assertTrue(state.game_over)
                self.assertTrue(state.running)
                self.assertEqual((state.player.x, state.player.y), (12, 10))

    def test_a_hop_not_away_from_an_adjacent_monster_is_ordinary(self):
        for monster_at, direction in (
            ((9, 10), Action.MOVE_N),  # adjacent, but the hop is sideways
            ((8, 10), Action.MOVE_E),  # straight behind, but not adjacent
            (None, Action.MOVE_E),  # nobody near
        ):
            with self.subTest(monster_at=monster_at, direction=direction):
                state, _ = self._arena(monster_at=monster_at)
                self.assertTrue(self.hop(state, direction))
                if monster_at:
                    self.assertTrue(state.monster_phase_pending())

    def test_other_bows_hops_are_unchanged(self):
        for kind in [k for k in ARCHER_WEAPONS if k != 'hand_crossbow']:
            with self.subTest(kind=kind):
                state, mon = self._arena(kind)
                assert mon is not None
                self.hop(state)
                self.assertTrue(state.monster_phase_pending())
                state.end_turn()
                self.assertEqual((mon.x, mon.y), (10, 10))

    def test_the_hop_keeps_its_cooldown(self):
        state, _ = self._arena()
        self.hop(state)
        turn = state.turn
        self.assertEqual(state.last_hop_turn, turn)
        state.handle_action(Action.SHOOT_W)
        state.end_turn()
        self.assertFalse(state.handle_action(Action.ABILITY))
        self.assertFalse(state.hop_primed)
        self.assertTrue(state.messages[-1].startswith('Hop recovering'))
        for _ in range(HOP_COOLDOWN):
            state.handle_action(Action.WAIT)
            state.end_turn()
        state.handle_action(Action.ABILITY)
        self.assertTrue(state.hop_primed)

    def test_the_combo_shot_consumes_an_arrow_and_hop_plus_shot_is_one_turn(self):
        state, _ = self._arena()
        quiver = state.player.quiver
        assert quiver is not None
        turn = state.turn
        self.hop(state)
        self.assertEqual(state.player.quiver, quiver)
        state.handle_action(Action.SHOOT_W)
        self.assertEqual(state.player.quiver, quiver - 1)
        self.assertEqual(len(state.events_of(Shot)), 1)
        state.end_turn()
        self.assertEqual(state.turn, turn + 1)

    def test_no_reload(self):
        state, _ = self._arena(monster_at=None)
        self.assertTrue(state.handle_action(Action.SHOOT_W))
        state.end_turn()
        self.assertTrue(state.handle_action(Action.SHOOT_W))


class RecordingRenderer(Renderer):
    """main.run's renderer: scripted actions, a log of frames."""

    def __init__(self, actions, on_draw=None):
        self.actions = list(actions)
        self.frames = []
        self.on_draw = on_draw

    def draw(self, state):
        self.frames.append(('draw', state.player.x, state.monster_phase_pending()))
        if self.on_draw is not None:
            self.on_draw(state)

    def pause(self, ms):
        self.frames.append(('pause', ms))

    def get_action(self):
        return self.actions.pop(0) if self.actions else Action.QUIT


class MainLoopTests(unittest.TestCase):
    def test_q_after_a_deadly_hop_through_main_run_reaches_the_death_screen(self):
        test = HandCrossbowHopShotTests()
        state, _ = test._arena()
        _monster(state, 12, 11, power=5000)
        state.player.hp = 1
        with mock.patch.object(state.rng, 'random', return_value=0.99):
            renderer = RecordingRenderer([Action.ABILITY, Action.MOVE_E, Action.ABILITY])
            main.run(renderer, state, delay_ms=0)
        # Q died with the hop's half; the loop went on and drew the death
        # screen; the script's QUIT (not that Q) ended the run.
        self.assertTrue(state.game_over)
        self.assertFalse(state.restart_requested)
        self.assertEqual(renderer.actions, [])
        self.assertGreaterEqual(len([f for f in renderer.frames if f[0] == 'draw']), 4)

    def test_a_scripted_run_through_the_combo(self):
        state, mon = HandCrossbowHopShotTests()._arena()
        assert mon is not None
        positions = []
        renderer = RecordingRenderer(
            [Action.ABILITY, Action.MOVE_E, Action.SHOOT_W, Action.ABILITY, Action.MOVE_E]
            + [Action.MOVE_N, Action.WAIT],
            on_draw=lambda s: positions.append(((s.player.x, s.player.y), (mon.x, mon.y))),
        )
        main.run(renderer, state, delay_ms=0)
        # The frame after the hop: the archer has moved, no monster half is
        # queued, and the next draw is after the shot's (pending) half.
        hop_frame = positions.index(((12, 10), (9, 10)))
        self.assertEqual(renderer.frames[hop_frame], ('draw', 12, False))
        self.assertFalse(state.running)
        # After the hop the frame shows the archer moved and the goblin not.
        self.assertIn(((12, 10), (9, 10)), positions)
        # The shot's half moved the goblin one step, never two in a round.
        xs = [m for _, m in positions]
        for a, b in zip(xs, xs[1:]):
            self.assertLessEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]), 1)
        self.assertFalse(state.game_over)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PygameMainLoopTests(unittest.TestCase):
    def test_the_window_draws_through_the_combo(self):
        from render.pygame_render import PygameRenderer

        renderer = PygameRenderer(40, 20)
        try:
            state, mon = HandCrossbowHopShotTests()._arena()
            assert mon is not None
            actions = [
                Action.ABILITY,
                Action.MOVE_E,
                Action.SHOOT_W,
                Action.ABILITY,
                Action.MOVE_E,
                Action.MOVE_S,
                Action.WAIT,
            ]
            renderer.get_action = lambda: actions.pop(0) if actions else Action.QUIT
            main.run(renderer, state, delay_ms=0)
            self.assertFalse(state.running)
            self.assertEqual(actions, [])
        finally:
            renderer.close()


if __name__ == '__main__':
    unittest.main()
