"""Headless tests for the browser build (web/): the async loop and WebRenderer.

web/loop.py is main.py's loop with `await`; the first suite mirrors
tests/test_loop.py against an async recording renderer (no pygame needed). The
second drives a real WebRenderer on SDL's dummy video driver with posted
events, and checks the browser's rules: nothing may call pygame.event.wait or
pygame.time.wait (they freeze the tab), nothing may touch pygame.Window or
toggle_fullscreen (they kill the app), and every wait must yield to the event
loop. Skipped cleanly without pygame.
"""

import asyncio
import os
import random
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

from game.item import Item
from game.monster import Monster
from game.state import GameState
from render.base import Action

WIDTH, HEIGHT = 40, 20
DELAY = 50


def run(coro, timeout=8):
    """Run a coroutine to completion; a hung wait fails instead of hanging."""
    return asyncio.run(asyncio.wait_for(coro, timeout))


# -- the loop, against a recording renderer -----------------------------------


class RecordingRenderer:
    """Async stand-in for the renderer: records the frame sequence."""

    def __init__(self, monster=None):
        self.events = []
        self.monster = monster

    async def draw(self, state):
        if self.monster is None:
            self.events.append(('draw', state.player.hp, list(state.messages)))
        else:
            damages = [h.damage for h in state.combat_events if h.attacker is state.player]
            self.events.append(
                ('draw', state.player.hp, list(state.messages), self.monster.hp, damages)
            )

    async def pause(self, ms):
        self.events.append(('pause', ms))

    def draws(self):
        return [e for e in self.events if e[0] == 'draw']

    def pauses(self):
        return [e for e in self.events if e[0] == 'pause']


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


