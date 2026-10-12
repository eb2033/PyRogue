"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import os
import sys
import unittest
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
    from render import screens
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
        cell = self.renderer.layout.cell_rect(state.player.x, state.player.y)
        screen = self.renderer.canvas.surface
        pixels = {tuple(screen.get_at((x, y)))[:3]
                  for x in range(cell.left, cell.right) for y in range(cell.top, cell.bottom)}
        self.assertTrue(pixels - {BACKGROUND}, 'player cell is blank')

    def test_get_action_maps_keys_like_curses(self):
        self.post(key(pygame.K_w, 'w'), key(pygame.K_s, 'S', shift=True),
                  key(pygame.K_UP), key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)
        self.assertEqual(self.renderer.get_action(), Action.SAVE)
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
        self.post(pygame.event.Event(pygame.VIDEORESIZE, size=(3000, 1500), w=3000, h=1500),
                  key(pygame.K_d, 'd'))
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
        self.post(enter, key(pygame.K_s, 's'), enter,
                  key(pygame.K_w, 'w'), key(pygame.K_RIGHT), key(pygame.K_PERIOD, '.'),
                  key(pygame.K_q, 'q'))
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
        cell = self.renderer.layout.cell_rect(state.player.x, state.player.y)
        self.assertTrue(cell_pixels(self.renderer, cell) - {BACKGROUND},
                        'frame not repainted after going fullscreen')

    def test_f11_in_a_menu_is_not_a_selection(self):
        # F11 twice (in and out), then Down: still on the title menu, so the
        # Enter selects Quit -- F11 neither confirmed nor moved anything.
        self.post(key(pygame.K_F11), key(pygame.K_F11), key(pygame.K_DOWN),
                  key(pygame.K_RETURN, '\r'))
        self.assertFalse(self.renderer.show_title_screen())
        self.assertFalse(self.renderer.fullscreen)

    def test_fullscreen_failure_is_harmless(self):
        size = self.renderer.canvas.surface.get_size()
        window = mock.Mock()
        window.set_fullscreen.side_effect = pygame.error('no fullscreen here')
        with mock.patch.object(PygameRenderer, '_display_window', return_value=window):
            self.renderer.toggle_fullscreen()
        with mock.patch.object(PygameRenderer, '_display_window', return_value=None), \
                mock.patch('pygame.display.set_mode', side_effect=pygame.error('no')):
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
        cell = self.renderer.layout.cell_rect(x, y)

        self.renderer.draw(state)
        boss_pixels = lit_pixels(self.renderer, cell)
        boss.is_boss = False
        self.renderer.draw(state)
        plain_pixels = lit_pixels(self.renderer, cell)

        self.assertGreater(len(boss_pixels), len(plain_pixels))
        # Brightest *red* pixel: the grey floor dot under the glyph is in both.
        def brightest_red(pixels):
            return max(sum(p) for p in pixels if p[0] > p[1] + 40)
        self.assertGreater(brightest_red(boss_pixels), brightest_red(plain_pixels))

    def test_font_path_reaches_the_layout(self):
        font = os.path.join(os.path.dirname(pygame.__file__), pygame.font.get_default_font())
        self.renderer.close()
        self.renderer = PygameRenderer(WIDTH, HEIGHT, font_path=font)
        self.assertEqual(self.renderer.layout.font_path, font)
        self.renderer.draw(GameState(WIDTH, HEIGHT))

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
        text = screens.GAME_OVER_TEXT
        x0 = max(0, (state.width - len(text)) // 2)
        layout = self.renderer.layout
        row = layout.cell_rect(x0, state.height // 2).union(
            layout.cell_rect(x0 + len(text) - 1, state.height // 2))
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


class DefaultRendererTest(unittest.TestCase):
    """main.default_renderer: a frozen (--windowed) exe has no terminal."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop('RENDERER', None)

    def test_source_run_defaults_to_curses(self):
        with mock.patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(main.default_renderer(), 'curses')

    def test_frozen_build_defaults_to_pygame(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(main.default_renderer(), 'pygame')

    def test_env_overrides_the_frozen_default(self):
        os.environ['RENDERER'] = 'curses'
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(main.default_renderer(), 'curses')

    def test_tcod_is_no_longer_a_choice(self):
        self.assertEqual(main.RENDERERS, ['curses', 'pygame'])


# -- helpers -----------------------------------------------------------------

def cell_pixels(renderer, rect, as_list=False):
    screen = renderer.canvas.surface
    pixels = [tuple(screen.get_at((x, y)))[:3]
              for y in range(rect.top, rect.bottom) for x in range(rect.left, rect.right)]
    return pixels if as_list else set(pixels)


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


if __name__ == '__main__':
    unittest.main()
