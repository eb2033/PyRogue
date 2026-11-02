"""Who stands where, and what stops what: one model of tile occupancy.

Every rule about a tile being "in the way" lives in BLOCKERS below, keyed
by what is asking (the purpose), and every site asks blocking_at (or, for
monster AI that only gets a set of tiles, blocker_tiles). A tile is
described by tags: its terrain, and what kind of entity is on it.

Terrain tags: 'wall', 'door' (a closed door: walkable, blocks sight),
'empty door' (a door with no living monster in it), 'not floor' (anything
but plain '.', so walls, doors and the stairs). Entity tags: 'player',
'monster' (a living one), 'shopkeeper', 'fixture' (a chest or a shrine),
'pile' (gold or arrows). An entity's kind is its class's `layer`
(game/entity.py), plus who the state says is the player and the shopkeeper.

The rules, x = blocks:

    purpose        wall door empty  not   player monster shop- fixture pile
                             door  floor                keeper
    MONSTER_MOVE    x                       x      x      x
    MONSTER_SHOT    x    x                  x      x      x
    ARROW           x          x
    HOP             x    x                  x      x      x      x
    REACH           x    x                  x      x      x
    KNOCKBACK       x                       x      x      x
    SUMMON          x    x          x       x      x      x      x      x

- MONSTER_MOVE -- a monster's step (chase, wander, retreat; Monster.
  take_turn gets the entity part as `occupied`). Only creatures block
  creatures: a monster walks through doorways and onto chests, shrines and
  piles (the renderer still paints it on top, see draw_layer).
- MONSTER_SHOT -- a goblin archer's line of fire (Monster.clear_shot and
  lane_tiles read the same `occupied` set: the entity part is identical to
  MONSTER_MOVE's), and the flight of an arrow it fired that the player
  dodged. Chests and shrines don't block a
  line: they are low, and the player's own arrows pass them.
- ARROW -- the player's arrow (game/archery.py): it stops before a wall or
  a closed door, and hits the monsters it meets (the bow's pierce decides
  how many). A door is entered only to hit a monster standing in it, and
  the arrow stops there. It flies past the shopkeeper, chests, shrines and
  piles: the shopkeeper can't be shot.
- HOP -- each tile of the archer's hop: it stops short of anything solid,
  including a chest or shrine (only walking uses them) and a doorway.
- REACH -- the tiles between the player and a spear's target: a chest or a
  pile is no obstacle, a door is.
- KNOCKBACK -- each tile a sling pushes a monster: it crosses doorways and
  chests, shrines and piles, and stops before a wall or a creature.
- SUMMON -- where a boss's goblins may appear: bare floor ('.') with
  nothing on it, reachable from the boss on foot within the summon radius
  (reachable_within), so never in the next room through a wall.

Spawn placement is not a blocking_at purpose but the same idea over a set:
game.floor.populate_level passes one `occupied` set through every spawner
-- it starts with the terrain walls (terrain_tiles), the player's start and
the shopkeeper, then spawn.spawn_level's
monsters, item.spawn_chests' chests (which also reserve rooms[-1].center(),
the stairs on a normal floor), the boss floor's stairs, and the shrine --
and each picks from free_tiles(room, occupied). So no chest or shrine is
ever *placed* on a creature or the stairs (a monster may walk onto one
later). (Monsters are placed before the
stairs are reserved, and may start on them.)

The player's own walk is not a purpose: walking into a creature attacks it
(or opens the shop), walking into a chest or shrine uses it, and walking
onto a pile picks it up (game.moves.try_move_player and arrive).

Standard library only, like the rest of game/.
"""

from game.entity import CREATURE, FIXTURE, PILE
from game.monster import Monster
from game.tiles import DOOR, FLOOR, WALL

MONSTER_MOVE = 'monster move'
MONSTER_SHOT = 'monster shot'
ARROW = 'arrow'
HOP = 'hop'
REACH = 'reach'
KNOCKBACK = 'knockback'
SUMMON = 'summon'

_CREATURES = frozenset({'player', 'monster', 'shopkeeper'})

# purpose -> the tags that make a tile block it (see the module docstring).
BLOCKERS = {
    MONSTER_MOVE: frozenset({'wall'}) | _CREATURES,
    MONSTER_SHOT: frozenset({'wall', 'door'}) | _CREATURES,
    ARROW: frozenset({'wall', 'empty door'}),
    HOP: frozenset({'wall', 'door', 'fixture'}) | _CREATURES,
    REACH: frozenset({'wall', 'door'}) | _CREATURES,
    KNOCKBACK: frozenset({'wall'}) | _CREATURES,
    SUMMON: frozenset({'wall', 'door', 'not floor', 'fixture', 'pile'}) | _CREATURES,
}


