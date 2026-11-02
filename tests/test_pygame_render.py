"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import collections
import contextlib
import os
import unittest
from typing import Any, cast
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

import main
from game.combat import Parry, Shot
from game.monster import Monster
from game.state import GameState
from render.base import Action

if pygame is not None:
    from render import camera, palette, screens
    from render.palette import BACKGROUND
    from render.pygame_render import PygameRenderer

WIDTH, HEIGHT = 40, 20


def key(k, char='', shift=False):
    mod = pygame.KMOD_SHIFT if shift else 0
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=char, mod=mod, scancode=0)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PygameRendererTest(unittest.TestCase):
    def setUp(self):
        self.renderer = PygameRenderer(WIDTH, HEIGHT)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def post(self, *events):
        for event in events:
            pygame.event.post(event)

    def test_draw_paints_the_player_cell(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.draw(state)
        # The camera follows the player over a map bigger than the view, so
        # the cell is wherever the current view puts it.
        cell = self.renderer._map_cell_rect(state.player.x, state.player.y)
        screen = self.renderer.canvas.surface
        pixels = {
            tuple(screen.get_at((x, y)))[:3]
            for x in range(cell.left, cell.right)
            for y in range(cell.top, cell.bottom)
        }
        self.assertTrue(pixels - {BACKGROUND}, 'player cell is blank')

    def test_walking_tilts_alternate_sign_but_a_jump_is_no_step(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        player = state.player
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.assertEqual(self.renderer.track_steps([player]), {})  # idle: upright
        angles = []
        for _ in range(4):
            player.x += 1
            angles.append(self.renderer.track_steps([player]).get(id(player)))
        self.assertEqual(angles, [15, -15, 15, -15])
        self.assertEqual(self.renderer.track_steps([player]), {})  # stopped
        # A jump is not a step, and gone entities are forgotten.
        player.x += 5
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.renderer.track_steps([])
        self.assertEqual(self.renderer._gait, {})

    def test_draw_plays_a_step_beat_and_ends_upright(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.follow_ms = self.renderer.zoom_ms = 0  # the camera's pan is not the step
        self.renderer.draw(state)
        state.player.x += 1
        start = pygame.time.get_ticks()
        with captured_frames(self.renderer) as frames:
            self.renderer.draw(state)
        self.assertGreaterEqual(pygame.time.get_ticks() - start, 110 - 20)  # the step beat
        self.assertGreater(len(frames), 1)  # leaning frames, then the final one
        self.assertNotEqual(  # the lean shows, and the last frame is upright
            pygame.image.tobytes(frames[0], 'RGB'), pygame.image.tobytes(frames[-1], 'RGB')
        )
        self.renderer.canvas.clear()
        self.renderer._paint_game(state)
        self.assertEqual(
            pygame.image.tobytes(frames[-1], 'RGB'),
            pygame.image.tobytes(self.renderer.canvas.surface, 'RGB'),
        )
        self.assertEqual(self.renderer._tilts, {})

    def test_get_action_maps_keys_ignores_unmapped_and_quits_on_close(self):
        self.post(
            key(pygame.K_w, 'w'),
            key(pygame.K_e, 'e'),
            key(pygame.K_UP),
            key(pygame.K_PERIOD, '.'),
        )
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)
        self.assertEqual(self.renderer.get_action(), Action.DESCEND)
        self.assertEqual(self.renderer.get_action(), Action.SHOOT_N)
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        # An unmapped key is None (ignored); closing the window is QUIT.
        self.post(key(pygame.K_z, 'z'))
        self.assertIsNone(self.renderer.get_action())
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    def test_resize_relayouts_and_keeps_waiting(self):
        self.renderer.draw(GameState(WIDTH, HEIGHT, seed=0))
        before = self.renderer.layout.cell_w
        pygame.display.set_mode((3000, 1500), pygame.RESIZABLE)
        self.post(
            pygame.event.Event(pygame.VIDEORESIZE, size=(3000, 1500), w=3000, h=1500),
            key(pygame.K_d, 'd'),
        )
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)
        self.assertGreater(self.renderer.layout.cell_w, before)
        self.assertEqual(self.renderer.canvas.surface.get_size(), (3000, 1500))

    def test_pause_keeps_typed_ahead_keys(self):
        for mouse in (False, True):
            with self.subTest(mouse_events_queued=mouse):
                if mouse:
                    self.post(self.motion(), key(pygame.K_a, 'a'), self.click())
                else:
                    self.post(key(pygame.K_a, 'a'))
                start = pygame.time.get_ticks()
                self.renderer.pause(50)
                self.assertGreaterEqual(pygame.time.get_ticks() - start, 50)
                self.assertEqual(self.renderer.get_action(), Action.MOVE_W)

    def test_window_close_during_pause_is_delivered_next(self):
        self.post(pygame.event.Event(pygame.QUIT))
        self.renderer.pause(20)
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    def test_zero_pause_is_instant(self):
        start = pygame.time.get_ticks()
        self.renderer.pause(0)
        self.assertLess(pygame.time.get_ticks() - start, 5)

    def test_menus_and_a_full_run_through_main_loop(self):
        import main

        enter = key(pygame.K_RETURN, '\r')
        # Title: Start. Class: down to Archer, enter. Then a few turns, quit.
        self.post(
            enter,
            key(pygame.K_s, 's'),
            enter,
            key(pygame.K_w, 'w'),
            key(pygame.K_RIGHT),
            key(pygame.K_PERIOD, '.'),
            key(pygame.K_q, 'q'),  # the ability key: does nothing mid-game
            pygame.event.Event(pygame.QUIT),
        )
        self.assertTrue(self.renderer.show_title_screen())
        char_class = self.renderer.choose_class()
        self.assertEqual(char_class, 'archer')
        assert char_class is not None  # for the type checker
        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        main.run(self.renderer, state, delay_ms=5)
        self.assertFalse(state.running)

    def test_q_or_closing_the_window_on_the_class_select_is_no_class(self):
        # The hint says 'q to quit': no Warrior run behind the player's back.
        for name, event in (
            ('q', key(pygame.K_q, 'q')),
            ('close', pygame.event.Event(pygame.QUIT)),
        ):
            with self.subTest(name):
                self.post(event)
                self.assertIsNone(self.renderer.choose_class())

    def test_q_on_the_class_select_goes_back_to_the_title(self):
        enter = key(pygame.K_RETURN, '\r')
        states, at_title, at_class = self.play_with_a_death(
            enter,  # title: Start
            key(pygame.K_q, 'q'),  # class select: back out
            key(pygame.K_DOWN),
            enter,  # title again: Quit
            pygame.event.Event(pygame.QUIT),  # ends a run that shouldn't have started
        )
        self.assertEqual(states, [])
        self.assertEqual(at_title, [0, 0])
        self.assertEqual(at_class, [0])

    def test_title_screen_keys(self):
        for name, events, started in (
            ('down, enter: Quit', [key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')], False),
            ('s, space: Quit', [key(pygame.K_s, 's'), key(pygame.K_SPACE, ' ')], False),
            ('q quits', [key(pygame.K_q, 'q')], False),
            # 'r' neither picks an option nor moves the highlight: enter still
            # takes Start.
            ('r does nothing', [key(pygame.K_r, 'r'), key(pygame.K_RETURN, '\r')], True),
        ):
            with self.subTest(name):
                self.post(*events)
                self.assertIs(self.renderer.show_title_screen(), started)

    # -- P1: fullscreen, bosses, fonts ---------------------------------------

    def test_f11_toggles_fullscreen_and_back_while_waiting_and_repaints(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.draw(state)
        windowed = self.renderer.canvas.surface.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        self.post(key(pygame.K_F11), key(pygame.K_w, 'w'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)  # F11 is no Action
        self.assertTrue(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), desktop)
        self.assertEqual(pygame.display.get_surface().get_size(), desktop)
        # The current frame is repainted at the new size.
        cell = self.renderer._map_cell_rect(state.player.x, state.player.y)
        self.assertTrue(
            set(cell_pixels(self.renderer, cell)) - {BACKGROUND},
            'frame not repainted after going fullscreen',
        )

        self.post(key(pygame.K_F11), key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), windowed)

    def test_f11_in_a_menu_is_not_a_selection(self):
        # F11 twice (in and out), then Down: still on the title menu, so the
        # Enter selects Quit -- F11 neither confirmed nor moved anything.
        self.post(
            key(pygame.K_F11), key(pygame.K_F11), key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')
        )
        self.assertFalse(self.renderer.show_title_screen())
        self.assertFalse(self.renderer.fullscreen)

    def test_fullscreen_failure_is_harmless(self):
        size = self.renderer.canvas.surface.get_size()
        window = mock.Mock()
        window.set_fullscreen.side_effect = pygame.error('no fullscreen here')
        with mock.patch.object(PygameRenderer, '_display_window', return_value=window):
            self.renderer.toggle_fullscreen()
        with (
            mock.patch.object(PygameRenderer, '_display_window', return_value=None),
            mock.patch('pygame.display.set_mode', side_effect=pygame.error('no')),
        ):
            self.renderer.toggle_fullscreen()
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), size)

    def test_fullscreen_falls_back_to_set_mode_without_window_api(self):
        windowed = self.renderer.canvas.surface.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        with mock.patch.object(PygameRenderer, '_display_window', return_value=None):
            self.renderer.toggle_fullscreen()
            self.assertEqual(self.renderer.canvas.surface.get_size(), desktop)
            self.renderer.toggle_fullscreen()
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), windowed)

    def test_boss_is_drawn_heavier_and_brighter_than_a_regular_monster(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        state.entities = [state.player]
        x, y = open_neighbour(state)
        boss = Monster(x, y, 'goblin', is_boss=True)
        state.entities.append(boss)
        # The boss stands next to the player; this compares the unzoomed cell.
        self.renderer.director.zoom = False

        self.renderer.draw(state)
        cell = self.renderer._map_cell_rect(x, y)  # where the camera put it
        boss_pixels = lit_pixels(self.renderer, cell)
        boss.is_boss = False
        self.renderer.draw(state)
        plain_pixels = lit_pixels(self.renderer, cell)

        self.assertGreater(len(boss_pixels), len(plain_pixels))

        # The glyph's solid core -- its most common red pixel -- is the colour
        # it was drawn in. (Not the brightest: an anti-aliased edge blended
        # over the white floor dot under the glyph can outshine the core.)
        def core_red(pixels):
            reds = [tuple(p[:3]) for p in pixels if p[0] > p[1] + 40]
            return sum(collections.Counter(reds).most_common(1)[0][0])

        self.assertGreater(core_red(boss_pixels), core_red(plain_pixels))

    def test_font_path_reaches_the_layout(self):
        font = os.path.join(os.path.dirname(pygame.__file__), pygame.font.get_default_font())
        self.renderer.close()
        self.renderer = PygameRenderer(WIDTH, HEIGHT, font_path=font)
        self.assertEqual(self.renderer.layout.font_path, font)
        self.renderer.draw(GameState(WIDTH, HEIGHT, seed=0))

    def test_make_renderer_uses_the_bundled_font_and_tiles_unless_tiles_is_zero(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('TILES', None)
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            font_path = cast(str, renderer.layout.font_path)
            self.assertTrue(font_path.endswith(main.BUNDLED_FONT_FILE))
            self.assertTrue(os.path.isfile(font_path))
            self.assertTrue(renderer.layout.tiles)
        finally:
            renderer.close()
        with mock.patch.dict(os.environ, {'TILES': '0'}):
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            self.assertFalse(renderer.layout.tiles)
        finally:
            renderer.close()

    # -- P3: mouse in the menus ----------------------------------------------

    @staticmethod
    def motion(pos=(5, 5)):
        return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(1, 1), buttons=(0, 0, 0))

    @staticmethod
    def click(pos=(5, 5), button=1):
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)

    def test_menu_hover_moves_the_highlight(self):
        seen = []

        def fake_hit(layout, menu, banner, pos):
            seen.append(menu.index)
            return {(1, 1): 1}.get(pos)

        self.post(self.motion((1, 1)), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', fake_hit):
            self.assertFalse(self.renderer.show_title_screen())  # Quit, via hover
        self.assertEqual(seen, [0])

    def test_menu_click_selects_like_enter(self):
        self.post(self.click((1, 1)))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertFalse(self.renderer.show_title_screen())
        self.post(self.click((2, 2)))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertTrue(self.renderer.show_title_screen())

    def test_menu_click_outside_any_option_or_a_right_click_does_nothing(self):
        self.post(
            self.click((9, 9)), self.motion((9, 9)), key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')
        )
        with mock.patch.object(screens, 'option_at', lambda *a: None):
            self.assertFalse(self.renderer.show_title_screen())  # keys decided it
        # A right click on an option is ignored.
        self.post(self.click((1, 1), button=3), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertTrue(self.renderer.show_title_screen())

    def test_menu_repaints_only_when_the_highlight_changes(self):
        self.post(self.motion(), self.motion(), self.motion(), key(pygame.K_RETURN, '\r'))
        with (
            mock.patch.object(screens, 'option_at', lambda *a: 1),
            mock.patch.object(screens, 'paint_menu') as paint,
        ):
            self.renderer.show_title_screen()
        # first paint, one repaint after the highlight moved, none for the
        # two motions that changed nothing, then Enter returns.
        self.assertEqual(paint.call_count, 2)

    def test_mouse_events_are_ignored_during_get_action(self):
        self.post(self.motion(), self.click(), self.click(button=3), key(pygame.K_d, 'd'))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_window_close_in_a_menu_is_delivered_by_get_action(self):
        self.post(self.motion(), pygame.event.Event(pygame.QUIT))
        self.assertFalse(self.renderer.show_title_screen())
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    # -- P1: game over, and a whole run --------------------------------------

    def test_game_over_shows_overlay_and_q_quits(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        kill_player_next_turn(state)
        # '.' lets the goblin kill us; 'w' after death is ignored; 'q' quits.
        self.post(key(pygame.K_PERIOD, '.'), key(pygame.K_w, 'w'), key(pygame.K_q, 'q'))
        frames = record_frames(self.renderer)
        main.run(self.renderer, state, delay_ms=1)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)
        self.assertGreaterEqual(frames.count(True), 2)  # game-over frame, before 'w' and 'q'
        self.assertOverlayDrawn(state)

    def test_window_close_on_game_over_quits(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        kill_player_next_turn(state)
        self.post(key(pygame.K_PERIOD, '.'), pygame.event.Event(pygame.QUIT))
        main.run(self.renderer, state, delay_ms=1)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)

    def test_r_is_restart_only_on_the_game_over_screen(self):
        # (On the title screen: test_title_screen_keys.)
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.draw(state)
        self.post(key(pygame.K_r, 'r'), key(pygame.K_PERIOD, '.'))
        self.assertIsNone(self.renderer.get_action())  # mid-game: ignored
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        state.game_over = True
        self.renderer.draw(state)
        self.post(key(pygame.K_r, 'r'))
        self.assertEqual(self.renderer.get_action(), Action.RESTART)

    def play_with_a_death(self, *events, second_run=()):
        """main.play with `events` queued and the first run's player one
        blow from death, carrying what a run collects (a belt potion, a boon,
        hop and parry cooldowns). `second_run` is posted once a second class
        select returns -- a window close queued from the start would be seen
        by the first run's pauses. Returns (states built, [states built when
        each title screen opened], [... when each class select opened])."""
        from game.item import Item

        real_state = GameState
        states, at_title, at_class = [], [], []

        def build(*args, **kwargs):
            state = real_state(*args, **kwargs)
            if not states:
                kill_player_next_turn(state)
                state.belt = [Item(0, 0, 'potion', 'common')]
                state.player.boons = ['iron_skin']
                state.last_hop_turn = state.last_parry_turn = 0
            states.append(state)
            return state

        real_title, real_class = self.renderer.show_title_screen, self.renderer.choose_class

        def title():
            at_title.append(len(states))
            return real_title()

        def choose():
            at_class.append(len(states))
            char_class = real_class()
            if len(at_class) == 2:
                self.post(*second_run)
            return char_class

        self.renderer.show_title_screen = title
        self.renderer.choose_class = choose
        self.post(*events)
        try:
            with mock.patch.object(main, 'GameState', side_effect=build):
                main.play(self.renderer, WIDTH, HEIGHT, delay_ms=1)
        finally:  # back to the real menus, for a second call in the same test
            del self.renderer.show_title_screen, self.renderer.choose_class
            pygame.event.clear()
        return states, at_title, at_class

    def test_r_on_the_death_screen_goes_back_to_the_title_and_a_fresh_run(self):
        enter = key(pygame.K_RETURN, '\r')
        states, at_title, at_class = self.play_with_a_death(
            enter,  # title: Start
            enter,  # class: Warrior
            key(pygame.K_PERIOD, '.'),  # the goblin kills us
            key(pygame.K_r, 'r'),  # death screen: restart
            enter,  # title again: Start
            key(pygame.K_s, 's'),
            enter,  # class: Archer
            second_run=[pygame.event.Event(pygame.QUIT)],
        )
        self.assertEqual(len(states), 2)
        dead, fresh = states
        self.assertTrue(dead.game_over)
        self.assertTrue(dead.restart_requested)
        # The title opened twice; the second run's GameState was built only
        # after its class was chosen.
        self.assertEqual(at_title, [0, 1])
        self.assertEqual(at_class, [0, 1])
        self.assertIsNot(fresh, dead)
        self.assertEqual(fresh.player.char_class, 'archer')
        self.assertFalse(fresh.game_over)
        self.assertFalse(fresh.restart_requested)
        self.assertEqual(fresh.depth, 1)
        self.assertEqual(fresh.turn, 0)
        self.assertEqual(fresh.player.hp, fresh.player.max_hp)
        self.assertEqual(fresh.belt, [])
        self.assertEqual(fresh.player.boons, [])
        self.assertFalse(fresh.parry_armed)
        self.assertIsNone(fresh.last_parry_turn)
        self.assertIsNone(fresh.last_hop_turn)
        self.assertFalse(fresh.hop_crit)
        from game.quiver import QUIVER_CAPACITY

        self.assertEqual(fresh.player.quiver, QUIVER_CAPACITY)
        # The renderer forgot the dead run too: its Director would otherwise
        # skip the new run's hits (their serials start again from zero).
        self.assertEqual(self.renderer.director._cursor, 0)

    def test_q_or_window_close_on_the_death_screen_still_quits_from_play(self):
        enter = key(pygame.K_RETURN, '\r')
        for name, last in (
            ('q', key(pygame.K_q, 'q')),
            ('close', pygame.event.Event(pygame.QUIT)),
        ):
            with self.subTest(name):
                states, at_title, _ = self.play_with_a_death(
                    enter, enter, key(pygame.K_PERIOD, '.'), last
                )
                self.assertEqual(len(states), 1)
                self.assertEqual(at_title, [0])  # never back to the title
                if name == 'q':
                    self.assertTrue(states[0].game_over)
                    self.assertFalse(states[0].restart_requested)

    def test_death_screen_shows_both_hints(self):
        self.assertEqual(screens.GAME_OVER_HINTS, ('press q to quit', 'press r to restart'))
        state = GameState(WIDTH, HEIGHT, seed=0)
        state.game_over = True
        self.renderer.draw(state)
        layout = self.renderer.layout
        box = screens.game_over_rect(layout)
        title_font, hint_font = screens.game_over_fonts(layout)
        self.assertGreaterEqual(
            box.height,
            title_font.get_linesize() + 2 * hint_font.get_linesize(),
        )
        self.assertGreaterEqual(box.width, hint_font.size('press r to restart')[0])
        self.assertTrue(layout.map_rect().contains(box))
        # Each hint's line inside the box has red ink on it.
        screen = self.renderer.canvas.surface
        top = box.top + layout.cell_h // 2 + title_font.get_linesize()
        for i in range(2):
            # Inset half a cell, clear of the box's red frame.
            line = pygame.Rect(
                box.left + layout.cell_w // 2,
                top + i * hint_font.get_linesize(),
                box.width - layout.cell_w,
                hint_font.get_height(),
            )
            pixels = pygame.image.tobytes(screen.subsurface(line), 'RGB')
            colours = {pixels[j : j + 3] for j in range(0, len(pixels), 3)}
            self.assertIn(bytes(palette.DANGER), colours, f'hint line {i}')

    def test_complete_run_title_class_descend_death_quit(self):
        """Plan WS-A acceptance: a complete run, in-window, through main.run.

        Keys go through the real event queue; between keystrokes the script
        only rearranges the world (puts the player on the stairs, brings a
        monster in for the kill) instead of path-finding to them."""
        enter = key(pygame.K_RETURN, '\r')
        self.post(enter, key(pygame.K_s, 's'), enter)  # Start, then Archer
        self.assertTrue(self.renderer.show_title_screen())
        char_class = self.renderer.choose_class()
        assert char_class is not None  # for the type checker
        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        self.assertEqual(state.player.char_class, 'archer')

        def to_stairs():
            state.player.x, state.player.y = find_tile(state, '>')
            state.update_fov()
            return [key(pygame.K_e, 'e')]

        def die_on_level_two():
            self.assertEqual(state.depth, 2)
            kill_player_next_turn(state)
            return [key(pygame.K_PERIOD, '.')]

        def on_game_over_frame():
            self.assertTrue(state.game_over)
            self.assertOverlayDrawn(state)
            return [key(pygame.K_d, 'd'), key(pygame.K_q, 'q')]  # move ignored; quit

        script = [to_stairs, die_on_level_two, on_game_over_frame]
        real_get_action = self.renderer.get_action

        def scripted_get_action():
            if script and not pygame.event.peek(pygame.KEYDOWN):
                for event in script.pop(0)():
                    pygame.event.post(event)
            return real_get_action()

        self.renderer.get_action = scripted_get_action
        main.run(self.renderer, state, delay_ms=1)
        self.assertEqual(script, [])
        self.assertEqual(state.depth, 2)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)

    def assertOverlayDrawn(self, state):
        """The game-over line differs from the same frame without it."""
        layout = self.renderer.layout
        row = screens.game_over_rect(layout)
        self.renderer.draw(state)
        with_overlay = cell_pixels(self.renderer, row, as_list=True)
        state.game_over = False
        try:
            self.renderer.draw(state)
            without = cell_pixels(self.renderer, row, as_list=True)
        finally:
            state.game_over = True
            self.renderer.draw(state)
        self.assertNotEqual(with_overlay, without)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class TileModeTest(unittest.TestCase):
    """The bundled tileset puts the window in tile mode: square map cells."""

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()

    def tearDown(self):
        self.renderer.close()

    def test_draw_paints_each_class_own_tile_over_the_floor(self):
        layout = self.renderer.layout
        self.assertTrue(layout.tiles)  # the bundled tileset: tile mode
        self.assertIsNotNone(layout.tile)
        for char_class, char in (('warrior', '@'), ('archer', '&')):
            with self.subTest(char_class):
                state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
                self.renderer.draw(state)
                rect = self.renderer._map_cell_rect(state.player.x, state.player.y)
                drawn = pygame.display.get_surface().subsurface(rect)
                expected = self.renderer.tileset.glyph('.', 0, layout.tile).copy()
                tile = self.renderer.tileset.glyph(char, state.player.color, layout.tile)
                expected.blit(tile, (0, 0))
                for point in [(layout.tile // 2, layout.tile // 2), (1, 1), (layout.tile // 3, 2)]:
                    self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3], point)
        self.assertIsNot(
            self.renderer.tileset.glyph('&', 0, layout.tile),
            self.renderer.tileset.glyph('@', 0, layout.tile),
        )

    def fight(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        state.entities = [state.player, goblin]
        state.update_fov()
        return state, goblin

    def test_melee_zooms_in_with_the_fight_centred_then_back_out(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        layout = self.renderer.layout
        map_rect = layout.map_rect()
        # The pair plus 2 squares each side: 6x5 or 5x6 cells fill the map
        # area on its tighter axis.
        view = self.renderer._view
        cell, _, ox, oy = camera.project(view, map_rect, layout.map_cell_size())
        self.assertGreater(cell, cast(int, layout.tile))
        self.assertLessEqual(
            min(map_rect.w // cell, map_rect.h // cell) - 1, min(view.width, view.height)
        )
        # The player's zoomed tile is where the projection says, at the bigger size.
        rect = pygame.Rect(ox + state.player.x * cell, oy + state.player.y * cell, cell, cell)
        drawn = pygame.display.get_surface().subsurface(rect)
        expected = self.renderer.tileset.glyph('.', 0, cell).copy()
        expected.blit(self.renderer.tileset.glyph('@', state.player.color, cell), (0, 0))
        for point in [(cell // 2, cell // 2), (1, 1), (cell // 3, 2)]:
            self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3])
        # The midpoint between the two sits on the centre of the map area.
        mid_x = ox + (state.player.x + goblin.x + 1) / 2 * cell
        mid_y = oy + (state.player.y + goblin.y + 1) / 2 * cell
        self.assertLessEqual(abs(mid_x - map_rect.centerx), 1)
        self.assertLessEqual(abs(mid_y - map_rect.centery), 1)
        # The fight over: back to the exploring view that follows the player.
        goblin.hp = 1
        state.attack(state.player, goblin)
        self.renderer.draw(state)
        self.assertIsNone(self.renderer.director.view)
        self.assertEqual(self.renderer._view, self.renderer.director.explore_view(state))

    def test_zoom_stays_inside_the_map_area(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, _ = self.fight()
        screen = cast(Any, pygame.display.get_surface())
        self.renderer.draw(state)
        self.assertIsNotNone(self.renderer._view)
        zoomed = screen.copy()
        self.renderer.director = camera.Director(zoom=False)
        self.renderer.draw(state)
        # Blank the map area in both: everything else must match exactly.
        map_rect = self.renderer.layout.map_rect()
        for surface in (zoomed, screen):
            surface.fill(BACKGROUND, map_rect)
        self.assertEqual(pygame.image.tobytes(zoomed, 'RGB'), pygame.image.tobytes(screen, 'RGB'))

    def test_beats_animate_and_a_queued_key_cuts_them_short(self):
        self.renderer.zoom_ms = 2000
        state, _ = self.fight()
        pygame.event.post(key(pygame.K_d, 'd'))
        start = pygame.time.get_ticks()
        self.renderer.draw(state)
        self.assertLess(pygame.time.get_ticks() - start, 1000)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)  # not swallowed

    def test_a_beat_plays_its_frames(self):
        self.renderer.zoom_ms = 80
        state, _ = self.fight()
        frames = []
        show = self.renderer._show
        with mock.patch.object(
            self.renderer, '_show', side_effect=lambda paint: (frames.append(1), show(paint))
        ):
            self.renderer.draw(state)
        self.assertGreater(len(frames), 2)  # in-between frames, then the final one

    def test_impact_flashes_the_defender(self):
        self.renderer.zoom_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        state.attack(goblin, state.player)
        frames = []
        with mock.patch.object(
            self.renderer, '_paint_impact', side_effect=lambda hit, t: frames.append((hit, t))
        ):
            self.renderer.draw(state)
        self.assertTrue(frames)
        self.assertIs(frames[0][0].defender, state.player)

    def test_crit_number_is_bigger_yellow_with_black_outline(self):
        from render.pygame_render import CRIT_OUTLINE_RGB, CRIT_RGB

        r = self.renderer
        self.assertGreater(
            r._glyph('-12', CRIT_RGB, bold=True, scale=2).get_height(),
            r._glyph('-12', CRIT_RGB, bold=True).get_height(),
        )
        state, goblin = self.fight()
        r.draw(state)
        state.player.power = 5
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        hit = state.hits()[-1]
        self.assertTrue(hit.crit)
        r.canvas.surface.fill((50, 50, 50))
        r._paint_impact(hit, 0.0)
        rect = r._map_cell_rect(hit.x, hit.y)
        area = r.canvas.surface.subsurface(
            rect.inflate(rect.width, rect.height).clip(r.canvas.surface.get_rect())
        )
        pixels = {
            tuple(area.get_at((x, y)))[:3]
            for x in range(area.get_width())
            for y in range(area.get_height())
        }
        self.assertIn(CRIT_RGB, pixels)
        self.assertIn(CRIT_OUTLINE_RGB, pixels)

    def _drawn_state(self, with_monster):
        state = GameState(WIDTH, HEIGHT, seed=0)
        state.entities = [state.player]
        if with_monster:
            state.entities.append(Monster(state.player.x + 2, state.player.y, 'goblin'))
        state.update_fov()
        self.renderer.draw(state)
        return state

    def _first_action(self, *events):
        for event in events:
            pygame.event.post(event)
        return self.renderer.get_action()

    def test_repeated_movement_is_ignored_while_a_monster_is_visible(self):
        self._drawn_state(True)
        w = key(pygame.K_w, 'w')
        # A second press with no release in between is an auto-repeat; the
        # 'wait' after it proves the repeat was skipped, not queued.
        self.assertEqual(self._first_action(w), Action.MOVE_N)
        self.assertEqual(self._first_action(w, key(pygame.K_PERIOD, '.')), Action.WAIT)
        # So is a key event carrying the repeat flag.
        rep = pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_d, unicode='d', mod=0, scancode=0, repeat=True
        )
        self.assertEqual(self._first_action(rep, key(pygame.K_PERIOD, '.')), Action.WAIT)

    def test_repeated_movement_passes_with_no_monster_visible(self):
        self._drawn_state(False)
        w = key(pygame.K_w, 'w')
        self.assertEqual(self._first_action(w), Action.MOVE_N)
        self.assertEqual(self._first_action(w), Action.MOVE_N)

    def test_repeated_wait_and_drink_pass_with_a_monster_visible(self):
        self._drawn_state(True)
        for k, char, action in (
            (pygame.K_PERIOD, '.', Action.WAIT),
            (pygame.K_h, 'h', Action.DRINK),
        ):
            ev = key(k, char)
            self.assertEqual(self._first_action(ev), action)
            self.assertEqual(self._first_action(ev), action)

    def test_released_then_pressed_movement_always_passes(self):
        self._drawn_state(True)
        w = key(pygame.K_w, 'w')
        up = pygame.event.Event(pygame.KEYUP, key=pygame.K_w, mod=0, scancode=0)
        self.assertEqual(self._first_action(w), Action.MOVE_N)
        self.assertEqual(self._first_action(up, w), Action.MOVE_N)

    def test_char_without_a_tile_is_drawn_as_its_glyph(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        stranger = Monster(state.player.x + 1, state.player.y, 'goblin')
        stranger.char = 'Z'  # no tiles.json entry
        state.entities.append(stranger)
        state.update_fov()
        self.renderer.draw(state)  # must not raise

    def test_game_over_overlay_is_drawn_on_the_map(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.draw(state)
        before = pygame.display.get_surface().copy()
        state.game_over = True
        self.renderer.draw(state)
        band = screens.game_over_rect(self.renderer.layout)
        self.assertTrue(self.renderer.layout.map_rect().contains(band))
        after = pygame.display.get_surface()
        self.assertNotEqual(
            pygame.image.tobytes(after.subsurface(band), 'RGB'),
            pygame.image.tobytes(before.subsurface(band), 'RGB'),
        )


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class HitShakeAndHealthBarTest(unittest.TestCase):
    """The hit shake (an Impact beat that always plays out, keys left queued)
    and enemy health bars, in tile mode."""

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = 0
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def fight(self, zoom=False):
        self.renderer.director = camera.Director(zoom=zoom)
        state = GameState(WIDTH, HEIGHT, seed=0)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        goblin.hp = goblin.max_hp = 20
        state.entities = [state.player, goblin]
        state.update_fov()
        self.renderer.draw(state)
        return state, goblin

    def played(self, state):
        """([(beat, ms)], played_out) for draw(state): the beats the Director
        stages and how long each holds, and whether a key typed ahead left
        them all to run to the end (and still queued for get_action)."""
        r = self.renderer
        beats, elapsed, kept = play_with_key_typed_ahead(r, state)
        timed = [(beat, beat_ms(r, beat)) for beat in beats]
        total = sum(ms for _, ms in timed)
        return timed, kept and elapsed >= total - 20 * len(timed)

    # -- shake ----------------------------------------------------------------

    def test_a_hit_plays_an_uninterruptible_shake_and_a_crit_plays_longer(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        timed, played_out = self.played(state)  # the monster's swing, then the hit
        self.assertEqual([type(b) for b, _ in timed], [camera.Swing, camera.Impact])
        self.assertEqual(timed[0][1], camera.SWING_MS)
        normal_ms = timed[1][1]
        self.assertTrue(played_out)  # a key typed ahead cuts neither beat short
        self.assertTrue(150 <= normal_ms <= 250, normal_ms)

        state.player.power = 1
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        self.assertTrue(state.hits()[-1].crit)
        timed, played_out = self.played(state)
        crit_ms = timed[1][1]
        self.assertTrue(played_out)
        self.assertTrue(normal_ms < crit_ms <= 350, crit_ms)

    def test_shake_offsets_frames_ends_still_and_keys_wait_until_it_ends(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        r = self.renderer
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]

        def type_ahead():  # the shake's first frame: the player types ahead
            for event in typed:
                pygame.event.post(event)

        start = pygame.time.get_ticks()
        with captured_frames(r, on_first=type_ahead) as frames:
            r.draw(state)
        elapsed = pygame.time.get_ticks() - start
        self.assertGreaterEqual(elapsed, r.impact_ms - 20)  # not cut short
        self.assertGreaterEqual(len(frames), 2)  # shake frame(s), then the final one
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))  # not consumed
        # The rows below the fight, clear of the flash and the damage rising
        # off the top, so only the shake can change them between frames.
        px, py = state.player.x, state.player.y
        strip = r._map_cell_rect(px - 4, py + 2).union(r._map_cell_rect(px + 4, py + 4))
        shown = [area_bytes(f, strip) for f in frames]
        self.assertTrue(any(f != shown[-1] for f in shown[:-1]))  # the map moved
        r.canvas.clear()
        r._paint_game(state)
        self.assertEqual(shown[-1], area_bytes(r.canvas.surface, strip))  # draw()'s frame is still
        hit = state.hits()[-1]
        shake = camera.shake_for(hit)
        self.assertEqual(self.renderer.shake_offset(shake, 1.0), (0, 0))
        # The keys typed during the shake, in order.
        self.assertEqual(r.get_action(), Action.MOVE_E)
        self.assertEqual(r.get_action(), Action.MOVE_S)

    def test_shake_moves_the_whole_map(self):
        state, _ = self.fight()
        r = self.renderer
        r._paint_game(state)
        still = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(state, shake=(4, -3))
        moved = r.canvas.surface
        centre = r.layout.map_rect().center
        for dx, dy in ((0, 0), (17, 5), (-30, 11)):
            p = (centre[0] + dx, centre[1] + dy)
            self.assertEqual(moved.get_at((p[0] + 4, p[1] - 3)), still.get_at(p))

    def test_window_close_still_ends_a_shake(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        self.renderer.impact_ms = 5000
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        start = pygame.time.get_ticks()
        self.renderer.draw(state)
        self.assertLess(pygame.time.get_ticks() - start, 1000)
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    # -- the struck sprite's own shake ----------------------------------------

    def impact_frame(self, state, hit, t, sprite=True):
        """The map painted at t of `hit`'s beat, without the map's shake, so
        only the sprite's own jitter differs between sprite=True and False."""
        r = self.renderer
        r.canvas.clear()
        shake = camera.shake_for(hit)
        r._paint_game(state, impact=(hit, t), sprite_shake=shake if sprite else None)
        return r.canvas.surface.copy()

    def assert_sprite_shakes(self, state, hit, attacker):
        r = self.renderer
        map_rect = r.layout.map_rect()
        if r._view is not None:
            r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            struck = r._map_cell_rect(hit.x, hit.y)
            other = r._map_cell_rect(attacker.x, attacker.y)
            bar = r.restock_bar_rect(state.player)
        finally:
            r._proj = None
        # The struck sprite may spill a few pixels over the edge it shares
        # with the attacker; the rest of the attacker's cell is its own
        # sprite, which must not jitter.
        spill = camera.sprite_shake_peak(camera.shake_for(hit), struck.height)
        if hit.defender is state.player:
            # The bar under the player (a warrior's parry bar, an archer's
            # restock bar) overhangs its cell, rim included, and shakes with it.
            spill += (bar.width - struck.width + 1) // 2 + 1
        dx, dy = attacker.x - hit.x, attacker.y - hit.y
        own = pygame.Rect(other)
        if dx:
            own.width -= spill
            own.left += spill if dx > 0 else 0
        else:
            own.height -= spill
            own.top += spill if dy > 0 else 0
        moved = False
        for step in range(10):
            t = step / 10
            jolted = self.impact_frame(state, hit, t)
            still = self.impact_frame(state, hit, t, sprite=False)
            if area_bytes(jolted, struck) != area_bytes(still, struck):
                moved = True
            self.assertEqual(area_bytes(jolted, own), area_bytes(still, own), t)
        self.assertTrue(moved, 'the struck sprite never moved')
        # The beat's end: exactly back in its cell, the whole map unchanged.
        end = self.impact_frame(state, hit, 1.0)
        still = self.impact_frame(state, hit, 1.0, sprite=False)
        self.assertEqual(area_bytes(end, map_rect), area_bytes(still, map_rect))

    def test_the_struck_monster_or_player_shakes_in_its_cell(self):
        with self.subTest('the struck monster'):
            state, goblin = self.fight()
            state.attack(state.player, goblin)
            hit = state.hits()[-1]
            self.assertIs(hit.defender, goblin)
            self.assertFalse(hit.killed)
            self.assert_sprite_shakes(state, hit, state.player)
        with self.subTest('the struck player'):
            state, goblin = self.fight()
            state.attack(goblin, state.player)
            hit = state.hits()[-1]
            self.assertIs(hit.defender, state.player)
            self.assert_sprite_shakes(state, hit, goblin)

    def test_the_struck_sprite_shakes_zoomed_in(self):
        state, goblin = self.fight(zoom=True)
        self.assertIsNotNone(self.renderer._view)
        state.attack(state.player, goblin)
        self.assert_sprite_shakes(state, state.hits()[-1], state.player)

    def test_sprite_shake_is_repeatable_decays_and_is_bigger_for_a_crit(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        hit = state.hits()[-1]
        crit = hit._replace(crit=True)
        r = self.renderer
        cell = r._map_cell_rect(hit.x, hit.y).height

        def peak(h):
            shake = camera.shake_for(h)
            ts = [i / 50 for i in range(50)]
            offsets = [r.sprite_shake_offset(shake, t, h) for t in ts]
            self.assertEqual(offsets, [r.sprite_shake_offset(shake, t, h) for t in ts])
            self.assertEqual(r.sprite_shake_offset(shake, 1.0, h), (0, 0))
            return max(max(abs(dx), abs(dy)) for dx, dy in offsets)

        normal, big = peak(hit), peak(crit)
        self.assertGreater(normal, 0)
        self.assertGreater(big, normal)
        self.assertLessEqual(normal, round(cell * camera.SHAKE_AMPLITUDE))
        self.assertLessEqual(big, round(cell * camera.CRIT_SHAKE_AMPLITUDE))
        # Not just the map's shake again: the sprite has its own draws.
        shake = camera.shake_for(hit)
        self.assertNotEqual(
            [camera.sprite_shake_offset(shake, i / 10, cell) for i in range(10)],
            [camera.shake_offset(shake, i / 10, cell) for i in range(10)],
        )

    def test_health_bar_moves_with_the_shaking_sprite(self):
        from render.pygame_render import HEALTH_BAR_COLORS

        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        still = r.health_bar_rect(goblin, state.player, map_rect)
        r._jolt = (goblin, (3, -2))
        try:
            moved = r.health_bar_rect(goblin, state.player, map_rect)
        finally:
            r._jolt = None
        self.assertEqual(moved, still.move(3, -2))
        # Painted with the goblin jolted: the bar is drawn at the moved rect.
        r.canvas.clear()
        r._jolt = (goblin, (3, -2))
        r._paint_game(state)
        self.assertIsNone(r._jolt)  # one frame only
        self.assertTrue(set(cell_pixels(r, moved)) <= HEALTH_BAR_COLORS)
        r.canvas.clear()
        r._paint_game(state)
        self.assertTrue(set(cell_pixels(r, still)) <= HEALTH_BAR_COLORS)

    # -- health bars ----------------------------------------------------------

    def bar(self, state, goblin):
        r = self.renderer
        r.draw(state)
        return r.health_bar_rect(goblin, state.player, r.layout.map_rect())

    def fill_width(self, rect, color):
        y = rect.centery
        screen = self.renderer.canvas.surface
        return sum(
            1 for x in range(rect.left, rect.right) if tuple(screen.get_at((x, y)))[:3] == color
        )

    def test_bar_fill_is_proportional_banded_and_only_bar_colours(self):
        from render.pygame_render import (
            HEALTH_AMBER,
            HEALTH_BAR_COLORS,
            HEALTH_GREEN,
            HEALTH_RED,
        )

        state, goblin = self.fight()
        for hp, color in (
            (20, HEALTH_GREEN),
            (11, HEALTH_GREEN),
            (10, HEALTH_AMBER),
            (5, HEALTH_AMBER),
            (4, HEALTH_RED),
        ):
            goblin.hp = hp
            rect = self.bar(state, goblin)
            self.assertEqual(self.fill_width(rect, color), round(rect.width * hp / 20), hp)
        goblin.hp = 20
        self.assertEqual(
            self.fill_width(self.bar(state, goblin), HEALTH_GREEN), self.bar(state, goblin).width
        )
        for hp in (20, 10, 3):
            goblin.hp = hp
            rect = self.bar(state, goblin)
            self.assertTrue(set(cell_pixels(self.renderer, rect)) <= HEALTH_BAR_COLORS)

    def test_bar_sits_above_the_cell_and_never_on_the_player(self):
        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        cell = r._map_cell_rect(goblin.x, goblin.y)
        far = collections.namedtuple('P', 'x y')(goblin.x + 5, goblin.y)
        above = r.health_bar_rect(goblin, far, map_rect)
        self.assertLessEqual(above.bottom, cell.top)
        self.assertLess(above.width, cell.width)
        # The player in the cell above: the bar moves onto the goblin's own top edge.
        player = collections.namedtuple('P', 'x y')(goblin.x, goblin.y - 1)
        own = r.health_bar_rect(goblin, player, map_rect)
        self.assertTrue(cell.contains(own))
        self.assertFalse(own.colliderect(r._map_cell_rect(player.x, player.y)))
        # Top row of the map: along its top edge too.
        top = Monster(goblin.x, 0, 'goblin')
        self.assertTrue(r._map_cell_rect(top.x, 0).contains(r.health_bar_rect(top, far, map_rect)))

    def goblin_below_player(self, char_class='warrior'):
        """A fight with the goblin in the cell straight below the player --
        where the player's ability bar hangs."""
        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        px, py = state.player.x, state.player.y
        state.game_map[py + 1][px] = '.'
        goblin = Monster(px, py + 1, 'goblin')
        goblin.hp, goblin.max_hp = 9, 20
        state.entities = [state.player, goblin]
        state.update_fov()
        return state, goblin

    def test_bar_is_not_covered_with_the_player_straight_above(self):
        """The player's ability bar (parry or restock) hangs under its cell,
        i.e. over the top of the goblin's cell below -- where the goblin's own
        bar goes when the player stands above it. Both stay whole: the
        health bar on top, clear of the ability bar."""
        from render.pygame_render import HEALTH_BAR_COLORS, RESTOCK_FILL

        r = self.renderer
        for char_class in ('warrior', 'archer'):
            with self.subTest(char_class=char_class):
                state, goblin = self.goblin_below_player(char_class)
                if char_class == 'archer':
                    state.restock_progress = 1
                r.draw(state)
                bar = r.health_bar_rect(goblin, state.player, r.layout.map_rect())
                self.assertTrue(r._map_cell_rect(goblin.x, goblin.y).contains(bar))
                self.assertTrue(set(cell_pixels(r, bar)) <= HEALTH_BAR_COLORS, char_class)
                ability = r.restock_bar_rect(state.player)
                self.assertFalse(bar.colliderect(ability.inflate(2, 2)), (bar, ability))
                self.assertIn(RESTOCK_FILL, cell_pixels(r, ability))

    def test_health_bars_are_painted_after_everything_else_on_the_map(self):
        """Swing, flight, impact (which repaints a killed victim's sprite),
        guard and the player's ability bar all go under the health bars; the
        hit shake still moves them."""
        state, goblin = self.goblin_below_player()
        from render.pygame_render import HEALTH_BAR_COLORS

        r = self.renderer
        r.draw(state)  # sets the view
        state.attack(state.player, goblin)
        hit = state.hits()[-1]
        swing = camera.Swing(
            hit,
            (state.player.x, state.player.y),
            (goblin.x, goblin.y),
            camera.SWING_SHAPES['long'],
        )
        flight = camera.Flight([[(state.player.x, state.player.y), (goblin.x, goblin.y)]], 1)
        parry = collections.namedtuple('Parry', 'x y')(state.player.x, state.player.y)
        shake = (2, 1)
        r.canvas.clear()
        r._paint_game(state)
        bar = r.health_bar_rect(goblin, state.player, r.layout.map_rect())
        quiet_pixels = cell_pixels(r, bar, as_list=True)
        self.assertTrue(set(quiet_pixels) <= HEALTH_BAR_COLORS)  # the bar on its own
        r.canvas.clear()
        r._paint_game(
            state,
            impact=(hit._replace(killed=True), 0.3),
            shake=shake,
            sprite_shake=camera.shake_for(hit),
            flight=(flight, 0.5),
            swing=(swing, 0.5),
            guard=(parry, 0.2),
        )
        # The effects cross the bar's cell, yet only bar colours are left on
        # it -- and it has moved with the shake.
        jolt = r.sprite_shake_offset(camera.shake_for(hit), 0.3, hit)  # the bar rides the sprite
        moved = bar.move(jolt).move(shake)
        self.assertEqual(cell_pixels(r, moved, as_list=True), quiet_pixels)

    def test_boss_bar_is_wider_and_bars_follow_the_zoom(self):
        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        far = collections.namedtuple('P', 'x y')(goblin.x + 5, goblin.y)
        boss = Monster(goblin.x, goblin.y, 'goblin', is_boss=True)
        self.assertGreater(
            r.health_bar_rect(boss, far, map_rect).width,
            r.health_bar_rect(goblin, far, map_rect).width,
        )
        normal = r.health_bar_rect(goblin, far, map_rect)
        state, goblin = self.fight(zoom=True)
        self.assertIsNotNone(r._view)
        r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            zoomed = r.health_bar_rect(goblin, far, map_rect)
            cell = r._map_cell_rect(goblin.x, goblin.y)
        finally:
            r._proj = None
        self.assertGreater(zoomed.width, normal.width)
        self.assertEqual(zoomed.centerx, cell.centerx)

    def test_no_bar_for_the_player_or_an_unseen_monster(self):
        from render.pygame_render import HEALTH_BAR_COLORS

        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        goblin_bar = r.health_bar_rect(goblin, state.player, map_rect)
        player_bar = r.health_bar_rect(state.player, goblin, map_rect)  # where one would go
        r.draw(state)
        self.assertTrue(set(cell_pixels(r, goblin_bar)) <= HEALTH_BAR_COLORS)
        self.assertFalse(set(cell_pixels(r, player_bar)) <= HEALTH_BAR_COLORS)
        state.visible[goblin.y][goblin.x] = False  # remembered, not in view
        state.seen[goblin.y][goblin.x] = True
        r.draw(state)
        self.assertFalse(set(cell_pixels(r, goblin_bar)) <= HEALTH_BAR_COLORS)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GlyphModeSpriteShakeTest(unittest.TestCase):
    """The struck sprite's own shake with no tileset: glyphs, not tiles."""

    fight = HitShakeAndHealthBarTest.fight
    impact_frame = HitShakeAndHealthBarTest.impact_frame
    assert_sprite_shakes = HitShakeAndHealthBarTest.assert_sprite_shakes
    test_the_struck_monster_or_player_shakes_in_its_cell = (
        HitShakeAndHealthBarTest.test_the_struck_monster_or_player_shakes_in_its_cell
    )
    test_the_struck_sprite_shakes_zoomed_in = (
        HitShakeAndHealthBarTest.test_the_struck_sprite_shakes_zoomed_in
    )

    def setUp(self):
        self.renderer = PygameRenderer(WIDTH, HEIGHT)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = 0
        self.assertFalse(self.renderer.layout.tile)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ChestChoiceScreenTest(unittest.TestCase):
    """The "choose one of three" overlay: drawn while state.is_choosing,
    answered with 1/2/3 or a left click on a card."""

    tiles = False

    def setUp(self):
        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        self.new_choice()

    def tearDown(self):
        self.renderer.close()

    def choice_items(self):
        from game.item import JUNK, Item

        return [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'epic'), Item(0, 0, JUNK)]

    def new_choice(self):
        """A fresh state with self.items on the choice screen."""
        self.state = GameState(WIDTH, HEIGHT, seed=70)
        self.items = self.choice_items()
        self.state.pending_choice = list(self.items)

    def click(self, pos, button=1):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def skip_rect(self):
        return screens.choice_skip_rect(self.renderer.layout, self.state)

    def test_frame_while_choosing_differs_from_one_without(self):
        box = screens.choice_rects(self.renderer.layout, self.state)[0]
        self.renderer.draw(self.state)
        with_choice = cell_pixels(self.renderer, box, as_list=True)
        pending, self.state.pending_choice = self.state.pending_choice, None
        self.renderer.draw(self.state)
        without = cell_pixels(self.renderer, box, as_list=True)
        self.state.pending_choice = pending
        self.assertNotEqual(with_choice, without)

    def test_three_cards_apart_and_the_skip_line_under_them_inside_the_box(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        for i, card in enumerate(cards):
            self.assertTrue(box.contains(card))
            for other in cards[i + 1 :]:
                self.assertFalse(card.colliderect(other))
        skip = self.skip_rect()
        self.assertTrue(box.contains(skip))
        for card in cards:
            self.assertFalse(skip.colliderect(card))
            self.assertLessEqual(card.bottom, skip.top)
        self.renderer.draw(self.state)
        self.assertGreater(len(cell_pixels(self.renderer, skip)), 1)  # text drawn

    def test_clicking_the_second_card_or_pressing_2_chooses_it(self):
        for how in ('click', 'key 2'):
            with self.subTest(how):
                self.new_choice()
                self.renderer.draw(self.state)
                if how == 'click':
                    self.click(self.cards()[1].center)
                else:
                    pygame.event.post(key(pygame.K_2, '2'))
                action = self.renderer.get_action()
                self.assertEqual(action, Action.CHOOSE_2)
                self.state.handle_action(action)
                self.assertFalse(self.state.is_choosing)
                self.assertIs(self.state.player.weapon, self.items[1])
                self.assertIsNone(self.state.player.armor)

    def test_clicking_outside_the_cards_does_nothing(self):
        self.renderer.draw(self.state)
        box = screens.choice_rects(self.renderer.layout, self.state)[0]
        self.click((box.left + 2, box.top + 2))  # the box, not a card
        self.click((0, 0))  # off the box entirely
        self.click(self.cards()[0].center, button=3)  # right click
        pygame.event.post(
            pygame.event.Event(
                pygame.MOUSEMOTION, pos=self.cards()[0].center, rel=(1, 1), buttons=(0, 0, 0)
            )
        )
        pygame.event.post(key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        self.assertTrue(self.state.is_choosing)

    def test_card_clicks_mean_nothing_once_the_choice_is_made(self):
        self.renderer.draw(self.state)
        center = self.cards()[0].center
        self.state.choose(2)
        self.renderer.draw(self.state)
        self.click(center)
        pygame.event.post(key(pygame.K_d, 'd'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_space_or_clicking_the_skip_line_skips(self):
        for how in ('space', 'click'):
            with self.subTest(how):
                self.new_choice()
                self.renderer.draw(self.state)
                weapon = self.state.player.weapon
                if how == 'space':
                    pygame.event.post(key(pygame.K_SPACE, ' '))
                else:
                    self.click(self.skip_rect().center)
                action = self.renderer.get_action()
                self.assertEqual(action, Action.SKIP)
                self.assertFalse(self.state.handle_action(action))  # no turn
                self.assertFalse(self.state.is_choosing)
                self.assertIs(self.state.player.weapon, weapon)
                self.assertIsNone(self.state.player.armor)
        # With no choice on screen, Space is the wait key again.
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_SPACE, ' '))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)

    def test_narrow_map_stacks_the_cards(self):
        renderer = self.renderer
        renderer._set_mode((420, 700), pygame.RESIZABLE)
        renderer._relayout()
        box, cards, compact = screens.choice_rects(renderer.layout, self.state)
        if compact:
            self.assertTrue(cards[0].bottom <= cards[1].top <= cards[1].bottom <= cards[2].top)
        skip = screens.choice_skip_rect(renderer.layout, self.state)
        self.assertLessEqual(cards[-1].bottom, skip.top)
        self.assertLessEqual(skip.bottom, box.bottom)
        renderer.draw(self.state)  # paints without error either way


class TileModeChestChoiceScreenTest(ChestChoiceScreenTest):
    tiles = True


class NewWeaponChoiceScreenTest(ChestChoiceScreenTest):
    """The same overlay with the longest weapon-type cards on it."""

    def choice_items(self):
        from game.item import JUNK, Item

        return [
            Item(0, 0, 'great_sword', 'rare'),
            Item(0, 0, 'rapier', 'epic'),
            Item(0, 0, JUNK),
        ]


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BoonChoiceScreenTest(unittest.TestCase):
    """A shrine's boons on the same overlay as a chest's items: painted in
    glyph and tile mode, chosen with a key or a click on a card; and the
    shrine itself painted on the map."""

    tiles = False

    def setUp(self):
        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        self.new_choice()

    def tearDown(self):
        self.renderer.close()

    def new_choice(self):
        from game.shrine import BOONS

        self.state = GameState(WIDTH, HEIGHT, seed=71)
        self.boons = [BOONS['blood_pact'], BOONS['iron_skin'], BOONS['quick_hands']]
        self.state.pending_choice = list(self.boons)

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def test_boon_cards_paint_inside_the_box(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        self.renderer.draw(self.state)
        for card in cards:
            self.assertTrue(box.contains(card))
            self.assertGreater(len(cell_pixels(self.renderer, card)), 2)  # inked text

    def test_clicking_a_boon_card_or_its_key_takes_that_boon(self):
        for how, boon in (('click the second card', 'iron_skin'), ('key 3', 'quick_hands')):
            with self.subTest(how):
                self.new_choice()
                self.renderer.draw(self.state)
                if how.startswith('click'):
                    pygame.event.post(
                        pygame.event.Event(
                            pygame.MOUSEBUTTONDOWN, pos=self.cards()[1].center, button=1
                        )
                    )
                    action = self.renderer.get_action()
                    self.assertEqual(action, Action.CHOOSE_2)
                else:
                    pygame.event.post(key(pygame.K_3, '3'))
                    action = self.renderer.get_action()
                self.assertFalse(self.state.handle_action(action))  # no turn
                self.assertFalse(self.state.is_choosing)
                self.assertEqual(self.state.player.boons, [boon])

    def test_space_skips_a_boon_choice(self):
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_SPACE, ' '))
        self.state.handle_action(self.renderer.get_action())
        self.assertFalse(self.state.is_choosing)
        self.assertEqual(self.state.player.boons, [])

    def test_shrine_is_painted_on_the_map(self):
        from game.shrine import Shrine

        state = self.state
        state.pending_choice = None
        x, y = open_neighbour(state)
        self.renderer.draw(state)
        rect = self.renderer._map_cell_rect(x, y)
        floor = cell_pixels(self.renderer, rect, as_list=True)
        state.entities.append(Shrine(x, y))
        self.renderer.draw(state)
        self.assertNotEqual(cell_pixels(self.renderer, rect, as_list=True), floor)


class TileModeBoonChoiceScreenTest(BoonChoiceScreenTest):
    tiles = True


class ChoiceCardTextTest(unittest.TestCase):
    """render/choice.py's card text (stdlib only: no pygame needed)."""

    def text(self, kind, rarity='common'):
        from game.item import Item
        from render import choice

        return choice.stat_text(Item(0, 0, kind, rarity))

    def test_each_kind_at_each_rarity(self):
        expected = {
            'weapon': ['+1 damage', '+2 damage', '+4 damage', '+7 damage'],
            'armor': ['+3 defence', '+6 defence', '+12 defence', '+21 defence'],
            'leather': [
                '+2 defence, 4% dodge',
                '+3 defence, 6% dodge',
                '+6 defence, 9% dodge',
                '+10 defence, 12% dodge',
            ],
            'war_axe': [
                '+0 damage, +3 HP',
                '+1 damage, +6 HP',
                '+3 damage, +9 HP',
                '+6 damage, +15 HP',
            ],
            'rapier': [
                '-1 damage, strikes twice',
                '+0 damage, strikes twice',
                '+2 damage, strikes twice',
                '+5 damage, strikes twice',
            ],
            'great_sword': [
                '+2 damage, hits a 2nd adjacent foe',
                '+3 damage, hits a 2nd adjacent foe',
                '+5 damage, hits a 2nd adjacent foe',
                '+8 damage, hits a 2nd adjacent foe',
            ],
            'sword_shield': [
                '+1 damage, +3 defence',
                '+2 damage, +6 defence',
                '+4 damage, +9 defence',
                '+7 damage, +12 defence',
            ],
            'dagger': [
                '+0 damage, +5% crit',
                '+1 damage, +10% crit',
                '+3 damage, +15% crit',
                '+6 damage, +20% crit',
            ],
            'spear': [
                '+1 damage, reach 2',
                '+2 damage, reach 2',
                '+4 damage, reach 2',
                '+7 damage, reach 2',
            ],
            'longbow': [
                '+0 damage, pierces 2',
                '+1 damage, pierces 2',
                '+3 damage, pierces 3',
                '+6 damage, pierces 4',
            ],
            'heavy_crossbow': [
                '+3 damage, reload 2',
                '+4 damage, reload 2',
                '+6 damage, reload 1',
                '+9 damage, reload 1',
            ],
            'volley_bow': [
                '-1 damage, +2 arrows at 50%',
                '+0 damage, +2 arrows at 50%',
                '+2 damage, +3 arrows at 60%',
                '+5 damage, +3 arrows at 70%',
            ],
            'sling': [
                '+0 damage, knockback 1',
                '+1 damage, knockback 1',
                '+3 damage, knockback 2',
                '+6 damage, knockback 2',
            ],
            'hunters_bow': [
                '+0 damage, mark +25%',
                '+1 damage, mark +50%',
                '+3 damage, mark +75%',
                '+6 damage, mark +100%',
            ],
            'quickdraw': [
                '+1 damage, every 4 shots free',
                '+2 damage, every 4 shots free',
                '+4 damage, every 3 shots free',
                '+7 damage, every 2 shots free',
            ],
            'fencing_sword': [
                '+0 damage, riposte x2',
                '+1 damage, riposte x2.15',
                '+3 damage, riposte x2.3',
                '+6 damage, riposte x2.5',
            ],
            'hand_crossbow': [
                '+0 damage, hop-shot',
                '+1 damage, hop-shot',
                '+3 damage, hop-shot',
                '+6 damage, hop-shot',
            ],
        }
        from game.item import GEAR_KINDS, RARITIES

        self.assertEqual(set(expected), set(GEAR_KINDS))
        for kind, lines in expected.items():
            self.assertEqual([self.text(kind, r) for r in RARITIES], lines, kind)

    def test_card_lines_for_junk_and_for_a_new_kind(self):
        from game.item import JUNK, Item
        from render import choice

        junk = Item(0, 0, JUNK)
        self.assertEqual(choice.stat_text(junk), 'nothing useful')
        self.assertEqual(
            choice.card_lines(3, junk), ['[3]', 'Rusty scrap', 'junk', 'nothing useful']
        )
        # A new kind's card: its name and rarity.
        item = Item(0, 0, 'dagger', 'rare')
        self.assertEqual(
            choice.card_lines(1, item), ['[1]', item.name, 'rare', '+3 damage, +15% crit']
        )
        self.assertIn('+15% crit', choice.compact_lines(1, item)[1])

    def test_skip_line_for_a_chest_and_for_a_shrine(self):
        from game.item import Item
        from game.shrine import BOONS
        from render import choice
        from render.base import Action

        self.assertEqual(choice.skip_line([Item(0, 0, 'weapon')]), '[Space] Skip: leave the chest')
        self.assertEqual(choice.skip_line([BOONS['iron_skin']]), '[Space] Skip: leave the shrine')
        self.assertEqual(choice.SKIP_ACTION, Action.SKIP)
        self.assertIn('space', choice.HINT)
        self.assertNotIn('4', choice.HINT)


# -- helpers -----------------------------------------------------------------


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BossArenaTest(unittest.TestCase):
    """Dark stone in the arena's 3x3 centre and blood decals round the room
    (a stub `boss_arena` stands in for the one game/ provides)."""

    class Arena:
        x1, y1, x2, y2 = 8, 4, 28, 16

        def center(self):
            return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(
            WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')), combat_zoom=False
        )
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.arena = self.Arena()

    def tearDown(self):
        self.renderer.close()

    def state(self, arena):
        state = GameState(WIDTH, HEIGHT, seed=0)
        state.entities[:] = []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                edge = x in (0, WIDTH - 1) or y in (0, HEIGHT - 1)
                state.game_map[y][x] = '#' if edge else '.'
                state.visible[y][x] = state.seen[y][x] = True
        state.player.x, state.player.y = 1, 1
        state.boss_arena = arena
        return state

    def frame(self, arena):
        self.renderer.draw(self.state(arena))
        return self.renderer.canvas.surface.copy()

    def cell(self, surface, x, y):
        rect = self.renderer._map_cell_rect(x, y)
        return pygame.image.tobytes(surface.subsurface(rect), 'RGB')

    def decal_cells(self):
        layout = self.renderer._arena_decals(self.arena)
        return sorted(layout)

    def test_centre_stone_and_decal_cells_differ_from_plain_floor(self):
        plain, arena = self.frame(None), self.frame(self.arena)
        cx, cy = self.arena.center()
        self.assertNotEqual(self.cell(plain, cx, cy), self.cell(arena, cx, cy))

        # The tint is darker, not just different.
        def total(b):
            return sum(b)

        self.assertLess(total(self.cell(arena, cx, cy)), total(self.cell(plain, cx, cy)))
        # Decals outside the 3x3 centre change their cells too.
        changed = [
            c
            for c in self.decal_cells()
            if max(abs(c[0] - cx), abs(c[1] - cy)) > 1
            and self.cell(plain, *c) != self.cell(arena, *c)
        ]
        self.assertTrue(changed)

    def test_decals_are_stable_across_draws(self):
        first, second = self.frame(self.arena), self.frame(self.arena)
        self.assertEqual(pygame.image.tobytes(first, 'RGB'), pygame.image.tobytes(second, 'RGB'))
        layout = dict(self.renderer._arena_decals(self.arena))
        self.renderer._decal_layouts.clear()
        self.assertEqual(layout, self.renderer._arena_decals(self.arena))

    def test_no_arena_is_the_plain_frame(self):
        plain = self.frame(None)
        state = self.state(None)
        del state.boss_arena
        self.renderer.draw(state)
        self.assertEqual(
            pygame.image.tobytes(plain, 'RGB'),
            pygame.image.tobytes(self.renderer.canvas.surface, 'RGB'),
        )

    def test_decals_stay_off_walls(self):
        state = self.state(self.arena)
        cx, cy = self.arena.center()
        # A cell the arena really decorates (so the wall below would be marked
        # if decals didn't stop at it), made into a wall.
        x, y = next(c for c in self.decal_cells() if max(abs(c[0] - cx), abs(c[1] - cy)) > 1)
        state.game_map[y][x] = '#'
        self.renderer.draw(state)
        wall = self.cell(self.renderer.canvas.surface, x, y)
        state.boss_arena = None
        self.renderer.draw(state)
        self.assertEqual(wall, self.cell(self.renderer.canvas.surface, x, y))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ArcherVisualsTest(unittest.TestCase):
    """The archer in the window, in tile mode: an arrow flying to each hit
    before its impact, the restock bar under the player, and arrow piles."""

    TILES = True

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        tileset = Tileset(resource_path('assets')) if self.TILES else None
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = 0
        pygame.event.clear()
        patcher = mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = self.arena()
        self.renderer.draw(self.state)

    def tearDown(self):
        self.renderer.close()

    @staticmethod
    def arena(char_class='archer'):
        from game.item import Item

        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        for y in range(1, HEIGHT - 1):
            for x in range(1, WIDTH - 1):
                state.game_map[y][x] = '.'
        state.player.x, state.player.y = 10, 10
        # A plain single-target weapon, not the archer's starting longbow.
        state.player.weapon = Item(0, 0, 'weapon', 'common')
        state.entities = [state.player]
        state.update_fov()
        return state

    def goblin(self, x, y, hp=1000):
        goblin = Monster(x, y, 'goblin')
        goblin.hp = goblin.max_hp = hp
        self.state.entities.append(goblin)
        self.state.update_fov()
        return goblin

    def played(self):
        """(beats, played_out) for draw(self.state): the beats the Director
        stages, and whether a key typed ahead left them all to run to the end
        (and still queued for get_action)."""
        r = self.renderer
        beats, elapsed, kept = play_with_key_typed_ahead(r, self.state)
        total = sum(beat_ms(r, beat) for beat in beats)
        return beats, kept and elapsed >= total - 20 * len(beats)

    @staticmethod
    def kinds(beats):
        return [
            'flight' if isinstance(b, camera.Flight) else 'impact'
            for b in beats
            if isinstance(b, (camera.Flight, camera.Impact))
        ]

    @staticmethod
    def flight_of(path):
        """A one-arrow Flight over the whole of `path`."""
        return camera.Flight((tuple(path),), len(path) - 1)

    # -- flight ---------------------------------------------------------------

    def test_a_shot_plays_its_flight_then_the_impact(self):
        from render.pygame_render import FLIGHT_MS

        goblin = self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        beats, played_out = self.played()
        self.assertEqual(self.kinds(beats), ['flight', 'impact'])
        flight, impact = beats
        self.assertEqual(beat_ms(self.renderer, flight), 4 * FLIGHT_MS)
        self.assertTrue(played_out)  # the key waits; no beat is cut short
        self.assertEqual(flight.paths[0][-1], (goblin.x, goblin.y))
        self.assertIs(impact.hit.defender, goblin)

    def test_a_pierce_shots_second_impact_follows_the_second_flight(self):
        from game.item import Item

        Item(0, 0, 'longbow', 'common').apply(self.state.player, self.state.log)
        first, second = self.goblin(12, 10), self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        beats, _ = self.played()
        self.assertEqual(self.kinds(beats), ['flight', 'impact', 'flight', 'impact'])
        self.assertEqual(beats[0].paths[0][-1], (12, 10))
        self.assertIs(beats[1].hit.defender, first)
        self.assertEqual(beats[2].paths, (((12, 10), (13, 10), (14, 10)),))
        self.assertIs(beats[3].hit.defender, second)

    def test_a_miss_flies_to_the_pile_with_no_impact(self):
        self.state.game_map[10][14] = '#'
        self.state.handle_action('shoot_e')
        beats, _ = self.played()
        self.assertEqual(self.kinds(beats), ['flight'])
        self.assertEqual(beats[0].paths[0][-1], (13, 10))
        self.assertIsNotNone(self.state.arrows_at(13, 10))

    def test_the_arrow_is_drawn_along_its_path_pointing_the_way_it_flies(self):
        r = self.renderer
        self.state.game_map[10][16] = '#'
        self.state.handle_action('shoot_e')
        flight = self.flight_of(self.state.events_of(Shot)[0].path)
        ((centre, angle),) = r.flight_points(flight, 0.5)
        self.assertEqual(angle, 0)  # east
        self.assertEqual(r.flight_points(flight, 1.0)[0][0], r._map_cell_rect(15, 10).center)
        self.assertEqual(r.flight_points(self.flight_of(((5, 5), (5, 4))), 0.5)[0][1], 90)
        r.canvas.clear()
        r._paint_game(self.state)
        without = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(self.state, flight=(flight, 0.5))
        around = pygame.Rect(0, 0, 8, 8)
        around.center = centre
        self.assertNotEqual(area_bytes(r.canvas.surface, around), area_bytes(without, around))

    def test_the_arrow_is_drawn_under_the_impact(self):
        from render.pygame_render import ARROW_HEAD, ARROW_SHAFT

        goblin = self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        r = self.renderer
        hit = self.state.hits()[-1]
        flight = self.flight_of(self.state.events_of(Shot)[0].path)
        self.assertIs(hit.defender, goblin)
        cell = r._map_cell_rect(goblin.x, goblin.y)

        def arrow_pixels(**effects):
            r.canvas.clear()
            r._paint_game(self.state, **effects)
            return sum(
                1 for p in cell_pixels(r, cell, as_list=True) if p in (ARROW_HEAD, ARROW_SHAFT)
            )

        over_goblin = arrow_pixels(flight=(flight, 1.0))
        self.assertGreater(over_goblin, 0)  # the arrow is on top of the goblin's sprite
        # The impact's flash lands on the arrow, tinting it: it goes under.
        under_impact = arrow_pixels(impact=(hit, 0.1), flight=(flight, 1.0))
        self.assertLessEqual(under_impact, over_goblin // 4)

    def test_a_monster_killed_by_the_arrow_stays_on_screen_until_it_lands(self):
        goblin = self.goblin(13, 10, hp=1)
        r = self.renderer
        r.draw(self.state)
        alive = area_bytes(r.canvas.surface, r._map_cell_rect(13, 10))
        self.state.handle_action('shoot_e')
        self.assertFalse(goblin.alive)
        with captured_frames(r) as frames:
            r.draw(self.state)
        # Seen on the screen: the goblin is still standing while the arrow
        # flies, and gone from the frame draw() ends on.
        cell = r._map_cell_rect(13, 10)

        def differing(frame):
            was = pygame.image.frombytes(alive, cell.size, 'RGB')
            now = frame.subsurface(cell)
            return sum(
                1
                for x in range(cell.w)
                for y in range(cell.h)
                if was.get_at((x, y)) != now.get_at((x, y))
            )

        self.assertLess(differing(frames[0]), cell.w * cell.h // 10)  # still there
        self.assertGreater(differing(frames[-1]), cell.w * cell.h // 4)  # gone
        hit = self.state.hits()[-1]
        drawn = self.renderer._before_hits(self.state, self.state.visible_entities(), [hit])
        ghost = [e for e in drawn if isinstance(e, Monster)]
        self.assertEqual(len(ghost), 1)
        self.assertEqual((ghost[0].x, ghost[0].y, ghost[0].hp), (13, 10, 1))
        self.assertTrue(ghost[0].alive)
        self.assertFalse(goblin.alive)  # the state itself is untouched

    def test_keys_pressed_during_a_flight_wait_until_it_ends(self):
        r = self.renderer
        r.impact_ms = 0
        self.state.game_map[10][16] = '#'
        self.state.handle_action('shoot_e')  # five cells to fly
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]

        def type_ahead():
            for event in typed:
                pygame.event.post(event)

        start = pygame.time.get_ticks()
        with captured_frames(r, on_first=type_ahead) as shown:
            r.draw(self.state)
        elapsed = pygame.time.get_ticks() - start
        self.assertGreaterEqual(elapsed, 5 * r.flight_ms - 20)  # not cut short
        self.assertGreaterEqual(len(shown), 2)  # flight frame(s), then the final one
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))  # not consumed
        self.assertEqual(r.get_action(), Action.MOVE_E)
        self.assertEqual(r.get_action(), Action.MOVE_S)

    def volley(self):
        from game.item import Item

        Item(0, 0, 'volley_bow', 'common').apply(self.state.player, self.state.log)

    def test_a_volley_flies_all_its_arrows_at_once(self):
        self.volley()
        near, far = self.goblin(12, 9), self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        shot = self.state.events_of(Shot)[0]
        self.assertEqual(len(shot.arrows), 3)
        beats, played_out = self.played()
        kinds = self.kinds(beats)
        self.assertEqual(kinds[0], 'flight')
        self.assertTrue(played_out)  # keys wait in the queue
        first = beats[0]
        # One beat, all three arrows, each from the player's cell.
        self.assertEqual(len(first.paths), 3)
        self.assertEqual({p[0] for p in first.paths}, {(10, 10)})
        # Each arrow's impact comes after the flight that brings it there.
        impacts = [i for i, k in enumerate(kinds) if k == 'impact']
        struck = [beats[i].hit.defender for i in impacts]
        self.assertEqual(struck[:2], [near, far])
        for i in impacts:
            self.assertEqual(kinds[i - 1], 'flight')
            hit = beats[i].hit
            self.assertIn((hit.x, hit.y), {p[-1] for p in beats[i - 1].paths})
        # The near goblin's impact: the aim arrow hangs in the air meanwhile.
        self.assertIn(shot.path[2], {p[-1] for p in beats[impacts[0]].held})

    def test_a_volleys_arrows_are_all_drawn_mid_flight(self):
        r = self.renderer
        self.volley()
        self.state.handle_action('shoot_e')
        beats = camera.Director().plan(self.state)
        flight = beats[0]
        points = r.flight_points(flight, 0.5)
        self.assertEqual(len(points), 3)
        self.assertEqual(len({c for c, _ in points}), 3)  # side by side
        r.canvas.clear()
        r._paint_game(self.state)
        without = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(self.state, flight=(flight, 0.5))
        for centre, _ in points:
            around = pygame.Rect(0, 0, 8, 8)
            around.center = centre
            self.assertNotEqual(area_bytes(r.canvas.surface, around), area_bytes(without, around))

    def test_a_goblin_archers_arrow_flies_and_lands_like_the_archers(self):
        goblin = self.goblin(14, 10)
        self.state.player.hp = 1000
        with mock.patch.object(self.state.rng, 'random', return_value=0.99):  # no dodge
            self.state._monster_shot(goblin)
        beats, played_out = self.played()
        self.assertEqual(self.kinds(beats)[:2], ['flight', 'impact'])
        self.assertTrue(played_out)
        flight = beats[0]
        self.assertEqual(flight.paths, (((14, 10), (13, 10), (12, 10), (11, 10), (10, 10)),))
        self.assertIs(beats[1].hit.defender, self.state.player)
        # The same drawn arrow as the archer's, pointing west, at its size.
        r = self.renderer
        ((_, angle),) = r.flight_points(flight, 0.5)
        self.assertEqual(angle, 180)
        sprites = []
        real = r.arrow_sprite

        def record(*args):
            sprites.append(args)
            return real(*args)

        with mock.patch.object(r, 'arrow_sprite', side_effect=record):
            r._paint_game(self.state, flight=(flight, 0.5))
        self.assertEqual(sprites, [(round(min(r._map_cell_rect(10, 10).size) * 0.9), 180)])

    # -- restock bar ----------------------------------------------------------

    def fill_pixels(self, bar):
        from render.pygame_render import RESTOCK_FILL

        screen = self.renderer.canvas.surface
        y = bar.centery
        return sum(
            1
            for x in range(bar.left, bar.right)
            if tuple(screen.get_at((x, y)))[:3] == RESTOCK_FILL
        )

    def test_restock_bar_fill_is_proportional(self):
        r = self.renderer
        for progress in (0, 1, 2):
            self.state.restock_progress = progress
            r.draw(self.state)
            bar = r.restock_bar_rect(self.state.player)
            self.assertEqual(self.fill_pixels(bar), round(bar.width * progress / 3), progress)
            self.assertEqual(r.restock_fill(bar.width, progress), round(bar.width * progress / 3))
        self.assertEqual(r.restock_fill(30, 3), 30)

    def test_restock_bar_sits_under_the_player_at_one_and_a_half_the_old_size(self):
        from render.pygame_render import (
            RESTOCK_BAR_HEIGHT,
            RESTOCK_BAR_WIDTH,
            RESTOCK_FILL,
            RESTOCK_TRACK,
        )

        r = self.renderer
        cell = r._map_cell_rect(self.state.player.x, self.state.player.y)
        bar = r.restock_bar_rect(self.state.player)
        # Just below the sprite's feet: its rim is the first row under the cell.
        self.assertEqual(bar.top - 1, cell.bottom)
        self.assertFalse(bar.inflate(2, 2).colliderect(cell.inflate(0, -1)))
        self.assertEqual(bar.centerx, cell.centerx)
        # A little wider than the cell: it overhangs both sides evenly.
        self.assertGreaterEqual(bar.width, cell.width)
        self.assertLessEqual(bar.width, cell.width + max(2, cell.width // 10))
        self.assertLessEqual(bar.height, max(3, cell.height // 5))
        # One and a half times the old size:
        self.assertAlmostEqual(RESTOCK_BAR_WIDTH, 1.5 * 0.7)
        self.assertAlmostEqual(RESTOCK_BAR_HEIGHT, 1.5 * 0.1)
        # 1.5x the old 0.7 x 0.1 of the cell (at least 2 px, now 3), to the pixel.
        self.assertEqual(bar.width, round(cell.width * 1.05))
        self.assertEqual(bar.height, max(3, round(cell.height * 0.15)))
        # The 1 px dark rim is painted round it, the fill inside it.
        self.state.restock_progress = 3
        r.canvas.clear()
        r._paint_game(self.state)
        screen = r.canvas.surface
        self.assertEqual(tuple(screen.get_at((bar.left - 1, bar.centery)))[:3], RESTOCK_TRACK)
        self.assertEqual(tuple(screen.get_at((bar.right, bar.centery)))[:3], RESTOCK_TRACK)
        self.assertEqual(tuple(screen.get_at((bar.centerx, bar.top - 1)))[:3], RESTOCK_TRACK)
        self.assertEqual(tuple(screen.get_at(bar.center))[:3], RESTOCK_FILL)

    def test_no_restock_bar_for_a_warrior(self):
        r = self.renderer
        painted = []
        with mock.patch.object(
            r, '_paint_restock_bar', side_effect=lambda *a: painted.append(1)
        ) as paint:
            r.draw(self.state)
            self.assertEqual(painted, [1])
            painted.clear()
            warrior = self.arena('warrior')
            r.draw(warrior)
        self.assertEqual(painted, [])
        self.assertTrue(paint.called)
        # The bar a warrior does get is the parry's: restock_progress (never
        # set for a warrior) doesn't fill it, parry_progress() does.
        warrior.restock_progress = 2
        warrior.last_parry_turn = warrior.turn  # just spent: parry_progress() 0
        r.draw(warrior)
        bar = r.restock_bar_rect(warrior.player)
        self.assertEqual(self.fill_pixels(bar), 0)

    def test_restock_bar_stays_inside_the_map(self):
        r = self.renderer
        map_rect = r.layout.map_rect()
        player = self.state.player
        for x, y in ((0, 0), (1, 1), (WIDTH - 1, HEIGHT - 1), (0, HEIGHT - 1), (WIDTH - 1, 0)):
            player.x, player.y = x, y
            bar = r.restock_bar_rect(player)
            # Its rim too: the overhang never crosses the map's edge.
            self.assertTrue(map_rect.contains(bar.inflate(2, 2)), (x, y))
        player.x = 10
        player.y = 10
        unzoomed = r.restock_bar_rect(player)
        # The combat zoom: the bar follows the projection, still on the map.
        r._view = camera.combat_view(player, collections.namedtuple('P', 'x y')(11, 10))
        r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            bar = r.restock_bar_rect(player)
            cell = r._map_cell_rect(player.x, player.y)
        finally:
            r._proj = None
        self.assertTrue(map_rect.contains(bar.inflate(2, 2)))
        self.assertEqual(bar.centerx, cell.centerx)
        self.assertEqual(bar.top - 1, cell.bottom)  # below the zoomed sprite
        self.assertEqual(bar.width, round(cell.width * 1.05))
        self.assertGreater(bar.width, unzoomed.width)
        self.state.restock_progress = 2
        r.canvas.clear()
        r._paint_game(self.state)  # painted through the projection
        self.assertEqual(self.fill_pixels(bar), round(bar.width * 2 / 3))
        r._view = None

    # -- the warrior's parry bar ----------------------------------------------

    def warrior(self):
        state = self.arena('warrior')
        state.last_parry_turn = state.turn  # Q pressed and the parry spent
        return state

    def test_parry_bar_fills_over_the_cooldown_one_turn_at_a_time(self):
        from game.state import PARRY_COOLDOWN

        r = self.renderer
        state = self.warrior()
        bar = r.restock_bar_rect(state.player)
        fills = []
        for _ in range(PARRY_COOLDOWN + 1):
            r.draw(state)
            fills.append(self.fill_pixels(bar))
            state.handle_action('wait')
            state.cancel_monster_phase()
        self.assertEqual(fills, [round(bar.width * n / PARRY_COOLDOWN) for n in range(5)])
        self.assertEqual(fills[0], 0)
        self.assertEqual(fills[-1], bar.width)
        self.assertEqual(r.parry_fill(bar.width, 2), round(bar.width / 2))

    def test_parry_bar_is_drawn_like_the_restock_bar(self):
        from render.pygame_render import RESTOCK_FILL, RESTOCK_TRACK

        r = self.renderer
        state = self.warrior()
        state.turn += 2  # mid-cooldown
        r.canvas.clear()
        r._paint_game(state)
        bar = r.restock_bar_rect(state.player)
        cell = r._map_cell_rect(state.player.x, state.player.y)
        self.assertEqual(bar.top - 1, cell.bottom)
        self.assertEqual(bar.width, round(cell.width * 1.05))
        self.assertEqual(bar.height, max(3, round(cell.height * 0.15)))
        screen = r.canvas.surface
        self.assertEqual(tuple(screen.get_at((bar.left - 1, bar.centery)))[:3], RESTOCK_TRACK)
        self.assertEqual(tuple(screen.get_at((bar.centerx, bar.top - 1)))[:3], RESTOCK_TRACK)
        self.assertEqual(tuple(screen.get_at((bar.left, bar.centery)))[:3], RESTOCK_FILL)
        self.assertEqual(tuple(screen.get_at((bar.right - 1, bar.centery)))[:3], RESTOCK_TRACK)
        self.assertEqual(self.fill_pixels(bar), round(bar.width / 2))

    def test_parry_bar_is_full_when_ready_and_when_armed_and_the_archer_has_none(self):
        r = self.renderer
        state = self.arena('warrior')  # never used: ready
        bar = r.restock_bar_rect(state.player)
        r.draw(state)
        self.assertEqual(self.fill_pixels(bar), bar.width)
        self.assertTrue(state.handle_action('ability'))  # armed, on this very turn
        state.cancel_monster_phase()
        self.assertTrue(state.parry_armed)
        r.draw(state)
        self.assertEqual(self.fill_pixels(bar), bar.width)
        # No parry bar for the archer: its bar is the (empty) restock bar --
        # a parry bar, always ready here, would be full.
        r.draw(self.state)
        self.assertEqual(self.fill_pixels(r.restock_bar_rect(self.state.player)), 0)

    def test_parry_bar_stays_inside_the_map_and_follows_the_zoom(self):
        r = self.renderer
        map_rect = r.layout.map_rect()
        state = self.warrior()
        player = state.player
        screen = r.canvas.surface
        from render.pygame_render import RESTOCK_TRACK

        for x, y in ((0, 0), (5, 0), (WIDTH - 1, 0), (0, HEIGHT - 1), (WIDTH - 1, HEIGHT - 1)):
            player.x, player.y = x, y
            r.canvas.clear()
            r._paint_game(state)
            bar = r.restock_bar_rect(player)
            self.assertTrue(map_rect.contains(bar.inflate(2, 2)), (x, y))
            self.assertEqual(tuple(screen.get_at((bar.left - 1, bar.centery)))[:3], RESTOCK_TRACK)
        player.x, player.y = 10, 10
        state.turn += 3
        r._view = camera.combat_view(player, collections.namedtuple('P', 'x y')(11, 10))
        r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            bar = r.restock_bar_rect(player)
            cell = r._map_cell_rect(player.x, player.y)
        finally:
            r._proj = None
        self.assertTrue(map_rect.contains(bar.inflate(2, 2)))
        self.assertEqual(bar.width, round(cell.width * 1.05))
        r.canvas.clear()
        r._paint_game(state)  # painted through the projection
        self.assertEqual(self.fill_pixels(bar), round(bar.width * 3 / 4))
        r._view = None

    # -- arrow piles ----------------------------------------------------------

    def test_an_arrow_pile_is_painted_over_the_floor(self):
        from game.quiver import ArrowPile

        r = self.renderer
        floor = r._map_cell_rect(13, 13)
        plain = cell_pixels(r, floor, as_list=True)
        self.state.entities.insert(1, ArrowPile(13, 13))
        r.draw(self.state)
        painted = cell_pixels(r, floor, as_list=True)
        changed = sum(1 for a, b in zip(plain, painted) if a != b)
        self.assertGreater(changed, len(plain) // 10)  # clearly there, not a speck
        self.assert_arrow_look(painted)

    # -- gold -----------------------------------------------------------------

    ARROWS = 'arrow-sprite'

    def painted_chars(self):
        """Tile mode: the chars one draw() asks the tileset for, in paint
        order (an arrow pile's drawn arrow shows as ARROWS). The real painting
        runs; the tileset's public glyph() is only listened to. (Glyph mode
        has no such seam -- its tests compare pixels.)"""
        r = self.renderer
        painted = []
        real_arrow = r.arrow_sprite

        def arrow(*args):
            painted.append(self.ARROWS)
            return real_arrow(*args)

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(r, 'arrow_sprite', arrow))
            real_glyph = r.tileset.glyph

            def glyph(char, *args, **kwargs):
                painted.append(char)
                return real_glyph(char, *args, **kwargs)

            stack.enter_context(mock.patch.object(r.tileset, 'glyph', glyph))
            r.draw(self.state)
        return painted

    def cell_bytes(self, x, y):
        r = self.renderer
        return area_bytes(r.canvas.surface, r._map_cell_rect(x, y))

    def test_a_gold_chest_counts_as_standing_on_its_cell(self):
        from game.item import Chest

        self.state.entities.append(Chest(13, 13, kind='gold'))
        self.renderer.draw(self.state)
        self.assertIn((13, 13), self.renderer._occupied)

    def test_a_gold_pile_under_a_monster(self):
        """Glyph mode leaves out a pile something stands on ('$' and the
        monster's letter would overlap); tile mode draws it underneath."""
        from game.gold import GOLD_CHAR, GoldPile

        self.goblin(13, 13)
        self.renderer.draw(self.state)
        without = self.cell_bytes(13, 13)
        self.state.entities.append(GoldPile(13, 13, 5))
        if self.TILES:
            chars = self.painted_chars()
            self.assertLess(chars.index(GOLD_CHAR), chars.index('g'))
            self.assertNotEqual(self.cell_bytes(13, 13), without)  # it shows round the monster
        else:
            self.renderer.draw(self.state)
            self.assertEqual(self.cell_bytes(13, 13), without)  # nothing of it on the cell

    def test_a_monster_is_painted_over_a_chest_listed_after_it(self):
        """Creatures paint above chests and shrines whatever the entity
        list's order (game/level.draw_layer)."""
        from game.item import Chest
        from game.shrine import Shrine

        self.goblin(13, 13)
        orc = Monster(14, 13, 'orc')  # another letter, to tell the cells apart
        orc.hp = orc.max_hp = 1000
        self.state.entities.append(orc)
        self.state.update_fov()
        shrine = Shrine(14, 13)
        chest = Chest(13, 13, kind='gear')
        # Listed before the monsters, the way the game lists them...
        self.state.entities[1:1] = [chest, shrine]
        self.renderer.draw(self.state)
        before = [self.cell_bytes(13, 13), self.cell_bytes(14, 13)]
        # ... and after them: the same picture.
        self.state.entities.remove(chest)
        self.state.entities.remove(shrine)
        self.state.entities.extend([chest, shrine])
        if self.TILES:
            chars = self.painted_chars()
            self.assertLess(chars.index('='), chars.index('g'))
            self.assertLess(chars.index(shrine.char), chars.index('o'))
        else:
            self.renderer.draw(self.state)
        self.assertEqual([self.cell_bytes(13, 13), self.cell_bytes(14, 13)], before)

    def test_the_player_is_painted_over_an_arrow_pile_listed_after_it(self):
        from game.quiver import ArrowPile
        from render.pygame_render import ARCHER_TILE

        self.renderer.draw(self.state)
        without = self.cell_bytes(10, 10)
        self.state.entities.append(ArrowPile(10, 10))
        if self.TILES:
            # The pile is drawn, and the player over it.
            chars = self.painted_chars()
            player = max(chars.index(c) for c in ('@', ARCHER_TILE) if c in chars)
            self.assertIn(self.ARROWS, chars)
            self.assertLess(chars.index(self.ARROWS), player)
        else:
            self.renderer.draw(self.state)
            self.assertEqual(self.cell_bytes(10, 10), without)  # glyph mode leaves it out

    def test_a_kills_gold_waits_for_the_blow_that_drops_it(self):
        from game.gold import GoldPile

        goblin = self.goblin(13, 10, hp=1)
        self.state.handle_action('shoot_e')
        self.assertFalse(goblin.alive)
        self.assertIsNotNone(self.state.gold_at(13, 10))
        hit = self.state.hits()[-1]
        drawn = self.renderer._before_hits(self.state, self.state.visible_entities(), [hit])
        self.assertEqual([e for e in drawn if isinstance(e, GoldPile)], [])
        # Once the blow has landed, the pile is there.
        drawn = self.renderer._before_hits(self.state, self.state.visible_entities(), [])
        self.assertEqual(len([e for e in drawn if isinstance(e, GoldPile)]), 1)

    def assert_arrow_look(self, pixels):
        from render.pygame_render import ARROW_HEAD, ARROW_SHAFT

        self.assertTrue({ARROW_HEAD, ARROW_SHAFT} & set(pixels))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GlyphModeArcherVisualsTest(ArcherVisualsTest):
    TILES = False

    def assert_arrow_look(self, pixels):
        # The pile's light tint fills most of its text cell (a floor cell is
        # black round its dot), with the bold glyph on top.
        from render.pygame_render import PILE_BACKDROP_ALPHA

        tint = round(230 * PILE_BACKDROP_ALPHA / 255)
        tinted = [p for p in pixels if p[0] == p[1] == p[2] and abs(p[0] - tint) <= 2]
        self.assertGreater(len(tinted), len(pixels) // 4)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class MeleeSwingTest(unittest.TestCase):
    """A melee blow's Swing beat (render/camera.py) plays before its Impact,
    always to the end, and draws a light arc towards the struck cell."""

    def setUp(self):
        from game.item import Item
        from game.paths import resource_path
        from render.tileset import Tileset

        self.item = Item
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = self.renderer.follow_ms = 0
        self.renderer.director = camera.Director(zoom=False)
        patcher = mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def fight(self, kind='weapon', offset=(1, 0)):
        """The player on open floor holding `kind`, a sturdy goblin `offset`
        away, drawn once (so nothing old is left to stage)."""
        state = floor_level(WIDTH, HEIGHT)
        state.player.weapon = self.item(0, 0, kind, 'common')
        p = state.player
        goblin = Monster(p.x + offset[0], p.y + offset[1], 'goblin')
        goblin.hp = goblin.max_hp = 500
        state.entities.append(goblin)
        state.update_fov()
        # A fresh director: a new GameState's hit serials start again at 1.
        self.renderer.director = camera.Director(zoom=False)
        self.renderer.draw(state)
        return state, goblin

    def played(self, state):
        """([(beat kind, ms)], played_out) for draw(state): the beats the
        Director stages and how long each holds, and whether a key typed ahead
        left them all to run to the end (and still queued for get_action)."""
        r = self.renderer
        beats, elapsed, kept = play_with_key_typed_ahead(r, state)
        timed = [(type(beat).__name__.lower(), beat_ms(r, beat)) for beat in beats]
        total = sum(ms for _, ms in timed)
        return timed, kept and elapsed >= total - 20 * len(timed)

    def test_the_swing_plays_first_uninterruptible_then_the_impact(self):
        # The player's blow by weapon kind; a monster's blow (the player
        # holding a spear) plays the standard swing.
        for kind, ms, monster in (
            ('weapon', 120, False),
            ('dagger', 90, False),
            ('great_sword', 150, False),
            ('spear', 200, False),
            ('spear', camera.SWING_MS, True),
        ):
            with self.subTest(kind=kind, monster_blow=monster):
                state, goblin = self.fight(kind)
                if monster:
                    state.attack(goblin, state.player)
                else:
                    state.attack(state.player, goblin)
                calls, played_out = self.played(state)
                self.assertEqual([c[0] for c in calls], ['swing', 'impact'])
                self.assertEqual(calls[0][1], ms)
                self.assertTrue(played_out)  # a key typed ahead cuts neither short

    def test_an_arrow_plays_no_swing(self):
        state, goblin = self.fight()
        state._monster_shot(goblin)
        kinds = [c[0] for c in self.played(state)[0]]
        self.assertIn('impact', kinds)
        self.assertNotIn('swing', kinds)

    def test_keys_pressed_during_the_swing_are_not_consumed(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]

        def type_ahead():  # the swing's first frame: the player types ahead
            for event in typed:
                pygame.event.post(event)

        start = pygame.time.get_ticks()
        with captured_frames(self.renderer, on_first=type_ahead):
            self.renderer.draw(state)
        elapsed = pygame.time.get_ticks() - start
        # Neither the swing nor the impact was cut short by the keys.
        self.assertGreaterEqual(elapsed, camera.SWING_MS + self.renderer.impact_ms - 40)
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_S)

    def changed(self, state, swing, t):
        """Pixels the swing's arc changes at t: (x, y) list."""
        r = self.renderer
        r.canvas.clear()
        r._paint_game(state)
        before = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(state, swing=(swing, t))
        after = r.canvas.surface
        rect = r.layout.map_rect()
        return [
            (x, y)
            for y in range(rect.top, rect.bottom)
            for x in range(rect.left, rect.right)
            if after.get_at((x, y)) != before.get_at((x, y))
        ]

    def test_the_swing_is_drawn_in_the_direction_of_the_blow_and_gone_at_its_end(self):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            with self.subTest(direction=(dx, dy)):
                state, goblin = self.fight(offset=(dx, dy))
                state.attack(state.player, goblin)
                (swing,) = [
                    b for b in self.renderer.director.plan(state) if isinstance(b, camera.Swing)
                ]
                self.renderer._view = self.renderer.director.current(state)
                pixels = self.changed(state, swing, 0.5)
                self.assertGreater(len(pixels), 20)
                r = self.renderer
                r._proj = camera.project(r._view, r.layout.map_rect(), r.layout.map_cell_size())
                try:
                    origin = r._map_cell_rect(state.player.x, state.player.y)
                    struck = r._map_cell_rect(goblin.x, goblin.y)
                finally:
                    r._proj = None
                cx, cy = origin.center
                ahead = [(x - cx) * dx + (y - cy) * dy for x, y in pixels]
                self.assertTrue(all(a > 0 for a in ahead))  # nothing behind the attacker
                self.assertTrue(any(struck.collidepoint(p) for p in pixels))  # over the target
                # Light pixels: the arc itself.
                surface = r.canvas.surface
                light = [p for p in pixels if min(surface.get_at(p)[:3]) > 200]
                self.assertTrue(light)
                if (dx, dy) == (1, 0):  # the swing is gone once it ends
                    self.assertEqual(self.changed(state, swing, 1.0), [])

    def test_the_spear_swing_reaches_the_cell_two_away(self):
        state, goblin = self.fight('spear', offset=(2, 0))
        state.attack(state.player, goblin)
        (swing,) = [b for b in self.renderer.director.plan(state) if isinstance(b, camera.Swing)]
        self.renderer._view = self.renderer.director.current(state)
        pixels = self.changed(state, swing, 0.5)
        r = self.renderer
        r._proj = camera.project(r._view, r.layout.map_rect(), r.layout.map_cell_size())
        try:
            struck = r._map_cell_rect(goblin.x, goblin.y)
        finally:
            r._proj = None
        self.assertTrue(any(struck.collidepoint(p) for p in pixels))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ParryAnimationTest(unittest.TestCase):
    """A parried blow plays the monster's swing, the shield over the warrior,
    the riposte's swing and impact, then "Parry!" fading -- the blue text up
    from the shield on -- all to the end, keys left queued."""

    def setUp(self):
        from game.item import Item
        from game.paths import resource_path
        from render.tileset import Tileset

        self.item = Item
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = self.renderer.follow_ms = 0
        for target, value in (('BASE_CRIT_CHANCE', 0.0), ('dodge_chance', lambda _: 0)):
            patcher = mock.patch(f'game.fight.{target}', value)
            patcher.start()
            self.addCleanup(patcher.stop)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def fight(self, armed=True):
        """A warrior on open floor with a sturdy goblin east of them, drawn
        once; then the goblin swings (parried if `armed`)."""
        state = floor_level(WIDTH, HEIGHT)
        state.player.weapon = self.item(0, 0, 'weapon', 'common')
        p = state.player
        goblin = Monster(p.x + 1, p.y, 'goblin')
        goblin.hp = goblin.max_hp = 500
        state.entities.append(goblin)
        state.update_fov()
        self.renderer.director = camera.Director(zoom=False)
        self.renderer.draw(state)
        state.parry_armed = armed
        state._monster_melee(goblin)
        return state, goblin

    def played(self, state):
        """(calls, played_out, text_up) for draw(state). `calls`: (beat kind,
        ms, attacker or None) of each beat the Director stages. `played_out`:
        a key typed ahead left them all to run to the end, still queued.
        `text_up`: per frame shown, whether "Parry!" (blue ink) is on it, in
        the strip above the warrior."""
        r = self.renderer
        p = state.player
        above = r._map_cell_rect(p.x, p.y)
        above = pygame.Rect(
            above.left - 20, above.top - above.height, above.width + 40, above.height
        )
        with captured_frames(r) as frames:
            beats, elapsed, kept = play_with_key_typed_ahead(r, state)
        calls = [
            (
                type(b).__name__.lower(),
                beat_ms(r, b),
                b.origin if isinstance(b, camera.Swing) else None,
            )
            for b in beats
        ]
        total = sum(ms for _, ms, _ in calls)

        def blue_ink(frame):
            strip = frame.subsurface(above)
            return any(
                b > 120 and b > g > r
                for x in range(above.w)
                for y in range(above.h)
                for r_, g, b in [tuple(strip.get_at((x, y)))[:3]]
                for r in [r_]
            )

        text_up = [blue_ink(f) for f in frames]
        return calls, kept and elapsed >= total - 20 * len(calls), text_up

    def test_the_sequence_plays_in_order_uninterruptible(self):
        state, goblin = self.fight()
        p = state.player
        calls, played_out, text_up = self.played(state)
        self.assertEqual(
            [(kind, origin) for kind, _, origin in calls],
            [
                ('swing', (goblin.x, goblin.y)),  # the monster's
                ('guard', None),
                ('swing', (p.x, p.y)),  # the riposte, back from the warrior
                ('impact', None),
                ('parrytext', None),  # the text's fade
            ],
        )
        self.assertEqual(
            [ms for _, ms, _ in calls],
            [
                camera.SWING_MS,
                camera.GUARD_MS,
                camera.SWING_MS,
                self.renderer.impact_ms,
                camera.PARRY_FADE_MS,
            ],
        )
        self.assertTrue(played_out)
        # "Parry!" is not up for the monster's swing, goes up with the shield
        # and stays to the end of the sequence, and is gone from the last frame.
        self.assertFalse(text_up[0])
        self.assertFalse(text_up[-1])
        first = text_up.index(True)
        last = len(text_up) - 1 - text_up[::-1].index(True)
        self.assertTrue(all(text_up[first : last + 1]), text_up)
        # Up from the shield on: for at least the guard, riposte and impact.
        ms = [m for _, m, _ in calls]
        held = (ms[1] + ms[2] + ms[3]) / sum(ms)
        self.assertGreater(sum(text_up) / len(text_up), held - 0.15)

    def test_a_normal_blow_plays_its_swing_and_no_parry(self):
        state, goblin = self.fight(armed=False)
        calls, _, text_up = self.played(state)
        self.assertEqual(
            [(kind, origin) for kind, _, origin in calls],
            [('swing', (goblin.x, goblin.y)), ('impact', None)],
        )
        self.assertFalse(any(text_up))

    def test_a_dodged_blow_plays_nothing(self):
        with mock.patch('game.fight.dodge_chance', return_value=100):
            state, _ = self.fight()
        self.assertEqual(self.played(state)[0], [])

    def test_keys_pressed_during_the_parry_are_not_consumed(self):
        state, _ = self.fight()
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]

        def type_ahead():
            for event in typed:
                pygame.event.post(event)

        start = pygame.time.get_ticks()
        with captured_frames(self.renderer, on_first=type_ahead):
            self.renderer.draw(state)
        elapsed = pygame.time.get_ticks() - start
        total = 2 * camera.SWING_MS + camera.GUARD_MS + self.renderer.impact_ms
        self.assertGreaterEqual(elapsed, total + camera.PARRY_FADE_MS - 60)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_S)

    def parry_frame(self, state, **kw):
        """The pixels of the map area changed by painting with `kw`."""
        r = self.renderer
        r._view = r.director.current(state)
        r.canvas.clear()
        r._paint_game(state)
        before = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(state, **kw)
        after = r.canvas.surface
        rect = r.layout.map_rect()
        return {
            (x, y): tuple(after.get_at((x, y)))[:3]
            for y in range(rect.top, rect.bottom)
            for x in range(rect.left, rect.right)
            if after.get_at((x, y)) != before.get_at((x, y))
        }

    def test_the_shield_is_drawn_over_the_warriors_cell_and_fades(self):
        state, _ = self.fight()
        (parry,) = state.events_of(Parry)
        cell = self.renderer._map_cell_rect(state.player.x, state.player.y)
        early = self.parry_frame(state, guard=(parry, 0.3))
        self.assertGreater(len(early), 20)
        self.assertTrue(all(cell.collidepoint(p) for p in early))  # on the cell, nowhere else
        light = [p for p, rgb in early.items() if min(rgb) > 200]
        self.assertGreater(len(light), 10)  # the light outline itself
        # An outline, not a fill: the shield's middle is left as it was.
        self.assertNotIn(cell.center, early)
        late = self.parry_frame(state, guard=(parry, 0.9))
        self.assertLess(len([rgb for rgb in late.values() if min(rgb) > 200]), len(light))
        self.assertEqual(self.parry_frame(state, guard=(parry, 1.0)), {})

    def test_parry_text_is_blue_above_the_warriors_cell(self):
        state, _ = self.fight()
        (parry,) = state.events_of(Parry)
        cell = self.renderer._map_cell_rect(state.player.x, state.player.y)
        changed = self.parry_frame(state, parry_text=(parry, 1.0))
        self.assertGreater(len(changed), 30)
        self.assertTrue(all(y < cell.top for _, y in changed))  # above the cell
        xs = [x for x, _ in changed]
        self.assertLess(abs((min(xs) + max(xs)) / 2 - cell.centerx), 3)  # centred on it
        bright = [rgb for rgb in changed.values() if max(rgb) > 120]
        self.assertTrue(bright)
        # Blue dominates the text's lit pixels.
        blue = [rgb for rgb in bright if rgb[2] > rgb[1] > rgb[0]]
        self.assertGreater(len(blue), 0.8 * len(bright))
        self.assertIn((80, 160, 255), set(changed.values()))
        # Fading: dimmer at half alpha, gone at none.
        half = self.parry_frame(state, parry_text=(parry, 0.5))
        self.assertLess(max(rgb[2] for rgb in half.values()), max(rgb[2] for rgb in bright))
        self.assertEqual(self.parry_frame(state, parry_text=(parry, 0.0)), {})


def cell_pixels(renderer, rect, as_list=False):
    screen = renderer.canvas.surface
    pixels = [
        tuple(screen.get_at((x, y)))[:3]
        for y in range(rect.top, rect.bottom)
        for x in range(rect.left, rect.right)
    ]
    return pixels if as_list else set(pixels)


def area_bytes(surface, rect):
    """The RGB bytes of `rect` on `surface`, to compare two frames' areas."""
    return pygame.image.tobytes(surface.subsurface(rect).copy(), 'RGB')


def lit_pixels(renderer, rect):
    return [p for p in cell_pixels(renderer, rect, as_list=True) if p != BACKGROUND]


def find_tile(state, char):
    for y, row in enumerate(state.game_map):
        for x, tile in enumerate(row):
            if tile == char:
                return x, y
    raise AssertionError(f'no {char!r} on the map')


def open_neighbour(state):
    """An orthogonal floor tile next to the player (it starts mid-room)."""
    px, py = state.player.x, state.player.y
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if state.game_map[py + dy][px + dx] == '.':
            return px + dx, py + dy
    raise AssertionError('player has no open floor next to it')


def kill_player_next_turn(state):
    """Clear the level, then put one goblin next to a 1-HP player who can't
    dodge (no armor: an archer's leather would give the blow a dodge roll)."""
    state.cancel_monster_phase()
    state.player.hp = 1
    state.player.armor = None
    state.player.defense = 0
    x, y = open_neighbour(state)
    state.entities = [state.player, Monster(x, y, 'goblin', depth=state.depth)]
    state.update_fov()


@contextlib.contextmanager
def captured_frames(renderer, on_first=None):
    """The canvas at every display.flip() inside the block (a list of Surface
    copies, appended as they are shown). `on_first` runs once, at the first
    flip, e.g. to type ahead mid-animation. Only the display is stubbed out;
    the renderer paints and sequences exactly as it does for real."""
    frames = []
    real_flip = pygame.display.flip

    def flip():
        frames.append(renderer.canvas.surface.copy())
        if len(frames) == 1 and on_first is not None:
            on_first()
        real_flip()

    with mock.patch.object(pygame.display, 'flip', flip):
        yield frames


@contextlib.contextmanager
def recorded_beats(renderer):
    """The beats the renderer's Director plans inside the block, as a list --
    the public description of what draw() is about to stage."""
    director = renderer.director
    real_plan = director.plan
    beats = []

    def plan(state):
        planned = real_plan(state)
        beats.extend(planned)
        return planned

    with mock.patch.object(director, 'plan', plan):
        yield beats


def beat_ms(renderer, beat):
    """How long draw() holds `beat`, from the renderer's public timings."""
    if isinstance(beat, camera.Flight):
        return camera.flight_ms(beat, renderer.flight_ms)
    if isinstance(beat, camera.Swing):
        return renderer.swing_ms_for(beat)
    if isinstance(beat, camera.Impact):
        return renderer.impact_ms_for(beat.shake or camera.shake_for(beat.hit))
    if isinstance(beat, camera.Guard):
        return renderer.guard_ms
    if isinstance(beat, camera.ParryText):
        return renderer.parry_fade_ms
    return renderer.follow_ms if beat.follow else renderer.zoom_ms


def play_with_key_typed_ahead(renderer, state):
    """draw(state) with a key already queued: (beats, elapsed ms, key still
    queued). Beats that always play out take their full time and leave the key
    for get_action; an interruptible one would be cut short by it."""
    pygame.event.clear()
    pygame.event.post(key(pygame.K_d, 'd'))
    start = pygame.time.get_ticks()
    with recorded_beats(renderer) as beats:
        renderer.draw(state)
    elapsed = pygame.time.get_ticks() - start
    queued = pygame.event.peek(pygame.KEYDOWN)
    pygame.event.clear()
    return beats, elapsed, queued


def record_frames(renderer):
    """Wrap renderer.draw to note state.game_over at every frame."""
    frames = []
    real_draw = renderer.draw

    def draw(state):
        frames.append(state.game_over)
        real_draw(state)

    renderer.draw = draw
    return frames


def floor_level(width, height):
    """A GameState whose map is `width` x `height` of open floor, the player
    alone in the middle of it."""
    state = GameState(WIDTH, HEIGHT, seed=0)
    state.width, state.height = width, height
    state.game_map = [
        ['#' if x in (0, width - 1) or y in (0, height - 1) else '.' for x in range(width)]
        for y in range(height)
    ]
    state.visible = [[False] * width for _ in range(height)]
    state.seen = [[False] * width for _ in range(height)]
    state.entities = [state.player]
    state.player.x, state.player.y = width // 2, height // 2
    state.update_fov()
    return state


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class FollowCameraTest(unittest.TestCase):
    """The map area holds camera.view_size cells whatever the floor's size;
    the view follows the player over a bigger map."""

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer.zoom_ms = self.renderer.follow_ms = 0
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def assert_player_in_view(self, state):
        rect = self.renderer._map_cell_rect(state.player.x, state.player.y)
        self.assertTrue(self.renderer.layout.map_rect().contains(rect))

    def test_the_layout_is_the_view_not_the_level(self):
        layout = self.renderer.layout
        self.assertEqual((layout.map_width, layout.map_height), camera.view_size(WIDTH, HEIGHT))
        state = GameState(WIDTH, HEIGHT, seed=0)
        self.renderer.draw(state)
        tile, map_rect = layout.tile, layout.map_rect()
        state.next_level()
        self.renderer.draw(state)
        # A new, bigger floor: the same tiles in the same map area.
        self.assertEqual((layout.tile, layout.map_rect()), (tile, map_rect))
        self.assert_player_in_view(state)

    def test_the_view_follows_the_player_on_a_big_map(self):
        state = floor_level(100, 50)
        self.renderer.draw(state)
        self.assert_player_in_view(state)
        before = self.renderer._view
        # Exploring, cells are drawn at the layout's own tile: no shrinking.
        self.assertEqual(self.renderer._map_cell_rect(0, 0).width, self.renderer.layout.tile)
        for _ in range(10):
            state.player.x += 1
            state.turn += 1
            self.renderer.draw(state)
            self.assert_player_in_view(state)
        self.assertEqual(self.renderer._view.left, before.left + 10)
        # Run into the corner: the view stops at the map's edge.
        state.player.x, state.player.y = 98, 48
        state.turn += 1
        self.renderer.draw(state)
        self.assert_player_in_view(state)
        view = self.renderer._view
        self.assertEqual((view.left + view.width, view.top + view.height), (100, 50))

    def test_a_map_that_fits_is_shown_whole_and_never_pans(self):
        state = floor_level(20, 10)
        self.renderer.draw(state)
        view = self.renderer._view
        map_rect = self.renderer.layout.map_rect()
        for corner in ((0, 0), (19, 9)):
            self.assertTrue(map_rect.contains(self.renderer._map_cell_rect(*corner)))
        for dx in (3, -6):
            state.player.x += dx
            state.turn += 1
            self.renderer.draw(state)
            self.assertEqual(self.renderer._view, view)

    def test_a_step_pans_for_follow_ms_and_a_zoom_for_zoom_ms(self):
        state = floor_level(100, 50)
        self.renderer.draw(state)
        self.renderer.follow_ms, self.renderer.zoom_ms = 7, 999
        played = []
        with mock.patch.object(
            self.renderer, '_play', side_effect=lambda ms, *a, **k: played.append(ms)
        ):
            state.player.x += 1
            state.turn += 1
            self.renderer.draw(state)
            self.assertIn(7, played)
            self.assertNotIn(999, played)
            played.clear()
            goblin = Monster(state.player.x + 1, state.player.y, 'goblin')
            state.entities.append(goblin)
            state.update_fov()
            self.renderer.draw(state)
            self.assertIn(999, played)
        self.assertIsNotNone(self.renderer.director.view)  # zoomed on the fight


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class FirstWindowTest(unittest.TestCase):
    """The first window is 1920x1080 (capped on a smaller desktop), and on
    Windows the process is made DPI-aware before any display call."""

    def open_on(self, desktop, tiles=True):
        from game.paths import resource_path
        from render import ui
        from render.tileset import Tileset

        tileset = Tileset(resource_path('assets')) if tiles else Tileset()
        with mock.patch.object(ui, '_desktop_size', return_value=desktop):
            renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.addCleanup(renderer.close)
        return renderer

    def test_big_desktop_gets_a_1920x1080_window(self):
        for tiles in (True, False):
            with self.subTest(tiles=tiles):
                renderer = self.open_on((2560, 1440), tiles)
                self.assertEqual(renderer.canvas.surface.get_size(), (1920, 1080))
                self.assertTrue(pygame.display.get_surface().get_flags() & pygame.RESIZABLE)

    def test_small_desktop_caps_the_window(self):
        renderer = self.open_on((1366, 768))
        width, height = renderer.canvas.surface.get_size()
        self.assertLessEqual(width, 1366 * 0.85)
        self.assertLessEqual(height, 768 * 0.85)
        self.assertEqual(width * 9 // 16, height)

    def test_dpi_awareness_is_set_before_the_display_starts(self):
        from render import pygame_render

        calls = []
        real_init = pygame.display.init

        def init():
            calls.append('init')
            real_init()

        with (
            mock.patch.object(
                pygame_render, '_make_dpi_aware', side_effect=lambda: calls.append('dpi')
            ),
            mock.patch('pygame.display.init', side_effect=init),
        ):
            renderer = PygameRenderer(WIDTH, HEIGHT)
        self.addCleanup(renderer.close)
        self.assertEqual(calls, ['dpi', 'init'])


class DpiAwarenessTest(unittest.TestCase):
    """render.pygame_render._make_dpi_aware, with sys.platform and ctypes.windll
    mocked: only Windows makes a call, and no failure escapes."""

    def setUp(self):
        if pygame is None:
            self.skipTest('pygame-ce not installed')

    def run_on(self, platform, windll):
        import ctypes

        from render import pygame_render

        with (
            mock.patch.object(pygame_render, 'sys', mock.Mock(platform=platform)),
            mock.patch.object(ctypes, 'windll', windll, create=True),
        ):
            return pygame_render._make_dpi_aware()

    def test_not_windows_makes_no_call(self):
        for platform in ('linux', 'darwin'):
            with self.subTest(platform=platform):
                windll = mock.Mock()
                self.assertFalse(self.run_on(platform, windll))
                self.assertEqual(windll.mock_calls, [])

    def test_windows_asks_for_per_monitor_awareness(self):
        windll = mock.Mock()
        self.assertTrue(self.run_on('win32', windll))
        windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
        windll.user32.SetProcessDPIAware.assert_not_called()

    def test_old_windows_falls_back_to_system_awareness(self):
        windll = mock.Mock()
        windll.shcore.SetProcessDpiAwareness.side_effect = OSError('no shcore')
        self.assertTrue(self.run_on('win32', windll))
        windll.user32.SetProcessDPIAware.assert_called_once_with()

    def test_every_failure_is_harmless(self):
        windll = mock.Mock()
        windll.shcore.SetProcessDpiAwareness.side_effect = OSError('no shcore')
        windll.user32.SetProcessDPIAware.side_effect = AttributeError('no user32')
        self.assertFalse(self.run_on('win32', windll))
        # A Python without ctypes.windll at all.
        self.assertFalse(self.run_on('win32', None))


if __name__ == '__main__':
    unittest.main()
