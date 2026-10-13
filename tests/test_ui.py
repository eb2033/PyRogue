"""Headless tests for render/ui.py and render/screens.py (desktop_build_plan.md
WS-D). Skip cleanly without pygame-ce. render/tileset.py: tests/test_tileset.py."""

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

if pygame is not None:
    from render import palette, screens, ui

WIDTH, HEIGHT = 40, 20


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
class TileLayoutTest(unittest.TestCase):
    """tiles=True: a square-celled map beside a text panel, both in the window."""

    def setUp(self):
        self.layout = ui.Layout(WIDTH, HEIGHT, tiles=True)

    def assertFitsInside(self, size):
        window = pygame.Rect((0, 0), size)
        map_rect, panel_rect = self.layout.map_rect(), self.layout.panel_rect()
        self.assertTrue(window.contains(map_rect), (map_rect, size))
        panel_text = pygame.Rect(panel_rect.topleft,
                                 (panel_rect.w, self.layout.cell_h * ui.PANEL_ROWS))
        self.assertTrue(window.contains(panel_text), (panel_text, size))
        self.assertFalse(map_rect.colliderect(panel_rect))

    def test_map_cells_are_square_tiles(self):
        self.layout.fit((1600, 900))
        self.assertIn(self.layout.tile, ui.TILE_SIZES)
        self.assertEqual(self.layout.map_cell_size(), (self.layout.tile, self.layout.tile))
        self.assertEqual(self.layout.map_rect().size,
                         (WIDTH * self.layout.tile, HEIGHT * self.layout.tile))
        x0, y0 = self.layout.map_cell_to_pixel(0, 0)
        self.assertEqual(self.layout.map_cell_to_pixel(3, 2),
                         (x0 + 3 * self.layout.tile, y0 + 2 * self.layout.tile))

    def test_bigger_window_never_gets_smaller_tiles(self):
        sizes = [(1024, 600), (1280, 720), (1600, 900), (1920, 1080), (3840, 2160)]
        tiles = []
        for size in sizes:
            self.layout.fit(size)
            self.assertFitsInside(size)
            tiles.append(self.layout.tile)
        self.assertEqual(tiles, sorted(tiles))
        self.assertGreater(tiles[-1], tiles[0])

    def test_panel_font_stays_readable_when_tiles_grow(self):
        self.layout.fit((1920, 1080))
        self.assertGreaterEqual(self.layout.font.get_height(),
                                self.layout._font(ui.MIN_TILE_FONT_SIZE).get_height())

    def test_tiny_window_does_not_raise(self):
        self.layout.fit((200, 100))
        self.assertEqual(self.layout.tile, ui.TILE_SIZES[-1])

    def test_preferred_size_fits_the_desktop(self):
        width, height = self.layout.preferred_window_size()
        desktop_w, desktop_h = ui._desktop_size()
        self.assertLessEqual(width, desktop_w)
        self.assertLessEqual(height, desktop_h)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PaintTest(unittest.TestCase):
    """Smoke tests: each paint function draws something and doesn't raise."""

    def setUp(self):
        self.layout = ui.Layout(WIDTH, HEIGHT)
        self.layout.fit((1200, 600))
        self.canvas = ui.Canvas(pygame.Surface((1200, 600)), self.layout)
        self.canvas.clear()

    def assertDrewSomething(self, rect):
        # Count pixels, don't average them: one line of text over the whole
        # map area averages to (0, 0, 0) with thinner fonts (Consolas on
        # Windows CI, Liberation Mono) even though ~1600 pixels are lit.
        area = self.canvas.surface.subsurface(rect)
        untouched = pygame.mask.from_threshold(area, palette.BACKGROUND, (1, 1, 1, 255))
        self.assertLess(untouched.count(), area.get_width() * area.get_height(),
                        'nothing drawn in this area')

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
