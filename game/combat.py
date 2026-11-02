"""What happened in a round, as plain data, for whoever draws or plays it.

GameState keeps one ordered stream of records, `GameState.events`, oldest
first: a `Hit` for every melee blow (the player's or a monster's), a `Shot`
for every shot (player or goblin archer), a `Parry` for every blow an armed
parry nullified, and a game.sound.SoundEvent for every sound hook. It is
cleared when the player acts. Every record carries a `serial` from one
counter that only ever grows (across rounds and levels), and the list is
always in serial order -- so a renderer that draws the same round several
times keeps a cursor (the last serial it handled) and reads only what is new
(`GameState.events_since`), without mutating the state. A new GameState
starts the counter again, so a renderer resets its cursors on a restart.

Records refer to each other instead of being matched up by the reader:

- A `Shot` owns the Hits its arrows made (in `arrows[i].hits`); they are not
  in the stream themselves. `GameState.hits()` lists every Hit of the round,
  stream and shots alike, in serial order.
- A `Parry` names its riposte's Hit (`riposte`), which follows it in the
  stream.
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
# on the path.
Arrow = namedtuple('Arrow', 'path hits')


class Shot(namedtuple('Shot', 'serial arrows')):
    """One shot: every arrow loosed by one shoot action, all leaving the
    shooter's cell together. `arrows` is a tuple of Arrows, the aim arrow
    first -- one element for every bow but the volley bow, whose extras
    follow it. Its serial is taken before any arrow flies, so it is lower
    than every Hit it owns."""

    __slots__ = ()

    @property
    def path(self):
        """The aim arrow's path (arrows[0]), for readers that fly one."""
        return self.arrows[0].path

    @property
    def hits(self):
        """The aim arrow's Hits (arrows[0])."""
        return self.arrows[0].hits

    def all_hits(self):
        """Every Hit this shot made, in serial order."""
        return sorted((hit for arrow in self.arrows for hit in arrow.hits), key=_serial)


def _serial(event):
    return event.serial


# A parried blow (game.fight.monster_melee): `monster` swung at `player`, who
# stood at (x, y), and the parry nullified it (no Hit for the blow).
# `riposte` is the Hit of the blow the parry returned to the monster (or
# None); it follows the Parry in the stream.
Parry = namedtuple('Parry', 'serial monster player x y riposte')
