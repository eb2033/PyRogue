"""The side panel's backdrop: a wooden noticeboard with a parchment page
hanging from a nail. Drawn procedurally (not from the tileset) so it stays
crisp at any cell size, and cached per size since it never changes between
frames -- a frame is one blit plus the text on top.

The area of the page under the text is a single flat colour (palette.PAGE):
all texture and shading live on the board and the page's margins, so ink is
easy to tell apart from paper (tests rely on that).

Paint-only, like screens.py: `paint(surface, board_rect, page_rect)`.
"""

import random

import pygame

from render import palette

FRAME = (70, 43, 22)
FRAME_LIGHT = (104, 68, 36)
FRAME_DARK = (44, 26, 12)
PLANKS = [(140, 95, 53), (128, 85, 46), (147, 101, 58), (133, 89, 50)]
SEAM = (82, 52, 26)
GRAIN = (112, 74, 40)
KNOT = (92, 60, 32)
NAIL = (150, 150, 158)
NAIL_LIGHT = (214, 214, 222)
NAIL_DARK = (78, 78, 86)
STRING = (66, 50, 34)
SHADOW = (0, 0, 0, 90)

_cache = {}


def paint(surface, board_rect, page_rect):
    """Blit the board (filling `board_rect`) with the page at `page_rect`."""
    key = (tuple(board_rect.size), tuple(page_rect.move(-board_rect.x, -board_rect.y)))
    if key not in _cache:
        if len(_cache) > 8:  # a few window sizes' worth; resizes make new ones
            _cache.clear()
        _cache[key] = _render(board_rect.size, page_rect.move(-board_rect.x, -board_rect.y))
    surface.blit(_cache[key], board_rect.topleft)


def _render(size, page):
    width, height = size
    board = pygame.Surface(size, pygame.SRCALPHA)
    frame = max(4, min(width, height) // 28)
    _planks(board, pygame.Rect(0, 0, width, height).inflate(-2 * frame, -2 * frame))
    _frame(board, frame)
    _page(board, page)
    _hang(board, page, frame)
    return board


def _planks(board, area):
    """Horizontal planks with seams, grain lines and the odd knot. Seeded, so
    the same size always draws the same wood."""
    rng = random.Random(1987)
    plank_h = max(10, area.height // 14)
    y, i = area.top, 0
    while y < area.bottom:
        h = min(plank_h + rng.randint(-2, 2), area.bottom - y)
        plank = pygame.Rect(area.left, y, area.width, h)
        board.fill(PLANKS[i % len(PLANKS)], plank)
        for _ in range(max(2, area.width // 40)):
            gy = rng.randint(plank.top + 2, max(plank.top + 2, plank.bottom - 3))
            gx = rng.randint(plank.left, plank.right - 1)
            length = rng.randint(area.width // 8, area.width // 3)
            pygame.draw.line(board, GRAIN, (gx, gy), (min(plank.right - 1, gx + length), gy))
        if rng.random() < 0.35 and h > 8:
            kx = rng.randint(plank.left + 6, max(plank.left + 6, plank.right - 12))
            pygame.draw.ellipse(board, KNOT, (kx, plank.top + h // 4, max(6, h), max(4, h // 2)))
        board.fill(SEAM, (area.left, plank.bottom - 2, area.width, 2))
        y, i = y + h, i + 1


def _frame(board, frame):
    rect = board.get_rect()
    pygame.draw.rect(board, FRAME, rect, frame)
    pygame.draw.rect(board, FRAME_LIGHT, rect, 1)
    pygame.draw.rect(board, FRAME_DARK, rect.inflate(-2 * frame + 2, -2 * frame + 2), 1)


def _page(board, page):
    """Drop shadow, then the sheet: shaded margins around a flat centre."""
    shadow = pygame.Surface(page.size, pygame.SRCALPHA)
    shadow.fill(SHADOW)
    offset = max(3, page.width // 60)
    board.blit(shadow, page.move(offset, offset))
    board.fill(palette.PAGE_EDGE, page)
    margin = max(3, page.width // 40)
    steps = 4
    for step in range(1, steps + 1):
        t = step / steps
        shade = tuple(round(e + (p - e) * t) for e, p in zip(palette.PAGE_EDGE, palette.PAGE))
        inset = round(margin * step / steps)
        board.fill(shade, page.inflate(-2 * inset, -2 * inset))
    pygame.draw.rect(board, (178, 158, 118), page, 1)


def _hang(board, page, frame):
    """A nail centred above the page, a string from it to both top corners."""
    nail = (page.centerx, max(frame + 4, page.top - (page.top - frame) * 2 // 3))
    radius = max(3, frame // 2 + 1)
    for corner in (
        (page.left + radius * 2, page.top + 1),
        (page.right - radius * 2, page.top + 1),
    ):
        pygame.draw.line(board, STRING, nail, corner, max(1, radius // 2))
        pygame.draw.circle(board, NAIL_DARK, corner, max(2, radius // 2))  # eyelets
    pygame.draw.circle(board, NAIL_DARK, (nail[0] + 1, nail[1] + 1), radius)
    pygame.draw.circle(board, NAIL, nail, radius)
    pygame.draw.circle(
        board, NAIL_LIGHT, (nail[0] - radius // 3, nail[1] - radius // 3), max(1, radius // 3)
    )
