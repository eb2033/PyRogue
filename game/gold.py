"""Gold: the piles killed enemies leave behind and the chests that hold it.

A pile is picked up by walking onto its tile (GameState.pick_up_gold). What
a monster drops grows with how tough it is (its hit points and power, so
depth scaling and bosses are already in the numbers), +-20% either way. The
constants are tuned so floors 1-4 pay about 120 gold in all.
"""

import random

from game.entity import PILE, Entity
from game.rng import Rng

GOLD_CHAR = '$'
GOLD_COLOR = 1  # yellow

# Tuned by the balance simulation in tests/test_gold.py (BalanceTest): a
# full clear of floors 1-4 pays about 120 gold (measured 119.5-122.6 over
# seeds 1 and 7 at 150 runs, on both the 50x20 and the .env's 40x20 base, with
# terrain walls kept off the spawners and floor 4's shop room empty of
# monsters and chests), of which gold chests are 36-37% (15-40% wanted, so
# kills stay the main source). A floor-4 common weapon costs 60, an uncommon
# 120, a boon 53.
GOLD_PER_HP = 0.234
GOLD_PER_POWER = 0.609
BOSS_GOLD_MULT = 3
GOLD_CHEST_PER_DEPTH = 3.2
GOLD_SPREAD = 0.2  # drops and chests vary by up to this fraction either way
# A gold chest also holds this much more (inclusive range), on top of its
# depth-scaled, spread amount.
GOLD_CHEST_BONUS = (5, 10)
# At most one gold chest per floor, placed with this probability: more often
# than a gear chest (0.4), less often than a floor's potion chests (~1).
GOLD_CHEST_CHANCE_PER_FLOOR = 0.7


class GoldPile(Entity):
    """Gold on the floor: one pile per tile. Not an obstacle."""

    layer = PILE

    def __init__(self, x, y, amount: int):
        super().__init__(x, y, GOLD_CHAR, color=GOLD_COLOR, name='gold')
        self.kind = 'gold'
        self.amount = amount


def _spread(rng: Rng) -> float:
    return rng.uniform(1 - GOLD_SPREAD, 1 + GOLD_SPREAD)


def drop_amount(monster, rng: Rng = random) -> int:
    """The gold `monster` leaves when it dies."""
    base = GOLD_PER_HP * monster.max_hp + GOLD_PER_POWER * monster.power
    if getattr(monster, 'is_boss', False):
        base *= BOSS_GOLD_MULT
    return max(1, round(base * _spread(rng)))


def chest_amount(depth: int, rng: Rng = random) -> int:
    """The gold in a gold chest opened on floor `depth`."""
    scaled = max(1, round(GOLD_CHEST_PER_DEPTH * depth * _spread(rng)))
    return scaled + rng.randint(*GOLD_CHEST_BONUS)
