"""In-window UI: geometry, grid text drawing, and the side panel. Owned by WS-D.

`Layout` is the single source of truth for where things go (desktop_build_plan.md
§5 WS-D task 2): the renderer asks it for cell sizes and positions rather than
computing pixel offsets itself. `Canvas` draws text onto a surface in grid
cells. There are two boards: `paint_panel` paints the stats board (headed
sections -- stats with a pixel HP bar, gear, a row of belt boxes, boons, a
controls table) and `paint_log` the log board (a wrapped message log as long
as the rows allow).

The stats board sits right of the map with the log board under the map, or --
`Layout.stacked`, when that gives the map bigger cells (a portrait or narrow
window) -- the stats board goes under the map and the log board under it.
Either way the stats board is the `PANEL_COLS`-wide block at grid cell
(`panel_x`, `panel_y`) and the log board the `log_cols`-wide one at (`log_x`,
`log_y`), so callers never need to know which. Each is drawn as a wooden
noticeboard (render/noticeboard.py) with its text inked on a parchment page:
stats text starts at (`text_x`, `text_y`), `PANEL_PAD_X` columns and
`PANEL_PAD_TOP` rows in, so the frame, the nail and the page's margins fit
around it; log text at (`log_text_x`, `log_text_y`).

Reads GameState; never mutates it.
"""

import textwrap
from typing import NamedTuple

import pygame

from game.gold import GOLD_COLOR
from game.item import belt_capacity, belt_slot_label, dodge_chance
from game.paths import resource_path
from game.quiver import QUIVER_CAPACITY
from game.shrine import BOON_COLOR, held_boons
from render import noticeboard, palette

# -- panel geometry -----------------------------------------------------------
# The board starts one column right of the map. It is kept narrow -- gear
# lines are split over two rows rather than widening it -- because every
# column it takes is map width: 34 columns is what lets a 1080p window use
# 40px tiles. Text rows below are relative to the text's top (`text_y`).
PANEL_GAP = 1
PANEL_COLS = 34
PANEL_PAD_X = 3  # frame + board + page margin, each side
PANEL_PAD_TOP = 3  # frame, the nail and string, the page margin
PANEL_PAD_BOTTOM = 2  # page margin, frame
PANEL_TEXT_COLS = PANEL_COLS - 2 * PANEL_PAD_X
# Sections: a bold header with a rule under it, then its rows.
HEADER_ROW = 0  # 'Class - Depth n', the first section's header
HP_ROW = 1
STATS_ROW = 2  # stats_text
ITEMS_ROW = 3  # items_text
GOLD_ROW = 4  # 'Gold N'
GEAR_TOP = 6  # header; weapon name + stats (7-8), armor name + stats (9-10)
BELT_TOP = 12  # header
BELT_ROW = 13  # one row of slot boxes
BOONS_TOP = 15  # header and the boons' short names, once the first is taken
BOON_ROWS = 2  # rows of names under it (wrapped), the second only when needed
CONTROLS_TOP = 18  # header; a key/action table, one row per binding
CONTROLS_KEY_COLS = 11  # the key column, 'wasd/arrows' wide
PANEL_TEXT_ROWS = 25  # text rows on the stats board's page
# The stats board is a fixed height; the message log has a board of its own.
PANEL_ROWS = PANEL_PAD_TOP + PANEL_TEXT_ROWS + PANEL_PAD_BOTTOM
# Stacked (panel under the map): blank text rows between map and panel, and
# between the panel and the log board.
STACK_GAP = 1

# -- log board geometry -------------------------------------------------------
# The log board sits under the map (side by side) or under the stats board
# (stacked). Its text row 0 is the 'LOG' header; messages start on row 1.
MIN_LOG_LINES = 4  # always room for this many
LOG_LINES = 12  # shown when the window has the rows for them
LOG_PAD_X = PANEL_PAD_X
LOG_PAD_TOP = 2  # frame, the page margin
LOG_PAD_BOTTOM = PANEL_PAD_BOTTOM
LOG_BOARD_MIN_ROWS = LOG_PAD_TOP + 1 + MIN_LOG_LINES + LOG_PAD_BOTTOM
LOG_BOARD_MAX_ROWS = LOG_PAD_TOP + 1 + LOG_LINES + LOG_PAD_BOTTOM
LOG_GAP = 1  # rows between the map's bottom and the log board

# The HP bar sits right of the 'HP: x/max' text, in panel columns.
HP_BAR_COL = 12  # 'HP: 999/999' is 11 wide
HP_BAR_COLS = PANEL_TEXT_COLS - HP_BAR_COL
HP_BAR_COLOR = palette.HP_BAR_FILL  # palette.INK_DANGER at or below 1/3 max
HP_BAR_TRACK = palette.HP_BAR_TRACK
EMPTY_SLOT = '\u2014'  # an empty belt slot's dash

