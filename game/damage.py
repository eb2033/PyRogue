"""Pure damage-reduction helpers (standard library only)."""

import random

from game.rng import Rng

# Defense value that gives 50% reduction. The single tuning knob.
DEFENSE_K = 10


def reduction(defense, k=DEFENSE_K):
    """Fraction of damage removed by `defense`: defense / (defense + k)."""
    if defense <= 0:
        return 0.0
    denom = defense + k
    if denom <= 0:
        return 0.0
    return defense / denom


def mitigate(raw, defense, k=DEFENSE_K):
    """Damage after defense, as a float, never below 1.0."""
    return max(1.0, raw * (1 - reduction(defense, k)))


def round_damage(value, rng: Rng = random):
    """Probabilistic rounding that preserves the average."""
    floor = int(value // 1)
    frac = value - floor
    if frac > 0 and rng.random() < frac:
        return floor + 1
    return floor


def plain_round(value):
    """Plain rounding; a drop-in replacement for round_damage."""
    return int(round(value))
