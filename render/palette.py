"""RGB colours for the pygame front end. Owned by WS-A (desktop_build_plan.md §5).

Mirrors curses_render.COLOR_PAIRS: the keys are the same Entity.color ints the
game stores (pair 1 player, 2 red, 3 gear chest, 4-7 the gear-rarity ladder
from game/item.py's RARITY_COLOR, 8 potion chest), so game/ never needs to know about RGB.
No pygame import -- plain tuples, usable from any module.
"""

COLORS = {
    1: (255, 215, 0),  # player (yellow)
    2: (220, 60, 60),  # red: low HP, death
    3: (0, 200, 200),  # chest (cyan)
    4: (70, 200, 70),  # uncommon (green)
    5: (90, 130, 255),  # rare (blue)
    6: (205, 90, 205),  # epic (magenta)
    7: (230, 230, 230),  # common (white)
    8: (255, 120, 190),  # potion chest (pink)
}
PLAYER = COLORS[1]
DANGER = COLORS[2]

TEXT = (200, 200, 200)
VISIBLE = (235, 235, 235)  # curses A_BOLD
SEEN = (90, 90, 90)  # curses A_DIM -- remembered, not currently in view
BACKGROUND = (0, 0, 0)


# The side panel is a parchment page on a wooden noticeboard
# (render/noticeboard.py): text there is ink, not light-on-black, so the
# rarity ladder has darker twins that read on paper. Same Entity.color keys.
PAGE = (236, 224, 194)  # flat under the text, so ink is easy to tell apart
PAGE_EDGE = (214, 196, 156)
INK = (52, 38, 26)
INK_DANGER = (178, 34, 30)
INK_COLORS = {
    2: INK_DANGER,
    3: (20, 110, 120),  # cyan
    4: (34, 118, 46),  # uncommon (green)
    5: (36, 76, 176),  # rare (blue)
    6: (136, 42, 156),  # epic (magenta)
    7: INK,  # common: plain ink, as white would vanish on paper
}
HP_BAR_FILL = (58, 140, 62)
HP_BAR_TRACK = (204, 186, 148)


def ink(index, default=INK):
    """Ink colour for an Entity.color int, for text on the panel's page."""
    return INK_COLORS.get(index, default)


def color(index: int, default: tuple[int, int, int] = TEXT) -> tuple[int, int, int]:
    """RGB for an Entity.color int, falling back for unknown values."""
    return COLORS.get(index, default)


def brighten(rgb, amount=0.35):
    """`rgb` moved `amount` of the way toward white -- the boss highlight,
    standing in for curses' A_BOLD on top of the pair's colour."""
    return tuple(round(c + (255 - c) * amount) for c in rgb)