# The bundled font (assets/fonts, SIL OFL) is the default everywhere, so the
# layout -- and the tests that pin it -- see the same metrics on every OS.
# System fonts are only the fallback for a build without it.
BUNDLED_FONT = resource_path('assets', 'fonts', 'JetBrainsMono-Regular.ttf')
FONT_NAMES = 'dejavusansmono,liberationmono,consolas,menlo,couriernew,monospace'
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 48
START_FONT_SIZE = 18

# Tile mode: on-screen map tile sizes, largest first, in steps of 4 so a
# window between two multiples of 8 (a portrait 800px, a 1366px laptop)
# doesn't drop a whole size. The 16px Kenney art is scaled nearest-neighbour;
# at the quarter steps that duplicates every 4th pixel row/column, which
# still reads crisper than smoothscale's blur (compared side by side).
TILE_SIZES = (64, 56, 48, 44, 40, 36, 32, 28, 24, 20, 16)
# A bigger tile is only worth it while the panel text stays readable.
MIN_TILE_FONT_SIZE = 12
MAX_TILE_FONT_SIZE = 20
# The first window: this size on any desktop where it fits within
# DESKTOP_SHARE of both dimensions, else the largest 16:9 size within that
# share (so it never fills the whole desktop, taskbar and title bar included).
FIRST_WINDOW = (1920, 1080)
DESKTOP_SHARE = 0.85
FALLBACK_DESKTOP = (1280, 800)


