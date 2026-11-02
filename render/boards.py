"""The stats and log boards, each cached as its own Surface.

Painting a board renders a few dozen lines of text with `font.render`, which
was 80-87% of a frame (CODE_REVIEW_2026-10-18.md §4). But a board only
changes when what it shows changes -- the player acts, a message is logged
-- or when the layout does. So each board is painted once onto an offscreen
Surface and every frame (map frames, the camera's beats and pans, impacts,
monster-phase frames) only blits it.

A board is rebuilt when its key changes. The key is (`layout_key`, content):

- content is every value the board displays, gathered by the same functions
  that paint it -- `ui.panel_content` (class, depth, HP and max HP, ATK, DEF
  and dodge, items, quiver, gold, gear names/bonuses/rarities, belt slots and
  capacity, boons, the class's controls) and `ui.log_content` (the message
  tail the page has rows for). The board is painted *from* that content, so
  nothing can be shown that the key doesn't cover;
- `layout_key` is the window size and every Layout field the boards' geometry
  is derived from (font, cell size, origin, grid size, board placement), so a
  resize, an F11 toggle or a refit rebuilds them. The renderer also calls
  `invalidate()` on every relayout, belt and braces.

The cache is filled on the main thread, inside the frame that first needs it:
not on a worker thread, because pygame's fonts and surfaces aren't
thread-safe, and a rebuild is a few ms once per change anyway.
"""

import copy

import pygame

from render import palette, ui


def layout_key(layout, window_size):
    """Everything about the layout and window that moves a board's pixels."""
    return (
        tuple(window_size),
        layout.font_path,
        layout.font_size,
        id(layout.font),
        layout.cell_w,
        layout.cell_h,
        layout.origin_x,
        layout.origin_y,
        layout.cols,
        layout.rows,
        layout.panel_x,
        layout.panel_y,
        layout.log_x,
        layout.log_y,
        layout.log_cols,
    )


def panel_area(layout):
    """Window pixels the stats board paints: its board, and its text area,
    which runs past the board when the grid ends first."""
    return layout.panel_rect().union(layout.text_rect())


def log_area(layout):
    """Window pixels the log board paints."""
    return layout.log_rect().union(layout.log_page_rect())


class BoardCache:
    """The two boards' cached surfaces. `paint(canvas, state)` blits both,
    rebuilding whichever one's key changed."""

    def __init__(self):
        # name -> (key, Surface, top-left in the window)
        self._boards = {}
        # Boards painted from scratch so far (tests and benchmarks read it).
        self.rebuilds = 0

    def invalidate(self):
        """Drop both boards: the next paint rebuilds them."""
        self._boards.clear()

    def paint(self, canvas, state):
        layout = canvas.layout
        where = layout_key(layout, canvas.surface.get_size())
        self._blit(
            canvas,
            'panel',
            (where, ui.panel_content(state)),
            panel_area(layout),
            ui.paint_panel_content,
        )
        if layout.log_cols > 0:
            self._blit(
                canvas,
                'log',
                (where, ui.log_content(state, layout)),
                log_area(layout),
                ui.paint_log_messages,
            )

    def _blit(self, canvas, name, key, area, paint):
        cached = self._boards.get(name)
        if cached is None or cached[0] != key:
            cached = (key, *self._build(canvas, area, key[1], paint))
            self._boards[name] = cached
        _, surface, topleft = cached
        if surface is not None:
            canvas.surface.blit(surface, topleft)

    def _build(self, canvas, area, content, paint):
        """(Surface, top-left) of one board painted from scratch: `paint` run
        on an offscreen canvas whose layout is shifted so `area`'s corner is
        its (0, 0). Off-window parts are left out; (None, None) if nothing of
        it is on screen."""
        self.rebuilds += 1
        area = area.clip(canvas.surface.get_rect())
        if area.width <= 0 or area.height <= 0:
            return None, None
        # The window's own pixel format, so the per-frame blit is a plain copy;
        # background underneath, as on a freshly cleared frame.
        surface = pygame.Surface(area.size, 0, canvas.surface)
        surface.fill(palette.BACKGROUND)
        shifted = copy.copy(canvas.layout)
        shifted.origin_x -= area.x
        shifted.origin_y -= area.y
        paint(ui.Canvas(surface, shifted), content)
        return surface, area.topleft
