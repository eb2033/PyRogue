"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import collections
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
        state = GameState(WIDTH, HEIGHT)
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

    def test_walking_tilts_alternate_sign(self):
        state = GameState(WIDTH, HEIGHT)
        player = state.player
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.assertEqual(self.renderer.track_steps([player]), {})  # idle: upright
        angles = []
        for _ in range(4):
            player.x += 1
            angles.append(self.renderer.track_steps([player]).get(id(player)))
        self.assertEqual(angles, [15, -15, 15, -15])
        self.assertEqual(self.renderer.track_steps([player]), {})  # stopped

    def test_a_jump_is_not_a_step_and_gone_entities_are_forgotten(self):
        state = GameState(WIDTH, HEIGHT)
        player = state.player
        self.renderer.track_steps([player])
        player.x += 5
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.renderer.track_steps([])
        self.assertEqual(self.renderer._gait, {})

    def test_draw_plays_a_step_beat_and_ends_upright(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        state.player.x += 1
        with mock.patch.object(self.renderer, '_play') as play:
            self.renderer.draw(state)
        self.assertEqual(play.call_args[0][0], 110)
        self.assertEqual(self.renderer._tilts, {})

    def test_get_action_maps_keys(self):
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

    def test_unmapped_key_returns_none_and_is_ignored(self):
        self.post(key(pygame.K_z, 'z'))
        self.assertIsNone(self.renderer.get_action())

    def test_window_close_is_quit(self):
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    def test_resize_relayouts_and_keeps_waiting(self):
        self.renderer.draw(GameState(WIDTH, HEIGHT))
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
        state = GameState(WIDTH, HEIGHT, char_class=char_class)
        main.run(self.renderer, state, delay_ms=5)
        self.assertFalse(state.running)

    def test_title_quit_option(self):
        self.post(key(pygame.K_DOWN), key(pygame.K_RETURN, '\r'))
        self.assertFalse(self.renderer.show_title_screen())

    # -- P1: fullscreen, bosses, fonts ---------------------------------------

    def test_f11_toggles_fullscreen_and_back_while_waiting(self):
        self.renderer.draw(GameState(WIDTH, HEIGHT))
        windowed = self.renderer.canvas.surface.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        self.post(key(pygame.K_F11), key(pygame.K_w, 'w'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)  # F11 is no Action
        self.assertTrue(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), desktop)
        self.assertEqual(pygame.display.get_surface().get_size(), desktop)

        self.post(key(pygame.K_F11), key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), windowed)

    def test_f11_repaints_the_current_frame(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        self.renderer.toggle_fullscreen()
        cell = self.renderer._map_cell_rect(state.player.x, state.player.y)
        self.assertTrue(
            set(cell_pixels(self.renderer, cell)) - {BACKGROUND},
            'frame not repainted after going fullscreen',
        )

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
        state = GameState(WIDTH, HEIGHT)
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
        self.renderer.draw(GameState(WIDTH, HEIGHT))

    def test_make_renderer_uses_the_bundled_font(self):
        renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            font_path = cast(str, renderer.layout.font_path)
            self.assertTrue(font_path.endswith(main.BUNDLED_FONT))
            self.assertTrue(os.path.isfile(font_path))
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

    def test_menu_click_outside_any_option_does_nothing(self):
        self.post(
            self.click((9, 9)), self.motion((9, 9)), key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')
        )
        with mock.patch.object(screens, 'option_at', lambda *a: None):
            self.assertFalse(self.renderer.show_title_screen())  # keys decided it

    def test_menu_right_click_is_ignored(self):
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

    def test_menu_keys_unchanged_with_mouse_support(self):
        self.post(key(pygame.K_s, 's'), key(pygame.K_SPACE, ' '))
        self.assertFalse(self.renderer.show_title_screen())
        self.post(key(pygame.K_q, 'q'))
        self.assertFalse(self.renderer.show_title_screen())

    def test_mouse_events_are_ignored_during_get_action(self):
        self.post(self.motion(), self.click(), self.click(button=3), key(pygame.K_d, 'd'))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_pause_keeps_keys_when_mouse_events_are_queued(self):
        self.post(self.motion(), key(pygame.K_a, 'a'), self.click())
        self.renderer.pause(30)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_W)

    def test_window_close_in_a_menu_is_delivered_by_get_action(self):
        self.post(self.motion(), pygame.event.Event(pygame.QUIT))
        self.assertFalse(self.renderer.show_title_screen())
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    # -- P1: game over, and a whole run --------------------------------------

    def test_game_over_shows_overlay_and_q_quits(self):
        state = GameState(WIDTH, HEIGHT)
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
        state = GameState(WIDTH, HEIGHT)
        kill_player_next_turn(state)
        self.post(key(pygame.K_PERIOD, '.'), pygame.event.Event(pygame.QUIT))
        main.run(self.renderer, state, delay_ms=1)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)

    def test_r_mid_game_is_ignored(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        self.post(key(pygame.K_r, 'r'), key(pygame.K_PERIOD, '.'))
        self.assertIsNone(self.renderer.get_action())
        self.assertEqual(self.renderer.get_action(), Action.WAIT)

    def test_r_on_the_game_over_screen_is_restart(self):
        state = GameState(WIDTH, HEIGHT)
        state.game_over = True
        self.renderer.draw(state)
        self.post(key(pygame.K_r, 'r'))
        self.assertEqual(self.renderer.get_action(), Action.RESTART)

    def test_r_on_the_title_screen_does_nothing(self):
        # 'r' neither picks an option nor moves the highlight: enter still
        # takes Start.
        self.post(key(pygame.K_r, 'r'), key(pygame.K_RETURN, '\r'))
        self.assertTrue(self.renderer.show_title_screen())

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
        with mock.patch.object(main, 'GameState', side_effect=build):
            main.play(self.renderer, WIDTH, HEIGHT, delay_ms=1)
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
        self.assertEqual(self.renderer.director._last_hit, 0)

    def test_q_on_the_death_screen_still_quits_from_play(self):
        enter = key(pygame.K_RETURN, '\r')
        states, at_title, _ = self.play_with_a_death(
            enter, enter, key(pygame.K_PERIOD, '.'), key(pygame.K_q, 'q')
        )
        self.assertEqual(len(states), 1)
        self.assertEqual(at_title, [0])  # never back to the title
        self.assertTrue(states[0].game_over)
        self.assertFalse(states[0].restart_requested)

    def test_window_close_on_the_death_screen_still_quits_from_play(self):
        enter = key(pygame.K_RETURN, '\r')
        states, at_title, _ = self.play_with_a_death(
            enter, enter, key(pygame.K_PERIOD, '.'), pygame.event.Event(pygame.QUIT)
        )
        self.assertEqual(len(states), 1)
        self.assertEqual(at_title, [0])

    def test_death_screen_shows_both_hints(self):
        self.assertEqual(screens.GAME_OVER_HINTS, ('press q to quit', 'press r to restart'))
        state = GameState(WIDTH, HEIGHT)
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
        state = GameState(WIDTH, HEIGHT, char_class=self.renderer.choose_class())
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

    def test_layout_is_in_tile_mode(self):
        self.assertTrue(self.renderer.layout.tiles)
        self.assertIsNotNone(self.renderer.layout.tile)

    def test_draw_paints_the_players_tile_over_the_floor(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        layout = self.renderer.layout
        rect = self.renderer._map_cell_rect(state.player.x, state.player.y)
        drawn = pygame.display.get_surface().subsurface(rect)
        expected = self.renderer.tileset.glyph('.', 0, layout.tile).copy()
        expected.blit(self.renderer.tileset.glyph('@', state.player.color, layout.tile), (0, 0))
        for point in [(layout.tile // 2, layout.tile // 2), (1, 1), (layout.tile // 3, 2)]:
            self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3])

    def test_archer_is_drawn_with_its_own_tile(self):
        state = GameState(WIDTH, HEIGHT, char_class='archer')
        self.renderer.draw(state)
        layout = self.renderer.layout
        rect = self.renderer._map_cell_rect(state.player.x, state.player.y)
        drawn = pygame.display.get_surface().subsurface(rect)
        expected = self.renderer.tileset.glyph('.', 0, layout.tile).copy()
        expected.blit(self.renderer.tileset.glyph('&', state.player.color, layout.tile), (0, 0))
        point = (layout.tile // 2, layout.tile // 2)
        self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3])
        self.assertIsNot(
            self.renderer.tileset.glyph('&', 0, layout.tile),
            self.renderer.tileset.glyph('@', 0, layout.tile),
        )

    def fight(self):
        state = GameState(WIDTH, HEIGHT)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        state.entities = [state.player, goblin]
        state.update_fov()
        return state, goblin

    def test_melee_zooms_in_with_the_fight_centred(self):
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

    def test_fight_over_zooms_back_out(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        self.assertIsNotNone(self.renderer._view)
        goblin.hp = 1
        state.attack(state.player, goblin)
        self.renderer.draw(state)
        # Back to the exploring view that follows the player.
        self.assertIsNone(self.renderer.director.view)
        self.assertEqual(self.renderer._view, self.renderer.director.explore_view(state))

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
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        hit = state.combat_events[-1]
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
        state = GameState(WIDTH, HEIGHT)
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

    def test_repeat_flag_movement_is_ignored_with_a_monster_visible(self):
        self._drawn_state(True)
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
        state = GameState(WIDTH, HEIGHT)
        stranger = Monster(state.player.x + 1, state.player.y, 'goblin')
        stranger.char = 'Z'  # no tiles.json entry
        state.entities.append(stranger)
        state.update_fov()
        self.renderer.draw(state)  # must not raise

    def test_game_over_overlay_is_drawn_on_the_map(self):
        state = GameState(WIDTH, HEIGHT)
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

    def test_tiles_env_zero_keeps_glyph_mode(self):
        with mock.patch.dict(os.environ, {'TILES': '0'}):
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            self.assertFalse(renderer.layout.tiles)
        finally:
            renderer.close()

    def test_make_renderer_uses_the_bundled_tiles_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('TILES', None)
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            self.assertTrue(renderer.layout.tiles)
        finally:
            renderer.close()


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
        state = GameState(WIDTH, HEIGHT)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        goblin.hp = goblin.max_hp = 20
        state.entities = [state.player, goblin]
        state.update_fov()
        self.renderer.draw(state)
        return state, goblin

    def played(self, state):
        """The (ms, interruptible) of every beat draw() plays."""
        calls = []
        with mock.patch.object(
            self.renderer,
            '_play',
            side_effect=lambda ms, paint, interruptible=True: calls.append((ms, interruptible)),
        ):
            self.renderer.draw(state)
        return calls

    # -- shake ----------------------------------------------------------------

    def test_a_hit_plays_an_uninterruptible_shake_and_a_crit_plays_longer(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        swing, *normal = self.played(state)  # the monster's swing, then the hit
        self.assertEqual(swing, (camera.SWING_MS, False))
        self.assertEqual(len(normal), 1)
        normal_ms, interruptible = normal[0]
        self.assertFalse(interruptible)
        self.assertTrue(150 <= normal_ms <= 250, normal_ms)

        state.player.power = 1
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        self.assertTrue(state.combat_events[-1].crit)
        _, (crit_ms, interruptible), *_ = self.played(state)
        self.assertFalse(interruptible)
        self.assertTrue(normal_ms < crit_ms <= 350, crit_ms)

    def test_shake_offsets_frames_and_ends_still(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        offsets = []
        real = self.renderer._paint_game

        def paint(state, impact=None, shake=(0, 0), **kw):
            offsets.append(shake)
            real(state, impact=impact, shake=shake, **kw)

        with mock.patch.object(self.renderer, '_paint_game', side_effect=paint):
            self.renderer.draw(state)
        self.assertTrue(any(o != (0, 0) for o in offsets[:-1]), offsets)
        self.assertEqual(offsets[-1], (0, 0))  # draw()'s own frame is still
        hit = state.combat_events[-1]
        shake = camera.shake_for(hit)
        self.assertEqual(self.renderer.shake_offset(shake, 1.0), (0, 0))

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

    def test_keys_pressed_during_the_shake_wait_until_it_ends(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]
        real_show = self.renderer._show
        shown = []

        def show(paint):
            if not shown:  # the shake's first frame: the player types ahead
                for event in typed:
                    pygame.event.post(event)
            shown.append(1)
            real_show(paint)

        start = pygame.time.get_ticks()
        with mock.patch.object(self.renderer, '_show', side_effect=show):
            self.renderer.draw(state)
        elapsed = pygame.time.get_ticks() - start
        self.assertGreaterEqual(elapsed, self.renderer.impact_ms - 20)  # not cut short
        self.assertGreaterEqual(len(shown), 2)  # shake frame(s), then the final one
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))  # not consumed
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)  # in order
        self.assertEqual(self.renderer.get_action(), Action.MOVE_S)

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

    def test_the_struck_monster_shakes_in_its_cell(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        hit = state.combat_events[-1]
        self.assertIs(hit.defender, goblin)
        self.assertFalse(hit.killed)
        self.assert_sprite_shakes(state, hit, state.player)

    def test_the_struck_player_shakes_in_its_cell(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        hit = state.combat_events[-1]
        self.assertIs(hit.defender, state.player)
        self.assert_sprite_shakes(state, hit, goblin)

    def test_the_struck_sprite_shakes_zoomed_in(self):
        state, goblin = self.fight(zoom=True)
        self.assertIsNotNone(self.renderer._view)
        state.attack(state.player, goblin)
        self.assert_sprite_shakes(state, state.combat_events[-1], state.player)

    def test_sprite_shake_is_repeatable_decays_and_is_bigger_for_a_crit(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        hit = state.combat_events[-1]
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

    def test_bar_fill_is_proportional_and_banded(self):
        from render.pygame_render import HEALTH_AMBER, HEALTH_GREEN, HEALTH_RED

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

    def test_bar_has_only_bar_colours(self):
        from render.pygame_render import HEALTH_BAR_COLORS

        state, goblin = self.fight()
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
        state, goblin = self.fight()
        painted = []
        with mock.patch.object(
            self.renderer, '_paint_health_bar', side_effect=lambda m, p, r: painted.append(m)
        ):
            self.renderer.draw(state)
            self.assertEqual(painted, [goblin])
            painted.clear()
            state.visible[goblin.y][goblin.x] = False  # remembered, not in view
            state.seen[goblin.y][goblin.x] = True
            self.renderer.draw(state)
        self.assertEqual(painted, [])


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GlyphModeSpriteShakeTest(unittest.TestCase):
    """The struck sprite's own shake with no tileset: glyphs, not tiles."""

    fight = HitShakeAndHealthBarTest.fight
    impact_frame = HitShakeAndHealthBarTest.impact_frame
    assert_sprite_shakes = HitShakeAndHealthBarTest.assert_sprite_shakes
    test_the_struck_monster_shakes_in_its_cell = (
        HitShakeAndHealthBarTest.test_the_struck_monster_shakes_in_its_cell
    )
    test_the_struck_player_shakes_in_its_cell = (
        HitShakeAndHealthBarTest.test_the_struck_player_shakes_in_its_cell
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
        import random

        from game.item import JUNK, Item

        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        random.seed(70)
        self.state = GameState(WIDTH, HEIGHT)
        self.items = [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'epic'), Item(0, 0, JUNK)]
        self.state.pending_choice = list(self.items)

    def tearDown(self):
        self.renderer.close()

    def click(self, pos, button=1):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def test_frame_while_choosing_differs_from_one_without(self):
        box = screens.choice_rects(self.renderer.layout, self.state)[0]
        self.renderer.draw(self.state)
        with_choice = cell_pixels(self.renderer, box, as_list=True)
        pending, self.state.pending_choice = self.state.pending_choice, None
        self.renderer.draw(self.state)
        without = cell_pixels(self.renderer, box, as_list=True)
        self.state.pending_choice = pending
        self.assertNotEqual(with_choice, without)

    def test_three_cards_inside_the_box_and_apart(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        for i, card in enumerate(cards):
            self.assertTrue(box.contains(card))
            for other in cards[i + 1 :]:
                self.assertFalse(card.colliderect(other))

    def test_clicking_a_card_chooses_it(self):
        self.renderer.draw(self.state)
        self.click(self.cards()[1].center)
        action = self.renderer.get_action()
        self.assertEqual(action, Action.CHOOSE_2)
        self.state.handle_action(action)
        self.assertFalse(self.state.is_choosing)
        self.assertIs(self.state.player.weapon, self.items[1])

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

    def test_keyboard_2_chooses_the_second_item(self):
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_2, '2'))
        self.state.handle_action(self.renderer.get_action())
        self.assertIs(self.state.player.weapon, self.items[1])
        self.assertIsNone(self.state.player.armor)

    def test_card_clicks_mean_nothing_once_the_choice_is_made(self):
        self.renderer.draw(self.state)
        center = self.cards()[0].center
        self.state.choose(2)
        self.renderer.draw(self.state)
        self.click(center)
        pygame.event.post(key(pygame.K_d, 'd'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_narrow_map_stacks_the_cards(self):
        renderer = self.renderer
        renderer._set_mode((420, 700), pygame.RESIZABLE)
        renderer._relayout()
        box, cards, compact = screens.choice_rects(renderer.layout, self.state)
        if compact:
            self.assertTrue(cards[0].bottom <= cards[1].top <= cards[1].bottom <= cards[2].top)
        renderer.draw(self.state)  # paints without error either way


class TileModeChestChoiceScreenTest(ChestChoiceScreenTest):
    tiles = True


class NewWeaponChoiceScreenTest(ChestChoiceScreenTest):
    """The same overlay with the longest weapon-type cards on it."""

    def setUp(self):
        super().setUp()
        from game.item import JUNK, Item

        self.items = [
            Item(0, 0, 'great_sword', 'rare'),
            Item(0, 0, 'rapier', 'epic'),
            Item(0, 0, JUNK),
        ]
        self.state.pending_choice = list(self.items)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BoonChoiceScreenTest(unittest.TestCase):
    """A shrine's boons on the same overlay as a chest's items: painted in
    glyph and tile mode, chosen with 2 or a click on the second card; and
    the shrine itself painted on the map."""

    tiles = False

    def setUp(self):
        import random

        from game.shrine import BOONS

        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        random.seed(71)
        self.state = GameState(WIDTH, HEIGHT)
        self.boons = [BOONS['blood_pact'], BOONS['iron_skin'], BOONS['quick_hands']]
        self.state.pending_choice = list(self.boons)

    def tearDown(self):
        self.renderer.close()

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def test_boon_cards_paint_inside_the_box(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        self.renderer.draw(self.state)
        for card in cards:
            self.assertTrue(box.contains(card))
            self.assertGreater(len(cell_pixels(self.renderer, card)), 2)  # inked text

    def test_clicking_a_boon_card_takes_that_boon(self):
        self.renderer.draw(self.state)
        pygame.event.post(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=self.cards()[1].center, button=1)
        )
        action = self.renderer.get_action()
        self.assertEqual(action, Action.CHOOSE_2)
        self.assertFalse(self.state.handle_action(action))  # no turn
        self.assertFalse(self.state.is_choosing)
        self.assertEqual(self.state.player.boons, ['iron_skin'])

    def test_keyboard_3_takes_the_third_boon(self):
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_3, '3'))
        self.state.handle_action(self.renderer.get_action())
        self.assertEqual(self.state.player.boons, ['quick_hands'])

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
        }
        from game.item import GEAR_KINDS, RARITIES

        self.assertEqual(set(expected), set(GEAR_KINDS))
        for kind, lines in expected.items():
            self.assertEqual([self.text(kind, r) for r in RARITIES], lines, kind)

    def test_junk_still_shows_nothing_useful(self):
        from game.item import JUNK, Item
        from render import choice

        junk = Item(0, 0, JUNK)
        self.assertEqual(choice.stat_text(junk), 'nothing useful')
        self.assertEqual(
            choice.card_lines(3, junk), ['[3]', 'Rusty scrap', 'junk', 'nothing useful']
        )

    def test_cards_name_and_rarity_for_a_new_kind(self):
        from game.item import Item
        from render import choice

        item = Item(0, 0, 'dagger', 'rare')
        self.assertEqual(
            choice.card_lines(1, item), ['[1]', item.name, 'rare', '+3 damage, +15% crit']
        )
        self.assertIn('+15% crit', choice.compact_lines(1, item)[1])


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
        state = GameState(WIDTH, HEIGHT)
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

    def test_centre_stone_differs_from_plain_floor(self):
        plain, arena = self.frame(None), self.frame(self.arena)
        cx, cy = self.arena.center()
        self.assertNotEqual(self.cell(plain, cx, cy), self.cell(arena, cx, cy))

        # The tint is darker, not just different.
        def total(b):
            return sum(b)

        self.assertLess(total(self.cell(arena, cx, cy)), total(self.cell(plain, cx, cy)))

    def test_decal_cell_differs_from_plain_floor(self):
        plain, arena = self.frame(None), self.frame(self.arena)
        cx, cy = self.arena.center()
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
        state.game_map[6][10] = '#'
        decals = {(10, 6): (0, 0, 1.0)}
        with mock.patch.object(self.renderer, '_arena_decals', return_value=decals):
            self.renderer.draw(state)
        after = self.renderer.canvas.surface
        wall = self.cell(after, 10, 6)
        state.boss_arena = None
        self.renderer.draw(state)
        self.assertEqual(wall, self.cell(self.renderer.canvas.surface, 10, 6))


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
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = self.arena()
        self.renderer.draw(self.state)

    def tearDown(self):
        self.renderer.close()

    @staticmethod
    def arena(char_class='archer'):
        from game.item import Item

        state = GameState(WIDTH, HEIGHT, char_class=char_class)
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
        """(kind, ms, interruptible) of every beat draw() plays: 'flight' or
        'impact', told apart by the paint's keyword arguments (an impact may
        also carry the arrows held in the air during it)."""
        calls = []

        def play(ms, paint, interruptible=True):
            seen = {}
            with mock.patch.object(
                self.renderer, '_paint_game', side_effect=lambda state, **kw: seen.update(kw)
            ):
                paint(0.5)
            kind = 'impact' if seen.get('impact') else 'flight' if seen.get('flight') else '?'
            calls.append((kind, ms, interruptible, seen))

        with mock.patch.object(self.renderer, '_play', side_effect=play):
            self.renderer.draw(self.state)
        return calls

    @staticmethod
    def flight_of(path):
        """A one-arrow Flight over the whole of `path`."""
        return camera.Flight((tuple(path),), len(path) - 1)

    # -- flight ---------------------------------------------------------------

    def test_a_shot_plays_its_flight_then_the_impact(self):
        from render.pygame_render import FLIGHT_MS

        goblin = self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        calls = self.played()
        self.assertEqual([c[0] for c in calls], ['flight', 'impact'])
        kind, ms, interruptible, seen = calls[0]
        self.assertEqual(ms, 4 * FLIGHT_MS)
        self.assertFalse(interruptible)
        flight, _ = seen['flight']
        self.assertEqual(flight.paths[0][-1], (goblin.x, goblin.y))
        # While the arrow flies the goblin is drawn as it was before the hit.
        self.assertEqual([h.defender for h in seen['pending']], [goblin])
        impact_hit, _ = calls[1][3]['impact']
        self.assertIs(impact_hit.defender, goblin)

    def test_a_pierce_shots_second_impact_follows_the_second_flight(self):
        from game.item import Item

        Item(0, 0, 'longbow', 'common').apply(self.state.player, self.state.log)
        first, second = self.goblin(12, 10), self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        calls = self.played()
        self.assertEqual([c[0] for c in calls], ['flight', 'impact', 'flight', 'impact'])
        self.assertEqual(calls[0][3]['flight'][0].paths[0][-1], (12, 10))
        self.assertIs(calls[1][3]['impact'][0].defender, first)
        self.assertEqual(calls[2][3]['flight'][0].paths, (((12, 10), (13, 10), (14, 10)),))
        self.assertIs(calls[3][3]['impact'][0].defender, second)

    def test_a_miss_flies_to_the_pile_with_no_impact(self):
        self.state.game_map[10][14] = '#'
        self.state.handle_action('shoot_e')
        calls = self.played()
        self.assertEqual([c[0] for c in calls], ['flight'])
        self.assertEqual(calls[0][3]['flight'][0].paths[0][-1], (13, 10))
        self.assertIsNotNone(self.state.arrows_at(13, 10))

    def test_the_arrow_is_drawn_along_its_path_pointing_the_way_it_flies(self):
        r = self.renderer
        self.state.game_map[10][16] = '#'
        self.state.handle_action('shoot_e')
        flight = self.flight_of(self.state.shots[0].path)
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
        goblin = self.goblin(14, 10)
        self.state.handle_action('shoot_e')
        order = []
        r = self.renderer
        with (
            mock.patch.object(r, '_paint_flight', side_effect=lambda *a: order.append('arrow')),
            mock.patch.object(r, '_paint_impact', side_effect=lambda *a: order.append('impact')),
            mock.patch.object(r, '_paint_entity', side_effect=lambda e: order.append('entity')),
        ):
            hit = self.state.combat_events[-1]
            flight = self.flight_of(self.state.shots[0].path)
            r._paint_game(self.state, impact=(hit, 0.1), flight=(flight, 0.9))
        self.assertIs(hit.defender, goblin)
        self.assertEqual(order[-2:], ['arrow', 'impact'])
        self.assertLess(order.index('entity'), order.index('arrow'))

    def test_a_monster_killed_by_the_arrow_stays_on_screen_until_it_lands(self):
        goblin = self.goblin(13, 10, hp=1)
        self.state.handle_action('shoot_e')
        self.assertFalse(goblin.alive)
        hit = self.state.combat_events[-1]
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
        real_show = r._show
        shown = []

        def show(paint):
            if not shown:
                for event in typed:
                    pygame.event.post(event)
            shown.append(1)
            real_show(paint)

        start = pygame.time.get_ticks()
        with mock.patch.object(r, '_show', side_effect=show):
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
        shot = self.state.shots[0]
        self.assertEqual(len(shot.arrows), 3)
        calls = self.played()
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds[0], 'flight')
        self.assertTrue(all(not c[2] for c in calls))  # keys wait in the queue
        first, _ = calls[0][3]['flight']
        # One beat, all three arrows, each from the player's cell.
        self.assertEqual(len(first.paths), 3)
        self.assertEqual({p[0] for p in first.paths}, {(10, 10)})
        # Each arrow's impact comes after the flight that brings it there.
        impacts = [i for i, k in enumerate(kinds) if k == 'impact']
        struck = [calls[i][3]['impact'][0].defender for i in impacts]
        self.assertEqual(struck[:2], [near, far])
        for i in impacts:
            self.assertEqual(kinds[i - 1], 'flight')
            hit = calls[i][3]['impact'][0]
            self.assertIn((hit.x, hit.y), {p[-1] for p in calls[i - 1][3]['flight'][0].paths})
        # The near goblin's impact: the aim arrow hangs in the air meanwhile.
        held, t = calls[impacts[0]][3]['flight']
        self.assertEqual(t, 1.0)
        self.assertIn(shot.path[2], {p[-1] for p in held.paths})

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
        with mock.patch.object(self.state, '_dodged', return_value=False):
            self.state._monster_shot(goblin)
        calls = self.played()
        self.assertEqual([c[0] for c in calls[:2]], ['flight', 'impact'])
        self.assertFalse(calls[0][2] or calls[1][2])
        flight, _ = calls[0][3]['flight']
        self.assertEqual(flight.paths, (((14, 10), (13, 10), (12, 10), (11, 10), (10, 10)),))
        self.assertIs(calls[1][3]['impact'][0].defender, self.state.player)
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

    def test_restock_bar_sits_under_the_player_in_its_cell(self):
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

    def test_restock_bar_is_one_and_a_half_times_the_old_size(self):
        from render.pygame_render import (
            RESTOCK_BAR_HEIGHT,
            RESTOCK_BAR_WIDTH,
            RESTOCK_FILL,
            RESTOCK_TRACK,
        )

        self.assertAlmostEqual(RESTOCK_BAR_WIDTH, 1.5 * 0.7)
        self.assertAlmostEqual(RESTOCK_BAR_HEIGHT, 1.5 * 0.1)
        r = self.renderer
        cell = r._map_cell_rect(self.state.player.x, self.state.player.y)
        bar = r.restock_bar_rect(self.state.player)
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

    def test_parry_bar_is_full_when_ready_and_when_armed(self):
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

    def test_no_parry_bar_for_the_archer(self):
        r = self.renderer
        painted = []
        with mock.patch.object(r, '_paint_parry_bar', side_effect=lambda *a: painted.append(1)):
            r.draw(self.state)
            self.assertEqual(painted, [])
            r.draw(self.warrior())
        self.assertEqual(painted, [1])

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
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
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
        """(ms, interruptible, beat kind) of every beat draw() plays."""
        calls = []

        def play(ms, paint, interruptible=True):
            frame = {}  # the keywords one frame of the beat is painted with
            with mock.patch.object(
                self.renderer, '_paint_game', side_effect=lambda s, **kw: frame.update(kw)
            ):
                paint(0.5)
            kind = 'swing' if frame.get('swing') else 'impact' if frame.get('impact') else 'other'
            calls.append((ms, interruptible, kind))

        with mock.patch.object(self.renderer, '_play', side_effect=play):
            self.renderer.draw(state)
        return calls

    def test_the_swing_plays_first_uninterruptible_then_the_impact(self):
        for kind, ms in (('weapon', 120), ('dagger', 90), ('great_sword', 150), ('spear', 200)):
            with self.subTest(kind=kind):
                state, goblin = self.fight(kind)
                state.attack(state.player, goblin)
                calls = self.played(state)
                self.assertEqual([c[2] for c in calls], ['swing', 'impact'])
                self.assertEqual(calls[0][:2], (ms, False))
                self.assertFalse(calls[1][1])

    def test_a_monster_blow_plays_the_standard_swing(self):
        state, goblin = self.fight('spear')
        state.attack(goblin, state.player)
        calls = self.played(state)
        self.assertEqual([c[2] for c in calls], ['swing', 'impact'])
        self.assertEqual(calls[0][0], camera.SWING_MS)

    def test_an_arrow_plays_no_swing(self):
        state, goblin = self.fight()
        state._monster_shot(goblin)
        kinds = [c[2] for c in self.played(state)]
        self.assertIn('impact', kinds)
        self.assertNotIn('swing', kinds)

    def test_keys_pressed_during_the_swing_are_not_consumed(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]
        real_show = self.renderer._show
        shown = []

        def show(paint):
            if not shown:  # the swing's first frame: the player types ahead
                for event in typed:
                    pygame.event.post(event)
            shown.append(1)
            real_show(paint)

        start = pygame.time.get_ticks()
        with mock.patch.object(self.renderer, '_show', side_effect=show):
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

    def test_the_swing_is_drawn_in_the_direction_of_the_blow(self):
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

    def test_the_swing_is_gone_once_it_ends(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        (swing,) = [b for b in self.renderer.director.plan(state) if isinstance(b, camera.Swing)]
        self.renderer._view = self.renderer.director.current(state)
        self.assertEqual(self.changed(state, swing, 1.0), [])


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
            patcher = mock.patch(f'game.state.{target}', value)
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
        """(ms, interruptible, beat kind, attacker or None, text up) of every
        beat draw() plays, from one frame of each painted mid-beat."""
        calls = []
        r = self.renderer

        def play(ms, paint, interruptible=True):
            frame = {}
            with mock.patch.object(r, '_paint_game', side_effect=lambda s, **kw: frame.update(kw)):
                paint(0.5)
            attacker = None
            if frame.get('swing'):
                kind, attacker = 'swing', frame['swing'][0].origin
            elif frame.get('guard'):
                kind = 'guard'
            elif frame.get('impact'):
                kind = 'impact'
            elif frame.get('parry_text'):
                kind = 'text'
            else:
                kind = 'other'
            text = bool(frame.get('parry_text') or r._parry_text)
            calls.append((ms, interruptible, kind, attacker, text))

        with mock.patch.object(r, '_play', side_effect=play):
            r.draw(state)
        return calls

    def test_the_sequence_plays_in_order_uninterruptible(self):
        state, goblin = self.fight()
        p = state.player
        calls = self.played(state)
        self.assertEqual(
            [c[2:] for c in calls],
            [
                ('swing', (goblin.x, goblin.y), False),  # the monster's, no text yet
                ('guard', None, True),
                ('swing', (p.x, p.y), True),  # the riposte, back from the warrior
                ('impact', None, True),
                ('text', None, True),  # the text's fade
            ],
        )
        self.assertEqual(
            [c[0] for c in calls],
            [
                camera.SWING_MS,
                camera.GUARD_MS,
                camera.SWING_MS,
                self.renderer.impact_ms,
                camera.PARRY_FADE_MS,
            ],
        )
        self.assertTrue(all(not c[1] for c in calls))
        self.assertIsNone(self.renderer._parry_text)  # gone once the sequence ends

    def test_a_normal_blow_plays_its_swing_and_no_parry(self):
        state, goblin = self.fight(armed=False)
        calls = self.played(state)
        self.assertEqual(
            [c[2:4] for c in calls], [('swing', (goblin.x, goblin.y)), ('impact', None)]
        )
        self.assertFalse(any(c[4] for c in calls))

    def test_a_dodged_blow_plays_nothing(self):
        with mock.patch('game.state.dodge_chance', return_value=100):
            state, _ = self.fight()
        self.assertEqual(self.played(state), [])

    def test_keys_pressed_during_the_parry_are_not_consumed(self):
        state, _ = self.fight()
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]
        real_show = self.renderer._show
        shown = []

        def show(paint):
            if not shown:
                for event in typed:
                    pygame.event.post(event)
            shown.append(1)
            real_show(paint)

        start = pygame.time.get_ticks()
        with mock.patch.object(self.renderer, '_show', side_effect=show):
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
        (parry,) = state.parries
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
        (parry,) = state.parries
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
    """Clear the level, then put one goblin next to a 1-HP player."""
    state.cancel_monster_phase()
    state.player.hp = 1
    state.player.defense = 0
    x, y = open_neighbour(state)
    state.entities = [state.player, Monster(x, y, 'goblin', depth=state.depth)]
    state.update_fov()


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
    state = GameState(WIDTH, HEIGHT)
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
        state = GameState(WIDTH, HEIGHT)
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


if __name__ == '__main__':
    unittest.main()