class Layout:
    """Grid geometry: how many cells, how big, and where the grid sits.

    Glyph mode (the default): the window is a `cols x rows` grid of monospace
    cells -- the map at the top left, the stats board at column `panel_x`,
    row `panel_y`, the log board at column `log_x`, row `log_y`. `fit()`
    picks the largest font whose grid fits the window and letterboxes it;
    text is re-rendered at the new size rather than scaled, so it stays
    crisp. The grid grows a few rows when the window has them spare, up to
    what a full message log uses.

    Tile mode (`tiles=True`): the map is its own grid of square `tile`-pixel
    cells at `map_origin`, because 16x16 art can't go in a ~1:2 text cell.
    Text still uses a monospace grid, now covering the whole window, so the
    menus centre in it and the boards start at grid cells next to the map.
    `fit()` picks the largest tile size that leaves the boards a readable
    font.

    In both modes the stats board goes right of the map with the log board
    under the map, or -- `stacked` -- the stats board under the map and the
    log board under that, whichever gives the map bigger cells (in tile
    mode, a tie goes to the bigger text font; otherwise to side by side).

    `map_width` x `map_height` is the map *area* in cells -- the renderer
    passes camera.view_size, the exploring view, not the current floor's map
    (which grows with depth and is panned under that view).
    """

    def __init__(self, map_width, map_height, font_path=None, tiles=False):
        pygame.font.init()
        self.map_width = map_width
        self.map_height = map_height
        self.tiles = tiles
        self.tile = None
        self.stacked = False
        self.cols, self.rows, _, *placement = self._glyph_grid(False)
        self.panel_x, self.panel_y, self.log_x, self.log_y, self.log_cols = placement
        self.font_path = font_path or _default_font()
        self._fonts = {}
        self.font_size = START_FONT_SIZE
        self.font = self._font(START_FONT_SIZE)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        self.origin_x = self.origin_y = 0
        self.map_origin = (0, 0)

    def _font(self, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(self.font_path, size)
        return self._fonts[size]

    @staticmethod
    def _cell_size(font):
        return font.size('M')[0], font.get_linesize()

    # -- glyph mode -----------------------------------------------------------

    def _glyph_grid(self, stacked):
        """(cols, min_rows, max_rows, panel_x, panel_y, log_x, log_y, log_cols)
        of the glyph grid: min_rows holds the shortest log board, max_rows a
        full one.

        The map is always at grid cell (0, 0): the renderer draws it with
        Canvas.put, i.e. in grid cells."""
        if stacked:
            panel_y = self.map_height + STACK_GAP
            log_y = panel_y + PANEL_ROWS + STACK_GAP
            cols = max(self.map_width, PANEL_COLS)
            return (
                cols,
                log_y + LOG_BOARD_MIN_ROWS,
                log_y + LOG_BOARD_MAX_ROWS,
                0,
                panel_y,
                0,
                log_y,
                cols,
            )
        log_y = self.map_height + LOG_GAP
        return (
            self.map_width + PANEL_GAP + PANEL_COLS,
            max(log_y + LOG_BOARD_MIN_ROWS, PANEL_ROWS),
            max(log_y + LOG_BOARD_MAX_ROWS, PANEL_ROWS),
            self.map_width + PANEL_GAP,
            0,
            0,
            log_y,
            self.map_width,
        )

    def _largest_glyph_font(self, cols, rows, win_w, win_h):
        """Largest font size whose `cols x rows` grid fits; MIN_FONT_SIZE if none."""
        for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
            cell_w, cell_h = self._cell_size(self._font(size))
            if cell_w * cols <= win_w and cell_h * rows <= win_h:
                return size
        return MIN_FONT_SIZE

    def _fit_glyphs(self, window_size):
        win_w, win_h = window_size
        sizes = {}
        for stacked in (False, True):
            cols, min_rows = self._glyph_grid(stacked)[:2]
            sizes[stacked] = self._largest_glyph_font(cols, min_rows, win_w, win_h)
        self.stacked = sizes[True] > sizes[False]
        cols, min_rows, max_rows, *placement = self._glyph_grid(self.stacked)
        self.panel_x, self.panel_y, self.log_x, self.log_y, self.log_cols = placement
        # Once the text is already large, a full-length log beats a slightly
        # bigger font (fonts with tall line heights would otherwise cut it).
        full = self._largest_glyph_font(cols, max_rows, win_w, win_h)
        if full >= START_FONT_SIZE:
            sizes[self.stacked] = full
        self.font_size = sizes[self.stacked]
        self.font = self._font(self.font_size)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        # Rows the window has spare go to the message log.
        self.cols = cols
        self.rows = max(min_rows, min(max_rows, win_h // self.cell_h))
        self.origin_x = max(0, (win_w - self.cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - self.cell_h * self.rows) // 2)
        self.map_origin = (self.origin_x, self.origin_y)

    # -- tile mode ------------------------------------------------------------

    def _block_size(self, tile, cell, stacked=False, log_rows=LOG_BOARD_MIN_ROWS):
        """Pixel size of map + stats board + log board (`log_rows` tall) at
        this tile size and text cell."""
        cell_w, cell_h = cell
        map_w, map_h = self.map_width * tile, self.map_height * tile
        if stacked:
            rows_below = STACK_GAP + PANEL_ROWS + STACK_GAP + log_rows
            return (max(map_w, PANEL_COLS * cell_w), map_h + rows_below * cell_h)
        # Side by side the map's top is on a text row, and the log board
        # starts on the first whole row under it.
        map_rows = -(-map_h // cell_h)
        return (
            map_w + (PANEL_GAP + PANEL_COLS) * cell_w,
            max((map_rows + LOG_GAP + log_rows) * cell_h, PANEL_ROWS * cell_h),
        )

    def _pick_tile_and_font(self, win_w, win_h, stacked=False):
        """(tile, font size, shortfall). The largest tile whose map + boards
        fit with the text font at least MIN_TILE_FONT_SIZE, and the largest
        such font; if even the smallest tile needs a smaller font, the
        smallest tile and whatever font fits. `shortfall` is 1.0 when that
        fits the window, else the share of it that does (the worse axis)."""

        def coverage(tile, size):
            block_w, block_h = self._block_size(tile, self._cell_size(self._font(size)), stacked)
            return min(1.0, win_w / block_w, win_h / block_h)

        def height_fits(tile, size):
            return self._block_size(tile, self._cell_size(self._font(size)), stacked)[1] <= win_h

        for tile in TILE_SIZES:
            for size in range(MAX_TILE_FONT_SIZE, MIN_TILE_FONT_SIZE - 1, -1):
                if coverage(tile, size) == 1.0:
                    return tile, size, 1.0
        tile = TILE_SIZES[-1]
        for size in range(MIN_TILE_FONT_SIZE - 1, MIN_FONT_SIZE - 1, -1):
            if coverage(tile, size) == 1.0:
                return tile, size, 1.0
        # Nothing fits (the map alone may be wider than the window): the
        # biggest font among those that overflow the least, since shrinking
        # the text doesn't help when the map is what overflows.
        # A font whose boards still fit the window's height wins a tie, so
        # an over-wide map doesn't drag them off the bottom too.
        best = max(
            range(MAX_TILE_FONT_SIZE, MIN_FONT_SIZE - 1, -1),
            key=lambda size: (coverage(tile, size), height_fits(tile, size), size),
        )
        return tile, best, coverage(tile, best)

    def _choose_tiles(self, win_w, win_h):
        """(stacked, tile, font size): stacked only if it gives a bigger tile,
        or the same tile with a bigger text font. In a window too small for
        either, whichever overflows it less (so map and boards don't overlap
        in a narrow window that can't even fit the map)."""
        side_tile, side_size, side_fit = self._pick_tile_and_font(win_w, win_h, False)
        tile, size, stacked_fit = self._pick_tile_and_font(win_w, win_h, True)
        if (stacked_fit, tile, size) > (side_fit, side_tile, side_size):
            return True, tile, size
        return False, side_tile, side_size

    def _grow_tile_font(self, size, win_w, win_h):
        """Once the tile is chosen, the text font may grow past
        MAX_TILE_FONT_SIZE (up to MAX_FONT_SIZE) while map + boards, with a
        full-length log, still fit: at 4K a 20pt panel next to 64px tiles is
        unreadably small. Never shrinks the log below what `size` gives."""
        for bigger in range(MAX_FONT_SIZE, size, -1):
            block_w, block_h = self._block_size(
                self.tile,
                self._cell_size(self._font(bigger)),
                self.stacked,
                log_rows=LOG_BOARD_MAX_ROWS,
            )
            if block_w <= win_w and block_h <= win_h:
                return bigger
        return size

    def _fit_tiles(self, window_size):
        win_w, win_h = window_size
        self.stacked, self.tile, size = self._choose_tiles(win_w, win_h)
        size = self._grow_tile_font(size, win_w, win_h)
        self.font_size = size
        self.font = self._font(size)
        cell_w, cell_h = self.cell_w, self.cell_h = self._cell_size(self.font)
        # The text grid covers the whole window (menus centre in it).
        self.cols = max(PANEL_COLS, win_w // cell_w)
        self.rows = max(PANEL_ROWS, win_h // cell_h)
        self.origin_x = max(0, (win_w - cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - cell_h * self.rows) // 2)
        # Centre map + boards as one block, then snap the stats board onto
        # the text grid and place the map against it.
        # Centre on a full-length log board when that fits, so the log isn't
        # cut short by boards that start too low.
        block_w, block_h = self._block_size(
            self.tile, (cell_w, cell_h), self.stacked, log_rows=LOG_BOARD_MAX_ROWS
        )
        if block_w > win_w or block_h > win_h:
            block_w, block_h = self._block_size(self.tile, (cell_w, cell_h), self.stacked)
        map_w, map_h = self.map_width * self.tile, self.map_height * self.tile
        block_left = max(0, (win_w - block_w) // 2)
        block_top = max(0, (win_h - block_h) // 2)
        if self.stacked:
            self._place_stacked_tiles(block_left, block_top, win_w, map_w, map_h)
            return
        panel_left = block_left + map_w + PANEL_GAP * cell_w
        self.panel_x = min(
            max(0, self.cols - PANEL_COLS), max(0, round((panel_left - self.origin_x) / cell_w))
        )
        # The map's top is on the stats board's row; keep the shortest log
        # board under the map inside the grid when the grid has the rows.
        rows_needed = max(PANEL_ROWS, -(-map_h // cell_h) + LOG_GAP + LOG_BOARD_MIN_ROWS)
        self.panel_y = min(
            max(0, self.rows - rows_needed), max(0, (block_top - self.origin_y) // cell_h)
        )
        self.map_origin = (
            max(0, self.origin_x + (self.panel_x - PANEL_GAP) * cell_w - map_w),
            self.origin_y + self.panel_y * cell_h,
        )
        self._place_log_under_map()

    def _place_log_under_map(self):
        """Side by side: the log board LOG_GAP rows under the map, on the
        whole text columns inside the map's width (and left of the panel)."""
        cell_w, cell_h = self.cell_w, self.cell_h
        map_rect = self.map_rect()
        self.log_y = -(-(map_rect.bottom - self.origin_y) // cell_h) + LOG_GAP
        self.log_x = max(0, -(-(map_rect.left - self.origin_x) // cell_w))
        right = min((map_rect.right - self.origin_x) // cell_w, self.panel_x, self.cols)
        self.log_cols = max(0, right - self.log_x)

    def _place_stacked_tiles(self, block_left, block_top, win_w, map_w, map_h):
        """Map on top, the stats board under it, the log board under that, all
        left-aligned on the stats board's column."""
        cell_w, cell_h = self.cell_w, self.cell_h
        self.panel_x = min(
            max(0, self.cols - PANEL_COLS), max(0, round((block_left - self.origin_x) / cell_w))
        )
        map_left = max(0, min(self.origin_x + self.panel_x * cell_w, win_w - map_w))

        # First whole text row below the map, plus the gap.
        def row_below(map_top):
            return -(-(map_top + map_h - self.origin_y) // cell_h) + STACK_GAP

        # Pull the boards up to keep them inside the window, but never above
        # the row below a map at the very top: overlapping the map is worse
        # than running off the bottom of a window too small for all three.
        boards = PANEL_ROWS + STACK_GAP + LOG_BOARD_MIN_ROWS
        panel_y = min(row_below(block_top), self.rows - boards)
        self.panel_y = max(0, panel_y, row_below(0))
        panel_top = self.origin_y + self.panel_y * cell_h
        # If the panel had to move up, the map moves up with it.
        map_top = min(block_top, panel_top - STACK_GAP * cell_h - map_h)
        self.map_origin = (map_left, max(0, map_top))
        # The log board: as wide as the stats board, or the map if wider.
        self.log_x = self.panel_x
        self.log_y = self.panel_y + PANEL_ROWS + STACK_GAP
        under_map = (map_left + map_w - self.origin_x) // cell_w - self.log_x
        self.log_cols = max(0, min(max(PANEL_COLS, under_map), self.cols - self.log_x))

    # -- public geometry ------------------------------------------------------

    def preferred_window_size(self):
        """The first window's size (`first_window_size`), in either mode: the
        font or tile then follows from fit()."""
        return first_window_size()

    def fit(self, window_size):
        """Recompute font, cell size, board placement and letterbox origin
        for a window size."""
        if self.tiles:
            self._fit_tiles(window_size)
        else:
            self._fit_glyphs(window_size)

    def map_cell_size(self):
        """(w, h) of one map cell: a text cell, or a square tile."""
        if self.tile:
            return self.tile, self.tile
        return self.cell_w, self.cell_h

    def map_cell_to_pixel(self, x, y):
        """Top-left pixel of map cell (x, y), in either mode."""
        cell_w, cell_h = self.map_cell_size()
        return self.map_origin[0] + x * cell_w, self.map_origin[1] + y * cell_h

    def cell_to_pixel(self, x, y):
        """Top-left pixel of grid cell (x, y)."""
        return self.origin_x + x * self.cell_w, self.origin_y + y * self.cell_h

    def cell_rect(self, x, y):
        return pygame.Rect(*self.cell_to_pixel(x, y), self.cell_w, self.cell_h)

    def map_rect(self):
        """Pixel rect of the map area."""
        cell_w, cell_h = self.map_cell_size()
        return pygame.Rect(*self.map_origin, cell_w * self.map_width, cell_h * self.map_height)

    def _page_rect(self, text, board):
        """The parchment page around a board's `text` area: a margin of most
        of a column / row, clipped inside the board's frame."""
        page = text.inflate(2 * self.cell_w + 4, self.cell_h * 6 // 5)
        return page.clip(board.inflate(-2, -2))

    # The stats board.

    def panel_rows(self):
        """Rows the stats board takes: PANEL_ROWS, unless the grid ends first."""
        return max(1, min(PANEL_ROWS, self.rows - self.panel_y))

    def panel_rect(self):
        """Pixel rect of the stats noticeboard."""
        return pygame.Rect(
            *self.cell_to_pixel(self.panel_x, self.panel_y),
            self.cell_w * self.panel_width(),
            self.cell_h * self.panel_rows(),
        )

    def panel_width(self):
        """Columns of panel that fit: PANEL_COLS unless the grid is narrower."""
        return max(0, min(PANEL_COLS, self.cols - self.panel_x))

    @property
    def text_x(self):
        """Grid column where the stats board's text starts."""
        return self.panel_x + PANEL_PAD_X

    @property
    def text_y(self):
        """Grid row where the stats board's text starts (its row 0)."""
        return self.panel_y + PANEL_PAD_TOP

    def text_width(self):
        """Columns of text the stats page holds."""
        return max(0, self.panel_width() - 2 * PANEL_PAD_X)

    def text_rect(self):
        """Pixel rect of the stats page's text area (flat paper under the ink)."""
        return pygame.Rect(
            *self.cell_to_pixel(self.text_x, self.text_y),
            self.cell_w * self.text_width(),
            self.cell_h * PANEL_TEXT_ROWS,
        )

    def page_rect(self):
        """Pixel rect of the stats board's parchment page."""
        return self._page_rect(self.text_rect(), self.panel_rect())

    # The log board.

    def log_lines(self):
        """Message rows on the log page at this size: as many as the grid's
        rows allow under the 'LOG' header, up to LOG_LINES -- and never fewer
        than MIN_LOG_LINES (the board then runs off the bottom of a window
        too small for it, rather than onto the map)."""
        free = self.rows - (self.log_text_y + 1) - LOG_PAD_BOTTOM
        return max(MIN_LOG_LINES, min(LOG_LINES, free))

    def log_rect(self):
        """Pixel rect of the log noticeboard, frame included."""
        rows = LOG_PAD_TOP + 1 + self.log_lines() + LOG_PAD_BOTTOM
        return pygame.Rect(
            *self.cell_to_pixel(self.log_x, self.log_y),
            self.cell_w * self.log_cols,
            self.cell_h * rows,
        )

    @property
    def log_text_x(self):
        """Grid column where the log's text starts."""
        return self.log_x + LOG_PAD_X

    @property
    def log_text_y(self):
        """Grid row of the log's text row 0 (the header; messages from row 1)."""
        return self.log_y + LOG_PAD_TOP

    def log_text_width(self):
        """Columns of text the log page holds."""
        return max(0, self.log_cols - 2 * LOG_PAD_X)

    def log_page_rect(self):
        """Pixel rect of the log board's parchment page."""
        text = pygame.Rect(
            *self.cell_to_pixel(self.log_text_x, self.log_text_y),
            self.cell_w * self.log_text_width(),
            self.cell_h * (1 + self.log_lines()),
        )
        return self._page_rect(text, self.log_rect())


class Canvas:
    """Draws characters and strings into grid cells of `surface`.

    `surface` is reassigned by the renderer when the window is recreated;
    glyphs are cached per font, so a `Layout.fit()` needs no cache reset.
    """

    def __init__(self, surface, layout):
        self.surface = surface
        self.layout = layout
        self._glyphs = {}

    def clear(self):
        self.surface.fill(palette.BACKGROUND)

    def text_surface(self, text, color=palette.TEXT, background=None, bold=False, underline=False):
        """`text` rendered in the current font, for callers placing it by pixel."""
        return self._render(text, color, background, underline=underline, bold=bold)

    def _render(self, text, color, background=None, underline=False, bold=False):
        font = self.layout.font
        font.set_underline(underline)
        font.set_bold(bold)
        try:
            return font.render(text, True, color, background)
        finally:
            font.set_underline(False)
            font.set_bold(False)

    def put(self, x, y, char, color, underline=False, bold=False):
        """One character in cell (x, y). Cached -- this is the map's hot path."""
        key = (id(self.layout.font), char, color, underline, bold)
        if key not in self._glyphs:
            self._glyphs[key] = self._render(char, color, underline=underline, bold=bold)
        self.surface.blit(self._glyphs[key], self.layout.cell_to_pixel(x, y))

    def put_str(self, x, y, text, color=palette.TEXT, background=None, bold=False):
        """Text starting at cell (x, y), clipped to the grid's width."""
        layout = self.layout
        if not (0 <= y < layout.rows and 0 <= x < layout.cols):
            return
        text = text[: layout.cols - x]
        if text:
            self.surface.blit(
                self._render(text, color, background, bold=bold), layout.cell_to_pixel(x, y)
            )

    def put_str_centered(self, y, text, color=palette.TEXT, background=None):
        self.put_str(max(0, (self.layout.cols - len(text)) // 2), y, text, color, background)


# -- the panel ----------------------------------------------------------------


class PanelContent(NamedTuple):
    """Everything the stats board shows, as plain values (see panel_content)."""

    header: str  # 'Class - Depth n'
    hp: int
    max_hp: int
    danger: bool  # HP at or below a third: the HP text and bar go red
    stats: str  # stats_text
    items: str  # items_text
    gold: str  # 'Gold n'
    gear: tuple  # per slot: (name line, stats line, ink)
    belt: tuple  # per belt box: (label, ink)
    belt_full: bool  # the belt holds a potion: the first box is outlined
    boons: tuple  # the held boons' short names
    controls: tuple  # controls_rows for the class


def panel_content(state):
    """What the stats board shows for `state`, as a PanelContent. Two equal
    contents paint identical boards at the same layout -- which makes this
    the key render/boards.py caches the stats board under."""
    player = state.player
    belt = state.belt
    return PanelContent(
        header=f'{player.char_class.capitalize()} - Depth {state.depth}',
        hp=player.hp,
        max_hp=player.max_hp,
        danger=player.hp <= player.max_hp // 3,
        stats=stats_text(player),
        items=items_text(player),
        gold=f'Gold {player.gold}',
        gear=tuple(
            _gear_lines(label, item, stat)
            for label, item, stat in [('Wpn', player.weapon, 'atk'), ('Arm', player.armor, 'def')]
        ),
        belt=tuple(
            (EMPTY_SLOT, palette.INK)
            if i >= len(belt) or belt[i] is None
            else (belt_slot_label(belt[i], player), palette.ink(belt[i].color))
            for i in range(belt_capacity(player))
        ),
        belt_full=bool(belt),
        boons=tuple(boon.short for boon in held_boons(player)),
        controls=tuple(controls_rows(player.char_class)),
    )


def paint_panel(canvas, state):
    """The stats board: the noticeboard, then its sections inked on the page
    -- class & depth with HP (text and a bar), stats and items; gear (two
    rows a slot); the potion belt as a row of boxes; boons, once one is
    held; and a controls table. Text is clipped to the page's width. The
    message log is on its own board: paint_log."""
    paint_panel_content(canvas, panel_content(state))


def paint_panel_content(canvas, content):
    """paint_panel for an already-gathered PanelContent."""
    layout = canvas.layout
    if layout.panel_width() > 0:
        noticeboard.paint(canvas.surface, layout.panel_rect(), layout.page_rect())
    x, top = layout.text_x, layout.text_y
    width = layout.text_width()

    def put(row, text, color=palette.INK):
        canvas.put_str(x, top + row, text[:width], color)

    def header(row, text):
        _paint_header(canvas, x, top + row, width, text)

    header(HEADER_ROW, content.header)
    put(
        HP_ROW,
        f'HP: {content.hp}/{content.max_hp}',
        palette.INK_DANGER if content.danger else palette.INK,
    )
    _paint_hp_bar(canvas, x, top + HP_ROW, width, content.hp, content.max_hp, content.danger)
    put(STATS_ROW, content.stats)
    put(ITEMS_ROW, content.items)
    put(GOLD_ROW, content.gold, palette.ink(GOLD_COLOR))

    header(GEAR_TOP, 'GEAR')
    for row, (name, stats, color) in enumerate(content.gear):
        put(GEAR_TOP + 1 + 2 * row, name, color)
        if stats:
            put(GEAR_TOP + 2 + 2 * row, stats, color)

    header(BELT_TOP, 'BELT')
    _paint_belt(canvas, content.belt, content.belt_full)

    if content.boons:
        # The header says what they are: just their short names under it.
        header(BOONS_TOP, 'BOONS')
        for i, row in enumerate(_boon_name_rows(content.boons, width)):
            put(BOONS_TOP + 1 + i, row, palette.ink(BOON_COLOR))

    header(CONTROLS_TOP, 'CONTROLS')
    _paint_controls(canvas, x, top + CONTROLS_TOP + 1, width, content.controls)


def paint_log(canvas, state):
    """The log board: its noticeboard, a 'LOG' header, then the newest
    messages word-wrapped to the page, as many as its rows allow."""
    paint_log_messages(canvas, log_content(state, canvas.layout))


def log_content(state, layout):
    """The messages the log board can show at `layout`: the newest
    log_lines() of them (each takes at least a row). Two equal tails paint
    identical boards -- the key render/boards.py caches the log board under."""
    return tuple(state.messages[-layout.log_lines() :])


def paint_log_messages(canvas, messages):
    """paint_log for a tuple of messages (log_content)."""
    layout = canvas.layout
    if layout.log_cols <= 0:
        return
    noticeboard.paint(canvas.surface, layout.log_rect(), layout.log_page_rect())
    x, top, width = layout.log_text_x, layout.log_text_y, layout.log_text_width()
    _paint_header(canvas, x, top, width, 'LOG')
    for i, line in enumerate(log_rows(messages, width, layout.log_lines())):
        canvas.put_str(x, top + 1 + i, line, palette.INK)


def controls_rows(char_class):
    """The controls table's (key, action) rows for a class: the archer moves
    with wasd and shoots with the arrows; everyone else moves with both."""
    if char_class == 'archer':
        moves = [('wasd', 'move'), ('arrows', 'shoot')]
    else:
        moves = [('wasd/arrows', 'move')]
    return moves + [('space', 'wait'), ('e', 'descend'), ('h', 'drink'), ('q', 'ability')]


def stats_text(player):
    """The panel's stats row: 'ATK n   DEF n', plus '   DODGE n%' when the
    worn armor gives any dodge (game.item.dodge_chance)."""
    text = f'ATK {player.power}   DEF {player.defense}'
    dodge = dodge_chance(player)
    return f'{text}   DODGE {dodge}%' if dodge else text


def items_text(player):
    """The panel's item row: 'Items: n', plus '   Arrows n/12' for a player
    with a quiver (the archer; game/quiver.py)."""
    text = f'Items: {len(player.items_used)}'
    if player.quiver is None:
        return text
    return f'{text}   Arrows {player.quiver}/{QUIVER_CAPACITY}'


def boon_rows(boons, width):
    """The held boons' short names, space-separated and wrapped to `width`
    columns over at most BOON_ROWS rows (BOONS_TOP + 1 and the blank row
    before CONTROLS). A name is never split across rows."""
    return _boon_name_rows([boon.short for boon in boons], width)


def _boon_name_rows(names, width):
    """boon_rows for the short `names` themselves (PanelContent.boons)."""
    rows = textwrap.wrap(' '.join(names), max(1, width))
    return rows[:BOON_ROWS]


def log_rows(messages, width, rows):
    """The newest messages, word-wrapped to `width`, that fit in `rows` rows,
    oldest first. A message is shown whole or not at all, except that one too
    long for every row on its own is cut to its first `rows` lines."""
    if width <= 0 or rows <= 0:
        return []
    lines = []
    for message in reversed(messages):
        wrapped = textwrap.wrap(message, width) or ['']
        if len(lines) + len(wrapped) > rows:
            if not lines:
                lines = wrapped[:rows]
            break
        lines[:0] = wrapped
    return lines


def _paint_header(canvas, x, y, width, text):
    """A section header in text row `y`: bold ink, with a 1px rule across
    `width` columns along the foot of the row."""
    if width <= 0:
        return
    canvas.put_str(x, y, text[:width], palette.INK, bold=True)
    layout = canvas.layout
    left, row_top = layout.cell_to_pixel(x, y)
    foot = row_top + layout.cell_h - 1
    canvas.surface.fill(palette.TABLE_RULE, (left, foot, width * layout.cell_w, 1))


def _paint_controls(canvas, x, y, width, rows):
    """`rows` of (key, action) as a table from text row `y`, one row each:
    the key bold and centred in a shaded CONTROLS_KEY_COLS-wide column, the
    action a column into the second cell, 1px TABLE_RULE borders round every
    cell. The borders stay inside the rows the table takes."""
    if width <= 0 or not rows:
        return
    layout, surface = canvas.layout, canvas.surface
    key_cols = min(CONTROLS_KEY_COLS, width)
    left, top = layout.cell_to_pixel(x, y)
    table_w, key_w, cell_h = width * layout.cell_w, key_cols * layout.cell_w, layout.cell_h
    for i, (key, action) in enumerate(rows):
        row_top = top + i * cell_h
        cell = pygame.Rect(left, row_top, key_w, cell_h)
        surface.fill(palette.PAGE_EDGE, cell)
        text = _fit_width(canvas, key, key_w - 4)
        surface.blit(text, text.get_rect(center=cell.center))
        canvas.put_str(
            x + key_cols + 1, y + i, action[: max(0, width - key_cols - 1)], palette.INK
        )
    height = len(rows) * cell_h
    for i in range(len(rows)):
        surface.fill(palette.TABLE_RULE, (left, top + i * cell_h, table_w, 1))
    surface.fill(palette.TABLE_RULE, (left, top + height - 1, table_w, 1))
    for edge in (left, left + key_w, left + table_w - 1):
        surface.fill(palette.TABLE_RULE, (edge, top, 1, height))


def _fit_width(canvas, text, width):
    """`text` in bold ink if that fits in `width` pixels; else regular (the
    font's bold is synthetic, a pixel or so wider a glyph, so 'wasd/arrows'
    overflows its column), squeezed to `width` if even that doesn't fit."""
    bold = canvas.text_surface(text, palette.INK, bold=True)
    if bold.get_width() <= width:
        return bold
    regular = canvas.text_surface(text, palette.INK)
    if regular.get_width() <= width:
        return regular
    return pygame.transform.smoothscale(regular, (max(1, width), regular.get_height()))


def belt_slot_rects(layout, slots):
    """Pixel rects of `slots` equal belt boxes side by side across the stats
    page's text width on BELT_ROW. Neighbours share their 1px border."""
    if slots <= 0:
        return []
    left, top = layout.cell_to_pixel(layout.text_x, layout.text_y + BELT_ROW)
    step = (layout.text_width() * layout.cell_w - 1) // slots
    return [pygame.Rect(left + i * step, top, step + 1, layout.cell_h) for i in range(slots)]


def _paint_belt(canvas, slots, outline_first):
    """The potion belt on BELT_ROW: one box per (label, ink) in `slots`
    (PanelContent.belt -- a potion's heal after the player's boons in its
    rarity's ink, or a dash in plain ink when empty), centred. The first box
    -- the one 'h' drinks -- is outlined in ink if `outline_first` (the belt
    holds a potion)."""
    if canvas.layout.text_width() <= 0:
        return
    boxes = belt_slot_rects(canvas.layout, len(slots))
    surface = canvas.surface
    for box, (label, color) in zip(boxes, slots):
        text = canvas.text_surface(label, color)
        surface.blit(text, text.get_rect(center=box.center))
        pygame.draw.rect(surface, palette.TABLE_RULE, box, 1)
    if boxes and outline_first:
        pygame.draw.rect(surface, palette.INK, boxes[0], 2)


def _paint_hp_bar(canvas, x, y, width, hp, max_hp, danger):
    """A pixel bar in text row `y`, from panel column HP_BAR_COL: a dim track
    with the current share of max HP filled green, or red when in danger."""
    cols = min(HP_BAR_COLS, width - HP_BAR_COL)
    if cols <= 0:
        return
    layout = canvas.layout
    left, row_top = layout.cell_to_pixel(x + HP_BAR_COL, y)
    inset = layout.cell_h // 4
    track = pygame.Rect(
        left, row_top + inset, cols * layout.cell_w, max(2, layout.cell_h - 2 * inset)
    )
    canvas.surface.fill(HP_BAR_TRACK, track)
    share = max(0.0, min(1.0, hp / max_hp)) if max_hp > 0 else 0.0
    filled = round(track.width * share)
    if hp > 0:
        filled = max(1, filled)
    if filled:
        canvas.surface.fill(
            palette.INK_DANGER if danger else HP_BAR_COLOR,
            (track.left, track.top, filled, track.height),
        )


def _gear_lines(label, item, stat_label):
    """(name line, stats line, ink) for an equipment slot: the item's name,
    then its bonus and rarity indented under it, in its rarity's ink; or
    '(none)' and no stats line."""
    if item is None:
        return f'{label}: (none)', '', palette.INK
    return (
        f'{label}: {item.name}',
        f'     {item.bonus:+d} {stat_label}  [{item.rarity}]',
        palette.ink(item.color),
    )


def first_window_size(desktop=None):
    """FIRST_WINDOW (1920x1080) when it fits inside DESKTOP_SHARE of the
    desktop (`desktop`, else the primary one); otherwise the largest 16:9
    size inside that share. Never the whole desktop."""
    desktop_w, desktop_h = desktop or _desktop_size()
    target_w, target_h = FIRST_WINDOW
    usable_w, usable_h = int(desktop_w * DESKTOP_SHARE), int(desktop_h * DESKTOP_SHARE)
    if usable_w >= target_w and usable_h >= target_h:
        return FIRST_WINDOW
    width = max(16, min(usable_w, usable_h * target_w // target_h))
    return width, width * target_h // target_w


def _desktop_size():
    """The primary desktop's size, or a laptop-ish guess when unknown."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        sizes = None
    return sizes[0] if sizes else FALLBACK_DESKTOP


def _default_font():
    """The bundled font if it's there, else a system monospace font."""
    if BUNDLED_FONT.is_file():
        return str(BUNDLED_FONT)
    return pygame.font.match_font(FONT_NAMES)
