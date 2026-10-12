"""Headless tests for render/ui.py, render/screens.py and render/tileset.py
(desktop_build_plan.md WS-D / WS-C). Skip cleanly without pygame-ce."""

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
from render.menu import Menu
from render.tileset import Tileset

if pygame is not None:
    from render import palette, screens, ui

WIDTH, HEIGHT = 40, 20


class TilesetStubTest(unittest.TestCase):
    """The fallback contract: no assets means 'draw the glyph', never an error."""

    def test_missing_assets_fall_back_to_glyphs(self):
        tileset = Tileset(path=None)
        self.assertFalse(tileset.available)
        self.assertIsNone(tileset.glyph('@', 1))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.layout = ui.Layout(WIDTH, HEIGHT)

    def test_grid_holds_map_and_panel(self):
        self.assertEqual(self.layout.panel_x, WIDTH + ui.PANEL_GAP)
        self.assertEqual(self.layout.cols, WIDTH + ui.PANEL_GAP + ui.PANEL_COLS)
        self.assertGreaterEqual(self.layout.rows, HEIGHT)

    def test_bigger_window_gets_bigger_cells_and_stays_inside(self):
        self.layout.fit((800, 400))
        small = self.layout.cell_w
        self.layout.fit((2400, 1200))
        self.assertGreater(self.layout.cell_w, small)
        self.assertLessEqual(self.layout.cell_w * self.layout.cols, 2400)
        self.assertLessEqual(self.layout.cell_h * self.layout.rows, 1200)

    def test_grid_is_letterboxed_in_the_centre(self):
        self.layout.fit((4000, 600))  # far wider than the grid needs
        grid_w = self.layout.cell_w * self.layout.cols
        self.assertAlmostEqual(self.layout.origin_x, (4000 - grid_w) // 2, delta=1)

    def test_map_and_panel_rects_do_not_overlap(self):
        self.layout.fit((1200, 600))
        self.assertFalse(self.layout.map_rect().colliderect(self.layout.panel_rect()))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PaintTest(unittest.TestCase):
    """Smoke tests: each paint function draws something and doesn't raise."""

    def setUp(self):
        self.layout = ui.Layout(WIDTH, HEIGHT)
        self.layout.fit((1200, 600))
        self.canvas = ui.Canvas(pygame.Surface((1200, 600)), self.layout)
        self.canvas.clear()

    def assertDrewSomething(self, rect):
        area = self.canvas.surface.subsurface(rect)
        self.assertNotEqual(pygame.transform.average_color(area)[:3], palette.BACKGROUND)

    def test_panel(self):
        ui.paint_panel(self.canvas, GameState(WIDTH, HEIGHT))
        self.assertDrewSomething(self.layout.panel_rect())

    def test_menu(self):
        screens.paint_menu(self.canvas, Menu(screens.CLASS_OPTIONS), ['Choose your class'],
                           screens.CLASS_DESCRIPTIONS)
        self.assertDrewSomething(self.canvas.surface.get_rect())

    def test_game_over(self):
        screens.paint_game_over(self.canvas, GameState(WIDTH, HEIGHT))
        self.assertDrewSomething(self.layout.map_rect())


if __name__ == '__main__':
    unittest.main()
