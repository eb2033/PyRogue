"""Tile characters and the walkability rule.

Walkability is a char comparison, not a tile-type system (spec §3).
"""

WALL = '#'
FLOOR = '.'
DOOR = '+'
STAIRS_DOWN = '>'


def is_walkable(game_map, x, y):
    """True if (x, y) can be stood on. Note the map is indexed [y][x]."""
    return game_map[y][x] != WALL


def is_transparent(game_map, x, y):
    """True if (x, y) does not block sight.

    Used by the shadowcasting FOV in fov.py. Doors block sight the same as
    walls (they still count as walkable via is_walkable) so a room stays
    hidden from a corridor, and from its neighbors, until the player is
    actually standing in the doorway or past it.
    """
    return game_map[y][x] not in (WALL, DOOR)
