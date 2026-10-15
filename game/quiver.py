"""The archer's quiver and the arrows that lie on the floor.

An archer carries up to QUIVER_CAPACITY arrows (Player.quiver; a warrior's is
None: no quiver at all). Every shot spends one, and a shot is refused with
none left. The arrow is not lost: it lies where the shot ended, as an
ArrowPile, and walking onto the pile puts it back in the quiver. On top of
that the quiver restocks itself by one arrow every RESTOCK_TURNS player turns
(GameState.restock_progress counts them, 0..RESTOCK_TURNS).
"""

from game.entity import Entity

QUIVER_CAPACITY = 12
RESTOCK_TURNS = 3
ARROW_PILE_CHAR = ')'  # a NetHack-style weapon/ammo glyph; not yet tiled
ARROW_PILE_COLOR = 7


class ArrowPile(Entity):
    """Arrows on the floor: one pile per tile, `count` arrows in it. Not a
    chest and not an obstacle -- the player and monsters walk over it."""

    def __init__(self, x, y, count=1):
        super().__init__(x, y, ARROW_PILE_CHAR, color=ARROW_PILE_COLOR, name='arrows')
        self.kind = 'arrows'
        self.count = count
