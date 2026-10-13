"""In-window menu screens and overlays. Owned by WS-D.

Paint-only: each function draws one frame onto a ui.Canvas. The event loop
that drives a menu (waiting for keys, moving the render.menu.Menu cursor) lives
in pygame_render.py, so these stay testable without input. WS-D adds mouse
hover/click by extending this contract with hit-testing (e.g. "which option is
at this pixel"), agreed with WS-A -- keyboard stays mandatory.

P0 state: the spike's menus moved here unchanged.
"""

from render import palette

TITLE_OPTIONS = ['Start', 'Quit']
CLASS_OPTIONS = ['Warrior', 'Archer']
CLASS_DESCRIPTIONS = {
    'warrior': 'Melee. Walk into an enemy to hit it.',
    'archer': 'Ranged. WASD moves, arrow keys fire.',
}
MENU_HINT = 'up/down or w/s to choose, enter to select, q to quit'
GAME_OVER_TEXT = 'YOU DIED -- press q to quit'


def paint_menu(canvas, menu, banner_lines, descriptions=None):
    """A banner, the menu's options (selected one highlighted), and the
    selected option's description, laid out like the curses menu."""
    rows = canvas.layout.rows
    options = menu.options
    top = max(1, rows // 2 - len(banner_lines) - len(options) - 2)
    for i, line in enumerate(banner_lines):
        canvas.put_str_centered(top + i, line, palette.PLAYER)

    options_top = top + len(banner_lines) + 2
    for i, option in enumerate(options):
        if i == menu.index:
            canvas.put_str_centered(options_top + i * 2, f'> {option} <',
                                    palette.BACKGROUND, palette.TEXT)
            description = (descriptions or {}).get(option.lower())
            if description:
                canvas.put_str_centered(options_top + len(options) * 2 + 1, description)
        else:
            canvas.put_str_centered(options_top + i * 2, f'  {option}  ')

    canvas.put_str_centered(rows - 2, MENU_HINT)


def option_at(layout, menu, banner_lines, pixel):
    """Index of the menu option under window pixel `pixel`, or None.

    Hit-testing for mouse hover/click (WS-D owns it; pygame_render's
    _run_menu calls it). Must agree with paint_menu's geometry for the same
    `layout`, `menu` and `banner_lines`. P3 stub: no option is ever hit, so
    the menus stay keyboard-only until WS-D fills this in.
    """
    return None


def paint_game_over(canvas, state):
    """Overlay drawn on top of the final game frame, centred on the map."""
    text = canvas.text_surface(GAME_OVER_TEXT, palette.DANGER, palette.BACKGROUND)
    canvas.surface.blit(text, text.get_rect(center=canvas.layout.map_rect().center))
