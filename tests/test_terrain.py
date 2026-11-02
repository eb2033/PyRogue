"""game/dungeon.py add_terrain: wall features inside rooms."""

import functools
import random
import unittest

from game.dungeon import add_terrain, generate_dungeon, generate_level
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, WALL

DEPTHS = (1, 5, 9, 17)
SEEDS = range(12)


@functools.cache
def _levels():
    out = []
    for depth in DEPTHS:
        for seed in SEEDS:
            rng = random.Random(seed * 100 + depth)
            game_map, rooms = generate_level(40, 20, depth, rng)
            out.append((depth, seed, game_map, rooms))
    return tuple(out)


def levels():
    """The generated levels, built once (tests only read them)."""
    return iter(_levels())


@functools.cache
def base_level(depth, seed):
    """The same level as generate_level builds, before terrain."""
    from game.dungeon import map_size, room_size_range

    w, h = map_size(40, 20, depth)
    lo, hi = room_size_range(depth)
    rng = random.Random(seed * 100 + depth)
    game_map, rooms = generate_dungeon(w, h, min_size=lo, max_size=hi, rng=rng)
    return game_map, rooms, rng


def terrain_tiles(game_map, base, room):
    """Tiles in `room` that terrain turned from floor into wall."""
    return {
        (x, y)
        for y in range(room.y1, room.y2)
        for x in range(room.x1, room.x2)
        if base[y][x] == FLOOR and game_map[y][x] == WALL
    }


def flood(game_map, start):
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in seen and game_map[ny][nx] != WALL:
                seen.add((nx, ny))
                stack.append((nx, ny))
    return seen


def walkable(game_map):
    return {(x, y) for y, row in enumerate(game_map) for x, c in enumerate(row) if c != WALL}


def components(tiles):
    """Group `tiles` into 8-connected clusters (one cluster per feature)."""
    left = set(tiles)
    out = []
    while left:
        stack = [left.pop()]
        cluster = set(stack)
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in left:
                        left.remove(n)
                        cluster.add(n)
                        stack.append(n)
        out.append(cluster)
    return out


class TerrainTests(unittest.TestCase):
    def test_terrain_keeps_every_tile_reachable_and_the_layout_unchanged(self):
        for depth, seed, game_map, rooms in levels():
            base, base_rooms, _ = base_level(depth, seed)
            before = flood(base, rooms[0].center())
            after = flood(game_map, rooms[0].center())
            self.assertEqual(after, walkable(game_map) & before, (depth, seed))
            self.assertEqual(len(before) - len(after), self._removed(game_map, base))
            # the start room has none, and rooms are exactly the base rooms
            self.assertEqual(terrain_tiles(game_map, base, rooms[0]), set())
            self.assertEqual(len(rooms), len(base_rooms))
            self.assertEqual(
                [(r.x1, r.y1, r.x2, r.y2) for r in rooms],
                [(r.x1, r.y1, r.x2, r.y2) for r in base_rooms],
            )

    @staticmethod
    def _removed(game_map, base):
        return sum(
            1
            for y, row in enumerate(base)
            for x, c in enumerate(row)
            if c != WALL and game_map[y][x] == WALL
        )

    def test_features_are_clear_of_centres_doors_and_stairs_and_sized_two_or_three(self):
        found = 0
        for depth, seed, game_map, rooms in levels():
            base, _, _ = base_level(depth, seed)
            centres = [r.center() for r in rooms]
            for room in rooms:
                tiles = terrain_tiles(game_map, base, room)
                for cluster in components(tiles):
                    self.assertIn(len(cluster), (2, 3), (depth, seed, cluster))
                for x, y in tiles:
                    found += 1
                    for cx, cy in centres:
                        self.assertFalse(
                            abs(x - cx) <= 1 and abs(y - cy) <= 1, (depth, seed, (x, y))
                        )
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        self.assertNotEqual(game_map[ny][nx], DOOR, (depth, seed))
                    self.assertNotEqual(base[y][x], STAIRS_DOWN)
        self.assertGreater(found, 0)

    def test_feature_count_by_room_width(self):
        for depth, seed, game_map, rooms in levels():
            base, _, _ = base_level(depth, seed)
            for room in rooms[1:]:
                n = len(components(terrain_tiles(game_map, base, room)))
                limit = 3 if room.x2 - room.x1 <= 12 else 6
                self.assertLessEqual(n, limit, (depth, seed))
        # rooms of 12 or less get up to 3; the wide rooms of floor 17 up to 6
        wide = [
            len(components(terrain_tiles(m, base_level(d, s)[0], r)))
            for d, s, m, rooms in levels()
            if d == 17
            for r in rooms[1:]
            if r.x2 - r.x1 > 12
        ]
        self.assertTrue(any(n > 3 for n in wide), wide)

    def test_nothing_spawns_on_terrain(self):
        from game.state import GameState

        for depth in DEPTHS:
            for seed in range(6):
                state = GameState(40, 20, seed=seed)
                state.depth = depth - 1
                state.next_level()
                for e in state.entities:
                    self.assertNotEqual(state.game_map[e.y][e.x], WALL, (depth, seed, e.char))

    def test_terrain_tiles_helper_and_free_tiles_skip_walls(self):
        from game import level

        for depth, seed, game_map, rooms in levels():
            base, _, _ = base_level(depth, seed)
            expected = set().union(*(terrain_tiles(game_map, base, r) for r in rooms))
            self.assertEqual(level.terrain_tiles(game_map, rooms), expected, (depth, seed))
            for room in rooms:
                free = level.free_tiles(room, set(), game_map)
                self.assertTrue(all(game_map[y][x] != WALL for x, y in free))
                self.assertEqual(
                    len(free) + len(terrain_tiles(game_map, base, room)),
                    len(level.free_tiles(room, set())),
                )

    def test_seeded_replay_and_add_terrain_uses_only_the_given_rng(self):
        a = generate_level(40, 20, 9, random.Random(4))
        b = generate_level(40, 20, 9, random.Random(4))
        self.assertEqual(a[0], b[0])
        base_map, rooms, _ = base_level(5, 1)
        game_map = [row[:] for row in base_map]
        random.seed(1)
        state = random.getstate()
        add_terrain(game_map, rooms, random.Random(2))
        self.assertEqual(random.getstate(), state)


if __name__ == '__main__':
    unittest.main()
