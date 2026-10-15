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

from unittest import mock

from game.item import BELT_SLOTS, POTION_HEAL, Item, belt_slot_label
from game.state import GameState
from render.menu import Menu

if pygame is not None:
    from render import noticeboard, palette, screens, ui

try:
    from render import curses_render
except ImportError:  # pragma: no cover - Windows without windows-curses
    curses_render = None

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


# Window sizes every layout test sweeps: landscape, 4K, portrait, narrow, tiny.
SIZES = [(1280, 720), (1920, 1080), (3840, 2160), (800, 1200), (700, 900),
         (1024, 600), (2000, 700), (300, 200)]


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
        panel_text = pygame.Rect(panel_rect.topleft,
                                 (panel_rect.w, layout.cell_h * ui.PANEL_ROWS))
        self.assertTrue(window.contains(panel_text), (panel_text, size))
        self.assertGreaterEqual(layout.rows - layout.panel_y, ui.PANEL_ROWS)
        self.assertGreaterEqual(layout.panel_width(), ui.PANEL_COLS)

    def test_every_size_fits_without_overlap(self):
        for tiles in (False, True):
            for size in SIZES[:-1]:  # the tiny one can't fit anything legibly
                with self.subTest(tiles=tiles, size=size):
                    self.assertSane(fitted(size, tiles), size)

    def test_tiny_window_does_not_raise(self):
        for tiles in (False, True):
            fitted(SIZES[-1], tiles).panel_rect()

    def test_window_narrower_than_the_smallest_map_still_does_not_overlap(self):
        # 40 x 16px tiles = 640px: a 600px-wide window can't hold the map, so
        # it overflows -- but the panel must go under it, not on top of it.
        layout = fitted((600, 1000), tiles=True)
        self.assertTrue(layout.stacked)
        self.assertFalse(layout.map_rect().colliderect(layout.panel_rect()))

    def test_landscape_stays_side_by_side(self):
        for tiles in (False, True):
            for size in [(1280, 720), (1920, 1080), (3840, 2160)]:
                with self.subTest(tiles=tiles, size=size):
                    layout = fitted(size, tiles)
                    self.assertFalse(layout.stacked)
                    self.assertGreater(layout.panel_rect().left, layout.map_rect().right)

    def test_portrait_and_narrow_stack_the_panel_under_the_map(self):
        for tiles in (False, True):
            for size in [(800, 1200), (600, 1000)]:
                with self.subTest(tiles=tiles, size=size):
                    layout = fitted(size, tiles)
                    self.assertTrue(layout.stacked)
                    self.assertGreaterEqual(layout.panel_rect().top, layout.map_rect().bottom)

    def test_stacking_gives_the_map_bigger_glyphs(self):
        stacked = fitted((800, 1200))
        side = ui.Layout(WIDTH, HEIGHT)
        cols, rows = side._glyph_grid(False)[:2]
        side_size = side._largest_glyph_font(cols, rows, 800, 1200)
        self.assertGreater(stacked.cell_w, side._cell_size(side._font(side_size))[0])

    def test_glyph_map_stays_at_grid_cell_zero(self):
        # The renderer draws glyph-mode map cells with Canvas.put (grid cells).
        for size in [(1280, 720), (800, 1200)]:
            layout = fitted(size)
            self.assertEqual(layout.map_origin, layout.cell_to_pixel(0, 0))
            self.assertEqual(layout.map_cell_to_pixel(3, 2), layout.cell_to_pixel(3, 2))

    def test_refit_back_to_landscape_unstacks(self):
        layout = fitted((800, 1200))
        layout.fit((1280, 720))
        self.assertFalse(layout.stacked)
        self.assertEqual(layout.panel_x, WIDTH + ui.PANEL_GAP)
        self.assertEqual(layout.panel_y, 0)

    def test_4k_tile_panel_font_grows_past_the_tile_cap(self):
        layout = fitted((3840, 2160), tiles=True)
        self.assertGreater(layout.font.get_height(),
                           layout._font(ui.MAX_TILE_FONT_SIZE).get_height())


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class MessageLogTest(unittest.TestCase):
    """Task 2: more log lines than the terminal's 4, wrapped to the panel."""

    def test_log_has_at_least_the_terminals_lines_and_at_most_the_cap(self):
        for tiles in (False, True):
            for size in SIZES[:-1]:
                with self.subTest(tiles=tiles, size=size):
                    lines = fitted(size, tiles).log_lines()
                    self.assertGreaterEqual(lines, ui.MIN_LOG_LINES)
                    self.assertLessEqual(lines, ui.LOG_LINES)

    def test_a_roomy_window_shows_more_than_the_terminal(self):
        self.assertGreater(ui.LOG_LINES, ui.MIN_LOG_LINES)
        for tiles in (False, True):
            self.assertEqual(fitted((3840, 2160), tiles).log_lines(), ui.LOG_LINES)

    def test_preferred_glyph_window_shows_a_longer_log(self):
        layout = ui.Layout(WIDTH, HEIGHT)
        layout.fit(layout.preferred_window_size())
        self.assertGreater(layout.log_lines(), ui.MIN_LOG_LINES)

    def test_log_rows_keeps_the_newest_whole_messages(self):
        messages = ['one', 'two words here', 'three']
        self.assertEqual(ui.log_rows(messages, 10, 3), ['two words', 'here', 'three'])
        self.assertEqual(ui.log_rows(messages, 10, 2), ['three'])
        self.assertEqual(ui.log_rows(messages, 40, 10), messages)

    def test_log_rows_never_exceeds_width_or_rows(self):
        messages = ['x' * 100, 'a b c d e f g h i j k l m n o p']
        for width, rows in [(10, 3), (5, 1), (44, 12)]:
            lines = ui.log_rows(messages, width, rows)
            self.assertLessEqual(len(lines), rows)
            self.assertTrue(all(len(line) <= width for line in lines), lines)

    def test_a_message_too_long_for_the_log_is_cut_not_dropped(self):
        self.assertEqual(ui.log_rows(['aaaa bbbb cccc'], 4, 2), ['aaaa', 'bbbb'])

    def test_empty_log(self):
        self.assertEqual(ui.log_rows([], 44, 4), [])


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class CanvasBoldTest(unittest.TestCase):
    """Task 3: Canvas.put / put_str take bold=, cached like plain glyphs."""

    def setUp(self):
        self.layout = fitted((1200, 600))
        self.canvas = ui.Canvas(pygame.Surface((1200, 600)), self.layout)

    def cell_bytes(self, x, y):
        return pygame.image.tobytes(self.canvas.surface.subsurface(self.layout.cell_rect(x, y)),
                                    'RGB')

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
                            for point in (bar.center, bar.topleft,
                                          (bar.right - 1, bar.bottom - 1)):
                                self.assertEqual(
                                    screens.option_at(layout, menu, banner, point), i)

    def test_rows_between_and_around_options_hit_nothing(self):
        for tiles, size, layout in self.layouts():
            menu = Menu(screens.TITLE_OPTIONS)
            banner = self.BANNERS[1]
            first, second = self.highlights(layout, menu, banner).values()
            x = first.centerx
            with self.subTest(tiles=tiles, size=size):
                for point in [(x, first.top - 1), (x, first.bottom + layout.cell_h // 2),
                              (x, second.bottom), (layout.origin_x, first.centery),
                              (-1, -1)]:
                    self.assertIsNone(screens.option_at(layout, menu, banner, point), point)

    def test_hit_area_spans_the_widest_option(self):
        layout = fitted((1200, 600))
        menu = Menu(screens.CLASS_OPTIONS)  # 'Warrior' is wider than 'Archer'
        warrior, archer = self.highlights(layout, menu, ['x']).values()
        self.assertLess(archer.w, warrior.w)
        for x in (warrior.left, warrior.right - 1):
            self.assertEqual(screens.option_at(layout, menu, ['x'], (x, archer.centery)), 1)
        self.assertIsNone(screens.option_at(layout, menu, ['x'],
                                            (warrior.right + 1, archer.centery)))

    def test_hint_wraps_in_a_narrow_grid(self):
        layout = fitted((600, 1000))
        self.assertTrue(layout.stacked)
        self.assertLess(layout.cols, len(screens.MENU_HINT))
        canvas = ui.Canvas(pygame.Surface((600, 1000)), layout)
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
        screens.paint_game_over(self.canvas)
        self.assertDrewSomething(self.layout.map_rect())


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
        self.assertLessEqual(title_font.size(screens.GAME_OVER_TITLE)[0],
                             layout.map_rect().width - 2 * layout.cell_w)
        self.assertGreaterEqual(title_font.get_height(), layout.font.get_height())


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class NoticeboardTest(unittest.TestCase):
    """The panel is a wooden board with a parchment page, kept narrow so the
    map gets bigger tiles."""

    def test_common_window_sizes_get_bigger_tiles(self):
        for size, tile in [((1280, 720), 24), ((1600, 900), 32), ((1920, 1080), 40)]:
            with self.subTest(size=size):
                self.assertGreaterEqual(fitted(size, tiles=True).tile, tile)

    def test_board_and_page_are_drawn_behind_the_text(self):
        for tiles, size in [(False, (1280, 720)), (True, (1920, 1080)), (True, (600, 1000))]:
            with self.subTest(tiles=tiles, size=size):
                layout = fitted(size, tiles)
                surface = pygame.Surface(size)
                canvas = ui.Canvas(surface, layout)
                canvas.clear()
                ui.paint_panel(canvas, GameState(WIDTH, HEIGHT))
                board, page = layout.panel_rect(), layout.page_rect()
                self.assertTrue(board.contains(page))
                self.assertTrue(page.contains(layout.text_rect()))
                frame = surface.get_at((board.left + 1, board.centery))[:3]
                self.assertNotEqual(frame, palette.BACKGROUND)
                self.assertNotEqual(frame, palette.PAGE)
                # Paper under the text is flat: a blank row reads as pure PAGE.
                blank = pygame.Rect(layout.cell_to_pixel(layout.text_x, layout.text_y + 5),
                                    (layout.text_width() * layout.cell_w, layout.cell_h))
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


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PanelParityTest(unittest.TestCase):
    """Task 6: the WS-D acceptance checklist. Every item
    curses_render._draw_panel shows is painted, on its row, in its colour,
    in side-by-side, stacked, and tile layouts; plus the pixel extras (HP bar,
    longer wrapped log).

    The panel is ink on a parchment page (render/noticeboard.py), so
    "painted" means pixels that aren't the flat page colour, and colours are
    the palette's ink twins. Same items and order as curses; each gear slot
    takes two rows here (name, then bonus + rarity) to keep the board narrow.

    Checklist (rows relative to layout.text_y):
      [x] 0  title                        [x] 6  '-- gear --'
      [x] 1  'Class - Depth: n' (live)    [x] 7-8  weapon, rarity ink / (none)
      [x] 2  HP, red at <= 1/3 max        [x] 9-10 armor, rarity ink / (none)
          + bar beside it (extra)         [x] 11 potion belt, 3 slots, rarity ink
      [x] 3  ATK / DEF                    [x] 13 class-dependent controls line
      [x] 4  item count (live)            [x] 14-16 shared controls (+ 'h drink')
                                          [x] 18 '-- log --', 19+ newest messages
    """

    LAYOUTS = [(False, (1280, 720)), (False, (800, 1200)), (True, (1920, 1080)),
               (True, (700, 900))]

    def paint(self, state, tiles, size):
        self.layout = fitted(size, tiles)
        self.canvas = ui.Canvas(pygame.Surface(size), self.layout)
        self.canvas.clear()
        ui.paint_panel(self.canvas, state)

    def row_rect(self, row, first_col=0, cols=None):
        layout = self.layout
        cols = layout.text_width() - first_col if cols is None else cols
        return pygame.Rect(layout.cell_to_pixel(layout.text_x + first_col, layout.text_y + row),
                           (cols * layout.cell_w, layout.cell_h))

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
        state = GameState(WIDTH, HEIGHT, char_class=char_class)
        state.messages[:] = ['first message', 'second message']
        if hp is not None:
            state.player.hp = hp
        return state

    def test_rows_follow_curses_with_two_row_gear_slots(self):
        # _draw_panel: HP on row 2, gear_start = 6, belt on gear_start + 3,
        # controls_start = gear_start + 5, log_start = controls_start + 5 --
        # here each of the two gear slots takes one extra row.
        self.assertEqual((ui.HP_ROW, ui.GEAR_TOP, ui.BELT_ROW, ui.CONTROLS_TOP, ui.LOG_TOP),
                         (2, 6, 6 + 3 + 2, 6 + 5 + 2, 6 + 5 + 2 + 5))

    def test_every_text_row_is_painted_and_the_gaps_are_not(self):
        rows = [0, 1, ui.HP_ROW, 3, 4, ui.GEAR_TOP, ui.GEAR_TOP + 1, ui.GEAR_TOP + 3,
                ui.BELT_ROW, ui.CONTROLS_TOP, ui.CONTROLS_TOP + 1, ui.CONTROLS_TOP + 2,
                ui.CONTROLS_TOP + 3, ui.LOG_TOP, ui.LOG_TOP + 1, ui.LOG_TOP + 2]
        for _ in self.each_layout():
            for row in rows:
                self.assertGreater(self.pixels(self.row_rect(row)), 0, f'row {row} blank')
            # Every run starts with a weapon, so its stats row (GEAR_TOP + 2)
            # is drawn; no armor, so the armor's stats row stays empty.
            self.assertGreater(self.pixels(self.row_rect(ui.GEAR_TOP + 2)), 0)
            for blank in (5, ui.GEAR_TOP + 4, ui.BELT_ROW + 1,
                          ui.CONTROLS_TOP + 4, ui.LOG_TOP + 3):
                self.assertEqual(self.pixels(self.row_rect(blank)), 0, f'row {blank} drawn')

    def hp_colours(self, hp):
        """Per layout: (red in the HP text, red in bar, green in bar, empty track)."""
        for _ in self.each_layout(lambda: self.state(hp=hp)):
            text = self.row_rect(ui.HP_ROW, 0, ui.HP_BAR_COL)
            bar = self.row_rect(ui.HP_ROW, ui.HP_BAR_COL, ui.HP_BAR_COLS)
            yield (self.pixels(text, palette.INK_DANGER), self.pixels(bar, palette.INK_DANGER),
                   self.pixels(bar, ui.HP_BAR_COLOR), self.pixels(bar, ui.HP_BAR_TRACK))

    def test_full_hp_is_plain_text_and_a_full_green_bar(self):
        max_hp = self.state().player.max_hp
        for red_text, red_bar, green_bar, track in self.hp_colours(max_hp):
            self.assertEqual((red_text, red_bar, track), (0, 0, 0))
            self.assertGreater(green_bar, 0)

    def test_a_third_of_max_hp_turns_text_and_bar_red(self):
        max_hp = self.state().player.max_hp
        for red_text, red_bar, green_bar, track in self.hp_colours(max_hp // 3):
            self.assertGreater(red_text, 0)
            self.assertGreater(red_bar, 0)
            self.assertEqual(green_bar, 0)
            self.assertGreater(track, red_bar, 'a third full: mostly empty track')

    def test_just_above_a_third_is_still_green(self):
        max_hp = self.state().player.max_hp
        for red_text, red_bar, green_bar, _ in self.hp_colours(max_hp // 3 + 1):
            self.assertEqual((red_text, red_bar), (0, 0))
            self.assertGreater(green_bar, 0)

    def test_zero_hp_is_an_empty_track(self):
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

    def test_no_gear_is_plain_text(self):
        for _ in self.each_layout():
            for row in (ui.GEAR_TOP + 1, ui.GEAR_TOP + 3):
                rect = self.row_rect(row)
                self.assertGreater(self.pixels(rect, palette.INK), 0)
                for rarity_colour in (4, 5, 6):
                    self.assertEqual(self.pixels(rect, palette.ink(rarity_colour)), 0)

    def test_controls_depend_on_the_class(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                self.paint(self.state('warrior'), tiles, size)
                warrior = [self.row_bytes(ui.CONTROLS_TOP + i) for i in range(4)]
                self.paint(self.state('archer'), tiles, size)
                archer = [self.row_bytes(ui.CONTROLS_TOP + i) for i in range(4)]
                self.assertNotEqual(warrior[0], archer[0])
                self.assertEqual(warrior[1:], archer[1:])

    def test_class_depth_and_item_count_are_live(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                state = self.state()
                self.paint(state, tiles, size)
                class_row, items_row = self.row_bytes(1), self.row_bytes(4)
                state.depth += 1
                state.player.inventory.append(Item(0, 0))
                self.paint(state, tiles, size)
                self.assertNotEqual(self.row_bytes(1), class_row)
                self.assertNotEqual(self.row_bytes(4), items_row)
                self.paint(self.state('archer'), tiles, size)
                self.assertNotEqual(self.row_bytes(1), class_row)

    def test_log_fills_its_rows_with_messages(self):
        def make():
            state = self.state()
            state.messages[:] = [f'message {i}' for i in range(30)]
            return state
        for _ in self.each_layout(make):
            lines = self.layout.log_lines()
            self.assertGreaterEqual(lines, ui.MIN_LOG_LINES)
            for i in range(lines):
                self.assertGreater(self.pixels(self.row_rect(ui.LOG_TOP + 1 + i)), 0)
            below = ui.LOG_TOP + 1 + lines
            # The row under the last log line is paper (or, on a short board,
            # the frame, whose dark wood is close to ink): no text on paper.
            paper = self.row_rect(below).clip(self.layout.page_rect().inflate(-8, -8))
            if paper.height == self.layout.cell_h:
                self.assertEqual(self.pixels(paper, palette.INK), 0)

    def test_long_messages_wrap_inside_the_panel(self):
        def make():
            state = self.state()
            state.messages[:] = ['word ' * 40, 'x' * 120]
            return state
        for _ in self.each_layout(make):
            panel = self.layout.panel_rect()
            right = pygame.Rect(panel.right, panel.top,
                                self.canvas.surface.get_width() - panel.right, panel.height)
            if right.width > 0:
                self.assertEqual(self.drawn(right), 0, 'text overran the panel')
            self.assertGreater(self.pixels(self.row_rect(ui.LOG_TOP + 2)), 0, 'not wrapped')

    def test_panel_paints_nothing_on_the_map(self):
        for _ in self.each_layout():
            self.assertEqual(self.drawn(self.layout.map_rect()), 0)

    def belt_slot_rects(self, belt):
        """Pixel rects of the three belt slots' text on BELT_ROW, from the
        same column arithmetic as ui._paint_belt."""
        col, rects = len('Belt: '), []
        for i in range(BELT_SLOTS):
            text = belt_slot_label(belt[i] if i < len(belt) else None)
            if i == 0:
                text = f'[{text}]'
            rects.append(self.row_rect(ui.BELT_ROW, col, len(text)))
            col += len(text) + 1
        return rects

    def test_belt_shows_three_slots_each_in_its_rarity_ink(self):
        def make():
            state = self.state()
            state.belt[:] = [Item(0, 0, 'potion', 'epic'), Item(0, 0, 'potion', 'uncommon')]
            return state
        for state in self.each_layout(make):
            first, second, empty = self.belt_slot_rects(state.belt)
            epic, uncommon = palette.ink(6), palette.ink(4)
            self.assertGreater(self.pixels(first, epic), 0)
            self.assertEqual(self.pixels(first, uncommon), 0)
            self.assertGreater(self.pixels(second, uncommon), 0)
            self.assertEqual(self.pixels(second, epic), 0)
            # The empty third slot is drawn ('---') in plain ink.
            self.assertGreater(self.pixels(empty, palette.INK), 0)
            self.assertEqual(self.pixels(empty, epic) + self.pixels(empty, uncommon), 0)

    def test_belt_row_changes_with_its_contents(self):
        for tiles, size in self.LAYOUTS:
            with self.subTest(tiles=tiles, size=size):
                state = self.state()
                self.paint(state, tiles, size)
                empty = self.row_bytes(ui.BELT_ROW)
                self.assertGreater(self.pixels(self.row_rect(ui.BELT_ROW)), 0)
                state.belt.append(Item(0, 0, 'potion', 'common'))
                self.paint(state, tiles, size)
                self.assertNotEqual(self.row_bytes(ui.BELT_ROW), empty)



class _FakeScreen:
    """Just enough of a curses window for CursesRenderer._draw_panel:
    records every addstr as (y, x, text, attr)."""

    def __init__(self, rows=40, cols=120):
        self.size = (rows, cols)
        self.writes = []

    def getmaxyx(self):
        return self.size

    def addstr(self, y, x, text, attr=0):
        self.writes.append((y, x, text, attr))


@unittest.skipUnless(curses_render, 'curses not available')
class CursesBeltTest(unittest.TestCase):
    """The terminal panel's belt line, without a terminal: _draw_panel
    against a recording stand-in window, color_pair patched (it needs
    initscr). The pygame side is PanelParityTest's belt tests."""

    def draw(self, belt):
        state = GameState(WIDTH, HEIGHT)
        state.belt[:] = belt
        renderer = curses_render.CursesRenderer.__new__(curses_render.CursesRenderer)
        renderer.stdscr = _FakeScreen()
        with mock.patch.object(curses_render.curses, 'color_pair', lambda n: n << 8):
            renderer._draw_panel(state)
        return state, renderer.stdscr.writes

    def belt_writes(self, writes):
        row = 6 + 3  # gear_start + 3, as in PanelParityTest's row test
        return [(x, text, attr) for y, x, text, attr in writes if y == row]

    def test_three_slots_first_bracketed_in_rarity_colour(self):
        epic, common = Item(0, 0, 'potion', 'epic'), Item(0, 0, 'potion', 'common')
        state, writes = self.draw([epic, common])
        line = self.belt_writes(writes)
        texts = [text for _, text, _ in line]
        self.assertEqual(texts, ['Belt: ', f'[+{POTION_HEAL["epic"]}]',
                                 f'+{POTION_HEAL["common"]}', '---'])
        attrs = [attr for _, _, attr in line]
        self.assertEqual(attrs[1], epic.color << 8)
        self.assertEqual(attrs[2], common.color << 8)
        # Slots never overlap one another.
        for (x1, t1, _), (x2, _, _) in zip(line, line[1:]):
            self.assertGreater(x2, x1 + len(t1) - 1)

    def test_empty_belt_shows_three_empty_slots(self):
        _, writes = self.draw([])
        texts = [text for _, text, _ in self.belt_writes(writes)]
        self.assertEqual(texts, ['Belt: ', '[---]', '---', '---'])

    def test_belt_row_is_its_own(self):
        _, writes = self.draw([])
        rows = [y for y, _, _, _ in writes]
        # Only the belt's four writes land on its row; controls moved down.
        self.assertEqual(rows.count(9), 4)
        self.assertIn((11, 'wasd/arrows move'), [(y, t) for y, _, t, _ in writes])
        self.assertIn((14, 'h  drink  q  quit'), [(y, t) for y, _, t, _ in writes])


class GearLineSignTest(unittest.TestCase):
    def test_bonus_is_signed_once(self):
        _, rapier, _ = ui._gear_lines('Weapon', Item(0, 0, 'rapier', 'common'), 'atk')
        self.assertIn('-1 atk', rapier)
        self.assertNotIn('+-', rapier)
        _, sword, _ = ui._gear_lines('Weapon', Item(0, 0, 'great_sword', 'common'), 'atk')
        self.assertIn('+2 atk', sword)


if __name__ == '__main__':
    unittest.main()
