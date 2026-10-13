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
need to know which.

Reads GameState; never mutates it.
"""

import textwrap

import pygame

from render import palette

# -- panel geometry (rows relative to the panel's top) ------------------------
# The side panel starts two columns right of the map, as in curses; this many
# columns fit the widest gear line ("Wpn: <name> (+7 atk) [uncommon]").
PANEL_GAP = 2
PANEL_COLS = 44
HP_ROW = 2
GEAR_TOP = 6
CONTROLS_TOP = GEAR_TOP + 4
LOG_TOP = CONTROLS_TOP + 5        # the '-- log --' header; messages start below it
MIN_LOG_LINES = 4                 # the terminal's count: always room for this many
LOG_LINES = 12                    # shown when the window has the rows for them
LOG_SPARE_ROWS = 1                # blank row kept under the log
PANEL_ROWS = LOG_TOP + 1 + MIN_LOG_LINES + LOG_SPARE_ROWS   # 21: the minimum
PANEL_MAX_ROWS = LOG_TOP + 1 + LOG_LINES + LOG_SPARE_ROWS   # what a full log uses
# Stacked (panel under the map): blank text rows between map and panel.
STACK_GAP = 1

# The HP bar sits right of the 'HP: x/max' text, in panel columns.
HP_BAR_COL = 12                   # 'HP: 999/999' is 11 wide
HP_BAR_COLS = 20
HP_BAR_COLOR = palette.COLORS[4]  # green; palette.DANGER at or below 1/3 max
HP_BAR_TRACK = palette.SEEN

FONT_NAMES = 'dejavusansmono,liberationmono,consolas,menlo,couriernew,monospace'
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 48
START_FONT_SIZE = 18

# Tile mode: on-screen map tile sizes, largest first. Multiples of 8 so the
# 16px Kenney art scales by whole or half steps (nearest-neighbour).
TILE_SIZES = (64, 56, 48, 40, 32, 24, 16)
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
        # None -> pygame's default font. A bundled one comes in via font_path.
        self.font_path = font_path or pygame.font.match_font(FONT_NAMES)
        self._fonts = {}
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
            return (max(self.map_width, PANEL_COLS), panel_y + PANEL_ROWS,
                    panel_y + PANEL_MAX_ROWS, 0, panel_y)
        return (self.map_width + PANEL_GAP + PANEL_COLS,
                max(self.map_height, PANEL_ROWS), max(self.map_height, PANEL_MAX_ROWS),
                self.map_width + PANEL_GAP, 0)

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
        self.font = self._font(sizes[self.stacked])
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
            return (max(map_w, PANEL_COLS * cell_w),
                    map_h + (STACK_GAP + panel_rows) * cell_h)
        return (map_w + (PANEL_GAP + PANEL_COLS) * cell_w,
                max(map_h, panel_rows * cell_h))

    def _pick_tile_and_font(self, win_w, win_h, stacked=False):
        """(tile, font size, shortfall). The largest tile whose map + panel
        fit with the panel font at least MIN_TILE_FONT_SIZE, and the largest
        such font; if even the smallest tile needs a smaller font, the
        smallest tile and whatever font fits. `shortfall` is 1.0 when that
        fits the window, else the share of it that does (the worse axis)."""
        def coverage(tile, size):
            block_w, block_h = self._block_size(tile, self._cell_size(self._font(size)),
                                                stacked)
            return min(1.0, win_w / block_w, win_h / block_h)

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
        best = max(range(MAX_TILE_FONT_SIZE, MIN_FONT_SIZE - 1, -1),
                   key=lambda size: (coverage(tile, size), size))
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
                self.tile, self._cell_size(self._font(bigger)), self.stacked,
                panel_rows=PANEL_MAX_ROWS)
            if block_w <= win_w and block_h <= win_h:
                return bigger
        return size

    def _fit_tiles(self, window_size):
        win_w, win_h = window_size
        self.stacked, self.tile, size = self._choose_tiles(win_w, win_h)
        size = self._grow_tile_font(size, win_w, win_h)
        self.font = self._font(size)
        cell_w, cell_h = self.cell_w, self.cell_h = self._cell_size(self.font)
        # The text grid covers the whole window (menus centre in it).
        self.cols = max(PANEL_COLS, win_w // cell_w)
        self.rows = max(PANEL_ROWS, win_h // cell_h)
        self.origin_x = max(0, (win_w - cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - cell_h * self.rows) // 2)
        # Centre map + panel as one block, then snap the panel onto the text
        # grid and place the map against it.
        block_w, block_h = self._block_size(self.tile, (cell_w, cell_h), self.stacked)
        map_w, map_h = self.map_width * self.tile, self.map_height * self.tile
        block_left = max(0, (win_w - block_w) // 2)
        block_top = max(0, (win_h - block_h) // 2)
        if self.stacked:
            self._place_stacked_tiles(block_left, block_top, win_w, map_w, map_h)
            return
        panel_left = block_left + map_w + PANEL_GAP * cell_w
        self.panel_x = min(max(0, self.cols - PANEL_COLS),
                           max(0, round((panel_left - self.origin_x) / cell_w)))
        self.panel_y = min(max(0, self.rows - PANEL_ROWS),
                           max(0, (block_top - self.origin_y) // cell_h))
        self.map_origin = (
            max(0, self.origin_x + (self.panel_x - PANEL_GAP) * cell_w - map_w),
            self.origin_y + self.panel_y * cell_h,
        )

    def _place_stacked_tiles(self, block_left, block_top, win_w, map_w, map_h):
        """Map on top, panel under it, both left-aligned on the panel's column."""
        cell_w, cell_h = self.cell_w, self.cell_h
        self.panel_x = min(max(0, self.cols - PANEL_COLS),
                           max(0, round((block_left - self.origin_x) / cell_w)))
        map_left = max(0, min(self.origin_x + self.panel_x * cell_w, win_w - map_w))
        # First whole text row below the map, plus the gap.
        map_bottom = block_top + map_h
        panel_y = -(-(map_bottom - self.origin_y) // cell_h) + STACK_GAP
        self.panel_y = max(0, min(panel_y, self.rows - PANEL_ROWS))
        panel_top = self.origin_y + self.panel_y * cell_h
        # If the panel had to move up, the map moves up with it.
        self.map_origin = (map_left, max(0, min(block_top, panel_top - map_h)))

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

    def panel_rect(self):
        """Pixel rect of the panel, from its top to the bottom of the grid."""
        return pygame.Rect(*self.cell_to_pixel(self.panel_x, self.panel_y),
                           self.cell_w * PANEL_COLS, self.cell_h * (self.rows - self.panel_y))

    def panel_width(self):
        """Columns of panel text that fit: PANEL_COLS unless the grid is narrower."""
        return max(0, min(PANEL_COLS, self.cols - self.panel_x))

    def log_lines(self):
        """How many message-log rows the panel has at this size: as many as
        the grid's rows allow under the log header, up to LOG_LINES."""
        free = self.rows - (self.panel_y + LOG_TOP + 1) - LOG_SPARE_ROWS
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

    def text_surface(self, text, color=palette.TEXT, background=None,
                     bold=False, underline=False):
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
        text = text[:layout.cols - x]
        if text:
            self.surface.blit(self._render(text, color, background, bold=bold),
                              layout.cell_to_pixel(x, y))

    def put_str_centered(self, y, text, color=palette.TEXT, background=None):
        self.put_str(max(0, (self.layout.cols - len(text)) // 2), y, text, color, background)


# -- the panel ----------------------------------------------------------------

def paint_panel(canvas, state):
    """Every item of curses_render._draw_panel, on the same rows relative to
    the panel's top (`layout.panel_y`), clipped to the panel's width; plus an
    HP bar beside the HP text and a message log as long as the rows allow."""
    layout = canvas.layout
    player = state.player
    x, top = layout.panel_x, layout.panel_y
    width = layout.panel_width()

    def put(row, text, color=palette.TEXT):
        canvas.put_str(x, top + row, text[:width], color)

    put(0, 'PythonRogue')
    put(1, f'{player.char_class.capitalize()} - Depth: {state.depth}')
    danger = player.hp <= player.max_hp // 3
    put(HP_ROW, f'HP: {player.hp}/{player.max_hp}', palette.DANGER if danger else palette.TEXT)
    _paint_hp_bar(canvas, x, top + HP_ROW, width, player.hp, player.max_hp, danger)
    put(3, f'ATK {player.power}   DEF {player.defense}')
    put(4, f'Items: {len(player.inventory)}')

    put(GEAR_TOP, '-- gear --')
    put(GEAR_TOP + 1, *_gear_line('Wpn', player.weapon, 'atk'))
    put(GEAR_TOP + 2, *_gear_line('Arm', player.armor, 'def'))

    if player.char_class == 'archer':
        put(CONTROLS_TOP, 'wasd move, arrows shoot')
    else:
        put(CONTROLS_TOP, 'wasd/arrows move')
    put(CONTROLS_TOP + 1, '.  wait   e  descend')
    put(CONTROLS_TOP + 2, 'S  save   L  load')
    put(CONTROLS_TOP + 3, 'q  quit')

    put(LOG_TOP, '-- log --')
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


def _paint_hp_bar(canvas, x, y, width, hp, max_hp, danger):
    """A pixel bar in text row `y`, from panel column HP_BAR_COL: a dim track
    with the current share of max HP filled green, or red when in danger."""
    cols = min(HP_BAR_COLS, width - HP_BAR_COL)
    if cols <= 0:
        return
    layout = canvas.layout
    left, row_top = layout.cell_to_pixel(x + HP_BAR_COL, y)
    inset = layout.cell_h // 4
    track = pygame.Rect(left, row_top + inset, cols * layout.cell_w,
                        max(2, layout.cell_h - 2 * inset))
    canvas.surface.fill(HP_BAR_TRACK, track)
    share = max(0.0, min(1.0, hp / max_hp)) if max_hp > 0 else 0.0
    filled = round(track.width * share)
    if hp > 0:
        filled = max(1, filled)
    if filled:
        canvas.surface.fill(palette.DANGER if danger else HP_BAR_COLOR,
                            (track.left, track.top, filled, track.height))


def _gear_line(label, item, stat_label):
    """(text, colour) of a gear line: the item in its rarity colour, or none."""
    if item is None:
        return f'{label}: (none)', palette.TEXT
    return (f'{label}: {item.name} (+{item.bonus} {stat_label}) [{item.rarity}]',
            palette.color(item.color))


def _desktop_size():
    """The primary desktop's size, or a laptop-ish guess when unknown."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        sizes = None
    return sizes[0] if sizes else FALLBACK_DESKTOP
