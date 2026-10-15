"""In-window UI: geometry, grid text drawing, and the side panel. Owned by WS-D.

`Layout` is the single source of truth for where things go (desktop_build_plan.md
§5 WS-D task 2): the renderer asks it for cell sizes and positions rather than
computing pixel offsets itself. `Canvas` draws text onto a surface in grid
cells. `paint_panel` is the side panel: every item curses_render._draw_panel
shows, on the same relative rows, plus a pixel HP bar and a longer, wrapped
message log.

The panel sits right of the map, or under it when that gives the map bigger
cells (a portrait or narrow window) -- `Layout.stacked`. Either way it is the
`PANEL_COLS`-wide block at grid cell (`panel_x`, `panel_y`), so callers never
need to know which. It is drawn as a wooden noticeboard (render/noticeboard.py)
with the stats inked on a parchment page hanging from it: text starts at
(`text_x`, `text_y`), `PANEL_PAD_X` columns and `PANEL_PAD_TOP` rows in, so the
frame, the nail and the page's margins fit around it.

Reads GameState; never mutates it.
"""

import textwrap

import pygame

from game.item import belt_capacity, belt_slot_label
from game.paths import resource_path
from game.shrine import BOON_COLOR, boons_text
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
HP_ROW = 2
GEAR_TOP = 6  # header; weapon name + stats, armor name + stats
BELT_ROW = GEAR_TOP + 5  # the potion belt, under the armor
BOONS_ROW = BELT_ROW + 1  # shrine boons; blank until the first is taken
CONTROLS_TOP = GEAR_TOP + 7
LOG_TOP = CONTROLS_TOP + 5  # the '-- log --' header; messages start below it
MIN_LOG_LINES = 4  # the terminal's count: always room for this many
LOG_LINES = 12  # shown when the window has the rows for them
PANEL_ROWS = PANEL_PAD_TOP + LOG_TOP + 1 + MIN_LOG_LINES + PANEL_PAD_BOTTOM  # the minimum
PANEL_MAX_ROWS = PANEL_PAD_TOP + LOG_TOP + 1 + LOG_LINES + PANEL_PAD_BOTTOM  # a full log
# Stacked (panel under the map): blank text rows between map and panel.
STACK_GAP = 1

# The HP bar sits right of the 'HP: x/max' text, in panel columns.
HP_BAR_COL = 12  # 'HP: 999/999' is 11 wide
HP_BAR_COLS = PANEL_TEXT_COLS - HP_BAR_COL
HP_BAR_COLOR = palette.HP_BAR_FILL  # palette.INK_DANGER at or below 1/3 max
HP_BAR_TRACK = palette.HP_BAR_TRACK

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
# The first window takes at most this share of the desktop.
DESKTOP_SHARE = 0.85
FALLBACK_DESKTOP = (1280, 800)


