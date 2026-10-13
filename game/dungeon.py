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


def wall_sides(room):
    """The four sides of the wall ring around `room`'s floor, as lists of
    (x, y) running along each side. Corners are left out: a corner tile
    touches no floor tile of the room orthogonally, so it can't be a doorway."""
    return [
        [(x, room.y1 - 1) for x in range(room.x1, room.x2)],  # north
        [(x, room.y2) for x in range(room.x1, room.x2)],      # south
        [(room.x1 - 1, y) for y in range(room.y1, room.y2)],  # west
        [(room.x2, y) for y in range(room.y1, room.y2)],      # east
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

            rooms.append(new_room)

    if not rooms:
        fallback = Rect(1, 1, max(1, w - 2), max(1, h - 2))
        carve_room(game_map, fallback)
        rooms.append(fallback)

    place_doors(game_map, rooms)
    return game_map, rooms


def place_stairs(game_map, rooms):
    """Stretch goal #1: stairs down at rooms[-1].center() (spec §8.1)."""
    sx, sy = rooms[-1].center()
    game_map[sy][sx] = STAIRS_DOWN
    return sx, sy
