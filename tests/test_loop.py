"""The main loop's monster-phase driving, exercised with a fake renderer.

main.resolve_monster_phase is what makes the monster half of a round
*visible*: it draws the world before each monster acts and holds the frame
afterwards. That is pure logic once the renderer is a stand-in, so it can be
tested without a window.
"""

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.item import Item
from game.monster import Monster
from game.state import GameState
from main import resolve_monster_phase, resolve_player_strikes
from render.base import Renderer

DELAY = 50


class RecordingRenderer(Renderer):
    """Records the frame sequence instead of drawing it."""

    def __init__(self):
        self.events = []

    def draw(self, state):
        self.events.append(('draw', state.player.hp, list(state.messages)))

    def pause(self, ms):
        self.events.append(('pause', ms))

    def draws(self):
        return [e for e in self.events if e[0] == 'draw']

    def pauses(self):
        return [e for e in self.events if e[0] == 'pause']


class HpRecordingRenderer(RecordingRenderer):
    """Also records one monster's HP and the damage of the player's hits
    so far, as each frame is drawn."""

    def __init__(self, monster):
        super().__init__()
        self.monster = monster

    def draw(self, state):
        damages = [h.damage for h in state.combat_events if h.attacker is state.player]
        self.events.append(
            ('draw', state.player.hp, list(state.messages), self.monster.hp, damages)
        )


def run_one_action(renderer, state, action, delay_ms):
    """One pass of main.run's loop body, minus the input."""
    state.handle_action(action)
    resolve_player_strikes(renderer, state, delay_ms)
    resolve_monster_phase(renderer, state, delay_ms)


def state_with_monsters(offsets, player_hp=200, monster_power=2, monster_hp=200):
    random.seed(40)
    state = GameState(50, 20)
    state.player.hp = state.player.max_hp = player_hp
    state.entities = [state.player]
    for dx, dy in offsets:
        m = Monster(state.player.x + dx, state.player.y + dy, 'goblin')
        m.power, m.hp, m.max_hp = monster_power, monster_hp, monster_hp
        state.entities.append(m)
    return state


class MonsterPhaseFramesTests(unittest.TestCase):
    def test_player_action_is_drawn_before_the_monster_answers(self):
        """The whole point of the split: you see your own blow land, then the
        reply -- not both at once."""
        state = state_with_monsters([(1, 0)])
        renderer = RecordingRenderer()

        state.handle_action('move_e')  # bump-attack
        hp_after_player_half = state.player.hp
        messages_after_player_half = list(state.messages)

        resolve_monster_phase(renderer, state, DELAY)

        first = renderer.draws()[0]
        self.assertEqual(
            first[1], hp_after_player_half, "first frame already showed the monster's reply"
        )
        self.assertEqual(first[2], messages_after_player_half)
        self.assertIn('You hit', ' '.join(first[2]))
        self.assertNotIn('hits you', ' '.join(first[2]))
        # ...and the reply does land, just afterwards.
        self.assertLess(state.player.hp, hp_after_player_half)

    def test_one_held_frame_per_visible_monster(self):
        state = state_with_monsters([(1, 0), (-1, 0), (0, 1)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, DELAY)
        self.assertEqual(len(renderer.pauses()), 3)
        self.assertEqual(renderer.pauses()[0], ('pause', DELAY))

    def test_each_frame_shows_one_more_blow_than_the_last(self):
        state = state_with_monsters([(1, 0), (-1, 0), (0, 1)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, DELAY)
        hits = [sum('hits you' in m for m in draw[2]) for draw in renderer.draws()]
        self.assertEqual(hits, [0, 1, 2])  # strictly one at a time

    def test_quiet_round_costs_no_held_frames(self):
        """Walking an empty dungeon must stay as responsive as before."""
        state = state_with_monsters([])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, DELAY)
        self.assertEqual(renderer.pauses(), [])

    def test_phase_drains_and_leaves_nothing_pending(self):
        state = state_with_monsters([(1, 0), (-1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, DELAY)
        self.assertFalse(state.monster_phase_pending())

    def test_death_cuts_the_frame_sequence_short(self):
        state = state_with_monsters([(1, 0), (-1, 0), (0, 1)], player_hp=2)
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, DELAY)
        self.assertTrue(state.game_over)
        self.assertEqual(len(renderer.pauses()), 1)  # only the killing blow

    def test_rapier_second_strike_waits_for_the_first_hit_to_be_drawn(self):
        """Attack -> hit 1 drawn (its damage only) -> hit 2 -> monsters."""
        state = state_with_monsters([(1, 0)])
        state.player.weapon = Item(0, 0, 'rapier', 'epic')
        goblin = state.entities[1]
        renderer = HpRecordingRenderer(goblin)

        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.0):
            run_one_action(renderer, state, 'move_e', DELAY)

        player_hits = [h for h in state.combat_events if h.attacker is state.player]
        self.assertEqual(len(player_hits), 2)
        first, second = (h.damage for h in player_hits)
        frames = renderer.draws()
        # Frame 1: strike 1 only -- one hit, the goblin down by its damage.
        self.assertEqual(frames[0][3], 200 - first)
        self.assertEqual(frames[0][4], [first])
        # The first hit's beat is held before strike 2 is rolled.
        self.assertEqual(renderer.events[1], ('pause', DELAY))
        # Frame 2: both strikes, and the goblin hasn't answered yet.
        self.assertEqual(frames[1][3], 200 - first - second)
        self.assertEqual(frames[1][4], [first, second])
        self.assertNotIn('hits you', ' '.join(frames[1][2]))
        # ...and the goblin does answer, after both strikes.
        attackers = [h.attacker for h in state.combat_events]
        self.assertEqual(attackers, [state.player, state.player, goblin])
        self.assertEqual(state.turn, 1)

    def test_rapier_kill_on_the_first_strike_holds_no_extra_frame(self):
        state = state_with_monsters([(1, 0)], monster_hp=1)
        state.player.weapon = Item(0, 0, 'rapier', 'epic')
        renderer = RecordingRenderer()
        run_one_action(renderer, state, 'move_e', DELAY)
        self.assertEqual(renderer.events, [])  # nothing left to step
        self.assertEqual(len(state.combat_events), 1)

    def test_warrior_bump_has_no_strike_step(self):
        state = state_with_monsters([(1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('move_e')
        resolve_player_strikes(renderer, state, DELAY)
        self.assertEqual(renderer.events, [])
        self.assertTrue(state.monster_phase_pending())

    def test_zero_delay_still_draws_every_step(self):
        """TURN_DELAY_MS=0 opts out of the waiting, not the sequencing."""
        state = state_with_monsters([(1, 0), (-1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        resolve_monster_phase(renderer, state, 0)
        self.assertEqual(len(renderer.draws()), 2)
        self.assertEqual(renderer.pauses(), [('pause', 0), ('pause', 0)])


if __name__ == '__main__':
    unittest.main()
