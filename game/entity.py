"""Entities (spec §4).

Monster, Item and the other subtypes live in game/monster.py, game/item.py
and friends; this file holds the base Entity and the Player.
"""

from typing import TYPE_CHECKING

from game.tiles import is_walkable

if TYPE_CHECKING:
    from game.item import Item


# What kind of thing an entity is on the map (game/level.py has the rules),
# and the order the renderer paints them in, lowest first: a creature is
# always drawn over a chest, a chest over a pile.
PILE = 0  # gold and arrows on the floor: never in anything's way
FIXTURE = 1  # chests and shrines: the player uses one by walking into it
CREATURE = 2  # the player, monsters, the shopkeeper: one to a tile


class Entity:
    layer = CREATURE

    def __init__(self, x, y, char, color=0, name=''):
        self.x, self.y = x, y
        self.char = char
        self.color = color
        self.name = name

    def move(self, dx, dy, game_map):
        """Move by (dx, dy) if the destination is walkable.

        No bounds check — the map border must stay solid wall. See CLAUDE.md.
        """
        nx, ny = self.x + dx, self.y + dy
        if is_walkable(game_map, nx, ny):
            self.x, self.y = nx, ny

    def distance_to(self, other):
        """Chebyshev distance — a cheap "is that thing near me" radius check.

        Deliberately *not* used to decide whether an attack can land; see
        is_adjacent for why the two differ.
        """
        return max(abs(self.x - other.x), abs(self.y - other.y))

    def is_adjacent(self, other):
        """True if `other` is orthogonally adjacent — the only squares an
        attack can cross.

        Orthogonal (Manhattan == 1), not Chebyshev, because everything that
        moves in this game moves in the four cardinal directions: the player
        via state.MOVE_DELTAS, monsters via monster.ORTHOGONAL_STEPS. A
        diagonal neighbour is a tile the player cannot bump-attack, so
        letting a monster strike from there gave it a free hit the player had
        no way to answer.
        """
        return abs(self.x - other.x) + abs(self.y - other.y) == 1


class Player(Entity):
    """The player: an Entity plus the stats GameState fills in.

    The defaults here are placeholders; GameState sets them from CLASS_STATS
    straight after construction.
    """

    def __init__(self, x, y, char='@', color=1, name='you'):
        super().__init__(x, y, char, color=color, name=name)
        self.char_class = 'warrior'
        self.hp = self.max_hp = 1
        self.base_power = self.power = 0
        self.defense = 0
        self.weapon: Item | None = None
        self.armor: Item | None = None
        self.items_used: list[
            str
        ] = []  # names of everything drunk or equipped this run, newest last (a history, not a bag)
        # Shrine boons taken this run (game/shrine.py BOONS keys), oldest
        # first. Their effects are derived from this list, never stored.
        self.boons: list[str] = []
        # Arrows in the quiver (game/quiver.py): an archer's starts at
        # QUIVER_CAPACITY; None means no quiver (a warrior).
        self.quiver: int | None = None
        # Gold carried (game/gold.py): picked up from piles and gold chests.
        self.gold = 0
        self.alive = True
