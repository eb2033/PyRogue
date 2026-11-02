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

from typing import cast
from unittest import mock

from game.item import BELT_SLOTS, Item, belt_capacity
from game.shrine import BOON_COLOR
from game.state import GameState
from render.menu import Menu

if pygame is not None:
    from render import noticeboard, palette, screens, ui

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
        panel_text = pygame.Rect(
            panel_rect.topleft, (panel_rect.w, self.layout.cell_h * ui.PANEL_ROWS)
        )
        self.assertTrue(window.contains(panel_text), (panel_text, size))
        self.assertFalse(map_rect.colliderect(panel_rect))
        log_rect = self.layout.log_rect()
        self.assertTrue(window.contains(log_rect), (log_rect, size))
        self.assertFalse(log_rect.colliderect(map_rect))
        self.assertFalse(log_rect.colliderect(panel_rect))

    def test_map_cells_are_square_tiles(self):
        self.layout.fit((1600, 900))
        tile = cast(int, self.layout.tile)
        self.assertIn(tile, ui.TILE_SIZES)
        self.assertEqual(self.layout.map_cell_size(), (tile, tile))
        self.assertEqual(self.layout.map_rect().size, (WIDTH * tile, HEIGHT * tile))
        x0, y0 = self.layout.map_cell_to_pixel(0, 0)
        self.assertEqual(
            self.layout.map_cell_to_pixel(3, 2),
            (x0 + 3 * tile, y0 + 2 * tile),
        )

    def test_every_common_window_fits_and_bigger_never_gets_smaller_tiles(self):
        sizes = [(1024, 600), (1280, 720), (1600, 900), (1920, 1080), (3840, 2160)]
        tiles = []
        for size in sizes:
            with self.subTest(size=size):
                self.layout.fit(size)
                self.assertFitsInside(size)
                self.assertIn(self.layout.tile, ui.TILE_SIZES)
                tiles.append(self.layout.tile)
        self.assertEqual(tiles, sorted(tiles))
        self.assertGreater(tiles[-1], tiles[0])

    def test_panel_font_stays_readable_when_tiles_grow_and_grows_past_the_cap_at_4k(self):
        self.layout.fit((1920, 1080))
        self.assertGreaterEqual(
            self.layout.font.get_height(), self.layout._font(ui.MIN_TILE_FONT_SIZE).get_height()
        )
        self.layout.fit((3840, 2160))
        self.assertGreater(
            self.layout.font.get_height(), self.layout._font(ui.MAX_TILE_FONT_SIZE).get_height()
        )

    def test_preferred_size_fits_the_desktop(self):
        width, height = self.layout.preferred_window_size()
        desktop_w, desktop_h = ui._desktop_size()
        self.assertLessEqual(width, desktop_w)
        self.assertLessEqual(height, desktop_h)

    def test_first_window_is_1920x1080_on_a_big_desktop(self):
        # Big enough that 1920x1080 stays within DESKTOP_SHARE of it.
        for desktop in [(2560, 1440), (3840, 2160), (2560, 1600)]:
            with self.subTest(desktop=desktop):
                self.assertEqual(ui.first_window_size(desktop), (1920, 1080))
        with mock.patch.object(ui, '_desktop_size', return_value=(2560, 1440)):
            self.assertEqual(self.layout.preferred_window_size(), (1920, 1080))

    def test_first_window_is_capped_16_9_on_a_small_desktop(self):
        # A 1536x864 desktop is 1920x1080 at Windows' 125% scaling, seen by
        # a process that isn't DPI-aware.
        for desktop in [
            (1536, 864),
            (1366, 768),
            (1280, 800),
            (1024, 768),
            (1920, 1000),
            (1920, 1080),
            (1920, 1200),
            (2048, 1152),
        ]:
            with self.subTest(desktop=desktop):
                width, height = ui.first_window_size(desktop)
                self.assertLessEqual(width, desktop[0] * ui.DESKTOP_SHARE)
                self.assertLessEqual(height, desktop[1] * ui.DESKTOP_SHARE)
                self.assertEqual(width * 9 // 16, height)
        # The largest 16:9 size inside 85%: bound by height on a 16:9 or wide
        # desktop (1536x864 -> 1305x734 usable), by width on a 4:3 one.
        self.assertEqual(ui.first_window_size((1536, 864)), (1304, 733))
        self.assertEqual(ui.first_window_size((1920, 1000)), (1511, 849))
        self.assertEqual(ui.first_window_size((1024, 768)), (870, 489))
        # A 1920x1080 desktop must not be filled by the window (taskbar,
        # title bar): 85% of it, 16:9.
        self.assertEqual(ui.first_window_size((1920, 1080)), (1632, 918))


# Window sizes every layout test sweeps: landscape, 4K, portrait, narrow, tiny.
SIZES = [
    (1280, 720),
    (1920, 1080),
    (3840, 2160),
    (800, 1200),
    (700, 900),
    (1024, 600),
    (2000, 700),
    (300, 200),
]


def fitted(size, tiles=False):
    layout = ui.Layout(WIDTH, HEIGHT, tiles=tiles)
    layout.fit(size)
    return layout


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class StackedLayoutTest(unittest.TestCase):
    """Task 4: the panel goes under the map when that gives bigger map cells."""

    def assertSane(self, layout, size):
        window = pygame.Rect((0, 0), size)
        map_rect, panel_rect = layout.map_rect(), layout.panel_rect()
        self.assertFalse(map_rect.colliderect(panel_rect), (map_rect, panel_rect))
        self.assertTrue(window.contains(map_rect), (map_rect, size))
        # The panel's minimum rows of text, at its full width, are on screen.
        panel_text = pygame.Rect(panel_rect.topleft, (panel_rect.w, layout.cell_h * ui.PANEL_ROWS))
        self.assertTrue(window.contains(panel_text), (panel_text, size))
        self.assertGreaterEqual(layout.rows - layout.panel_y, ui.PANEL_ROWS)
        self.assertGreaterEqual(layout.panel_width(), ui.PANEL_COLS)
        log_rect = layout.log_rect()
        self.assertFalse(log_rect.colliderect(map_rect), (log_rect, map_rect))
        self.assertFalse(log_rect.colliderect(panel_rect), (log_rect, panel_rect))

    def test_every_size_fits_without_overlap(self):
        for tiles in (False, True):
            for size in SIZES[:-1]:  # the tiny one can't fit anything legibly
                with self.subTest(tiles=tiles, size=size):
                    self.assertSane(fitted(size, tiles), size)

    def test_tiny_window_does_not_raise(self):
        for tiles in (False, True):
            fitted(SIZES[-1], tiles).panel_rect()
        # The tiniest tile window gets the smallest tile.
        self.assertEqual(fitted((200, 100), tiles=True).tile, ui.TILE_SIZES[-1])

    def test_landscape_stays_side_by_side_and_portrait_or_narrow_stacks(self):
        for tiles in (False, True):
            for size in [(1280, 720), (1920, 1080), (3840, 2160)]:
                with self.subTest(tiles=tiles, size=size):
                    layout = fitted(size, tiles)
                    self.assertFalse(layout.stacked)
                    self.assertGreater(layout.panel_rect().left, layout.map_rect().right)
        # Glyph mode stacks map, stats board and log board in a column of
        # text rows, so it takes a taller portrait than tile mode to win.
        # (600, 1000) in tile mode: 40 x 16px tiles = 640px, so the map
        # overflows -- but the panel must go under it, not on top of it.
        for tiles, sizes in [(False, [(600, 1400)]), (True, [(800, 1200), (600, 1000)])]:
            for size in sizes:
                with self.subTest(tiles=tiles, size=size):
                    layout = fitted(size, tiles)
                    self.assertTrue(layout.stacked)
                    self.assertGreaterEqual(layout.panel_rect().top, layout.map_rect().bottom)

    def test_stacking_gives_the_map_bigger_glyphs(self):
        stacked = fitted((600, 1400))
        self.assertTrue(stacked.stacked)
        side = ui.Layout(WIDTH, HEIGHT)
        cols, rows = side._glyph_grid(False)[:2]
        side_size = side._largest_glyph_font(cols, rows, 600, 1400)
        self.assertGreater(stacked.cell_w, side._cell_size(side._font(side_size))[0])

    def test_glyph_map_stays_at_grid_cell_zero(self):
        # The renderer draws glyph-mode map cells with Canvas.put (grid cells).
        for size in [(1280, 720), (600, 1400)]:
            layout = fitted(size)
            self.assertEqual(layout.map_origin, layout.cell_to_pixel(0, 0))
            self.assertEqual(layout.map_cell_to_pixel(3, 2), layout.cell_to_pixel(3, 2))

    def test_refit_back_to_landscape_unstacks(self):
        layout = fitted((600, 1400))
        self.assertTrue(layout.stacked)
        layout.fit((1280, 720))
        self.assertFalse(layout.stacked)
        self.assertEqual(layout.panel_x, WIDTH + ui.PANEL_GAP)
        self.assertEqual(layout.panel_y, 0)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class LogBoardTest(unittest.TestCase):
    """The message log has its own board: under the map side by side, under
    the stats board when stacked."""

    def test_log_board_never_overlaps_map_or_panel(self):
        for tiles in (False, True):
            for size in SIZES + [(320, 240)]:
                with self.subTest(tiles=tiles, size=size):
                    layout = fitted(size, tiles)
                    log, m, p = layout.log_rect(), layout.map_rect(), layout.panel_rect()
                    self.assertFalse(log.colliderect(m), (size, tiles))
                    self.assertFalse(log.colliderect(p), (size, tiles))

    def test_side_by_side_log_board_is_under_the_map_and_as_wide(self):
        layout = fitted((1920, 1080), True)
        self.assertFalse(layout.stacked)
        log, m = layout.log_rect(), layout.map_rect()
        self.assertGreaterEqual(log.top, m.bottom)
        self.assertLessEqual(m.left, log.left)
        self.assertLessEqual(log.right, m.right)
        self.assertGreater(log.width, m.width - 2 * layout.cell_w)

    def test_stacked_log_board_is_under_the_panel(self):
        for tiles in (False, True):
            with self.subTest(tiles=tiles):
                layout = fitted((600, 1400), tiles)
                self.assertTrue(layout.stacked)
                self.assertGreaterEqual(layout.log_rect().top, layout.panel_rect().bottom)

    def test_log_lines_between_min_and_cap(self):
        for tiles in (False, True):
            for size in SIZES:
                with self.subTest(tiles=tiles, size=size):
                    lines = fitted(size, tiles).log_lines()
                    self.assertTrue(ui.MIN_LOG_LINES <= lines <= ui.LOG_LINES, lines)

    def test_log_page_holds_the_log_text(self):
        layout = fitted((1920, 1080), True)
        self.assertTrue(layout.log_rect().contains(layout.log_page_rect()))
        text = pygame.Rect(
            layout.cell_to_pixel(layout.log_text_x, layout.log_text_y),
            (layout.log_text_width() * layout.cell_w, (1 + layout.log_lines()) * layout.cell_h),
        )
        self.assertTrue(layout.log_page_rect().contains(text))

    def test_stats_board_is_a_fixed_height(self):
        for tiles, size in [(False, (1280, 720)), (True, (1920, 1080)), (True, (3840, 2160))]:
            with self.subTest(tiles=tiles, size=size):
                layout = fitted(size, tiles)
                self.assertEqual(layout.panel_rows(), ui.PANEL_ROWS)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class MessageLogTest(unittest.TestCase):
    """Task 2: more log lines than the terminal's 4, wrapped to the log board."""

    def test_a_roomy_window_shows_more_than_the_terminal(self):
        self.assertGreater(ui.LOG_LINES, ui.MIN_LOG_LINES)
        for tiles in (False, True):
            self.assertEqual(fitted((3840, 2160), tiles).log_lines(), ui.LOG_LINES)

    def test_preferred_glyph_window_shows_a_longer_log(self):
        layout = ui.Layout(WIDTH, HEIGHT)
        with mock.patch.object(ui, '_desktop_size', return_value=(1920, 1080)):
            layout.fit(layout.preferred_window_size())
        self.assertGreater(layout.log_lines(), ui.MIN_LOG_LINES)

    def test_log_rows_keeps_the_newest_whole_messages(self):
        messages = ['one', 'two words here', 'three']
        self.assertEqual(ui.log_rows(messages, 10, 3), ['two words', 'here', 'three'])
        self.assertEqual(ui.log_rows(messages, 10, 2), ['three'])
        self.assertEqual(ui.log_rows(messages, 40, 10), messages)
        self.assertEqual(ui.log_rows([], 44, 4), [])  # an empty log

    def test_log_rows_never_exceeds_width_or_rows(self):
        messages = ['x' * 100, 'a b c d e f g h i j k l m n o p']
        for width, rows in [(10, 3), (5, 1), (44, 12)]:
            lines = ui.log_rows(messages, width, rows)
            self.assertLessEqual(len(lines), rows)
            self.assertTrue(all(len(line) <= width for line in lines), lines)

    def test_a_message_too_long_for_the_log_is_cut_not_dropped(self):
        self.assertEqual(ui.log_rows(['aaaa bbbb cccc'], 4, 2), ['aaaa', 'bbbb'])


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class CanvasBoldTest(unittest.TestCase):
    """Task 3: Canvas.put / put_str take bold=, cached like plain glyphs."""

    def setUp(self):
        self.layout = fitted((1200, 600))
        self.canvas = ui.Canvas(pygame.Surface((1200, 600)), self.layout)

    def cell_bytes(self, x, y):
        return pygame.image.tobytes(
            self.canvas.surface.subsurface(self.layout.cell_rect(x, y)), 'RGB'
        )

    def test_bold_glyph_differs_from_plain_and_is_cached_separately(self):
        self.canvas.clear()
        # Every other cell: a bold glyph may spill a pixel into the next one.
        self.canvas.put(0, 0, 'O', palette.TEXT)
        self.canvas.put(2, 0, 'O', palette.TEXT, bold=True)
        self.canvas.put(4, 0, 'O', palette.TEXT, underline=True, bold=True)
        self.assertNotEqual(self.cell_bytes(0, 0), self.cell_bytes(2, 0))
        self.assertNotEqual(self.cell_bytes(2, 0), self.cell_bytes(4, 0))
        self.assertEqual(len(self.canvas._glyphs), 3)
        self.canvas.put(6, 0, 'O', palette.TEXT, bold=True)
        self.assertEqual(len(self.canvas._glyphs), 3)
        self.assertEqual(self.cell_bytes(2, 0), self.cell_bytes(6, 0))

    def test_bold_does_not_leak_into_later_plain_text(self):
        self.canvas.clear()
        self.canvas.put_str(0, 0, 'HHHH', bold=True)
        self.canvas.put_str(0, 2, 'HHHH')
        self.canvas.put_str(0, 1, 'HHHH')
        self.assertEqual(self.cell_bytes(0, 1), self.cell_bytes(0, 2))
        self.assertNotEqual(self.cell_bytes(0, 0), self.cell_bytes(0, 1))
        self.assertFalse(self.layout.font.get_bold())

    def test_text_surface_bold(self):
        plain = self.canvas.text_surface('W')
        bold = self.canvas.text_surface('W', bold=True, underline=True)
        self.assertNotEqual(pygame.image.tobytes(plain, 'RGB'), pygame.image.tobytes(bold, 'RGB'))


def biggest(rects):
    return max(rects, key=lambda r: r.w * r.h)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class OptionAtTest(unittest.TestCase):
    """Task 5: the mouse hit-test WS-A's menu loop relies on agrees with
    paint_menu's geometry."""

    BANNERS = [['Banner'], ['#### #', '#  # #', '#### #'], ['Choose your class']]

    def layouts(self):
        for tiles in (False, True):
            for size in [(1200, 600), (1920, 1080), (700, 900)]:
                yield tiles, size, fitted(size, tiles)

    def highlights(self, layout, menu, banner):
        """{option index: pixel rect of its highlight bar}, read off a real
        paint_menu by moving the selection to each option in turn."""
        surface = pygame.Surface(layout.cell_to_pixel(layout.cols, layout.rows))
        canvas = ui.Canvas(surface, layout)
        rects = {}
        for i in range(len(menu.options)):
            menu.index = i
            canvas.clear()
            screens.paint_menu(canvas, menu, banner)
            # The selected option is drawn on a TEXT-coloured background.
            mask = pygame.mask.from_threshold(surface, palette.TEXT, (1, 1, 1, 255))
            rects[i] = biggest(mask.get_bounding_rects())
        menu.index = 0
        return rects

    def test_returns_none_or_a_valid_index(self):
        layout = fitted((1200, 600))
        menu = Menu(screens.TITLE_OPTIONS)
        for pixel in [(0, 0), (600, 300), (1199, 599), (-5, -5)]:
            hit = screens.option_at(layout, menu, ['Banner'], pixel)
            self.assertTrue(hit is None or 0 <= hit < len(menu.options), hit)

    def test_each_painted_option_hits_itself(self):
        for tiles, size, layout in self.layouts():
            for banner in self.BANNERS:
                for options in (screens.TITLE_OPTIONS, screens.CLASS_OPTIONS):
                    menu = Menu(options)
                    for i, bar in self.highlights(layout, menu, banner).items():
                        with self.subTest(tiles=tiles, size=size, banner=banner, option=i):
                            for point in (
                                bar.center,
                                bar.topleft,
                                (bar.right - 1, bar.bottom - 1),
                            ):
                                self.assertEqual(screens.option_at(layout, menu, banner, point), i)

    def test_rows_between_and_around_options_hit_nothing(self):
        for tiles, size, layout in self.layouts():
            menu = Menu(screens.TITLE_OPTIONS)
            banner = self.BANNERS[1]
            first, second = self.highlights(layout, menu, banner).values()
            x = first.centerx
            with self.subTest(tiles=tiles, size=size):
                for point in [
                    (x, first.top - 1),
                    (x, first.bottom + layout.cell_h // 2),
                    (x, second.bottom),
                    (layout.origin_x, first.centery),
                    (-1, -1),
                ]:
                    self.assertIsNone(screens.option_at(layout, menu, banner, point), point)

    def test_hit_area_spans_the_widest_option(self):
        layout = fitted((1200, 600))
        menu = Menu(screens.CLASS_OPTIONS)  # 'Warrior' is wider than 'Archer'
        warrior, archer = self.highlights(layout, menu, ['x']).values()
        self.assertLess(archer.w, warrior.w)
        for x in (warrior.left, warrior.right - 1):
            self.assertEqual(screens.option_at(layout, menu, ['x'], (x, archer.centery)), 1)
        self.assertIsNone(
            screens.option_at(layout, menu, ['x'], (warrior.right + 1, archer.centery))
        )

    def test_hint_wraps_in_a_narrow_grid(self):
        layout = fitted((600, 1400))
        self.assertTrue(layout.stacked)
        self.assertLess(layout.cols, len(screens.MENU_HINT))
        canvas = ui.Canvas(pygame.Surface((600, 1400)), layout)
        canvas.clear()
        screens.paint_menu(canvas, Menu(screens.TITLE_OPTIONS), ['x'])
        for row in (layout.rows - 3, layout.rows - 2):
            rect = layout.cell_rect(0, row).union(layout.cell_rect(layout.cols - 1, row))
            area = canvas.surface.subsurface(rect)
            blank = pygame.mask.from_threshold(area, palette.BACKGROUND, (1, 1, 1, 255))
            self.assertLess(blank.count(), area.get_width() * area.get_height(), row)


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
        self.assertLess(
            untouched.count(), area.get_width() * area.get_height(), 'nothing drawn in this area'
        )

    def test_each_paint_function_draws_in_its_area(self):
        state = GameState(WIDTH, HEIGHT, seed=0)
        cases = [
            ('panel', lambda: ui.paint_panel(self.canvas, state), self.layout.panel_rect()),
            ('log', lambda: ui.paint_log(self.canvas, state), self.layout.log_rect()),
            (
                'menu',
                lambda: screens.paint_menu(
                    self.canvas,
                    Menu(screens.CLASS_OPTIONS),
                    ['Choose your class'],
                    screens.CLASS_DESCRIPTIONS,
                ),
                self.canvas.surface.get_rect(),
            ),
            ('game over', lambda: screens.paint_game_over(self.canvas), self.layout.map_rect()),
        ]
        for name, paint, rect in cases:
            with self.subTest(name):
                self.canvas.clear()
                paint()
                self.assertDrewSomething(rect)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GameOverBannerTest(unittest.TestCase):
    """The banner is centred across the top of the map, its title four
    times the map's font."""

    def test_banner_is_centred_at_the_top_of_the_map(self):
        for tiles in (False, True):
            for width, height in [(WIDTH, HEIGHT), (20, 10)]:
                with self.subTest(tiles=tiles, map=(width, height)):
                    layout = ui.Layout(width, height, tiles=tiles)
                    layout.fit((1280, 720))
                    box = screens.game_over_rect(layout)
                    area = layout.map_rect()
                    self.assertTrue(area.contains(box))
                    self.assertEqual(box.centerx, area.centerx)
                    self.assertLess(box.top - area.top, layout.cell_h * 2)

    def test_title_is_four_times_the_map_font(self):
        layout = fitted((1280, 720), tiles=True)
        title_font, hint_font = screens.game_over_fonts(layout)
        self.assertEqual(title_font.get_height(), layout._font(layout.font_size * 4).get_height())
        self.assertEqual(hint_font, layout.font)

    def test_title_shrinks_to_fit_a_narrow_map(self):
        layout = ui.Layout(12, 10, tiles=False)
        layout.fit((1280, 720))
        title_font, _ = screens.game_over_fonts(layout)
        self.assertLessEqual(
            title_font.size(screens.GAME_OVER_TITLE)[0],
            layout.map_rect().width - 2 * layout.cell_w,
        )
        self.assertGreaterEqual(title_font.get_height(), layout.font.get_height())


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class NoticeboardTest(unittest.TestCase):
    """The panel is a wooden board with a parchment page, kept narrow so the
    map gets bigger tiles."""

    def test_common_window_sizes_get_bigger_tiles(self):
        for size, tile in [((1280, 720), 24), ((1600, 900), 32), ((1920, 1080), 40)]:
            with self.subTest(size=size):
                self.assertGreaterEqual(cast(int, fitted(size, tiles=True).tile), tile)

    def test_board_and_page_are_drawn_behind_the_text(self):
        for tiles, size in [(False, (1280, 720)), (True, (1920, 1080)), (True, (600, 1000))]:
            with self.subTest(tiles=tiles, size=size):
                layout = fitted(size, tiles)
                surface = pygame.Surface(size)
                canvas = ui.Canvas(surface, layout)
                canvas.clear()
                ui.paint_panel(canvas, GameState(WIDTH, HEIGHT, seed=0))
                ui.paint_log(canvas, GameState(WIDTH, HEIGHT, seed=0))
                board, page = layout.panel_rect(), layout.page_rect()
                self.assertTrue(board.contains(page))
                self.assertTrue(page.contains(layout.text_rect()))
                log = layout.log_rect()
                self.assertTrue(log.contains(layout.log_page_rect()))
                log_frame = surface.get_at((log.left + 1, log.centery))[:3]
                self.assertNotIn(log_frame, (palette.BACKGROUND, palette.PAGE))
                frame = surface.get_at((board.left + 1, board.centery))[:3]
                self.assertNotEqual(frame, palette.BACKGROUND)
                self.assertNotEqual(frame, palette.PAGE)
                # Paper under the text is flat: a blank row reads as pure PAGE.
                blank = pygame.Rect(
                    layout.cell_to_pixel(layout.text_x, layout.text_y + 5),
                    (layout.text_width() * layout.cell_w, layout.cell_h),
                )
                area = surface.subsurface(blank)
                paper = pygame.mask.from_threshold(area, palette.PAGE, (1, 1, 1, 255))
                self.assertEqual(paper.count(), area.get_width() * area.get_height())

    def test_board_is_cached_between_frames(self):
        layout = fitted((1920, 1080), tiles=True)
        surface = pygame.Surface((1920, 1080))
        noticeboard._cache.clear()
        for _ in range(3):
            noticeboard.paint(surface, layout.panel_rect(), layout.page_rect())
        self.assertEqual(len(noticeboard._cache), 1)

    def test_a_board_narrower_than_its_frame_paints_without_error(self):
        for width in range(1, 40):
            board = pygame.Surface((width, 60), pygame.SRCALPHA)
            noticeboard._planks(board, pygame.Rect(0, 0, width, 60).inflate(-2 * 4, -2 * 4))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PanelTest(unittest.TestCase):
    """Task 6: the WS-D acceptance checklist. Every panel item is painted, on
    its row, in its colour, in side-by-side, stacked, and tile layouts; plus
    the pixel extras (HP bar, longer wrapped log).

    The panel is ink on a parchment page (render/noticeboard.py), so
    "painted" means pixels that aren't the flat page colour, and colours are
    the palette's ink twins. Each gear slot takes two rows (name, then bonus +
    rarity) to keep the board narrow.

    Checklist (rows relative to layout.text_y; headers are bold with a rule):
      [x] 0  'Class - Depth n' (live)     [x] 12 'BELT'
      [x] 1  HP, red at <= 1/3 max        [x] 13 one row of slot boxes, rarity
             + bar beside it (extra)             ink, the first outlined
                                                 when the belt isn't empty
      [x] 2  ATK / DEF (+ DODGE)          [x] 15 'BOONS', 16-17 boons (wrapped)
      [x] 3  item count (live, quiver)           -- once one is taken
      [x] 4  gold ('Gold 0' too)          [x] 18 'CONTROLS'
      [x] 6  'GEAR'                       [x] 19+ key/action table, one row
      [x] 7-8  weapon, rarity ink                 per binding, by class
      [x] 9-10 armor, rarity ink / (none)
    The log board (rows relative to layout.log_text_y):
      [x] 0  'LOG'                        [x] 1+ newest messages, wrapped
    """

    LAYOUTS = [
        (False, (1280, 720)),
        (False, (600, 1400)),
        (True, (1920, 1080)),
        (True, (700, 1000)),
    ]

    def paint(self, state, tiles, size, log=True):
        self.layout = fitted(size, tiles)
        self.canvas = ui.Canvas(pygame.Surface(size), self.layout)
        self.canvas.clear()
        ui.paint_panel(self.canvas, state)
        if log:
            ui.paint_log(self.canvas, state)

    def row_rect(self, row, first_col=0, cols=None):
        layout = self.layout
        cols = layout.text_width() - first_col if cols is None else cols
        return pygame.Rect(
            layout.cell_to_pixel(layout.text_x + first_col, layout.text_y + row),
            (cols * layout.cell_w, layout.cell_h),
        )

    def pixels(self, rect, color=None):
        """Ink (non-page) pixels in `rect`, or pixels close to `color`."""
        area = self.canvas.surface.subsurface(rect)
        if color is None:
            paper = pygame.mask.from_threshold(area, palette.PAGE, (1, 1, 1, 255))
            return area.get_width() * area.get_height() - paper.count()
        return pygame.mask.from_threshold(area, color, (12, 12, 12, 255)).count()

    def drawn(self, rect):
        """Pixels in `rect` that aren't the window background."""
        area = self.canvas.surface.subsurface(rect)
        untouched = pygame.mask.from_threshold(area, palette.BACKGROUND, (1, 1, 1, 255))
        return area.get_width() * area.get_height() - untouched.count()

    def log_row_rect(self, row):
        """Pixel rect of the log board's text row `row` (0 is the header)."""
        layout = self.layout
        return pygame.Rect(
            layout.cell_to_pixel(layout.log_text_x, layout.log_text_y + row),
            (layout.log_text_width() * layout.cell_w, layout.cell_h),
        )

    def row_bytes(self, row):
        return pygame.image.tobytes(self.canvas.surface.subsurface(self.row_rect(row)), 'RGB')

    def each_layout(self, make_state=None):
        for tiles, size in self.LAYOUTS:
            state = (make_state or self.state)()
            with self.subTest(tiles=tiles, size=size):
                self.paint(state, tiles, size)
                yield state

    @staticmethod
    def state(char_class='warrior', hp=None):
        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        state.messages[:] = ['first message', 'second message']
        if hp is not None:
            state.player.hp = hp
        return state

    def test_section_rows(self):
        # Stats on rows 0-4 (gold last), then GEAR,
        # BELT, BOONS and CONTROLS, each a header with its rows under it.
        self.assertEqual(
            (
                ui.HEADER_ROW,
                ui.HP_ROW,
                ui.STATS_ROW,
                ui.ITEMS_ROW,
                ui.GOLD_ROW,
                ui.GEAR_TOP,
                ui.BELT_TOP,
                ui.BELT_ROW,
                ui.BOONS_TOP,
                ui.CONTROLS_TOP,
                ui.PANEL_TEXT_ROWS,
            ),
            (0, 1, 2, 3, 4, 6, 12, 13, 15, 18, 25),
        )
        # The longest controls table (the archer's) fits on the page.
        self.assertLessEqual(ui.CONTROLS_TOP + 1 + len(ui.controls_rows('archer')), 25)

    def test_every_section_row_is_painted(self):
        rows = (
            ui.HEADER_ROW,
            ui.HP_ROW,
            ui.STATS_ROW,
            ui.ITEMS_ROW,
            ui.GOLD_ROW,
            ui.GEAR_TOP,
            ui.GEAR_TOP + 1,
            ui.GEAR_TOP + 2,  # every run starts with a weapon: its stats row
            ui.GEAR_TOP + 3,
            ui.BELT_TOP,
            ui.BELT_ROW,
            ui.CONTROLS_TOP,
            ui.CONTROLS_TOP + 1,
        )
        for _ in self.each_layout():
            for row in rows:
                self.assertGreater(self.pixels(self.row_rect(row)), 0, f'row {row} blank')
            # The log board: its header and the two messages, then paper.
            for row in (0, 1, 2):
                self.assertGreater(self.pixels(self.log_row_rect(row)), 0, f'log row {row} blank')
            self.assertEqual(self.pixels(self.log_row_rect(3)), 0, 'log row 3 drawn')

    def test_gaps_between_sections_and_the_boons_rows_without_boons_are_blank(self):
        # No armor, so its stats row is empty too.
        gaps = (5, ui.GEAR_TOP + 4, ui.BELT_TOP - 1, ui.BOONS_TOP - 1, ui.CONTROLS_TOP - 1)
        for _ in self.each_layout():
            for row in gaps:
                self.assertEqual(self.pixels(self.row_rect(row)), 0, f'row {row} drawn')
            for row in (ui.BOONS_TOP, ui.BOONS_TOP + 1):
                self.assertEqual(self.pixels(self.row_rect(row)), 0, f'boons row {row} drawn')

    def test_section_and_log_headers_are_ruled(self):
        # A 1px TABLE_RULE line across the text width at the header row's foot.
        for _ in self.each_layout():
            for row in (ui.HEADER_ROW, ui.GEAR_TOP, ui.BELT_TOP, ui.CONTROLS_TOP):
                rect = self.row_rect(row)
                foot = pygame.Rect(rect.left, rect.bottom - 1, rect.width, 1)
                self.assertEqual(self.pixels(foot, palette.TABLE_RULE), rect.width, row)
            # The log board's 'LOG' header too.
            rect = self.log_row_rect(0)
            foot = pygame.Rect(rect.left, rect.bottom - 1, rect.width, 1)
            self.assertEqual(self.pixels(foot, palette.TABLE_RULE), rect.width, 'log')

    def test_controls_rows_by_class(self):
        self.assertEqual(ui.controls_rows('archer')[:2], [('wasd', 'move'), ('arrows', 'shoot')])
        self.assertEqual(ui.controls_rows('warrior')[0], ('wasd/arrows', 'move'))
        self.assertEqual(ui.controls_rows('archer')[2:], ui.controls_rows('warrior')[1:])
        self.assertEqual(
            ui.controls_rows('warrior')[1:],
            [('space', 'wait'), ('e', 'descend'), ('h', 'drink'), ('q', 'ability')],
        )

    def test_controls_table_has_one_row_per_binding_by_class(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                self.paint(self.state('warrior'), tiles, size)
                for i in range(1, 6):
                    self.assertGreater(self.pixels(self.row_rect(ui.CONTROLS_TOP + i)), 0, i)
                self.assertEqual(self.pixels(self.row_rect(ui.CONTROLS_TOP + 6)), 0)
                warrior = [self.row_bytes(ui.CONTROLS_TOP + i) for i in range(1, 6)]
                self.paint(self.state('archer'), tiles, size)
                for i in range(1, 7):
                    self.assertGreater(self.pixels(self.row_rect(ui.CONTROLS_TOP + i)), 0, i)
                archer = [self.row_bytes(ui.CONTROLS_TOP + i) for i in range(1, 7)]
                self.assertNotEqual(warrior[0], archer[0])
                # The archer's extra 'arrows shoot' row; the rest are shared.
                # (The table's bottom rule is on the last row only.)
                self.assertEqual(warrior[1:-1], archer[2:-1])

    def test_controls_key_column_is_shaded_and_ruled(self):
        for _ in self.each_layout():
            row = ui.CONTROLS_TOP + 2  # ('space', 'wait')
            key = self.row_rect(row, 0, ui.CONTROLS_KEY_COLS)
            action = self.row_rect(row, ui.CONTROLS_KEY_COLS)
            shaded = self.pixels(key, palette.PAGE_EDGE)
            self.assertGreater(shaded, key.width * key.height // 2)
            # Only the odd antialiased edge of the action text comes close.
            self.assertLess(self.pixels(action, palette.PAGE_EDGE), shaded // 10)
            self.assertGreater(self.pixels(key, palette.TABLE_RULE), 0)
            self.assertGreater(self.pixels(action, palette.TABLE_RULE), 0)
            self.assertGreater(self.pixels(action, palette.INK), 0, 'action text')

    def hp_colours(self, hp):
        """Per layout: (red in the HP text, red in bar, green in bar, empty track)."""
        for _ in self.each_layout(lambda: self.state(hp=hp)):
            text = self.row_rect(ui.HP_ROW, 0, ui.HP_BAR_COL)
            bar = self.row_rect(ui.HP_ROW, ui.HP_BAR_COL, ui.HP_BAR_COLS)
            yield (
                self.pixels(text, palette.INK_DANGER),
                self.pixels(bar, palette.INK_DANGER),
                self.pixels(bar, ui.HP_BAR_COLOR),
                self.pixels(bar, ui.HP_BAR_TRACK),
            )

    def test_hp_text_and_bar_colour_by_hp(self):
        max_hp = self.state().player.max_hp
        with self.subTest('full hp: plain text and a full green bar'):
            for red_text, red_bar, green_bar, track in self.hp_colours(max_hp):
                self.assertEqual((red_text, red_bar, track), (0, 0, 0))
                self.assertGreater(green_bar, 0)
        with self.subTest('a third of max hp turns text and bar red'):
            for red_text, red_bar, green_bar, track in self.hp_colours(max_hp // 3):
                self.assertGreater(red_text, 0)
                self.assertGreater(red_bar, 0)
                self.assertEqual(green_bar, 0)
                self.assertGreater(track, red_bar, 'a third full: mostly empty track')
        with self.subTest('just above a third is still green'):
            for red_text, red_bar, green_bar, _ in self.hp_colours(max_hp // 3 + 1):
                self.assertEqual((red_text, red_bar), (0, 0))
                self.assertGreater(green_bar, 0)
        with self.subTest('zero hp is an empty track'):
            for _, red_bar, green_bar, track in self.hp_colours(0):
                self.assertEqual((red_bar, green_bar), (0, 0))
                self.assertGreater(track, 0)

    def test_hp_bar_fill_is_proportional(self):
        state = self.state()
        state.player.hp = state.player.max_hp // 2 + 1
        self.paint(state, False, (1280, 720))
        bar = self.row_rect(ui.HP_ROW, ui.HP_BAR_COL, ui.HP_BAR_COLS)
        filled = self.pixels(bar, ui.HP_BAR_COLOR)
        empty = self.pixels(bar, ui.HP_BAR_TRACK)
        share = state.player.hp / state.player.max_hp
        self.assertAlmostEqual(filled / (filled + empty), share, delta=0.05)

    def test_gear_lines_are_in_their_rarity_colour(self):
        def make():
            state = self.state()
            state.player.weapon = Item(0, 0, 'weapon', 'epic')
            state.player.armor = Item(0, 0, 'armor', 'uncommon')
            return state

        for state in self.each_layout(make):
            epic = palette.ink(state.player.weapon.color)
            uncommon = palette.ink(state.player.armor.color)
            for weapon in (self.row_rect(ui.GEAR_TOP + 1), self.row_rect(ui.GEAR_TOP + 2)):
                self.assertGreater(self.pixels(weapon, epic), 0)
                self.assertEqual(self.pixels(weapon, uncommon), 0)
            for armor in (self.row_rect(ui.GEAR_TOP + 3), self.row_rect(ui.GEAR_TOP + 4)):
                self.assertGreater(self.pixels(armor, uncommon), 0)
                self.assertEqual(self.pixels(armor, epic), 0)

    def test_dodge_is_shown_for_leather_and_not_for_heavy_armor(self):
        def wearing(kind):
            def make():
                state = self.state()
                Item(0, 0, kind, 'uncommon').apply(state.player, state.log)
                return state

            return make

        for state in self.each_layout(wearing('leather')):
            text = ui.stats_text(state.player)
            self.assertTrue(text.endswith('DODGE 6%'), text)
            plain = len(f'ATK {state.player.power}   DEF {state.player.defense}')
            self.assertGreater(self.pixels(self.row_rect(ui.STATS_ROW, plain)), 0)
        for state in self.each_layout(wearing('armor')):
            text = ui.stats_text(state.player)
            self.assertNotIn('DODGE', text)
            self.assertEqual(self.pixels(self.row_rect(ui.STATS_ROW, len(text))), 0)

    def test_archer_shows_the_quiver_on_the_items_row(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                state = self.state('archer')
                state.player.quiver = 9
                self.paint(state, tiles, size)
                text = ui.items_text(state.player)
                self.assertEqual(text, 'Items: 0   Arrows 9/12')
                quiver = self.row_rect(ui.ITEMS_ROW, len('Items: 0'))
                self.assertGreater(self.pixels(quiver), 0)
                before = self.row_bytes(ui.ITEMS_ROW)
                state.player.quiver = 3
                self.paint(state, tiles, size)
                self.assertNotEqual(self.row_bytes(ui.ITEMS_ROW), before)
        for state in self.each_layout():
            text = ui.items_text(state.player)
            self.assertNotIn('Arrows', text)
            self.assertEqual(self.pixels(self.row_rect(ui.ITEMS_ROW, len(text))), 0)

    def test_no_gear_is_plain_text(self):
        for _ in self.each_layout():
            for row in (ui.GEAR_TOP + 1, ui.GEAR_TOP + 3):
                rect = self.row_rect(row)
                self.assertGreater(self.pixels(rect, palette.INK), 0)
                for rarity_colour in (4, 5, 6):
                    self.assertEqual(self.pixels(rect, palette.ink(rarity_colour)), 0)

    def test_class_depth_item_count_gold_and_belt_rows_are_live(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                state = self.state()
                self.paint(state, tiles, size)
                class_row = self.row_bytes(ui.HEADER_ROW)
                items_row = self.row_bytes(ui.ITEMS_ROW)
                gold_row = self.row_bytes(ui.GOLD_ROW)
                belt_row = self.row_bytes(ui.BELT_ROW)
                # Gold and the belt are always painted, 'Gold 0' and an empty
                # belt included.
                self.assertGreater(self.pixels(self.row_rect(ui.GOLD_ROW)), 0)
                self.assertGreater(self.pixels(self.row_rect(ui.BELT_ROW)), 0)
                state.depth += 1
                state.player.items_used.append(Item(0, 0).name)
                state.player.gold = 37
                state.belt.append(Item(0, 0, 'potion', 'common'))
                self.paint(state, tiles, size)
                self.assertNotEqual(self.row_bytes(ui.HEADER_ROW), class_row, 'depth')
                self.assertNotEqual(self.row_bytes(ui.ITEMS_ROW), items_row, 'items')
                self.assertGreater(self.pixels(self.row_rect(ui.GOLD_ROW)), 0)
                self.assertNotEqual(self.row_bytes(ui.GOLD_ROW), gold_row, 'gold')
                self.assertNotEqual(self.row_bytes(ui.BELT_ROW), belt_row, 'belt')
                self.paint(self.state('archer'), tiles, size)
                self.assertNotEqual(self.row_bytes(ui.HEADER_ROW), class_row, 'class')

    def test_log_fills_its_rows_with_messages(self):
        def make():
            state = self.state()
            state.messages[:] = [f'message {i}' for i in range(30)]
            return state

        for _ in self.each_layout(make):
            lines = self.layout.log_lines()
            self.assertGreaterEqual(lines, ui.MIN_LOG_LINES)
            for i in range(lines):
                self.assertGreater(self.pixels(self.log_row_rect(1 + i)), 0)
            # The row under the last log line is paper (or, on a short board,
            # the frame, whose dark wood is close to ink): no text on paper.
            below = self.log_row_rect(1 + lines)
            paper = below.clip(self.layout.log_page_rect().inflate(-8, -8))
            if paper.height == self.layout.cell_h:
                self.assertEqual(self.pixels(paper, palette.INK), 0)

    def test_long_messages_wrap_inside_the_log_board(self):
        def make():
            state = self.state()
            state.messages[:] = ['word ' * 80, 'x' * 300]
            return state

        for _ in self.each_layout(make):
            layout = self.layout
            log = layout.log_rect()
            # Between the log board's right edge and whatever is right of it
            # (the stats board side by side, the window edge stacked).
            panel = layout.panel_rect()
            edge = panel.left if panel.left >= log.right else self.canvas.surface.get_width()
            right = pygame.Rect(log.right, log.top, edge - log.right, log.height)
            right = right.clip(self.canvas.surface.get_rect())
            if right.width > 0 and right.height > 0:
                self.assertEqual(self.drawn(right), 0, 'text overran the log board')
            self.assertGreater(self.pixels(self.log_row_rect(2)), 0, 'not wrapped')

    def test_long_message_wraps_inside_the_log_page(self):
        # Outside the page (its board's frame and wood) the long message
        # leaves the log board exactly as an empty log does.
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                empty = self.state()
                empty.messages[:] = []
                self.paint(empty, tiles, size)
                page, board = self.layout.log_page_rect(), self.layout.log_rect()
                strip = pygame.Rect(page.right, board.top, board.right - page.right, board.height)
                strip = strip.clip(self.canvas.surface.get_rect())
                before = pygame.image.tobytes(self.canvas.surface.subsurface(strip), 'RGB')
                full = self.state()
                full.log('word ' * 80)
                self.paint(full, tiles, size)
                after = pygame.image.tobytes(self.canvas.surface.subsurface(strip), 'RGB')
                self.assertEqual(after, before, 'text ran off the log page')
                self.assertGreater(self.pixels(self.log_row_rect(2)), 0, 'not wrapped')

    def test_panel_paints_neither_the_log_nor_the_map_and_paint_log_does(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                state = self.state()
                state.log('hello there')
                self.paint(state, tiles, size, log=False)
                self.assertEqual(self.drawn(self.log_row_rect(1)), 0)
                self.assertEqual(self.drawn(self.layout.map_rect()), 0)
                ui.paint_log(self.canvas, state)
                self.assertGreater(self.pixels(self.log_row_rect(1)), 0)
                # Neither board paints anything on the map.
                self.assertEqual(self.drawn(self.layout.map_rect()), 0)

    def slot_boxes(self, state):
        return ui.belt_slot_rects(self.layout, belt_capacity(state.player))

    @staticmethod
    def inside(box):
        """A slot box without its border or outline: just the label."""
        return box.inflate(-6, -6)

    def test_belt_boxes_split_the_text_width_equally_and_are_ruled(self):
        for state in self.each_layout():
            boxes = self.slot_boxes(state)
            self.assertEqual(len(boxes), BELT_SLOTS)
            text = self.layout.text_rect()
            belt_row = self.row_rect(ui.BELT_ROW)
            self.assertEqual(len({box.width for box in boxes}), 1)
            for box in boxes:
                self.assertTrue(belt_row.contains(box), box)
            self.assertEqual(boxes[0].left, text.left)
            self.assertGreater(boxes[-1].right, text.right - len(boxes))
            # Ruled: the last box's right edge is a TABLE_RULE line.
            last = boxes[-1]
            right = pygame.Rect(last.right - 1, last.top, 1, last.height)
            self.assertEqual(self.pixels(right, palette.TABLE_RULE), last.height)

    def test_belt_shows_three_slots_each_in_its_rarity_ink(self):
        def make():
            state = self.state()
            state.belt[:] = [Item(0, 0, 'potion', 'epic'), Item(0, 0, 'potion', 'uncommon')]
            return state

        for state in self.each_layout(make):
            first, second, empty = map(self.inside, self.slot_boxes(state))
            epic, uncommon = palette.ink(6), palette.ink(4)
            self.assertGreater(self.pixels(first, epic), 0)
            self.assertEqual(self.pixels(first, uncommon), 0)
            self.assertGreater(self.pixels(second, uncommon), 0)
            self.assertEqual(self.pixels(second, epic), 0)
            # The empty third slot is drawn (a dash) in plain ink.
            self.assertGreater(self.pixels(empty, palette.INK), 0)
            self.assertEqual(self.pixels(empty, epic) + self.pixels(empty, uncommon), 0)

    def test_first_belt_slot_is_outlined_in_ink_only_while_it_holds_a_potion(self):
        def make():
            state = self.state()
            state.belt.append(Item(0, 0, 'potion', 'common'))
            return state

        for state in self.each_layout(make):
            boxes = self.slot_boxes(state)
            first, last = boxes[0], boxes[-1]
            edge = pygame.Rect(first.left, first.top, 2, first.height)
            self.assertEqual(self.pixels(edge, palette.INK), 2 * first.height)
            edge = pygame.Rect(last.left + 1, last.top, 2, last.height)
            self.assertEqual(self.pixels(edge, palette.INK), 0)
        # An empty belt, nothing for 'h' to drink: the first box is ruled like
        # the others.
        for state in self.each_layout():
            first = self.slot_boxes(state)[0]
            edge = pygame.Rect(first.left, first.top, 2, first.height)
            self.assertEqual(self.pixels(edge, palette.INK), 0, 'empty belt')

    def test_boons_section_appears_once_a_boon_is_taken(self):
        def make():
            state = self.state()
            state.player.boons[:] = ['blood_pact', 'keen_eye']
            return state

        for _ in self.each_layout(make):
            self.assertGreater(self.pixels(self.row_rect(ui.BOONS_TOP)), 0)
            row = self.row_rect(ui.BOONS_TOP + 1)
            self.assertGreater(self.pixels(row, palette.ink(BOON_COLOR)), 0)
        # Without boons both rows stay blank
        # (test_gaps_between_sections_and_the_boons_rows_without_boons_are_blank).

    SEVEN_BOONS = [
        'blood_pact',
        'iron_skin',
        'quick_hands',
        'keen_eye',
        'stone_heart',
        'blood_pact_half',
        'iron_skin_half',
    ]

    def test_seven_boons_wrap_onto_a_second_row(self):
        """Seven short names don't fit one page row: they wrap onto the row
        under it (the blank one before CONTROLS), none of them cut."""
        from game.shrine import ALL_BOONS

        shorts = [ALL_BOONS[key].short for key in self.SEVEN_BOONS]

        def make():
            state = self.state()
            state.player.boons[:] = list(self.SEVEN_BOONS)
            return state

        for _ in self.each_layout(make):
            width = self.layout.text_width()
            self.assertGreater(len(' '.join(shorts)), width)
            rows = ui.boon_rows([ALL_BOONS[key] for key in self.SEVEN_BOONS], width)
            self.assertEqual(len(rows), 2)
            self.assertEqual(' '.join(rows).split(), shorts)
            self.assertTrue(all(len(row) <= width for row in rows), rows)
            for row in (ui.BOONS_TOP + 1, ui.BOONS_TOP + 2):
                rect = self.row_rect(row)
                self.assertGreater(self.pixels(rect, palette.ink(BOON_COLOR)), 0, row)
            self.assertLess(ui.BOONS_TOP + 2, ui.CONTROLS_TOP)

    def test_four_belt_boxes_fit_the_page_in_one_row(self):
        def make():
            state = self.state()
            state.player.boons[:] = ['quick_hands']
            return state

        for state in self.each_layout(make):
            # Still one row: the row under the belt is blank.
            self.assertEqual(self.pixels(self.row_rect(ui.BELT_ROW + 1)), 0)
            boxes = self.slot_boxes(state)
            self.assertEqual(len(boxes), 4)
            text = self.layout.text_rect()
            for box in boxes:
                self.assertTrue(text.contains(box), box)
            self.assertGreater(self.pixels(self.inside(boxes[3]), palette.INK), 0)
            # Right of the text area the belt row is bare page margin, the
            # same as the blank row under it.
            page = self.layout.page_rect()
            row, below = self.row_rect(ui.BELT_ROW), self.row_rect(ui.BELT_ROW + 1)
            margin = pygame.Rect(text.right, row.top, page.right - text.right, row.height)
            under = margin.move(0, below.top - row.top)

            def raw(rect):
                return pygame.image.tobytes(self.canvas.surface.subsurface(rect), 'RGB')

            self.assertEqual(raw(margin), raw(under))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GearLineSignTest(unittest.TestCase):
    def test_bonus_is_signed_once(self):
        _, rapier, _ = ui._gear_lines('Weapon', Item(0, 0, 'rapier', 'common'), 'atk')
        self.assertIn('-1 atk', rapier)
        self.assertNotIn('+-', rapier)
        _, sword, _ = ui._gear_lines('Weapon', Item(0, 0, 'great_sword', 'common'), 'atk')
        self.assertIn('+2 atk', sword)


if __name__ == '__main__':
    unittest.main()
