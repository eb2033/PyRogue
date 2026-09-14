"""Room-and-corridor dungeon generation (spec §3).

Room sizes follow the spec's 4-8. Placement is attempt-based rather than a
fixed number of tries (see max_attempts below): it keeps rolling random rooms
until it either hits the target room count (min_rooms-max_rooms, default
4-6) or runs out of attempts, so a 50x20 map reliably lands in that range
instead of stalling out around 2-3 rooms.
"""

import random

from game.rect import Rect
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, WALL


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


def _room_at(x, y, rooms):
    for room in rooms:
        if room.x1 <= x < room.x2 and room.y1 <= y < room.y2:
            return room
    return None


def _corridor_path(prev_x, prev_y, new_x, new_y, horizontal_first):
    """The ordered tile-by-tile walk of an L-shaped corridor from (prev_x,
    prev_y) to (new_x, new_y), matching whichever of carve_h_corridor/
    carve_v_corridor ran first below.

    Each step must land on a tile adjacent to the previous one -- door
    placement below relies on that to detect where the path crosses a room
    boundary. A naive range(min, max) per axis would list a segment in
    ascending order regardless of which way it's actually walked, which
    breaks adjacency (and so wrongly detects room boundary crossings, e.g.
    from a mid-corridor bend that happens to coincide with a room center)
    whenever a segment runs backwards (new < prev).
    """
    path = [(prev_x, prev_y)]
    x, y = prev_x, prev_y

    def walk_x(x, y, target_x):
        step = 1 if target_x >= x else -1
        while x != target_x:
            x += step
            path.append((x, y))
        return x

    def walk_y(x, y, target_y):
        step = 1 if target_y >= y else -1
        while y != target_y:
            y += step
            path.append((x, y))
        return y

    if horizontal_first:
        x = walk_x(x, y, new_x)
        walk_y(x, y, new_y)
    else:
        y = walk_y(x, y, new_y)
        walk_x(x, y, new_x)
    return path


def _place_doors(game_map, rooms, prev_x, prev_y, new_x, new_y, horizontal_first):
    """Drop a door at every point where a corridor crosses a room boundary,
    so each room is sealed off for line-of-sight purposes (tiles.
    is_transparent treats DOOR as opaque, same as a wall) until the player
    is standing in the doorway or past it."""
    path = _corridor_path(prev_x, prev_y, new_x, new_y, horizontal_first)
    prev_owner = _room_at(path[0][0], path[0][1], rooms)
    for i in range(1, len(path)):
        x, y = path[i]
        owner = _room_at(x, y, rooms)
        if owner is not prev_owner:
            if prev_owner is not None:
                dx, dy = path[i - 1]
                game_map[dy][dx] = DOOR
            if owner is not None:
                game_map[y][x] = DOOR
        prev_owner = owner


def generate_dungeon(w, h, min_rooms=4, max_rooms=6, min_size=4, max_size=8,
                     max_attempts=300):
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

            carve_room(game_map, new_room)

            if rooms:
                prev_x, prev_y = rooms[-1].center()
                new_x, new_y = new_room.center()
                horizontal_first = random.random() < 0.5
                if horizontal_first:
                    carve_h_corridor(game_map, prev_x, new_x, prev_y)
                    carve_v_corridor(game_map, prev_y, new_y, new_x)
                else:
                    carve_v_corridor(game_map, prev_y, new_y, prev_x)
                    carve_h_corridor(game_map, prev_x, new_x, new_y)
                _place_doors(game_map, rooms + [new_room], prev_x, prev_y,
                            new_x, new_y, horizontal_first)

            rooms.append(new_room)

    if not rooms:
        fallback = Rect(1, 1, max(1, w - 2), max(1, h - 2))
        carve_room(game_map, fallback)
        rooms.append(fallback)

    return game_map, rooms


def place_stairs(game_map, rooms):
    """Stretch goal #1: stairs down at rooms[-1].center() (spec §8.1)."""
    sx, sy = rooms[-1].center()
    game_map[sy][sx] = STAIRS_DOWN
    return sx, sy