class Layout:
    """Grid geometry: how many cells, how big, and where the grid sits.

    Glyph mode (the default): the window is a `cols x rows` grid of monospace
    cells -- the map at the top left, the panel at column `panel_x`, row
    `panel_y`. `fit()` picks the largest font whose grid fits the window and
    letterboxes it; text is re-rendered at the new size rather than scaled, so
    it stays crisp. The grid grows a few rows when the window has them spare,
    up to what a full message log uses.

    Tile mode (`tiles=True`): the map is its own grid of square `tile`-pixel
    cells at `map_origin`, because 16x16 art can't go in a ~1:2 text cell.
    Text still uses a monospace grid, now covering the whole window, so the
    menus centre in it and the panel starts at column `panel_x`, row
    `panel_y`, next to the map. `fit()` picks the largest tile size that
    leaves the panel a readable font.

    In both modes the panel goes right of the map, or -- `stacked` -- under
    it, whichever gives the map bigger cells (in tile mode, a tie goes to the
    bigger panel font; otherwise to side by side).
    """

    def __init__(self, map_width, map_height, font_path=None, tiles=False):
        pygame.font.init()
        self.map_width = map_width
        self.map_height = map_height
        self.tiles = tiles
        self.tile = None
        self.stacked = False
        self.cols, self.rows, _, self.panel_x, self.panel_y = self._glyph_grid(False)
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
        """(cols, min_rows, max_rows, panel_x, panel_y) of the glyph grid.

        The map is always at grid cell (0, 0): the renderer draws it with
        Canvas.put, i.e. in grid cells."""
        if stacked:
            panel_y = self.map_height + STACK_GAP
            return (
                max(self.map_width, PANEL_COLS),
                panel_y + PANEL_ROWS,
                panel_y + PANEL_MAX_ROWS,
                0,
                panel_y,
            )
        return (
            self.map_width + PANEL_GAP + PANEL_COLS,
            max(self.map_height, PANEL_ROWS),
            max(self.map_height, PANEL_MAX_ROWS),
            self.map_width + PANEL_GAP,
            0,
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
        cols, min_rows, max_rows, self.panel_x, self.panel_y = self._glyph_grid(self.stacked)
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

    def _block_size(self, tile, cell, stacked=False, panel_rows=PANEL_ROWS):
        """Pixel size of map + gap + panel at this tile size and text cell."""
        cell_w, cell_h = cell
        map_w, map_h = self.map_width * tile, self.map_height * tile
        if stacked:
            return (max(map_w, PANEL_COLS * cell_w), map_h + (STACK_GAP + panel_rows) * cell_h)
        return (map_w + (PANEL_GAP + PANEL_COLS) * cell_w, max(map_h, panel_rows * cell_h))

    def _pick_tile_and_font(self, win_w, win_h, stacked=False):
        """(tile, font size, shortfall). The largest tile whose map + panel
        fit with the panel font at least MIN_TILE_FONT_SIZE, and the largest
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
        # A font whose panel still fits the window's height wins a tie, so
        # an over-wide map doesn't drag the panel off the bottom too.
        best = max(
            range(MAX_TILE_FONT_SIZE, MIN_FONT_SIZE - 1, -1),
            key=lambda size: (coverage(tile, size), height_fits(tile, size), size),
        )
        return tile, best, coverage(tile, best)

    def _choose_tiles(self, win_w, win_h):
        """(stacked, tile, font size): stacked only if it gives a bigger tile,
        or the same tile with a bigger panel font. In a window too small for
        either, whichever overflows it less (so map and panel don't overlap
        in a narrow window that can't even fit the map)."""
        side_tile, side_size, side_fit = self._pick_tile_and_font(win_w, win_h, False)
        tile, size, stacked_fit = self._pick_tile_and_font(win_w, win_h, True)
        if (stacked_fit, tile, size) > (side_fit, side_tile, side_size):
            return True, tile, size
        return False, side_tile, side_size

    def _grow_tile_font(self, size, win_w, win_h):
        """Once the tile is chosen, the panel font may grow past
        MAX_TILE_FONT_SIZE (up to MAX_FONT_SIZE) while map + panel, with a
        full-length log, still fit: at 4K a 20pt panel next to 64px tiles is
        unreadably small. Never shrinks the log below what `size` gives."""
        for bigger in range(MAX_FONT_SIZE, size, -1):
            block_w, block_h = self._block_size(
                self.tile,
                self._cell_size(self._font(bigger)),
                self.stacked,
                panel_rows=PANEL_MAX_ROWS,
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
        # Centre map + panel as one block, then snap the panel onto the text
        # grid and place the map against it.
        # Centre on the board with a full log when that fits, so the log
        # isn't cut short by a panel that starts too low.
        block_w, block_h = self._block_size(
            self.tile, (cell_w, cell_h), self.stacked, panel_rows=PANEL_MAX_ROWS
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
        self.panel_y = min(
            max(0, self.rows - PANEL_ROWS), max(0, (block_top - self.origin_y) // cell_h)
        )
        self.map_origin = (
            max(0, self.origin_x + (self.panel_x - PANEL_GAP) * cell_w - map_w),
            self.origin_y + self.panel_y * cell_h,
        )

    def _place_stacked_tiles(self, block_left, block_top, win_w, map_w, map_h):
        """Map on top, panel under it, both left-aligned on the panel's column."""
        cell_w, cell_h = self.cell_w, self.cell_h
        self.panel_x = min(
            max(0, self.cols - PANEL_COLS), max(0, round((block_left - self.origin_x) / cell_w))
        )
        map_left = max(0, min(self.origin_x + self.panel_x * cell_w, win_w - map_w))

        # First whole text row below the map, plus the gap.
        def row_below(map_top):
            return -(-(map_top + map_h - self.origin_y) // cell_h) + STACK_GAP

        # Pull the panel up to keep it inside the window, but never above the
        # row below a map at the very top: overlapping the map is worse than
        # running off the bottom of a window too small for both.
        panel_y = min(row_below(block_top), self.rows - PANEL_ROWS)
        self.panel_y = max(0, panel_y, row_below(0))
        panel_top = self.origin_y + self.panel_y * cell_h
        # If the panel had to move up, the map moves up with it.
        map_top = min(block_top, panel_top - STACK_GAP * cell_h - map_h)
        self.map_origin = (map_left, max(0, map_top))

    # -- public geometry ------------------------------------------------------

    def preferred_window_size(self):
        """Glyph mode: the side-by-side grid with a full log, at the starting
        font size. Tile mode: map and panel at the biggest tile that fits most
        of the desktop."""
        if self.tiles:
            desktop_w, desktop_h = _desktop_size()
            win_w, win_h = int(desktop_w * DESKTOP_SHARE), int(desktop_h * DESKTOP_SHARE)
            stacked, tile, size = self._choose_tiles(win_w, win_h)
            return self._block_size(tile, self._cell_size(self._font(size)), stacked)
        cols, _, max_rows = self._glyph_grid(False)[:3]
        cell_w, cell_h = self._cell_size(self._font(START_FONT_SIZE))
        return cell_w * cols, cell_h * max_rows

    def fit(self, window_size):
        """Recompute font, cell size, panel placement and letterbox origin
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

    def panel_rows(self):
        """Rows the board takes: padding, the stats, and the log at this size."""
        rows = PANEL_PAD_TOP + LOG_TOP + 1 + self.log_lines() + PANEL_PAD_BOTTOM
        return max(1, min(rows, self.rows - self.panel_y))

    def panel_rect(self):
        """Pixel rect of the noticeboard."""
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
        """Grid column where the panel's text starts."""
        return self.panel_x + PANEL_PAD_X

    @property
    def text_y(self):
        """Grid row where the panel's text starts (its row 0)."""
        return self.panel_y + PANEL_PAD_TOP

    def text_width(self):
        """Columns of text the page holds."""
        return max(0, self.panel_width() - 2 * PANEL_PAD_X)

    def text_rect(self):
        """Pixel rect of the page's text area (flat paper under the ink)."""
        return pygame.Rect(
            *self.cell_to_pixel(self.text_x, self.text_y),
            self.cell_w * self.text_width(),
            self.cell_h * (LOG_TOP + 1 + self.log_lines()),
        )

    def page_rect(self):
        """Pixel rect of the parchment page: the text area plus a margin of
        most of a column / row, inside the board."""
        text = self.text_rect()
        page = text.inflate(2 * self.cell_w + 4, self.cell_h * 6 // 5)
        return page.clip(self.panel_rect().inflate(-2, -2))

    def log_lines(self):
        """How many message-log rows the panel has at this size: as many as
        the grid's rows allow under the log header, up to LOG_LINES."""
        free = self.rows - (self.text_y + LOG_TOP + 1) - PANEL_PAD_BOTTOM
        return max(1, min(LOG_LINES, free))


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


def paint_panel(canvas, state):
    """The noticeboard, then every item of curses_render._draw_panel inked on
    its page, in the same order (gear lines take two rows each here), clipped
    to the page's width; plus an HP bar beside the HP text and a message log
    as long as the rows allow."""
    layout = canvas.layout
    if layout.panel_width() > 0:
        noticeboard.paint(canvas.surface, layout.panel_rect(), layout.page_rect())
    player = state.player
    x, top = layout.text_x, layout.text_y
    width = layout.text_width()

    def put(row, text, color=palette.INK, bold=False):
        canvas.put_str(x, top + row, text[:width], color, bold=bold)

    put(0, 'PythonRogue', bold=True)
    put(1, f'{player.char_class.capitalize()} - Depth: {state.depth}')
    danger = player.hp <= player.max_hp // 3
    put(HP_ROW, f'HP: {player.hp}/{player.max_hp}', palette.INK_DANGER if danger else palette.INK)
    _paint_hp_bar(canvas, x, top + HP_ROW, width, player.hp, player.max_hp, danger)
    put(3, f'ATK {player.power}   DEF {player.defense}')
    put(4, f'Items: {len(player.inventory)}')

    put(GEAR_TOP, '-- gear --', bold=True)
    for row, (label, item, stat) in enumerate(
        [('Wpn', player.weapon, 'atk'), ('Arm', player.armor, 'def')]
    ):
        name, stats, color = _gear_lines(label, item, stat)
        put(GEAR_TOP + 1 + 2 * row, name, color)
        if stats:
            put(GEAR_TOP + 2 + 2 * row, stats, color)
    _paint_belt(canvas, x, top + BELT_ROW, width, state.belt, player)
    boons = boons_text(player)
    if boons:
        put(BOONS_ROW, boons, palette.ink(BOON_COLOR))

    if player.char_class == 'archer':
        put(CONTROLS_TOP, 'wasd move, arrows shoot')
    else:
        put(CONTROLS_TOP, 'wasd/arrows move')
    put(CONTROLS_TOP + 1, '.  wait   e  descend')
    put(CONTROLS_TOP + 2, 'S  save   L  load')
    put(CONTROLS_TOP + 3, 'h  drink  q  quit')

    put(LOG_TOP, '-- log --', bold=True)
    for i, line in enumerate(log_rows(state.messages, width, layout.log_lines())):
        put(LOG_TOP + 1 + i, line)


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


def _paint_belt(canvas, x, y, width, belt, player):
    """'Belt: [+20] +35 ---' in text row `y`, like curses_render's
    _draw_belt_line: the bracketed first slot is the one 'h' drinks; each
    potion in its rarity's ink, empty slots in plain ink. One slot per
    belt_capacity(player), each showing its heal after the player's boons."""
    label = 'Belt: '
    canvas.put_str(x, y, label[:width], palette.INK)
    col = len(label)
    for i in range(belt_capacity(player)):
        item = belt[i] if i < len(belt) else None
        text = belt_slot_label(item, player)
        if i == 0:
            text = f'[{text}]'
        if col < width:
            color = palette.ink(item.color) if item is not None else palette.INK
            canvas.put_str(x + col, y, text[: width - col], color)
        col += len(text) + 1


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
