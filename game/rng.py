"""The type of the `rng` parameters threaded through generation, loot,
monster AI and combat.

A running game passes its own generator, GameState.rng (a `random.Random`
built from GameState's `seed`), to every one of them, so the same seed and
the same actions replay the same game and the global `random` module is
never touched. The module functions still default to the `random` module
itself, for direct callers (tests, tools); tests pass a seeded
`random.Random` for reproducible rolls. Both offer the same methods.
"""

import random
from types import ModuleType

Rng = random.Random | ModuleType
