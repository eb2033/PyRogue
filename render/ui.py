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


class Layout:
    """Grid geometry: how many cells, how big, and where the grid sits.

    The window is a `cols x rows` grid of monospace cells -- the map at the
    left, the panel from column `panel_x`. `fit()` picks the largest font
    whose grid fits the window and letterboxes it; text is re-rendered at the
    new size rather than scaled, so it stays crisp.
    """

    def __init__(self, map_width, map_height, font_path=None):
        pygame.font.init()
        self.map_width = map_width
        self.map_height = map_height
        self.panel_x = map_width + PANEL_GAP
        self.cols = self.panel_x + PANEL_COLS
        self.rows = max(map_height, PANEL_ROWS)
        # None -> pygame's default font. WS-C vendors a real one (plan §5).
        self.font_path = font_path or pygame.font.match_font(FONT_NAMES)
        self._fonts = {}
        self.font = self._font(START_FONT_SIZE)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        self.origin_x = self.origin_y = 0

    def _font(self, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(self.font_path, size)
        return self._fonts[size]

    @staticmethod
    def _cell_size(font):
        return font.size('M')[0], font.get_linesize()

    def preferred_window_size(self):
        """Window size that fits the grid exactly at the starting font size."""
        cell_w, cell_h = self._cell_size(self._font(START_FONT_SIZE))
        return cell_w * self.cols, cell_h * self.rows

    def fit(self, window_size):
        """Recompute font, cell size, and letterbox origin for a window size."""
        win_w, win_h = window_size
        for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
            cell_w, cell_h = self._cell_size(self._font(size))
            if cell_w * self.cols <= win_w and cell_h * self.rows <= win_h:
                break
        self.font = self._font(size)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        self.origin_x = max(0, (win_w - self.cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - self.cell_h * self.rows) // 2)

    def cell_to_pixel(self, x, y):
        """Top-left pixel of grid cell (x, y)."""
        return self.origin_x + x * self.cell_w, self.origin_y + y * self.cell_h

    def cell_rect(self, x, y):
        return pygame.Rect(*self.cell_to_pixel(x, y), self.cell_w, self.cell_h)

    def map_rect(self):
        """Pixel rect of the map area."""
        return pygame.Rect(*self.cell_to_pixel(0, 0),
                           self.cell_w * self.map_width, self.cell_h * self.map_height)

    def panel_rect(self):
        """Pixel rect of the side panel."""
        return pygame.Rect(*self.cell_to_pixel(self.panel_x, 0),
                           self.cell_w * PANEL_COLS, self.cell_h * self.rows)


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
    """Same items, same rows as curses_render._draw_panel."""
    player = state.player
    x = canvas.layout.panel_x
    canvas.put_str(x, 0, 'PythonRogue')
    canvas.put_str(x, 1, f'{player.char_class.capitalize()} - Depth: {state.depth}')
    hp_color = palette.DANGER if player.hp <= player.max_hp // 3 else palette.TEXT
    canvas.put_str(x, 2, f'HP: {player.hp}/{player.max_hp}', hp_color)
    canvas.put_str(x, 3, f'ATK {player.power}   DEF {player.defense}')
    canvas.put_str(x, 4, f'Items: {len(player.inventory)}')

    gear_start = 6
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
