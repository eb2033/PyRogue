"""What happened in a fight, as plain data, for whoever draws it.

GameState.attack() records a `Hit` for every blow -- melee, arrow, or a monster
swinging back -- in `GameState.combat_events`. A renderer can stage those (an
impact flash, a combat camera) without GameState knowing anything about
animation. Each hit carries a serial number that only ever grows, so a
renderer that draws the same round several times can tell which hits it has
already shown without mutating the state.

Every arrow also records a `Shot` in `GameState.shots` (same lifetime as
combat_events): the cells it flew through, so a renderer can draw it flying
and land it on each of its Hits.
"""

from collections import namedtuple

# (x, y) is where the defender stood when hit -- still valid once a killed
# monster has been removed from the entity list.
# `crit` is last and defaults to False so older positional constructions hold.
Hit = namedtuple('Hit', 'serial attacker defender damage killed x y crit')
Hit.__new__.__defaults__ = (False,)

# One arrow's flight (game/archery.py). `path` is the cells it passed through
# in order: the shooter's cell first, then every tile it entered, ending where
# it stopped (the last monster it hit, or the last free tile before a wall).
# A volley's side arrow goes from the shooter's cell straight to its first,
# diagonal, tile. `hits` are the Hits it made, in order; each one's (x, y) is
# on the path. `serial` comes from the same counter as Hit.serial and is taken
# before the arrow flies, so a Shot sorts before its own Hits.
Shot = namedtuple('Shot', 'serial path hits')
