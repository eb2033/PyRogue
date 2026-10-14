"""What the "choose one of three" chest screen says. Standard library only.

Both renderers draw a pending chest choice (GameState.pending_choice) from the
text here, so the terminal and the window show the same three cards, with the
same numbers, in the same order. Geometry is each renderer's own business
(curses works in terminal cells, the window in pixels); `grid_layout` is the
cell version, which curses uses.
"""

from game.item import GEAR_SLOTS
from render.base import Action

TITLE = 'Choose one'
HINT = 'press 1, 2 or 3'
# Action -> index into pending_choice; GameState.handle_action uses the same order.
CHOOSE_ACTIONS = (Action.CHOOSE_1, Action.CHOOSE_2, Action.CHOOSE_3)

JUNK_STAT = 'nothing useful'
JUNK_RARITY = 'junk'


def _effect_text(item):
    """The weapon type's special effect, or None for a plain weapon/armor."""
    if item.max_hp_bonus:
        return f'+{item.max_hp_bonus} HP'
    if item.strikes > 1:
        return 'strikes twice' if item.strikes == 2 else f'strikes {item.strikes}x'
    if item.cleave:
        return 'hits a 2nd adjacent foe'
    if item.defense_bonus:
        return f'+{item.defense_bonus} defence'
    if item.crit_bonus:
        return f'+{round(item.crit_bonus * 100)}% crit'
    if item.reach > 1:
        return f'reach {item.reach}'
    return None


def stat_text(item):
    """'+N damage' (with the weapon type's effect after a comma, e.g.
    '-1 damage, strikes twice') / '+N defence', or 'nothing useful' for junk.
    Every kind in the weapon slot reads 'damage'; armor reads 'defence'."""
    slot = GEAR_SLOTS.get(item.kind)
    if slot is None or item.bonus is None:
        return JUNK_STAT
    if slot == 'armor':
        return f'+{item.bonus} defence'
    effect = _effect_text(item)
    damage = f'{item.bonus:+d} damage'
    return damage if effect is None else f'{damage}, {effect}'


def rarity_text(item):
    return item.rarity or JUNK_RARITY


def card_lines(number, item):
    """A card's lines, top to bottom, for a card drawn side by side:
    its number, the name, the rarity, the stat."""
    return [f'[{number}]', item.name, rarity_text(item), stat_text(item)]


def compact_lines(number, item):
    """The same content in two lines, for cards stacked in a narrow area."""
    return [f'{number}  {item.name}', f'   {rarity_text(item)}, {stat_text(item)}']


def cards(items):
    """(number, item) for each offer, numbered from 1 in pending_choice order."""
    return list(enumerate(items, start=1))


def tight_line(number, item):
    """All of a card on one line, for a terminal too short for compact cards."""
    return f'{number} {item.name} ({rarity_text(item)}, {stat_text(item)})'


# -- cell geometry (curses) --------------------------------------------------

CARD_GAP = 1
# Modes, roomiest first: bordered cards side by side, two-line cards stacked,
# one line per card with no blank rows.
ACROSS, COMPACT, TIGHT = 'across', 'compact', 'tight'
LINES = {ACROSS: card_lines, COMPACT: compact_lines, TIGHT: lambda n, item: [tight_line(n, item)]}


def grid_layout(items, cols, rows):
    """Cell geometry of the choice box inside a `cols x rows` area at (0, 0).

    Returns (box, card_rects, mode): rects are (x, y, w, h) in cells, `mode`
    one of ACROSS / COMPACT / TIGHT, and LINES[mode](number, item) is the text
    of a card. The roomiest mode that fits is used (TIGHT if none does); the
    box is centred in the area and clipped to it, so a tiny area gives a
    cut-down box -- callers still truncate text to what fits. Rows inside the
    box: the border, the title, (a blank,) the cards, (a blank,) the hint,
    the border.
    """
    numbered = cards(items)

    def widest(mode):
        return max((len(line) for n, item in numbered for line in LINES[mode](n, item)),
                   default=0)

    card_w = widest(ACROSS) + 4                     # border + a space each side
    card_h = len(card_lines(1, items[0])) + 2 if items else 2
    frame_w = max(len(TITLE), len(HINT))
    sizes = {
        ACROSS: (max(len(items) * card_w + (len(items) - 1) * CARD_GAP, frame_w) + 4,
                 card_h + 6),
        COMPACT: (max(widest(COMPACT), frame_w) + 4, 2 * len(items) + 6),
        TIGHT: (max(widest(TIGHT), frame_w) + 4, len(items) + 4),
    }
    mode = next((m for m in (ACROSS, COMPACT) if sizes[m][0] <= cols and sizes[m][1] <= rows),
                TIGHT)
    box_w, box_h = sizes[mode]
    box_w, box_h = max(1, min(box_w, cols)), max(1, min(box_h, rows))
    box_x = max(0, (cols - box_w) // 2)
    box_y = max(0, (rows - box_h) // 2)

    inner_w = max(0, box_w - 4)
    rects = []
    for i in range(len(items)):
        if mode == ACROSS:
            rects.append((box_x + 2 + i * (card_w + CARD_GAP), box_y + 3, card_w, card_h))
        elif mode == COMPACT:
            rects.append((box_x + 2, box_y + 3 + 2 * i, inner_w, 2))
        else:
            rects.append((box_x + 2, box_y + 2 + i, inner_w, 1))
    return (box_x, box_y, box_w, box_h), rects, mode
