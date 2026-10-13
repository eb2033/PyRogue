"""In-window menu screens and overlays. Owned by WS-D.

Paint-only: each function draws one frame onto a ui.Canvas. The event loop
that drives a menu (waiting for keys, moving the render.menu.Menu cursor) lives
in pygame_render.py, so these stay testable without input. Mouse hover/click
goes through option_at ("which option is at this pixel"), which that loop
calls; it shares paint_menu's geometry. Keyboard stays mandatory.
"""

import textwrap

import pygame

from render import palette

TITLE_OPTIONS = ['Start', 'Quit']
CLASS_OPTIONS = ['Warrior', 'Archer']
CLASS_DESCRIPTIONS = {
    'warrior': 'Melee. Walk into an enemy to hit it.',
    'archer': 'Ranged. WASD moves, arrow keys fire.',
}
MENU_HINT = 'up/down or w/s to choose, enter to select, q to quit'
GAME_OVER_TITLE = 'YOU DIED'
GAME_OVER_HINT = 'press q to quit'
GAME_OVER_SCALE = 4  # the title is this many times the map's font


def _menu_geometry(layout, options, banner_lines):
    """(banner top row, first option row). Option i is on row
    `options_top + 2 * i`; paint_menu and option_at both use this."""
    top = max(1, layout.rows // 2 - len(banner_lines) - len(options) - 2)
    return top, top + len(banner_lines) + 2


def _option_text(option, selected):
    return f'> {option} <' if selected else f'  {option}  '


def paint_menu(canvas, menu, banner_lines, descriptions=None):
    """A banner, the menu's options (selected one highlighted), and the
    selected option's description, laid out like the curses menu."""
    rows = canvas.layout.rows
    options = menu.options
    top, options_top = _menu_geometry(canvas.layout, options, banner_lines)
    for i, line in enumerate(banner_lines):
        canvas.put_str_centered(top + i, line, palette.PLAYER)

    for i, option in enumerate(options):
        if i == menu.index:
            canvas.put_str_centered(options_top + i * 2, _option_text(option, True),
                                    palette.BACKGROUND, palette.TEXT)
            description = (descriptions or {}).get(option.lower())
            if description:
                canvas.put_str_centered(options_top + len(options) * 2 + 1, description)
        else:
            canvas.put_str_centered(options_top + i * 2, _option_text(option, False))

    # A narrow grid (the panel stacked under the map) can't fit the hint on
    # one line: wrap it upwards from the usual row.
    hint = textwrap.wrap(MENU_HINT, max(1, canvas.layout.cols)) or ['']
    for i, line in enumerate(hint):
        canvas.put_str_centered(rows - 1 - len(hint) + i, line)


def option_at(layout, menu, banner_lines, pixel):
    """Index of the menu option under window pixel `pixel`, or None.

    Hit-testing for mouse hover/click; pygame_render's _run_menu calls it with
    the same `layout`, `menu` and `banner_lines` it painted with. An option's
    hit area is exactly its own text row (the blank rows between options hit
    nothing), across the columns the *widest* option's text spans as
    paint_menu centres it -- so every option has the same, generous width,
    and the mouse need not land on the letters of a short one.
    """
    options = menu.options
    if not options:
        return None
    _, options_top = _menu_geometry(layout, options, banner_lines)
    px, py = pixel
    if py < layout.origin_y:
        return None
    row = (py - layout.origin_y) // layout.cell_h
    index, odd = divmod(row - options_top, 2)
    if odd or not 0 <= index < len(options) or row >= layout.rows:
        return None
    # Same centring and clipping as Canvas.put_str_centered / put_str.
    width = max(len(_option_text(option, False)) for option in options)
    left = max(0, (layout.cols - width) // 2)
    right = min(layout.cols, left + width)
    x0 = layout.origin_x + left * layout.cell_w
    x1 = layout.origin_x + right * layout.cell_w
    return index if x0 <= px < x1 else None


def game_over_fonts(layout):
    """(title font, hint font). The title is GAME_OVER_SCALE times the map's
    font, shrunk back toward it if it wouldn't fit across the map."""
    room = layout.map_rect().width - 2 * layout.cell_w
    size = layout.font_size * GAME_OVER_SCALE
    while size > layout.font_size and layout._font(size).size(GAME_OVER_TITLE)[0] > room:
        size -= 1
    return layout._font(size), layout.font


def game_over_rect(layout):
    """Pixel rect of the game-over banner: a box centred across the top of
    the map, holding the big title and the hint under it."""
    title_font, hint_font = game_over_fonts(layout)
    text_w = max(title_font.size(GAME_OVER_TITLE)[0], hint_font.size(GAME_OVER_HINT)[0])
    text_h = title_font.get_linesize() + hint_font.get_linesize()
    box = pygame.Rect(0, 0, text_w + 2 * layout.cell_w, text_h + layout.cell_h)
    area = layout.map_rect()
    box.centerx = area.centerx
    box.top = area.top + layout.cell_h // 2
    return box


def paint_game_over(canvas):
    """Overlay drawn on top of the final game frame: the title and hint in a
    framed box placed by game_over_rect."""
    layout = canvas.layout
    box = game_over_rect(layout)
    canvas.surface.fill(palette.BACKGROUND, box)
    pygame.draw.rect(canvas.surface, palette.DANGER, box, max(1, layout.cell_h // 12))
    title_font, hint_font = game_over_fonts(layout)
    title = title_font.render(GAME_OVER_TITLE, True, palette.DANGER)
    hint = hint_font.render(GAME_OVER_HINT, True, palette.DANGER)
    top = box.top + layout.cell_h // 2
    canvas.surface.blit(title, title.get_rect(centerx=box.centerx, top=top))
    top += title_font.get_linesize()
    canvas.surface.blit(hint, hint.get_rect(centerx=box.centerx, top=top))