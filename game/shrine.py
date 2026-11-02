"""Shrines and the boons they grant. Standard library only.

A shrine (SHRINE_CHAR on the map) turns up on about SHRINE_CHANCE of the
floors that are not boss floors, at most one per floor, in a random room
other than rooms[0] (the player's start), never on the stairs or a chest.
Stepping onto it offers BOONS_OFFERED different boons as a choice (the same
choice screen a gear chest uses -- GameState.pending_choice); the player may
take one or skip, and the shrine is used up and removed from the map either way.

A boon is a bargain: every one has a benefit AND a cost, and they trade along
different axes so none is strictly better than another. The player keeps the
boons taken (Player.boons, a list of BOONS keys) for the rest of the run.
Their effects are never stored as stat changes, except max HP: power,
defence, crit chance, the potion belt's size and the potion heal multiplier
are recomputed from Player.boons wherever those stats are derived
(item.gear_power, item.gear_defense, state.crit_chance, item.belt_capacity,
item.potion_heal), so a boon can never apply twice. Max HP, like a War Axe's
bonus, is a running total: a boon's max_hp is added once, when it is taken
(GameState.take_boon), and from then on is part of max_hp.
"""

import math
import random
from dataclasses import dataclass, replace

from game.entity import FIXTURE, Entity
from game.level import free_tiles
from game.monster import is_boss_level
from game.rng import Rng

SHRINE_CHAR = '_'  # an altar, as in NetHack and DCSS
SHRINE_COLOR = 5  # blue, like the glowing orb its tile shows
# The placement rule: chance per non-boss floor; never on boss floors.
SHRINE_CHANCE = 0.4
SHRINE_ON_BOSS_FLOORS = False
BOONS_OFFERED = 3
BOON_COLOR = SHRINE_COLOR  # the ink the boon cards are drawn in


@dataclass(frozen=True)
class Boon:
    """One bargain. `benefit` and `cost` are the card's two short lines; the
    numbers below them are the effects (zero / 1.0 when a boon has none)."""

    key: str
    name: str
    short: str  # the panel's one-word label
    benefit: str
    cost: str
    power: int = 0
    max_hp: int = 0
    defense: int = 0
    crit: float = 0.0
    belt: int = 0
    heal: float = 1.0  # multiplies what every potion heals
    color: int = BOON_COLOR


_TABLE = (
    Boon('blood_pact', 'Blood pact', 'Blood', '+3 power', '-15 max HP', power=3, max_hp=-15),
    Boon('iron_skin', 'Iron skin', 'Iron', '+2 defence', '-25% potion heal', defense=2, heal=0.75),
    Boon(
        'quick_hands',
        'Quick hands',
        'Quick',
        '+1 belt slot',
        '-25% potion heal',
        belt=1,
        heal=0.75,
    ),
    Boon('keen_eye', 'Keen eye', 'Keen', '+10% crit', '-10 max HP', crit=0.10, max_hp=-10),
    Boon('stone_heart', 'Stone heart', 'Stone', '+15 max HP', '-1 power', max_hp=15, power=-1),
)
BOONS = {boon.key: boon for boon in _TABLE}


def _half_int(value: int) -> int:
    """Half a positive number, rounded half up, at least 1; 0 for a cost."""
    return max(1, math.floor(value / 2 + 0.5)) if value > 0 else 0


def _benefit_text(boon: Boon) -> str:
    """A boon's benefit line, built from its positive effects."""
    parts = []
    if boon.power > 0:
        parts.append(f'+{boon.power} power')
    if boon.defense > 0:
        parts.append(f'+{boon.defense} defence')
    if boon.belt > 0:
        parts.append(f'+{boon.belt} belt slot' + ('s' if boon.belt > 1 else ''))
    if boon.crit > 0:
        parts.append(f'+{round(boon.crit * 100)}% crit')
    if boon.max_hp > 0:
        parts.append(f'+{boon.max_hp} max HP')
    if boon.heal > 1.0:
        parts.append(f'+{round((boon.heal - 1) * 100)}% potion heal')
    return ', '.join(parts)


def half_boon(boon: Boon) -> Boon:
    """The shop's lesser version of `boon`: every benefit halved (rounded
    half up, at least 1; crit halved exactly) and no cost at all. Its own key
    (`<key>_half`), so it is told apart from the full shrine boon and both can
    be held."""
    if boon.heal < 1.0:
        heal = 1.0  # a cost: dropped
    else:
        heal = 1.0 + (boon.heal - 1.0) / 2
    half = replace(
        boon,
        key=f'{boon.key}_half',
        name=f'Lesser {boon.name.lower()}',
        short=boon.short + '\u00bd',
        cost='',
        power=_half_int(boon.power),
        max_hp=_half_int(boon.max_hp),
        defense=_half_int(boon.defense),
        crit=boon.crit / 2 if boon.crit > 0 else 0.0,
        belt=_half_int(boon.belt),
        heal=heal,
    )
    return replace(half, benefit=_benefit_text(half))


# The shop's half-strength boons (game/shop.py). Shrines never offer them.
HALF_BOONS = {b.key: b for b in (half_boon(x) for x in _TABLE)}
ALL_BOONS = {**BOONS, **HALF_BOONS}


def held_boons(player):
    """The Boons `player` holds -- shrine and shop ones -- in the order taken
    (unknown keys skipped)."""
    return [ALL_BOONS[key] for key in getattr(player, 'boons', ()) if key in ALL_BOONS]


def boon_total(player, field):
    """The sum of one additive effect (power, max_hp, defense, crit, belt)
    over every boon `player` holds. 0 for anyone without boons (monsters)."""
    return sum(getattr(boon, field) for boon in held_boons(player))


def heal_multiplier(player):
    """What potions heal is multiplied by: the product of the held boons'
    `heal` (two -25% boons give 0.5625)."""
    return math.prod(boon.heal for boon in held_boons(player))


def roll_boons(held=(), rng: Rng = random):
    """BOONS_OFFERED different Boons for a shrine. Boons the player already
    holds are left out while enough others remain, so a shrine rarely offers
    a repeat; once it can't, any boon may come up again (and stacks)."""
    fresh = [boon for boon in _TABLE if boon.key not in held]
    pool = fresh if len(fresh) >= BOONS_OFFERED else list(_TABLE)
    return rng.sample(pool, BOONS_OFFERED)


class Shrine(Entity):
    """A walkable altar. Not a Monster, not a Chest: GameState.shrine_at
    finds it, try_move_player visits it."""

    layer = FIXTURE

    def __init__(self, x, y):
        super().__init__(x, y, SHRINE_CHAR, color=SHRINE_COLOR, name='shrine')


def place_shrine(rooms, depth, occupied=(), boss_room=None, rng: Rng = random, exclude=()):
    """This floor's shrine, or None. Rolled with SHRINE_CHANCE; never on a
    boss floor (unless SHRINE_ON_BOSS_FLOORS), in rooms[0], in `boss_room`
    or in a room of `exclude` (the shop's), and never on a tile in
    `occupied` (the floor's shared occupancy set, game/level.py: the
    player, the shopkeeper, monsters, chests and the stairs)."""
    if is_boss_level(depth) and not SHRINE_ON_BOSS_FLOORS:
        return None
    if rng.random() >= SHRINE_CHANCE:
        return None
    candidates = [
        room
        for room in rooms[1:]
        if room is not boss_room and not any(room is ex for ex in exclude)
    ]
    rng.shuffle(candidates)
    for room in candidates:
        free = free_tiles(room, occupied)
        if free:
            return Shrine(*rng.choice(free))
    return None
