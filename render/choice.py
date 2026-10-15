"""What the "choose one of three" screen says. Standard library only.

The window draws a pending choice (GameState.pending_choice) from the text
here: three cards, numbered in pending_choice order. The offers are a chest's Items or a shrine's
Boons (game/shrine.py); every function here takes either, and a boon card
reads its name, its benefit and its cost where an item card reads its name,
rarity and stat. Geometry (in pixels) is render/screens.py's business.
"""

from game.item import GEAR_SLOTS
from game.shrine import Boon
from render.base import Action

TITLE = 'Choose one'
BOON_TITLE = 'Choose a boon'
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


def title(offers):
    """The box's title: BOON_TITLE for a shrine's boons, else TITLE."""
    return BOON_TITLE if offers and isinstance(offers[0], Boon) else TITLE


def stat_text(item):
    """'+N damage' (with the weapon type's effect after a comma, e.g.
    '-1 damage, strikes twice') / '+N defence' (leather adds ', N% dodge'),
    or 'nothing useful' for junk. Every kind in the weapon slot reads
    'damage'; armor reads 'defence'.
    For a boon: its cost (rarity_text gives its benefit)."""
    if isinstance(item, Boon):
        return item.cost
    slot = GEAR_SLOTS.get(item.kind)
    if slot is None or item.bonus is None:
        return JUNK_STAT
    if slot == 'armor':
        defence = f'+{item.bonus} defence'
        return f'{defence}, {item.dodge}% dodge' if item.dodge else defence
    effect = _effect_text(item)
    damage = f'{item.bonus:+d} damage'
    return damage if effect is None else f'{damage}, {effect}'


def rarity_text(item):
    """An item's rarity ('junk' for junk), or a boon's benefit."""
    if isinstance(item, Boon):
        return item.benefit
    return item.rarity or JUNK_RARITY


def card_lines(number, item):
    """A card's lines, top to bottom, for a card drawn side by side:
    its number, the name, the rarity, the stat (a boon: the number, the
    name, the benefit, the cost)."""
    return [f'[{number}]', item.name, rarity_text(item), stat_text(item)]


def compact_lines(number, item):
    """The same content in two lines, for cards stacked in a narrow area."""
    return [f'{number}  {item.name}', f'   {rarity_text(item)}, {stat_text(item)}']


def cards(items):
    """(number, item) for each offer, numbered from 1 in pending_choice order."""
    return list(enumerate(items, start=1))
