"""What happened in a fight, as plain data, for whoever draws it.

GameState.attack() records a `Hit` for every blow -- melee, arrow, or a monster
swinging back -- in `GameState.combat_events`. A renderer can stage those (an
impact flash, a combat camera) without GameState knowing anything about
animation. Each hit carries a serial number that only ever grows, so a
renderer that draws the same round several times can tell which hits it has
already shown without mutating the state.
"""

from collections import namedtuple

# (x, y) is where the defender stood when hit -- still valid once a killed
# monster has been removed from the entity list.
Hit = namedtuple('Hit', 'serial attacker defender damage killed x y')
