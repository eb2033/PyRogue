"""Room-and-corridor dungeon generation (spec §3).

Base room sizes follow the spec's 4-8; deeper floors add room_growth(depth)
tiles to every side of a room, and map_size enlarges the map to match, so a
floor still gets its 4-6 rooms (see "size by depth" below). Placement is attempt-based rather than a
fixed number of tries (see max_attempts below): it keeps rolling random rooms
until it either hits the target room count (min_rooms-max_rooms, default
4-6) or runs out of attempts, so a 50x20 map reliably lands in that range
instead of stalling out around 2-3 rooms.
"""

import heapq
import math
import random

from game.rect import Rect
from game.rng import Rng
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, WALL

# -- size by depth ------------------------------------------------------------
# THE one place to tune how rooms -- and with them the map -- grow with depth.
# ROOM_GROWTH: (first floor, extra tiles on EACH of a room's four sides),
# shallowest first; the last row holds for every floor below it (the cap).
# A room's width and height grow by twice the value. The base room size is
# the spec's, unchanged; the growth is added on top of it.
ROOM_GROWTH = (
    (1, 2),  # floors 1-8
    (9, 5),  # floors 9-16
    (17, 6),  # floors 17 and up
)
BASE_MIN_ROOM = 4
BASE_MAX_ROOM = 8
# The span an average base room takes along one axis: its mean size plus one
# wall. map_size scales the map by how much growth widens that span, so as
# many rooms fit as on an ungrown map.
ROOM_FOOTPRINT = (BASE_MIN_ROOM + BASE_MAX_ROOM) / 2 + 1


def room_growth(depth):
    """Tiles added to each side of every room on floor `depth`."""
    growth = ROOM_GROWTH[0][1]
    for first, extra in ROOM_GROWTH:
        if depth >= first:
            growth = extra
    return growth


def room_size_range(depth):
    """(min, max) room width/height on floor `depth`: the base range plus
    room_growth on both sides."""
    extra = 2 * room_growth(depth)
    return BASE_MIN_ROOM + extra, BASE_MAX_ROOM + extra


def map_size(base_w, base_h, depth):
    """(w, h) of floor `depth`'s map. `base_w` x `base_h` is the map for
    ungrown rooms (MAP_WIDTH/MAP_HEIGHT, 50x20 by default); each axis is
    scaled by how much room_growth widens a room's footprint, rounded up, so
    the room count stays in generate_dungeon's min_rooms-max_rooms. Never
    shrinks with depth, because room_growth doesn't."""
    scale = (ROOM_FOOTPRINT + 2 * room_growth(depth)) / ROOM_FOOTPRINT
    return math.ceil(base_w * scale), math.ceil(base_h * scale)


def generate_level(base_w, base_h, depth):
    """(game_map, rooms) for floor `depth`: map_size's map holding
    room_size_range's rooms. Its size is len(game_map[0]) x len(game_map)."""
    w, h = map_size(base_w, base_h, depth)
    min_size, max_size = room_size_range(depth)
    return generate_dungeon(w, h, min_size=min_size, max_size=max_size)


def make_empty_map(w, h, fill=WALL):
    return [[fill for _ in range(w)] for _ in range(h)]


def carve_room(game_map, room):
    for y in range(room.y1, room.y2):
        for x in range(room.x1, room.x2):
            game_map[y][x] = FLOOR


def carve_h_corridor(game_map, x1, x2, y):
    for x in range(min(x1, x2), max(x1, x2) + 1):
        game_map[y][x] = FLOOR


def carve_v_corridor(game_map, y1, y2, x):
    for y in range(min(y1, y2), max(y1, y2) + 1):
        game_map[y][x] = FLOOR


def wall_sides(room):
    """The four sides of the wall ring around `room`'s floor, as lists of
    (x, y) running along each side. Corners are left out: a corner tile
    touches no floor tile of the room orthogonally, so it can't be a doorway."""
    return [
        [(x, room.y1 - 1) for x in range(room.x1, room.x2)],  # north
        [(x, room.y2) for x in range(room.x1, room.x2)],  # south
        [(room.x1 - 1, y) for y in range(room.y1, room.y2)],  # west
        [(room.x2, y) for y in range(room.y1, room.y2)],  # east
    ]


