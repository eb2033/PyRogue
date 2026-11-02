"""The shop: every SHOP_INTERVAL-th floor has one, in its own room. Standard
library only.

A shopkeeper (SHOPKEEPER_CHAR) stands at the centre of a room that is not
rooms[0] (the start), not the last room (the stairs) and not the boss room;
nothing else spawns in that room. Walking into the shopkeeper opens the shop
(GameState.shop_open); the player buys with GameState.buy and can leave and
come back as often as they like while on the floor.

A shop always has five offers, in key order: two weapons of different kinds
for the player's class, two half-strength boons (shrine.half_boon: the
benefit at half, no cost) and a full heal. A weapon's rarity rolls like a
chest's (item.roll_rarity) and is then capped (rarity_cap) -- the shop never
sells Epic. Bought weapons and boons are gone; the heal stays, priced live by
the HP the player is missing.
"""

import random
from dataclasses import dataclass

from game.entity import Entity
from game.item import RARITIES, Item, class_weapons, roll_rarity
from game.rng import Rng
from game.shrine import HALF_BOONS, Boon

SHOP_INTERVAL = 4
SHOPKEEPER_CHAR = 'P'
SHOPKEEPER_COLOR = 7

# Price per floor, before the multipliers below.
GOLD_PER_FLOOR = 10
WEAPON_PRICE_FACTOR = 3
WEAPON_PRICE_MULT = {'common': 0.5, 'uncommon': 1, 'rare': 4 / 3}
BOON_PRICE_FACTOR = 1.33
HEAL_PRICE_PER_HP = 5
# The best rarity the shop sells: below CAP_RAISE_DEPTH, then from it on.
SHALLOW_RARITY_CAP = 'uncommon'
DEEP_RARITY_CAP = 'rare'
CAP_RAISE_DEPTH = 8


def is_shop_level(depth: int) -> bool:
    """True on floors 4, 8, 12, ..."""
    return depth % SHOP_INTERVAL == 0


def weapon_price(depth: int, rarity: str) -> int:
    return round(depth * GOLD_PER_FLOOR * WEAPON_PRICE_FACTOR * WEAPON_PRICE_MULT[rarity])


def boon_price(depth: int) -> int:
    return round(depth * GOLD_PER_FLOOR * BOON_PRICE_FACTOR)


def heal_price(player) -> int:
    """A full heal: HEAL_PRICE_PER_HP for every HP missing."""
    return (player.max_hp - player.hp) * HEAL_PRICE_PER_HP


def rarity_cap(depth: int) -> str:
    return SHALLOW_RARITY_CAP if depth < CAP_RAISE_DEPTH else DEEP_RARITY_CAP


def cap_rarity(rarity: str, depth: int) -> str:
    """`rarity`, or rarity_cap(depth) if that is lower."""
    cap = rarity_cap(depth)
    return rarity if RARITIES.index(rarity) <= RARITIES.index(cap) else cap


class Shopkeeper(Entity):
    """Stands still at the shop room's centre. Not a Monster: never moves,
    never fights, can't be shot (arrows fly past). Walking into it opens the
    shop."""

    def __init__(self, x, y):
        super().__init__(x, y, SHOPKEEPER_CHAR, color=SHOPKEEPER_COLOR, name='shopkeeper')
        self.alive = True


@dataclass
class Offer:
    kind: str  # 'weapon' | 'boon' | 'heal'
    item: Item | None
    boon: Boon | None
    price: int  # the heal's is ignored: heal_price(player) is used live
    sold: bool = False


@dataclass
class Shop:
    offers: list[Offer]  # weapon, weapon, boon, boon, heal


def roll_shop(depth: int, char_class: str, rng: Rng = random) -> Shop:
    """A floor's shop. Holding a boon (full or half) doesn't keep its half
    version off the shelf, so nothing the player holds is looked at."""
    offers = []
    for kind in rng.sample(class_weapons(char_class), 2):
        rarity = cap_rarity(roll_rarity(depth, rng), depth)
        offers.append(Offer('weapon', Item(0, 0, kind, rarity), None, weapon_price(depth, rarity)))
    for boon in rng.sample(list(HALF_BOONS.values()), 2):
        offers.append(Offer('boon', None, boon, boon_price(depth)))
    offers.append(Offer('heal', None, None, 0))
    return Shop(offers)


def pick_shop_room(rooms, boss_room, rng: Rng = random):
    """A random room that is not rooms[0], not rooms[-1] (the stairs) and not
    `boss_room`; None if there is none."""
    candidates = [room for room in rooms[1:-1] if room is not boss_room]
    return rng.choice(candidates) if candidates else None