def entity_tag(state, entity):
    """The tag `entity` puts on its tile, or None if it puts none (a dead
    monster)."""
    if entity is state.player:
        return 'player'
    if entity is state.shopkeeper:
        return 'shopkeeper'
    if isinstance(entity, Monster):
        return 'monster' if entity.alive else None
    layer = getattr(entity, 'layer', CREATURE)
    if layer == FIXTURE:
        return 'fixture'
    if layer == PILE:
        return 'pile'
    return None


def _on_map(state, x, y):
    return 0 <= y < len(state.game_map) and 0 <= x < len(state.game_map[y])


def _entities(state):
    """Every entity on the floor, the shopkeeper included even if a test
    left it out of state.entities."""
    keeper = getattr(state, 'shopkeeper', None)
    if keeper is not None and not any(e is keeper for e in state.entities):
        return [*state.entities, keeper]
    return state.entities


def tags_at(state, x, y, ignore=None):
    """The set of tags on (x, y) (module docstring). `ignore` is one entity
    left out: the one asking, which never blocks itself."""
    char = state.game_map[y][x]
    tags = set()
    if char == WALL:
        tags.add('wall')
    elif char == DOOR:
        tags.add('door')
    if char != FLOOR:
        tags.add('not floor')
    for e in _entities(state):
        if e is not ignore and e.x == x and e.y == y:
            tag = entity_tag(state, e)
            if tag is not None:
                tags.add(tag)
    if 'door' in tags and 'monster' not in tags:
        tags.add('empty door')
    return tags


def blocking_at(state, x, y, purpose, ignore=None):
    """True if (x, y) is in the way for `purpose` (a BLOCKERS key). Off the
    map always blocks."""
    if not _on_map(state, x, y):
        return True
    return not BLOCKERS[purpose].isdisjoint(tags_at(state, x, y, ignore))


def blocker_tiles(state, purpose, ignore=None):
    """The tiles whose *entities* block `purpose` -- the rule minus its
    terrain, for monster AI, which reads the map itself and is handed the
    rest as a set. `ignore` (the monster asking) is left out."""
    blockers = BLOCKERS[purpose]
    return {
        (e.x, e.y)
        for e in _entities(state)
        if e is not ignore and entity_tag(state, e) in blockers
    }


def occupant(state, x, y):
    """The living creature on (x, y) -- the player, a monster or the
    shopkeeper -- or None. Chests, shrines and piles are not occupants."""
    for e in _entities(state):
        if e.x == x and e.y == y and entity_tag(state, e) in _CREATURES:
            return e
    return None


def draw_layer(entity):
    """Paint order key: piles first, then chests and shrines, then
    creatures, so a creature is never hidden under what it stands by."""
    if isinstance(entity, Monster):
        return CREATURE
    return getattr(entity, 'layer', CREATURE)


def room_tiles(room, game_map=None):
    """Every tile of a room's rectangle, row by row (carve_room's range). With
    `game_map`, terrain walls (dungeon.add_terrain) are left out."""
    tiles = [(x, y) for y in range(room.y1, room.y2) for x in range(room.x1, room.x2)]
    if game_map is None:
        return tiles
    return [(x, y) for x, y in tiles if game_map[y][x] != WALL]


def free_tiles(room, occupied, game_map=None):
    """room_tiles(room, game_map) not in `occupied`, in the same order."""
    return [t for t in room_tiles(room, game_map) if t not in occupied]


def terrain_tiles(game_map, rooms):
    """The wall tiles standing inside the rooms' rectangles: terrain."""
    return {(x, y) for room in rooms for x, y in room_tiles(room) if game_map[y][x] == WALL}


def reachable_within(game_map, start, radius):
    """Walkable tiles reachable from `start` by 4-way steps without leaving
    the square of Chebyshev `radius` around it (start included)."""
    sx, sy = start
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for x, y in frontier:
            for t in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
                tx, ty = t
                if (
                    t in seen
                    or max(abs(tx - sx), abs(ty - sy)) > radius
                    or not (0 <= ty < len(game_map) and 0 <= tx < len(game_map[ty]))
                    or game_map[ty][tx] == WALL
                ):
                    continue
                seen.add(t)
                nxt.append(t)
        frontier = nxt
    return seen
