"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import os
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

from game.state import GameState
from render.base import Action

if pygame is not None:
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


if __name__ == '__main__':
    unittest.main()
