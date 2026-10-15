"""The type of the `rng` parameters threaded through generation and loot.

Callers pass either the `random` module itself (the default, so
`random.seed` still governs it) or a seeded `random.Random` -- the tests do
the latter for reproducible rolls. Both offer the same methods.
"""

import random
from types import ModuleType

Rng = random.Random | ModuleType