def place_doors(game_map, rooms):
    """Put a door in every doorway: a single-tile gap a corridor has cut
    through a room's wall ring. The door sits *in* the wall line, flanked by
    wall on both sides, so with tiles.is_transparent treating DOOR as opaque
    the room stays hidden until the player steps into the doorway.

    Runs after every corridor is carved, so a later corridor can't carve over
    an earlier door. A gap wider than one tile is where a corridor runs
    along the outside of the wall; one door can't close that, so it stays
    open."""
    for room in rooms:
        for side in wall_sides(room):
            run = []
            for pos in side + [None]:
                if pos is not None and game_map[pos[1]][pos[0]] == FLOOR:
                    run.append(pos)
                    continue
                if len(run) == 1:
                    dx, dy = run[0]
                    game_map[dy][dx] = DOOR
                run = []


# Corridor routing costs (see route_corridor). Crossing a wall is the
# expensive part, so corridors punch through as few as they can and prefer
# an existing doorway or corridor to a fresh one.
ROCK_COST = 3
FLOOR_COST = 1
DOORWAY_COST = 20


def _wall_index(rooms):
    """(sides, corners, rings): every non-corner wall-ring tile mapped to the
    set of (room, side) it belongs to; the set of ring corner tiles; and every
    ring tile, corners included, mapped to the set of rooms whose ring it is
    part of."""
    sides, corners, rings = {}, set(), {}
    for i, room in enumerate(rooms):
        for side_no, side in enumerate(wall_sides(room)):
            for pos in side:
                sides.setdefault(pos, set()).add((i, side_no))
                rings.setdefault(pos, set()).add(i)
        room_corners = {
            (room.x1 - 1, room.y1 - 1),
            (room.x2, room.y1 - 1),
            (room.x1 - 1, room.y2),
            (room.x2, room.y2),
        }
        corners.update(room_corners)
        for pos in room_corners:
            rings.setdefault(pos, set()).add(i)
    corners.difference_update(sides)  # a corner of one room can be a side of another
    return sides, corners, rings


def route_corridor(game_map, rooms, start, goal):
    """The cheapest 4-way path from `start` to `goal` (room centres), as a
    list of (x, y), or None. It crosses room walls only head-on, through a
    single tile: never along a wall, never through a ring corner, and never
    next to an existing doorway in the same wall (which would make a gap no
    door can close). Reusing an existing doorway or corridor is cheap."""
    h, w = len(game_map), len(game_map[0])
    sides, corners, rings = _wall_index(rooms)

    def cost(pos):
        x, y = pos
        if not (0 < x < w - 1 and 0 < y < h - 1) or pos in corners:
            return None
        if pos in sides:
            if game_map[y][x] != WALL:
                return FLOOR_COST  # an existing doorway
            for room, side_no in sides[pos]:
                for neighbour in _along_side(pos, side_no):
                    nx, ny = neighbour
                    if (room, side_no) in sides.get(neighbour, ()) and game_map[ny][nx] != WALL:
                        return None  # would widen that doorway
            return DOORWAY_COST
        return FLOOR_COST if game_map[y][x] != WALL else ROCK_COST

    best = {start: 0}
    came_from = {}
    queue = [(0, start)]
    while queue:
        dist, pos = heapq.heappop(queue)
        if pos == goal:
            path = [pos]
            while pos in came_from:
                pos = came_from[pos]
                path.append(pos)
            return path[::-1]
        if dist > best[pos]:
            continue
        x, y = pos
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            step = cost(nxt)
            if step is None:
                continue
            if rings.get(pos, set()) & rings.get(nxt, set()):
                # Walking along a wall -- including into a corner of the
                # ring that is also another room's side, which would leave
                # a door flanked by a doorway instead of wall.
                continue
            if dist + step < best.get(nxt, float('inf')):
                best[nxt] = dist + step
                came_from[nxt] = pos
                heapq.heappush(queue, (dist + step, nxt))
    return None


def _along_side(pos, side_no):
    """The two tiles beside `pos` along its wall (north/south walls run
    east-west, west/east walls run north-south)."""
    x, y = pos
    if side_no in (0, 1):
        return ((x - 1, y), (x + 1, y))
    return ((x, y - 1), (x, y + 1))


def connect_rooms(game_map, rooms, rng: Rng = random):
    """Corridors joining each room to the one placed before it, routed by
    route_corridor once every room is carved -- so no room can later land
    with its wall along an existing corridor. Falls back to the spec's
    L-shaped corridor if routing ever fails."""
    for prev, new in zip(rooms, rooms[1:]):
        path = route_corridor(game_map, rooms, prev.center(), new.center())
        if path is None:
            (px, py), (nx, ny) = prev.center(), new.center()
            if rng.random() < 0.5:
                carve_h_corridor(game_map, px, nx, py)
                carve_v_corridor(game_map, py, ny, nx)
            else:
                carve_v_corridor(game_map, py, ny, px)
                carve_h_corridor(game_map, px, nx, ny)
            continue
        for x, y in path:
            game_map[y][x] = FLOOR