class AsyncLoopTests(unittest.TestCase):
    def setUp(self):
        import web.loop

        self.loop = web.loop

    def phase(self, renderer, state, delay=DELAY):
        run(self.loop.resolve_monster_phase(renderer, state, delay))

    def one_action(self, renderer, state, action, delay=DELAY):
        state.handle_action(action)
        run(self.loop.resolve_player_strikes(renderer, state, delay))
        run(self.loop.resolve_monster_phase(renderer, state, delay))

    def test_player_action_is_drawn_before_the_monster_answers(self):
        state = state_with_monsters([(1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('move_e')
        hp_after_player_half = state.player.hp
        self.phase(renderer, state)
        first = renderer.draws()[0]
        self.assertEqual(first[1], hp_after_player_half)
        self.assertIn('You hit', ' '.join(first[2]))
        self.assertNotIn('hits you', ' '.join(first[2]))
        self.assertLess(state.player.hp, hp_after_player_half)

    def test_one_held_frame_per_visible_monster_and_one_blow_at_a_time(self):
        state = state_with_monsters([(1, 0), (-1, 0), (0, 1)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        self.phase(renderer, state)
        self.assertEqual(renderer.pauses(), [('pause', DELAY)] * 3)
        hits = [sum('hits you' in m for m in draw[2]) for draw in renderer.draws()]
        self.assertEqual(hits, [0, 1, 2])
        self.assertFalse(state.monster_phase_pending())

    def test_monsters_acting_out_of_sight_fold_in_without_frames(self):
        state = state_with_monsters([])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        self.phase(renderer, state)
        self.assertEqual(renderer.pauses(), [])

    def test_death_cuts_the_frame_sequence_short(self):
        state = state_with_monsters([(1, 0), (-1, 0), (0, 1)], player_hp=2)
        renderer = RecordingRenderer()
        state.handle_action('wait')
        self.phase(renderer, state)
        self.assertTrue(state.game_over)
        self.assertEqual(len(renderer.pauses()), 1)

    def test_rapier_second_strike_waits_for_the_first_hit_to_be_drawn(self):
        state = state_with_monsters([(1, 0)])
        state.player.weapon = Item(0, 0, 'rapier', 'epic')
        goblin = state.entities[1]
        renderer = RecordingRenderer(goblin)
        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.0):
            self.one_action(renderer, state, 'move_e')
        hits = [h for h in state.combat_events if h.attacker is state.player]
        self.assertEqual(len(hits), 2)
        first, second = (h.damage for h in hits)
        frames = renderer.draws()
        self.assertEqual(frames[0][3], 200 - first)
        self.assertEqual(frames[0][4], [first])
        self.assertEqual(renderer.events[1], ('pause', DELAY))
        self.assertEqual(frames[1][3], 200 - first - second)
        self.assertEqual(frames[1][4], [first, second])
        self.assertNotIn('hits you', ' '.join(frames[1][2]))
        attackers = [h.attacker for h in state.combat_events]
        self.assertEqual(attackers, [state.player, state.player, goblin])

    def test_rapier_kill_on_the_first_strike_holds_no_extra_frame(self):
        state = state_with_monsters([(1, 0)], monster_hp=1)
        state.player.weapon = Item(0, 0, 'rapier', 'epic')
        renderer = RecordingRenderer()
        self.one_action(renderer, state, 'move_e')
        self.assertEqual(renderer.events, [])

    def test_warrior_bump_has_no_strike_step(self):
        state = state_with_monsters([(1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('move_e')
        run(self.loop.resolve_player_strikes(renderer, state, DELAY))
        self.assertEqual(renderer.events, [])
        self.assertTrue(state.monster_phase_pending())

    def test_zero_delay_still_draws_every_step(self):
        state = state_with_monsters([(1, 0), (-1, 0)])
        renderer = RecordingRenderer()
        state.handle_action('wait')
        self.phase(renderer, state, 0)
        self.assertEqual(len(renderer.draws()), 2)
        self.assertEqual(renderer.pauses(), [('pause', 0), ('pause', 0)])


# -- the real WebRenderer -----------------------------------------------------


def key(k, char='', **extra):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=char, mod=0, scancode=0, **extra)


def click(pos=(5, 5), button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


def enter():
    return key(pygame.K_RETURN, '\r')


class Forbidden:
    """Stands in for an API the browser must never touch."""

    def __call__(self, *args, **kwargs):
        raise AssertionError('forbidden call')

    def __getattr__(self, name):
        raise AssertionError(f'forbidden attribute {name}')


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class WebRendererTests(unittest.TestCase):
    def setUp(self):
        from web.renderer import WebRenderer

        self.renderer = WebRenderer(WIDTH, HEIGHT)
        # get_ticks() reads 0 until SDL's timer is initialised, which on a
        # desktop only a first pygame.time.wait() does (pygbag's runtime
        # does it itself); without it every deadline loop would spin forever.
        pygame.time.wait(1)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def post(self, *events):
        for event in events:
            pygame.event.post(event)

    def drawn_state(self, with_monster):
        state = GameState(WIDTH, HEIGHT)
        state.entities = [state.player]
        if with_monster:
            state.entities.append(Monster(state.player.x + 2, state.player.y, 'goblin'))
        state.update_fov()
        run(self.renderer.draw(state))
        return state

    def first_action(self, *events):
        self.post(*events)
        return run(self.renderer.get_action())

    # menus

    def test_title_down_enter_is_quit_and_enter_is_start(self):
        self.post(key(pygame.K_DOWN), enter())
        self.assertFalse(run(self.renderer.show_title_screen()))
        self.post(enter())
        self.assertTrue(run(self.renderer.show_title_screen()))

    def test_class_menu_down_enter_picks_archer(self):
        self.post(key(pygame.K_s, 's'), enter())
        self.assertEqual(run(self.renderer.choose_class()), 'archer')

    def test_q_and_window_close_leave_menus(self):
        self.post(key(pygame.K_q, 'q'))
        self.assertFalse(run(self.renderer.show_title_screen()))
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertIsNone(run(self.renderer._run_menu(['x'], ['A', 'B'])))
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertEqual(run(self.renderer.get_action()), Action.QUIT)

    def test_window_close_in_a_menu_is_delivered_by_get_action(self):
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertFalse(run(self.renderer.show_title_screen()))
        self.assertEqual(run(self.renderer.get_action()), Action.QUIT)

    def test_menu_click_selects_like_enter(self):
        from render import screens

        self.post(click((1, 1)))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertFalse(run(self.renderer.show_title_screen()))
        self.post(click((2, 2)))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertTrue(run(self.renderer.show_title_screen()))

    # gameplay input

    def test_get_action_maps_keys_and_ignores_unmapped(self):
        self.post(key(pygame.K_w, 'w'), key(pygame.K_PERIOD, '.'))
        self.assertEqual(run(self.renderer.get_action()), Action.MOVE_N)
        self.assertEqual(run(self.renderer.get_action()), Action.WAIT)

    def test_chest_card_click_returns_choose(self):
        from render import screens

        state = GameState(WIDTH, HEIGHT)
        state.pending_choice = [
            Item(0, 0, 'armor', 'rare'),
            Item(0, 0, 'weapon', 'epic'),
            Item(0, 0, 'armor', 'epic'),
        ]
        run(self.renderer.draw(state))
        card = screens.choice_rects(self.renderer.layout, state)[1][1]
        self.post(click(card.center))
        self.assertEqual(run(self.renderer.get_action()), Action.CHOOSE_2)

    def test_held_movement_is_blocked_with_a_monster_in_view(self):
        self.drawn_state(True)
        w = key(pygame.K_w, 'w')
        self.assertEqual(self.first_action(w), Action.MOVE_N)
        self.assertEqual(self.first_action(w, key(pygame.K_PERIOD, '.')), Action.WAIT)
        rep = key(pygame.K_d, 'd', repeat=True)
        self.assertEqual(self.first_action(rep, key(pygame.K_PERIOD, '.')), Action.WAIT)

    def test_held_movement_passes_with_no_monster_in_view(self):
        self.drawn_state(False)
        w = key(pygame.K_w, 'w')
        self.assertEqual(self.first_action(w), Action.MOVE_N)
        self.assertEqual(self.first_action(w), Action.MOVE_N)

    # pause and beats

    def test_typing_ahead_during_pause_leaves_keys_queued(self):
        self.post(key(pygame.K_w, 'w'))
        run(self.renderer.pause(30))
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))
        self.assertEqual(run(self.renderer.get_action()), Action.MOVE_N)

    def test_pause_really_waits(self):
        start = pygame.time.get_ticks()
        run(self.renderer.pause(60))
        self.assertGreaterEqual(pygame.time.get_ticks() - start, 55)

    def test_interruptible_play_ends_on_a_queued_key(self):
        self.post(key(pygame.K_w, 'w'))
        start = pygame.time.get_ticks()
        run(self.renderer._play(1000, lambda t: None, True))
        self.assertLess(pygame.time.get_ticks() - start, 300)
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))

    def test_non_interruptible_play_runs_to_the_end(self):
        self.post(key(pygame.K_w, 'w'))
        start = pygame.time.get_ticks()
        run(self.renderer._play(120, lambda t: None, False))
        self.assertGreaterEqual(pygame.time.get_ticks() - start, 110)
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))

    # browser guards

    def test_nothing_calls_the_blocking_waits(self):
        state = GameState(WIDTH, HEIGHT)
        state.entities = [state.player, Monster(state.player.x + 1, state.player.y, 'goblin')]
        state.update_fov()
        boom = mock.Mock(side_effect=AssertionError('blocking wait'))
        with (
            mock.patch.object(pygame.event, 'wait', boom),
            mock.patch.object(pygame.time, 'wait', boom),
            mock.patch.object(pygame.time, 'delay', boom),
        ):
            self.post(enter())
            run(self.renderer.show_title_screen())
            self.post(enter())
            run(self.renderer.choose_class())
            run(self.renderer.pause(30))
            run(self.renderer.draw(state))
            state.handle_action('move_e')  # a hit: the next draw plays beats
            run(self.renderer.draw(state))
            self.post(key(pygame.K_PERIOD, '.'))
            self.assertEqual(run(self.renderer.get_action()), Action.WAIT)
        boom.assert_not_called()

    def test_no_window_or_fullscreen_calls_and_f11_is_ignored(self):
        from web.renderer import WebRenderer

        self.renderer.close()
        with (
            mock.patch.object(pygame, 'Window', Forbidden()),
            mock.patch.object(pygame.display, 'toggle_fullscreen', Forbidden()),
        ):
            self.renderer = WebRenderer(WIDTH, HEIGHT)
            self.assertFalse(getattr(self.renderer, 'fullscreen', False))
            pygame.event.clear()
            self.post(key(pygame.K_F11), key(pygame.K_w, 'w'))
            self.assertEqual(run(self.renderer.get_action()), Action.MOVE_N)
            self.post(key(pygame.K_F11), enter())
            self.assertTrue(run(self.renderer.show_title_screen()))
            self.assertFalse(getattr(self.renderer, 'fullscreen', False))

    def test_waits_yield_to_the_event_loop(self):
        async def scenario(coro):
            ticks = 0
            done = False

            async def ticker():
                nonlocal ticks
                while not done:
                    ticks += 1
                    await asyncio.sleep(0)

            task = asyncio.ensure_future(ticker())
            await coro
            done = True
            await task
            return ticks

        self.assertGreater(run(scenario(self.renderer.pause(100))), 3)
        # An input wait with nothing queued also yields until a key arrives.
        self.assertGreater(run(self.late_key_scenario(scenario)), 3)

    def late_key_scenario(self, scenario):
        async def go():
            async def post_later():
                await asyncio.sleep(0.05)
                self.post(key(pygame.K_PERIOD, '.'))

            poster = asyncio.ensure_future(post_later())
            ticks = await scenario(self.renderer.get_action())
            await poster
            return ticks

        return go()

    # a whole run

    def test_scripted_run_through_web_loop_terminates(self):
        import web.loop
        import web.renderer

        self.post(
            enter(),  # Start
            enter(),  # Warrior
            key(pygame.K_w, 'w'),
            key(pygame.K_d, 'd'),
            key(pygame.K_PERIOD, '.'),
            pygame.event.Event(pygame.QUIT),
        )
        with mock.patch('web.renderer.paint_goodbye', wraps=web.renderer.paint_goodbye) as paint:
            run(web.loop.play(self.renderer, WIDTH, HEIGHT, delay_ms=5), timeout=15)
        paint.assert_called_once()

    def test_quit_from_the_title_ends_on_the_goodbye_screen(self):
        import web.loop
        import web.renderer

        self.post(key(pygame.K_DOWN), enter())  # Quit
        with mock.patch('web.renderer.paint_goodbye', wraps=web.renderer.paint_goodbye) as paint:
            run(web.loop.play(self.renderer, WIDTH, HEIGHT, delay_ms=5), timeout=15)
        paint.assert_called_once()

    def test_goodbye_text_is_painted(self):
        import web.renderer

        with mock.patch.object(self.renderer.canvas, 'put_str_centered') as put:
            run(self.renderer.show_goodbye())
        painted = [call.args[1] for call in put.call_args_list]
        self.assertIn(web.renderer.GOODBYE_TITLE, painted)
        self.assertIn(web.renderer.GOODBYE_HINT, painted)


if __name__ == '__main__':
    unittest.main()
