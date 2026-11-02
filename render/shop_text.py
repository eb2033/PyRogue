"""What the shop screen says. Standard library only.

The shop (game/shop.py) has five offers, numbered 1-5 in key order. Each is
two lines: a name line and a detail line ending in the price. Geometry (in
pixels) is render/screens.py's business.
"""

from game.shop import heal_price
from render import choice

TITLE = 'Shop'
HINT = 'press 1-5 to buy; space leaves'
SOLD = 'sold'
FULL_HP = '(at full HP)'


def gold_line(player):
    return f'Your gold: {player.gold}'


def price_of(offer, player):
    """What the offer costs now (the heal's price follows the player's HP)."""
    return heal_price(player) if offer.kind == 'heal' else offer.price


def price_text(offer, player):
    """The price at the end of the offer's detail line ('120 gold'), or None
    when the line shows none (sold, or the heal at full HP)."""
    if offer.sold or (offer.kind == 'heal' and player.hp >= player.max_hp):
        return None
    return f'{price_of(offer, player)} gold'


def offer_lines(number, offer, player):
    """An offer's two lines: '[n] name' and its detail, which ends in
    price_text when there is one."""
    price = price_text(offer, player)
    if offer.kind == 'weapon':
        item = offer.item
        first = f'[{number}] {item.name} ({choice.rarity_text(item)})'
        detail = f'{choice.stat_text(item)}   {price}'
    elif offer.kind == 'boon':
        first = f'[{number}] {offer.boon.name}'
        detail = f'{offer.boon.benefit}   {price}'
    else:
        first = f'[{number}] Heal to full'
        detail = FULL_HP if price is None else price
    return [first, SOLD if offer.sold else detail]


def affordable(offer, player):
    """True if the player could buy it right now (not sold, enough gold, and
    for the heal, missing some HP)."""
    if offer.sold:
        return False
    if offer.kind == 'heal' and player.hp >= player.max_hp:
        return False
    return player.gold >= price_of(offer, player)
