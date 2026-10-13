"""In-window UI: geometry, grid text drawing, and the side panel. Owned by WS-D.

`Layout` is the single source of truth for where things go (desktop_build_plan.md
§5 WS-D task 2): the renderer asks it for cell sizes and positions rather than
computing pixel offsets itself. `Canvas` draws text onto a surface in grid
cells. `paint_panel` is the side panel, at parity with curses_render._draw_panel.

P0 state: this is the spike's glyph-grid code moved out of pygame_render.py
unchanged. WS-D owns turning it into the real HUD (HP bar, longer log, a
virtual canvas for DPI scaling) -- keep the names below stable, or agree the
change with WS-A, since pygame_render.py and screens.py call them.

Reads GameState; never mutates it.
"""

import pygame

from render import palette

MESSAGE_LOG_LINES = 4
# The side panel starts two columns right of the map, as in curses; this many
# columns fit the widest gear line ("Wpn: <name> (+7 atk) [uncommon]").
PANEL_GAP = 2
PANEL_COLS = 44
PANEL_ROWS = 21  # log ends on row 19, plus one spare

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
    cells -- the map at the left, the panel from column `panel_x`. `fit()`
    picks the largest font whose grid fits the window and letterboxes it;
    text is re-rendered at the new size rather than scaled, so it stays crisp.

    Tile mode (`tiles=True`): the map is its own grid of square `tile`-pixel
    cells at `map_origin`, because 16x16 art can't go in a ~1:2 text cell.
    Text still uses a monospace grid, now covering the whole window, so the
    menus centre in it and the panel starts at column `panel_x`, row
    `panel_y`, just right of the map. `fit()` picks the largest tile size
    that leaves the panel a readable font.
    """

    def __init__(self, map_width, map_height, font_path=None, tiles=False):
        pygame.font.init()
        self.map_width = map_width
        self.map_height = map_height
        self.tiles = tiles
        self.tile = None
        self.panel_x = map_width + PANEL_GAP
        self.panel_y = 0
        self.cols = self.panel_x + PANEL_COLS
        self.rows = max(map_height, PANEL_ROWS)
        # None -> pygame's default font. WS-C vendors a real one (plan §5).
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

    def preferred_window_size(self):
        """Glyph mode: the grid exactly, at the starting font size. Tile mode:
        the map and panel at the biggest tile that fits most of the desktop."""
        if self.tiles:
            desktop_w, desktop_h = _desktop_size()
            tile, size = self._pick_tile_and_font(int(desktop_w * DESKTOP_SHARE),
                                                  int(desktop_h * DESKTOP_SHARE))
            return self._block_size(tile, self._cell_size(self._font(size)))
        cell_w, cell_h = self._cell_size(self._font(START_FONT_SIZE))
        return cell_w * self.cols, cell_h * self.rows

    def _block_size(self, tile, cell):
        """Pixel size of map + gap + panel at this tile size and text cell."""
        cell_w, cell_h = cell
        return (self.map_width * tile + (PANEL_GAP + PANEL_COLS) * cell_w,
                max(self.map_height * tile, PANEL_ROWS * cell_h))

    def _pick_tile_and_font(self, win_w, win_h):
        """Largest tile whose map + panel fit with the panel font at least
        MIN_TILE_FONT_SIZE, and the largest such font; if even the smallest
        tile needs a smaller font, the smallest tile and whatever font fits."""
        def fits(tile, size):
            block_w, block_h = self._block_size(tile, self._cell_size(self._font(size)))
            return block_w <= win_w and block_h <= win_h

        for tile in TILE_SIZES:
            for size in range(MAX_TILE_FONT_SIZE, MIN_TILE_FONT_SIZE - 1, -1):
                if fits(tile, size):
                    return tile, size
        tile = TILE_SIZES[-1]
        for size in range(MIN_TILE_FONT_SIZE - 1, MIN_FONT_SIZE - 1, -1):
            if fits(tile, size):
                return tile, size
        return tile, MIN_FONT_SIZE

    def fit(self, window_size):
        """Recompute font, cell size, and letterbox origin for a window size."""
        if self.tiles:
            self._fit_tiles(window_size)
            return
        win_w, win_h = window_size
        for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
            cell_w, cell_h = self._cell_size(self._font(size))
            if cell_w * self.cols <= win_w and cell_h * self.rows <= win_h:
                break
        self.font = self._font(size)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        self.origin_x = max(0, (win_w - self.cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - self.cell_h * self.rows) // 2)
        self.map_origin = (self.origin_x, self.origin_y)

    def _fit_tiles(self, window_size):
        win_w, win_h = window_size
        self.tile, size = self._pick_tile_and_font(win_w, win_h)
        self.font = self._font(size)
        cell_w, cell_h = self.cell_w, self.cell_h = self._cell_size(self.font)
        # The text grid covers the whole window (menus centre in it).
        self.cols = max(PANEL_COLS, win_w // cell_w)
        self.rows = max(PANEL_ROWS, win_h // cell_h)
        self.origin_x = max(0, (win_w - cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - cell_h * self.rows) // 2)
        # Centre map + panel as one block, then snap the panel onto the text
        # grid and hang the map off its left edge.
        block_w, block_h = self._block_size(self.tile, (cell_w, cell_h))
        map_w = self.map_width * self.tile
        block_left = max(0, (win_w - block_w) // 2)
        block_top = max(0, (win_h - block_h) // 2)
        panel_left = block_left + map_w + PANEL_GAP * cell_w
        self.panel_x = min(max(0, self.cols - PANEL_COLS),
                           max(0, round((panel_left - self.origin_x) / cell_w)))
        self.panel_y = min(max(0, self.rows - PANEL_ROWS),
                           max(0, (block_top - self.origin_y) // cell_h))
        self.map_origin = (
            max(0, self.origin_x + (self.panel_x - PANEL_GAP) * cell_w - map_w),
            self.origin_y + self.panel_y * cell_h,
        )

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
        """Pixel rect of the side panel."""
        return pygame.Rect(*self.cell_to_pixel(self.panel_x, self.panel_y),
                           self.cell_w * PANEL_COLS, self.cell_h * (self.rows - self.panel_y))


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

    def text_surface(self, text, color=palette.TEXT, background=None):
        """`text` rendered in the current font, for callers placing it by pixel."""
        return self._render(text, color, background)

    def _render(self, text, color, background=None, underline=False):
        font = self.layout.font
        font.set_underline(underline)
        surface = font.render(text, True, color, background)
        font.set_underline(False)
        return surface

    def put(self, x, y, char, color, underline=False):
        """One character in cell (x, y). Cached -- this is the map's hot path."""
        key = (id(self.layout.font), char, color, underline)
        if key not in self._glyphs:
            self._glyphs[key] = self._render(char, color, underline=underline)
        self.surface.blit(self._glyphs[key], self.layout.cell_to_pixel(x, y))

    def put_str(self, x, y, text, color=palette.TEXT, background=None):
        """Text starting at cell (x, y), clipped to the grid's width."""
        layout = self.layout
        if not (0 <= y < layout.rows and 0 <= x < layout.cols):
            return
        text = text[:layout.cols - x]
        if text:
            self.surface.blit(self._render(text, color, background),
                              layout.cell_to_pixel(x, y))

    def put_str_centered(self, y, text, color=palette.TEXT, background=None):
        self.put_str(max(0, (self.layout.cols - len(text)) // 2), y, text, color, background)


def paint_panel(canvas, state):
    """Same items, same rows as curses_render._draw_panel (offset by
    `layout.panel_y`, which is 0 except in tile mode)."""
    player = state.player
    x, top = canvas.layout.panel_x, canvas.layout.panel_y
    canvas.put_str(x, top, 'PythonRogue')
    canvas.put_str(x, top + 1, f'{player.char_class.capitalize()} - Depth: {state.depth}')
    hp_color = palette.DANGER if player.hp <= player.max_hp // 3 else palette.TEXT
    canvas.put_str(x, top + 2, f'HP: {player.hp}/{player.max_hp}', hp_color)
    canvas.put_str(x, top + 3, f'ATK {player.power}   DEF {player.defense}')
    canvas.put_str(x, top + 4, f'Items: {len(player.inventory)}')

    gear_start = top + 6
    canvas.put_str(x, gear_start, '-- gear --')
    _paint_gear_line(canvas, x, gear_start + 1, 'Wpn', player.weapon, 'atk')
    _paint_gear_line(canvas, x, gear_start + 2, 'Arm', player.armor, 'def')

    controls_start = gear_start + 4
    if player.char_class == 'archer':
        canvas.put_str(x, controls_start, 'wasd move, arrows shoot')
    else:
        canvas.put_str(x, controls_start, 'wasd/arrows move')
    canvas.put_str(x, controls_start + 1, '.  wait   e  descend')
    canvas.put_str(x, controls_start + 2, 'S  save   L  load')
    canvas.put_str(x, controls_start + 3, 'q  quit')

    log_start = controls_start + 5
    canvas.put_str(x, log_start, '-- log --')
    for i, msg in enumerate(state.messages[-MESSAGE_LOG_LINES:]):
        canvas.put_str(x, log_start + 1 + i, msg)


def _paint_gear_line(canvas, x, y, label, item, stat_label):
    if item is None:
        canvas.put_str(x, y, f'{label}: (none)')
        return
    text = f'{label}: {item.name} (+{item.bonus} {stat_label}) [{item.rarity}]'
    canvas.put_str(x, y, text, palette.color(item.color))


def _desktop_size():
    """The primary desktop's size, or a laptop-ish guess when unknown."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        sizes = None
    return sizes[0] if sizes else FALLBACK_DESKTOP