def generate_dungeon(w, h, min_rooms=4, max_rooms=6, min_size=4, max_size=8, max_attempts=300):
    """Keeps rolling random, non-overlapping rooms until it hits a target
    room count in [min_rooms, max_rooms] or exhausts max_attempts. min_size/
    max_size are clamped to whatever fits in (w, h): a map smaller than the
    configured room size would otherwise hand random.randint an inverted
    range and crash. If nothing fits at all, a single room filling the
    interior is carved so callers can always rely on rooms[0]/rooms[-1]."""
    game_map = make_empty_map(w, h)
    rooms = []

    max_rw = min(max_size, w - 2)
    max_rh = min(max_size, h - 2)
    min_rw = min(min_size, max_rw)
    min_rh = min(min_size, max_rh)

    if max_rw >= 1 and max_rh >= 1:
        target_rooms = random.randint(min_rooms, max_rooms)
        attempts = 0
        while len(rooms) < target_rooms and attempts < max_attempts:
            attempts += 1
            rw = random.randint(min_rw, max_rw)
            rh = random.randint(min_rh, max_rh)
            max_rx = w - rw - 1
            max_ry = h - rh - 1
            if max_rx < 1 or max_ry < 1:
                continue
            rx = random.randint(1, max_rx)
            ry = random.randint(1, max_ry)
            new_room = Rect(rx, ry, rw, rh)

            if any(new_room.intersects(r) for r in rooms):
                continue  # overlaps, skip

            rooms.append(new_room)

    if not rooms:
        rooms.append(Rect(1, 1, max(1, w - 2), max(1, h - 2)))

    # Rooms first, then corridors: see connect_rooms.
    for room in rooms:
        carve_room(game_map, room)
    connect_rooms(game_map, rooms)
    place_doors(game_map, rooms)
    return game_map, rooms


def place_stairs(game_map, rooms):
    """Stretch goal #1: stairs down at rooms[-1].center() (spec §8.1)."""
    sx, sy = rooms[-1].center()
    game_map[sy][sx] = STAIRS_DOWN
    return sx, sy


# On a boss floor the stairs keep at least this Chebyshev distance from the
# boss when the room allows it, so the boss never starts beside them.
BOSS_STAIRS_MIN_DISTANCE = 2


def boss_stairs_tile(game_map, arena, boss_pos, occupied=(), rng: Rng = random):
    """Where the stairs go on a boss floor: a floor tile of `arena` (the boss
    room) that is not in `occupied` (the player, monsters, chests), not on
    `boss_pos`, and not in the arena's centre 3x3 (the tiles within 1 of
    arena.center(), where the boss stands). Picked at random among, in order:

    1. such tiles at least BOSS_STAIRS_MIN_DISTANCE from the boss;
    2. failing that, such tiles at any distance (rule 1 always holds while
       the boss is at the centre: every tile outside the 3x3 is then >= 2
       away, so this only matters if the boss was moved off it);
    3. failing that, any free floor tile of the room other than the boss's.

    Returns None only if the room has no free floor tile at all."""
    cx, cy = arena.center()

    def chebyshev(t, o):
        return max(abs(t[0] - o[0]), abs(t[1] - o[1]))

    free = [
        (x, y)
        for y in range(arena.y1, arena.y2)
        for x in range(arena.x1, arena.x2)
        if game_map[y][x] == FLOOR and (x, y) not in occupied and (x, y) != tuple(boss_pos)
    ]
    outside = [t for t in free if chebyshev(t, (cx, cy)) > 1]
    far = [t for t in outside if chebyshev(t, boss_pos) >= BOSS_STAIRS_MIN_DISTANCE]
    if far:
        return rng.choice(far)
    if outside:
        return rng.choice(outside)
    return rng.choice(free) if free else None


def place_boss_stairs(game_map, arena, boss_pos, occupied=(), rng: Rng = random):
    """Stairs down inside the boss room (boss_stairs_tile has the rules).
    Falls back to place_stairs' rule if the room has no free floor at all.
    Returns the stairs' (x, y)."""
    tile = boss_stairs_tile(game_map, arena, boss_pos, occupied, rng)
    if tile is None:
        return place_stairs(game_map, [arena])
    sx, sy = tile
    game_map[sy][sx] = STAIRS_DOWN
    return sx, sy
