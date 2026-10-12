"""RGB colours for the pygame front end. Owned by WS-A (desktop_build_plan.md §5).

Mirrors curses_render.COLOR_PAIRS: the keys are the same Entity.color ints the
game stores (pair 1 player, 2 red, 3 chest, 4-7 the gear-rarity ladder from
game/item.py's RARITY_COLOR), so game/ never needs to know about RGB.
No pygame import -- plain tuples, usable from any module.
"""

COLORS = {
    1: (255, 215, 0),     # player (yellow)
    2: (220, 60, 60),     # red: low HP, death
    3: (0, 200, 200),     # chest (cyan)
    4: (70, 200, 70),     # uncommon (green)
    5: (90, 130, 255),    # rare (blue)
    6: (205, 90, 205),    # epic (magenta)
    7: (230, 230, 230),   # common (white)
}
PLAYER = COLORS[1]
DANGER = COLORS[2]

TEXT = (200, 200, 200)
VISIBLE = (235, 235, 235)   # curses A_BOLD
SEEN = (90, 90, 90)         # curses A_DIM -- remembered, not currently in view
BACKGROUND = (0, 0, 0)


def color(index, default=TEXT):
    """RGB for an Entity.color int, falling back for unknown values."""
    return COLORS.get(index, default)


def brighten(rgb, amount=0.35):
    """`rgb` moved `amount` of the way toward white -- the boss highlight,
    standing in for curses' A_BOLD on top of the pair's colour."""
    return tuple(round(c + (255 - c) * amount) for c in rgb)
