"""Headless tests for game/ logic (no window — this exercises GameState
and its collaborators directly, the same way the renderer would).

Run with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import heapq
import os
import random
import sys
import time
import unittest
from typing import cast
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import dungeon
from game.combat import Hit, Parry, Shot
from game.damage import mitigate, round_damage
from game.dungeon import (
    BOSS_STAIRS_MIN_DISTANCE,
    boss_stairs_tile,
    generate_dungeon,
    generate_level,
    make_empty_map,
    map_size,
    place_doors,
    place_stairs,
    room_growth,
    room_size_range,
    wall_sides,
)
from game.entity import Entity
from game.fov import compute_fov, update_visibility
from game.gold import GoldPile
from game.item import (
    ARCHER_WEAPONS,
    ARMOR_DEFENSE,
    ARMOR_DROP_CHANCE,
    ARMOR_KINDS,
    ARMOR_SPLIT,
    BELT_SLOTS,
    CHEST_COLOR,
    GEAR_BONUS,
    GEAR_CHEST_DROPS,
    GEAR_DROP_KINDS,
    GEAR_KINDS,
    GEAR_SLOTS,
    ITEM_CHARS,
    JUNK,
    JUNK_CHANCE,
    JUNK_NAME,
    MAX_DODGE,
    MAX_SCALING_DEPTH,
    POTION_CHEST_COLOR,
    POTION_HEAL,
    RARITIES,
    WARRIOR_WEAPONS,
    WEAPON_TYPES,
    Chest,
    Item,
    belt_capacity,
    belt_slot_label,
    dodge_chance,
    rarity_weights_for_depth,
    roll_boss_drop,
    roll_gear_drop,
    roll_rarity,
    spawn_boss_chest,
    spawn_chests,
)
from game.monster import (
    BOSS_REFERENCE_KIND,
    CHASE_RANGE,
    GIVE_UP_AFTER,
    LANE_SEARCH_LIMIT,
    MONSTER_TYPES,
    ORTHOGONAL_STEPS,
    SHOOT_RANGE,
    SLIME_KINDS,
    Monster,
    is_boss_level,
    lane_tiles,
    scale_stats,
    spawn_boss,
    tier_for_depth,
)
from game.quiver import QUIVER_CAPACITY, RESTOCK_TURNS, ArrowPile
from game.rect import Rect
from game.shrine import (
    BOONS,
    BOONS_OFFERED,
    SHRINE_CHANCE,
    Boon,
    Shrine,
    boon_total,
    heal_multiplier,
    place_shrine,
    roll_boons,
)
from game.spawn import (
    BOSS_ESCORTS,
    FIRST_BOSS_DEPTH,
    SpawnRule,
    goblin_pack_size,
    pick_tiles,
    spawn_level,
)
from game.spawn import (
    goblin_archer_pack_size as archer_pack_size,
)
from game.state import (
    ARCHER_FOV_BONUS,
    BASE_CRIT_CHANCE,
    CRIT_MULTIPLIER,
    DESCENT_HEAL_FRACTION,
    MAX_MESSAGES,
    PARRY_COOLDOWN,
    GameState,
    crit_chance,
)
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, WALL, is_walkable


class PotionArticleTests(unittest.TestCase):
    def test_an_elixir_is_not_a_elixir(self):
        state = GameState(50, 20, seed=1)
        Item(0, 0, 'potion', 'epic').apply(state.player, state.log)
        self.assertIn('You drink an elixir of vitality', state.messages[-1])
        Item(0, 0, 'potion', 'common').apply(state.player, state.log)
        self.assertIn('You drink a potion', state.messages[-1])


class MessageLogTests(unittest.TestCase):
    def test_the_log_keeps_only_the_newest_messages(self):
        state = GameState(50, 20, seed=1)
        state.messages.clear()
        for i in range(MAX_MESSAGES + 25):
            state.log(f'line {i}')
        self.assertEqual(len(state.messages), MAX_MESSAGES)
        self.assertEqual(state.messages[-1], f'line {MAX_MESSAGES + 24}')
        self.assertEqual(state.messages[0], 'line 25')


class DungeonGenerationTests(unittest.TestCase):
    def test_rooms_are_carved_apart_inside_a_solid_border_with_stairs_in_the_last(self):
        for seed in (1, 2, 3, 4):
            with self.subTest(seed=seed):
                random.seed(seed)
                game_map, rooms = generate_dungeon(50, 20)
                self.assertEqual(len(game_map), 20)
                self.assertEqual(len(game_map[0]), 50)
                for x in range(50):
                    self.assertEqual(game_map[0][x], WALL)
                    self.assertEqual(game_map[19][x], WALL)
                for y in range(20):
                    self.assertEqual(game_map[y][0], WALL)
                    self.assertEqual(game_map[y][49], WALL)
                for i, r1 in enumerate(rooms):
                    for r2 in rooms[i + 1 :]:
                        self.assertFalse(r1.intersects(r2), 'rooms should not overlap')
                for room in rooms:
                    cx, cy = room.center()
                    self.assertEqual(game_map[cy][cx], FLOOR)
                sx, sy = place_stairs(game_map, rooms)
                self.assertEqual(game_map[sy][sx], STAIRS_DOWN)
                self.assertEqual((sx, sy), rooms[-1].center())


class SizeByDepthTests(unittest.TestCase):
    """Rooms grow with depth (dungeon.room_growth) and the map with them
    (dungeon.map_size), keeping 4-6 rooms a floor."""

    DEPTHS = (1, 8, 9, 16, 17, 30)

    def test_room_growth_table_and_the_size_range_it_gives(self):
        self.assertEqual([room_growth(d) for d in self.DEPTHS], [2, 2, 3, 3, 4, 4])
        # Growth is added on every side of the base room.
        for depth in self.DEPTHS:
            extra = 2 * room_growth(depth)
            self.assertEqual(room_size_range(depth), (4 + extra, 8 + extra))

        # A room's mean side is the base mean (6) plus growth on both sides;
        # each step down the table should look ~1.5x bigger, not ~2.5x.
        def mean_area(depth):
            return (6 + 2 * room_growth(depth)) ** 2

        for shallow, deep in ((8, 9), (16, 17)):
            ratio = mean_area(deep) / mean_area(shallow)
            self.assertTrue(1.3 <= ratio <= 1.6, (shallow, deep, ratio))

    def test_map_grows_with_depth_and_never_shrinks(self):
        for base in ((40, 20), (50, 20)):
            sizes = [map_size(*base, depth) for depth in range(1, 41)]
            for shallower, deeper in zip(sizes, sizes[1:]):
                self.assertGreaterEqual(deeper[0], shallower[0])
                self.assertGreaterEqual(deeper[1], shallower[1])
            # Bigger than the base from floor 1, and again at each growth step.
            self.assertGreater(sizes[0][0], base[0])
            self.assertGreater(sizes[0][1], base[1])
            self.assertGreater(sizes[8], sizes[7])  # floor 9
            self.assertGreater(sizes[16], sizes[15])  # floor 17

    def test_rooms_fit_inside_the_solid_border_at_every_depth(self):
        for depth in range(1, 31):
            random.seed(depth)
            game_map, rooms = generate_level(40, 20, depth)
            w, h = map_size(40, 20, depth)
            self.assertEqual((len(game_map[0]), len(game_map)), (w, h))
            low, high = room_size_range(depth)
            for room in rooms:
                self.assertTrue(1 <= room.x1 and room.x2 <= w - 1, (depth, vars(room)))
                self.assertTrue(1 <= room.y1 and room.y2 <= h - 1, (depth, vars(room)))
                self.assertTrue(low <= room.x2 - room.x1 <= high)
                self.assertTrue(low <= room.y2 - room.y1 <= high)
            for x in range(w):
                self.assertEqual((game_map[0][x], game_map[h - 1][x]), (WALL, WALL))
            for y in range(h):
                self.assertEqual((game_map[y][0], game_map[y][w - 1]), (WALL, WALL))

    def test_room_count_stays_in_range_at_every_depth(self):
        for depth in self.DEPTHS:
            for base in ((40, 20), (50, 20)):
                for seed in range(6):
                    random.seed(seed)
                    _, rooms = generate_level(*base, depth)
                    self.assertTrue(4 <= len(rooms) <= 6, (depth, base, seed, len(rooms)))

    def test_each_new_floor_down_to_25_is_rebuilt_in_size_with_entities_inside(self):
        # One walk down from floor 1 checks every floor next_level builds.
        state = GameState(40, 20, seed=6)
        self.assertEqual((state.width, state.height), map_size(40, 20, 1))
        self.assertIsNone(state.boss_arena)
        while state.depth <= 25:
            with self.subTest(depth=state.depth):
                w, h = map_size(40, 20, state.depth)
                self.assertEqual((state.width, state.height), (w, h))
                for grid in (state.game_map, state.visible, state.seen):
                    self.assertEqual((len(grid[0]), len(grid)), (w, h))
                self.assertTrue(state.visible[state.player.y][state.player.x])
                for entity in state.entities:
                    self.assertTrue(0 < entity.x < state.width - 1, (state.depth, entity))
                    self.assertTrue(0 < entity.y < state.height - 1, (state.depth, entity))
                    self.assertNotEqual(state.game_map[entity.y][entity.x], WALL)
                if is_boss_level(state.depth):
                    # A boss floor's arena is still one of its (grown) rooms.
                    arena = state.boss_arena
                    self.assertIn(arena, state.rooms[1:])
                    boss = next(m for m in state.entities if getattr(m, 'is_boss', False))
                    self.assertEqual((boss.x, boss.y), arena.center())
                    cx, cy = arena.center()
                    # The 3x3 centre area is inside the room.
                    for x in (cx - 1, cx + 1):
                        self.assertTrue(arena.x1 <= x < arena.x2)
                    for y in (cy - 1, cy + 1):
                        self.assertTrue(arena.y1 <= y < arena.y2)
                else:
                    self.assertIsNone(state.boss_arena)
            state.next_level()


class DoorPlacementTests(unittest.TestCase):
    """Doors sit in the doorway -- the gap in a room's wall ring -- never on
    the room's own floor, and a closed doorway hides the room."""

    @classmethod
    def setUpClass(cls):
        cls._maps = []
        for seed in range(300):
            random.seed(seed)
            cls._maps.append(generate_dungeon(40 if seed % 2 else 50, 20))

    def maps(self, count=300):
        # Shared, generated once (generation is ~2 ms a map). Tests
        # must not mutate them.
        return self._maps[:count]

    @staticmethod
    def inside(room, x, y):
        return room.x1 <= x < room.x2 and room.y1 <= y < room.y2

    def test_doors_are_in_a_wall_ring_never_on_room_floor(self):
        for game_map, rooms in self.maps():
            ring = {pos for room in rooms for side in wall_sides(room) for pos in side}
            for y, row in enumerate(game_map):
                for x, tile in enumerate(row):
                    if tile == DOOR:
                        self.assertIn((x, y), ring)
                        self.assertFalse(any(self.inside(r, x, y) for r in rooms))

    def test_every_wall_opening_is_a_single_tile_and_a_door(self):
        # Corridors are routed after every room exists and cross walls only
        # head-on, so every opening is a doorway one door can close.
        for game_map, rooms in self.maps():
            for room in rooms:
                for side in wall_sides(room):
                    tiles = [game_map[y][x] for x, y in side]
                    run = 0
                    for i, tile in enumerate(tiles):
                        run = run + 1 if tile != WALL else 0
                        self.assertLessEqual(run, 1, (room.x1, room.y1, side[i]))
                        before = tiles[i - 1] if i > 0 else WALL
                        after = tiles[i + 1] if i + 1 < len(tiles) else WALL
                        single_gap = tile != WALL and before == WALL and after == WALL
                        self.assertEqual(single_gap, tile == DOOR, (side[i], tiles))

    def test_a_closed_doorway_hides_the_room_from_the_corridor(self):
        checked = 0
        for game_map, rooms in self.maps(100):
            h, w = len(game_map), len(game_map[0])
            for room in rooms:
                for side, (ox, oy) in zip(wall_sides(room), [(0, -1), (0, 1), (-1, 0), (1, 0)]):
                    for x, y in side:
                        if game_map[y][x] != DOOR:
                            continue
                        outside = (x + ox, y + oy)  # the corridor side of the door
                        if any(self.inside(r, *outside) for r in rooms):
                            continue  # two rooms sharing a wall
                        visible = [[False] * w for _ in range(h)]
                        compute_fov(game_map, visible, *outside, 8)
                        seen_inside = [
                            (rx, ry)
                            for ry in range(room.y1, room.y2)
                            for rx in range(room.x1, room.x2)
                            if visible[ry][rx]
                        ]
                        self.assertEqual(seen_inside, [], (room.x1, room.y1, (x, y)))
                        checked += 1
        self.assertGreater(checked, 100)

    def test_every_room_is_reachable_from_the_start(self):
        for game_map, rooms in self.maps():
            start = rooms[0].center()
            seen, stack = {start}, [start]
            while stack:
                x, y = stack.pop()
                for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nxt not in seen and is_walkable(game_map, *nxt):
                        seen.add(nxt)
                        stack.append(nxt)
            for room in rooms:
                self.assertIn(room.center(), seen)

    def test_place_doors_leaves_wide_openings_alone(self):
        game_map = make_empty_map(12, 9)
        room = Rect(3, 3, 4, 3)
        for yy in range(room.y1, room.y2):
            for xx in range(room.x1, room.x2):
                game_map[yy][xx] = FLOOR
        game_map[2][4] = game_map[2][5] = FLOOR  # two-wide gap in the north wall
        game_map[6][4] = FLOOR  # one-wide gap in the south wall
        place_doors(game_map, [room])
        self.assertEqual((game_map[2][4], game_map[2][5]), (FLOOR, FLOOR))
        self.assertEqual(game_map[6][4], DOOR)


def _reference_route(game_map, rooms, start, goal):
    """route_corridor as it was before it moved to a flat cost grid: plain
    Dijkstra over (x, y) tuples with a cost() per edge. Kept as the oracle
    that the faster version picks the very same path."""
    h, w = len(game_map), len(game_map[0])
    sides, corners, rings = dungeon._wall_index(rooms)

    def cost(pos):
        x, y = pos
        if not (0 < x < w - 1 and 0 < y < h - 1) or pos in corners:
            return None
        if pos in sides:
            if game_map[y][x] != WALL:
                return dungeon.FLOOR_COST
            for room, side_no in sides[pos]:
                for nx, ny in dungeon._along_side(pos, side_no):
                    if (room, side_no) in sides.get((nx, ny), ()) and game_map[ny][nx] != WALL:
                        return None
            return dungeon.DOORWAY_COST
        return dungeon.FLOOR_COST if game_map[y][x] != WALL else dungeon.ROCK_COST

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
            if step is None or rings.get(pos, set()) & rings.get(nxt, set()):
                continue
            if dist + step < best.get(nxt, float('inf')):
                best[nxt] = dist + step
                came_from[nxt] = pos
                heapq.heappush(queue, (dist + step, nxt))
    return None


class RouteCorridorTests(unittest.TestCase):
    def test_picks_the_same_path_as_plain_dijkstra(self):
        # Replays connect_rooms corridor by corridor on seeded layouts, small
        # and grown, so later corridors see earlier ones (doorway reuse and
        # the no-widening rule both come into play).
        routed = 0
        for seed in range(12):
            depth = (1, 9, 17)[seed % 3]
            _, rooms = generate_level(40 if seed % 2 else 50, 20, depth, random.Random(seed))
            w, h = map_size(40 if seed % 2 else 50, 20, depth)
            game_map = make_empty_map(w, h)
            for room in rooms:
                dungeon.carve_room(game_map, room)
            for prev, new in zip(rooms, rooms[1:]):
                path = dungeon.route_corridor(game_map, rooms, prev.center(), new.center())
                self.assertEqual(
                    path, _reference_route(game_map, rooms, prev.center(), new.center())
                )
                if path is not None:
                    routed += 1
                    for x, y in path:
                        game_map[y][x] = FLOOR
        self.assertGreater(routed, 30)


class EntityMovementTests(unittest.TestCase):
    def test_a_move_onto_floor_succeeds_and_into_a_wall_is_blocked(self):
        game_map = [list(row) for row in ['#####', '#...#', '#####']]
        e = Entity(1, 1, '@')
        e.move(1, 0, game_map)
        self.assertEqual((e.x, e.y), (2, 1))
        e = Entity(1, 1, '@')
        e.move(-1, 0, game_map)
        self.assertEqual((e.x, e.y), (1, 1))
        game_map = [list(row) for row in ['###', '#.#', '###']]
        self.assertTrue(is_walkable(game_map, 1, 1))
        self.assertFalse(is_walkable(game_map, 0, 0))


class AdjacencyTests(unittest.TestCase):
    def test_is_adjacent_is_orthogonal_not_chebyshev_and_excludes_self_and_distant(self):
        origin = Entity(5, 5, '@')
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            self.assertTrue(origin.is_adjacent(Entity(5 + dx, 5 + dy, 'g')))
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            other = Entity(5 + dx, 5 + dy, 'g')
            self.assertFalse(origin.is_adjacent(other))
            self.assertEqual(origin.distance_to(other), 1)  # still Chebyshev-1
        self.assertFalse(origin.is_adjacent(Entity(5, 5, 'g')))
        self.assertFalse(origin.is_adjacent(Entity(5, 7, 'g')))


class FovShadowcastingTests(unittest.TestCase):
    def _grid(self, w, h):
        return [[False] * w for _ in range(h)]

    def test_compute_fov_lights_open_floor_and_shadows_what_a_wall_hides(self):
        with self.subTest('open room lights up to the radius'):
            game_map = [
                list(row)
                for row in [
                    '###########',
                    '#.........#',
                    '#.........#',
                    '#....@....#',
                    '#.........#',
                    '#.........#',
                    '###########',
                ]
            ]
            visible = self._grid(11, 7)
            compute_fov(game_map, visible, 5, 3, radius=4)
            self.assertTrue(visible[3][5])  # origin
            self.assertTrue(visible[3][1])  # 4 tiles west, in open room
            self.assertTrue(visible[1][5])  # 2 tiles north, open
        with self.subTest('a wall shadows the tile behind it'):
            # A single wall segment directly east of the player should shadow
            # the tile directly behind it, while the open tile to its side
            # (not directly hidden by the wall) stays visible.
            game_map = [
                list(row)
                for row in [
                    '###########',
                    '#.........#',
                    '#....@#...#',
                    '#.........#',
                    '###########',
                ]
            ]
            visible = self._grid(11, 5)
            compute_fov(game_map, visible, 5, 2, radius=5)
            self.assertTrue(visible[2][6], 'the wall tile itself should be lit')
            self.assertFalse(visible[2][7], 'directly behind the wall should be dark')
            self.assertTrue(visible[1][6], 'off to the side of the wall stays lit')

    def test_update_visibility_folds_into_seen(self):
        game_map = [list(row) for row in ['#####', '#...#', '#####']]
        visible = self._grid(5, 3)
        seen = self._grid(5, 3)
        update_visibility(game_map, visible, seen, 2, 1, radius=2)
        self.assertTrue(visible[1][2])
        self.assertTrue(seen[1][2])
        # Move away: visible clears but seen persists (fog-of-war memory).
        update_visibility(game_map, visible, seen, 1, 1, radius=1)
        self.assertTrue(seen[1][2])

    def test_update_visibility_with_previous_matches_a_full_recompute(self):
        # Clearing only the cells lit last time gives the same grids as
        # clearing everything, wherever the viewer walks.
        game_map, _ = generate_dungeon(50, 20, rng=random.Random(4))
        h, w = len(game_map), len(game_map[0])
        floor = [(x, y) for y in range(h) for x in range(w) if game_map[y][x] != WALL]
        rng = random.Random(5)
        visible, seen = self._grid(w, h), self._grid(w, h)
        full_visible, full_seen = self._grid(w, h), self._grid(w, h)
        lit = None
        for _ in range(60):
            x, y = rng.choice(floor)
            lit = update_visibility(game_map, visible, seen, x, y, 6, lit)
            update_visibility(game_map, full_visible, full_seen, x, y, 6)
            self.assertEqual(visible, full_visible)
            self.assertEqual(seen, full_seen)
            self.assertEqual(
                lit, {(tx, ty) for ty in range(h) for tx in range(w) if visible[ty][tx]}
            )


class MonsterTests(unittest.TestCase):
    # 7x7 open room, floor from (1,1) to (5,5).
    ROOM = ['#######'] + ['#.....#'] * 5 + ['#######']

    def room_map(self):
        return [list(row) for row in self.ROOM]

    def test_chases_player_within_range(self):
        random.seed(5)
        game_map = [list(row) for row in ['#' * 12] + ['#' + '.' * 10 + '#'] * 3 + ['#' * 12]]
        player = Entity(2, 2, '@')
        m = Monster(8, 2, 'goblin')
        m.take_turn(player, game_map)
        self.assertLess(m.x, 8)  # stepped toward the player

    def test_an_orthogonal_neighbour_attacks_instead_of_moving(self):
        with self.subTest('corridor'):
            game_map = [list(row) for row in ['#####', '#...#', '#####']]
            player = Entity(2, 1, '@')
            m = Monster(3, 1, 'goblin')
            self.assertEqual(m.take_turn(player, game_map), 'attack')
            self.assertEqual((m.x, m.y), (3, 1))  # did not move
        for make_map, (px, py), occupied in (
            (self.room_map, (3, 3), None),
            (lambda: room_with(11, 11), (5, 5), {(5, 5)}),
        ):
            for dx, dy in ORTHOGONAL_STEPS:
                with self.subTest(occupied=occupied, offset=(dx, dy)):
                    game_map = make_map()
                    player = Entity(px, py, '@')
                    m = Monster(px + dx, py + dy, 'goblin')
                    if occupied is None:
                        self.assertEqual(m.take_turn(player, game_map), 'attack')
                    else:
                        result = m.take_turn(player, game_map, occupied=occupied)
                        self.assertEqual(result, 'attack')
                    self.assertEqual((m.x, m.y), (px + dx, py + dy))

    def test_a_diagonal_neighbour_is_not_attacked_and_closes_in(self):
        """The bug: a diagonal monster used to get a free hit the player had
        no legal move to answer, since the player only moves 4-way. Making the
        attack orthogonal is only half the fix: the monster must still be able
        to reach a square it can attack from."""
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            with self.subTest(offset=(dx, dy)):
                game_map = self.room_map()
                player = Entity(3, 3, '@')
                m = Monster(3 + dx, 3 + dy, 'goblin')
                self.assertNotEqual(m.take_turn(player, game_map), 'attack')
                self.assertTrue(m.is_adjacent(player), 'failed to close in')
                self.assertEqual(m.take_turn(player, game_map), 'attack')

    def test_chase_falls_back_to_the_other_axis_when_blocked(self):
        """Diagonal deltas with the corner walled off used to stall the
        monster outright, because the whole diagonal step was rejected."""
        game_map = [list(r) for r in ['#####', '#...#', '#.#.#', '#...#', '#####']]
        player = Entity(1, 1, '@')
        m = Monster(3, 3, 'goblin')  # (2, 2) between them is wall
        m.take_turn(player, game_map)
        self.assertNotEqual((m.x, m.y), (3, 3))
        self.assertTrue(is_walkable(game_map, m.x, m.y))

    def test_monster_moves_only_orthogonally_and_never_onto_the_player(self):
        """The invariant that lets take_turn drop its old "don't step on the
        player" guard: with orthogonal steps and orthogonal adjacency, a step
        onto the player's tile is unreachable by construction."""
        random.seed(21)
        allowed = set(ORTHOGONAL_STEPS) | {(0, 0)}
        for px in range(1, 6):
            for py in range(1, 6):
                for mx in range(1, 6):
                    for my in range(1, 6):
                        if (mx, my) == (px, py):
                            continue
                        game_map = self.room_map()
                        player = Entity(px, py, '@')
                        m = Monster(mx, my, 'goblin')
                        m.take_turn(player, game_map)
                        self.assertIn((m.x - mx, m.y - my), allowed)
                        self.assertNotEqual((m.x, m.y), (px, py))


def in_room(room, m):
    return room.x1 <= m.x < room.x2 and room.y1 <= m.y < room.y2


_ROOMS_CACHE = {}


def seeded_floors(depth, n=200, sizes=((40, 20), (50, 20))):
    """(rooms, monsters, boss_room) for n seeded floors at `depth`."""
    for seed in range(n):
        w, h = sizes[seed % len(sizes)]
        key = (seed, w, h)
        if key not in _ROOMS_CACHE:  # generation dominates; spawning is cheap
            random.seed(seed)
            _ROOMS_CACHE[key] = generate_dungeon(w, h)[1]
        rooms = _ROOMS_CACHE[key]
        monsters, boss_room = spawn_level(rooms, depth, rng=random.Random(seed))
        yield rooms, monsters, boss_room


class SpawnRuleTests(unittest.TestCase):
    """game/spawn.py: one enemy kind per room, pack sizes by depth, orc
    pairs never touching, and the boss arena."""

    def test_goblin_pack_size_by_depth(self):
        for d in range(1, 5):
            self.assertEqual(goblin_pack_size(d), 1)
        for d in range(5, 8):
            self.assertEqual(goblin_pack_size(d), 2)
        for d in range(8, 11):
            self.assertEqual(goblin_pack_size(d), 3)
        for d in range(11, 13):
            self.assertEqual(goblin_pack_size(d), 4)
        for d in range(13, 200):
            self.assertEqual(goblin_pack_size(d), 5)

    def test_start_room_is_empty_and_every_other_room_has_exactly_one_kind(self):
        for depth in (1, 3, 6, 8, 9, 12, 16, 30):
            for rooms, monsters, boss_room in seeded_floors(depth, n=100):
                self.assertFalse(
                    [m for m in monsters if in_room(rooms[0], m)], f'start room at {depth}'
                )
                for room in rooms[1:]:
                    here = [m for m in monsters if in_room(room, m)]
                    self.assertTrue(here, f'empty room at depth {depth}')
                    kinds = {(m.kind, m.is_boss) for m in here if not m.is_boss}
                    if room is boss_room:
                        self.assertTrue(any(m.is_boss for m in here))
                        self.assertLessEqual(len(kinds), 1)
                    else:
                        self.assertEqual(len(kinds), 1)
        # The same on hand-made rooms.
        rooms = [Rect(1, 1, 8, 8), Rect(20, 1, 8, 8), Rect(1, 12, 8, 6)]
        for seed in range(50):
            for depth in (1, 8, 12):
                monsters, _ = spawn_level(rooms, depth, random.Random(seed))
                self.assertTrue(monsters)
                for m in monsters:
                    self.assertFalse(in_room(rooms[0], m))

    def test_goblin_packs_follow_the_depth_size(self):
        for depth in (1, 4, 5, 8, 11, 13, 20):
            for _rooms, monsters, _boss_room in seeded_floors(depth, n=100):
                for room in _rooms[1:]:
                    gob = [m for m in monsters if in_room(room, m) and m.kind == 'goblin']
                    if gob:
                        self.assertEqual(len(gob), goblin_pack_size(depth))
                        self.assertLessEqual(len(gob), 5)

    def test_orcs_are_single_through_the_first_boss_floor_then_spread_pairs(self):
        seen_orc = False
        for depth in (1, 4, 7, 8):
            for rooms, monsters, boss_room in seeded_floors(depth, n=100):
                for room in rooms[1:]:
                    if room is boss_room:
                        continue
                    orcs = [m for m in monsters if in_room(room, m) and m.kind == 'orc']
                    self.assertLessEqual(len(orcs), 1)
                    seen_orc = seen_orc or bool(orcs)
        self.assertTrue(seen_orc)
        # After the first boss: pairs that never touch.
        pairs = 0
        for depth in (9, 12, 16, 25):
            for rooms, monsters, boss_room in seeded_floors(depth, n=150):
                for room in rooms[1:]:
                    if room is boss_room:
                        continue
                    orcs = [m for m in monsters if in_room(room, m) and m.kind == 'orc']
                    if orcs:
                        self.assertEqual(len(orcs), 2)
                        a, b = orcs
                        self.assertGreaterEqual(a.distance_to(b), 2)
                        pairs += 1
        self.assertGreater(pairs, 100)

    def test_both_kinds_appear_about_evenly(self):
        # Floor 3 has three rules of weight 1: goblins, an orc and a small slime.
        counts = {'goblin': 0, 'orc': 0, 'slime_small': 0}
        for rooms, monsters, _ in seeded_floors(3, n=300):
            for room in rooms[1:]:
                counts[[m for m in monsters if in_room(room, m)][0].kind] += 1
        total = sum(counts.values())
        for kind, n in counts.items():
            self.assertLess(abs(n / total - 1 / 3), 0.06, kind)

    def test_boss_floors_have_a_centred_boss_and_the_first_one_an_escort(self):
        with self.subTest('first boss floor: one adjacent orc escort'):
            for rooms, monsters, boss_room in seeded_floors(FIRST_BOSS_DEPTH, n=200):
                self.assertIsNotNone(boss_room)
                self.assertIsNot(boss_room, rooms[0])
                bosses = [m for m in monsters if m.is_boss]
                self.assertEqual(len(bosses), 1)
                boss = bosses[0]
                self.assertEqual((boss.x, boss.y), boss_room.center())
                others = [m for m in monsters if in_room(boss_room, m) and not m.is_boss]
                self.assertEqual(len(others), 1)
                escort = others[0]
                self.assertEqual(escort.kind, 'orc')
                self.assertTrue(escort.is_adjacent(boss))
        with self.subTest('later boss floors: no escort'):
            self.assertNotIn(16, BOSS_ESCORTS)
            for depth in (16, 24):
                for _rooms, monsters, boss_room in seeded_floors(depth, n=100):
                    here = [m for m in monsters if in_room(boss_room, m)]
                    self.assertEqual(len(here), 1)
                    self.assertTrue(here[0].is_boss)
                    self.assertEqual((here[0].x, here[0].y), boss_room.center())
        with self.subTest('no boss off boss floors'):
            for depth in (1, 7, 9, 15):
                for _, monsters, boss_room in seeded_floors(depth, n=30):
                    self.assertIsNone(boss_room)
                    self.assertFalse(any(m.is_boss for m in monsters))

    def test_a_new_rule_adds_a_kind(self):
        rules = (
            SpawnRule('goblin', 1, None, lambda d: 1, 1, False),
            SpawnRule('orc', 1, None, lambda d: 3, 1, True),
        )
        rooms = [Rect(1, 1, 4, 4), Rect(10, 1, 6, 6), Rect(20, 1, 6, 6)]
        for seed in range(50):
            monsters, _ = spawn_level(rooms, 2, rng=random.Random(seed), rules=rules)
            for room in rooms[1:]:
                here = [m for m in monsters if in_room(room, m)]
                self.assertEqual(len({m.kind for m in here}), 1)
                if here[0].kind == 'orc':
                    self.assertEqual(len(here), 3)
                    for i, a in enumerate(here):
                        for b in here[i + 1 :]:
                            self.assertGreaterEqual(a.distance_to(b), 2)
        # Spread tiles fit even in the smallest room.
        for seed in range(200):
            tiles = pick_tiles(Rect(1, 1, 4, 4), 3, random.Random(seed), spread=True)
            self.assertEqual(len(tiles), 3)


def open_floor_state(seed, fov_radius=6):
    """A GameState whose whole interior is floor, emptied of entities, with
    the player at (10, 10). Lets a test place monsters without the random
    dungeon getting in the way."""
    state = GameState(50, 20, fov_radius=fov_radius, seed=seed)
    state.game_map = [
        [
            WALL if x in (0, state.width - 1) or y in (0, state.height - 1) else FLOOR
            for x in range(state.width)
        ]
        for y in range(state.height)
    ]
    state.player.x, state.player.y = 10, 10
    state.entities = [state.player]
    state.update_fov()
    return state


class MonsterCollisionTests(unittest.TestCase):
    """Monsters must never stack on one tile, nor stand on the player."""

    CORRIDOR = ['#' * 12, '#' + '.' * 10 + '#', '#' * 12]

    def test_crowded_room_never_shares_a_tile(self):
        state = open_floor_state(60)
        state.player.hp = state.player.max_hp = 10**6
        # A tight 5x4 block of goblins right next to the player, so they all
        # want the same handful of tiles at once.
        for x in range(12, 17):
            for y in range(8, 12):
                m = Monster(x, y, 'goblin')
                m.power = 1
                state.entities.append(m)
        monsters = [e for e in state.entities if isinstance(e, Monster)]

        def check(when):
            spots = [(m.x, m.y) for m in monsters]
            self.assertEqual(len(spots), len(set(spots)), f'monsters stacked {when}')
            self.assertNotIn(
                (state.player.x, state.player.y), spots, f'a monster stood on the player {when}'
            )

        for turn in range(80):
            state.handle_action('wait')
            while state.step_monster_phase():
                check(f'mid-round on turn {turn}')  # one monster at a time
            check(f'after turn {turn}')
        self.assertFalse(state.game_over)

    def test_wanderers_never_share_a_tile(self):
        """The same, for monsters that never see the player (FOV radius 1)
        and so only ever wander."""
        state = open_floor_state(61, fov_radius=1)
        for x in range(30, 35):
            for y in range(3, 7):
                state.entities.append(Monster(x, y, 'goblin'))
        monsters = [e for e in state.entities if isinstance(e, Monster)]
        for _ in range(150):
            state.end_turn()
            spots = [(m.x, m.y) for m in monsters]
            self.assertEqual(len(spots), len(set(spots)))
        self.assertTrue(all(not m.chasing for m in monsters))

    def test_a_blocked_monster_tries_its_other_axis_or_waits(self):
        with self.subTest('one-tile corridor: the rear chaser waits its turn'):
            # There is no other axis: it just waits rather than overlapping or swapping.
            game_map = [list(r) for r in self.CORRIDOR]
            player = Entity(1, 1, '@')
            front, rear = Monster(5, 1, 'goblin'), Monster(6, 1, 'goblin')
            occupied = {(player.x, player.y), (front.x, front.y)}
            self.assertIsNone(rear.take_turn(player, game_map, occupied=occupied))
            self.assertEqual((rear.x, rear.y), (6, 1))
            self.assertEqual((front.x, front.y), (5, 1))
        with self.subTest('open room: the chaser tries its other axis'):
            game_map = [list(r) for r in MonsterTests.ROOM]
            player = Entity(1, 1, '@')
            ahead = Monster(3, 3, 'goblin')
            m = Monster(4, 3, 'goblin')  # larger gap is x, but (3, 3) is taken
            m.take_turn(player, game_map, occupied={(1, 1), (ahead.x, ahead.y)})
            self.assertEqual((m.x, m.y), (4, 2))
        with self.subTest('boxed-in wanderer stays put'):
            game_map = [list(r) for r in MonsterTests.ROOM]
            player = Entity(5, 5, '@')
            m = Monster(2, 2, 'goblin')
            occupied = {(2 + dx, 2 + dy) for dx, dy in ORTHOGONAL_STEPS} | {(5, 5)}
            random.seed(62)
            for _ in range(30):
                self.assertIsNone(
                    m.take_turn(player, game_map, occupied=occupied, sees_player=False)
                )
                self.assertEqual((m.x, m.y), (2, 2))

    def test_adjacent_monsters_both_reach_the_player_without_overlapping(self):
        state = open_floor_state(63)
        state.player.hp = state.player.max_hp = 10**6
        # `behind` is lined up on a's row; `offset` is a row below it.
        a = Monster(13, 10, 'goblin')
        behind = Monster(14, 10, 'goblin')
        offset = Monster(14, 11, 'goblin')
        state.entities += [a, behind, offset]
        for _ in range(8):
            state.end_turn()
            spots = [(m.x, m.y) for m in (a, behind, offset)]
            self.assertEqual(len(spots), len(set(spots)))
        self.assertTrue(a.is_adjacent(state.player))
        self.assertTrue(offset.is_adjacent(state.player))
        # With its line blocked by a, the one behind walks round to another
        # lane (the lane chase) instead of queueing up behind a, and gets a
        # side of the player too -- without ever overlapping anyone.
        self.assertTrue(behind.is_adjacent(state.player))

    def test_no_two_monsters_spawn_on_one_tile(self):
        for seed in range(100):
            random.seed(seed)
            game_map, rooms = generate_dungeon(40, 20)
            for depth in (1, 8, 9, 16):
                monsters, _ = spawn_level(rooms, depth, rng=random.Random(seed))
                spots = [(m.x, m.y) for m in monsters]
                self.assertEqual(len(spots), len(set(spots)))
                self.assertNotIn(rooms[0].center(), spots)


class ChaseGiveUpTests(unittest.TestCase):
    """A chasing monster that goes GIVE_UP_AFTER turns in a row without
    seeing the player stops pursuing and wanders again."""

    def corridor(self):
        return [list(r) for r in ['#' * 20, '#' + '.' * 18 + '#', '#' * 20]]

    def test_stops_after_exactly_three_blind_turns_and_not_before(self):
        self.assertEqual(GIVE_UP_AFTER, 3)
        game_map = self.corridor()
        player = Entity(1, 1, '@')
        m = Monster(1 + CHASE_RANGE, 1, 'goblin')
        m.take_turn(player, game_map, sees_player=True)
        self.assertTrue(m.chasing)
        self.assertEqual(m.lost_sight, 0)

        for miss in range(1, GIVE_UP_AFTER):
            x_before = m.x
            m.take_turn(player, game_map, sees_player=False)
            self.assertTrue(m.chasing, f'gave up after only {miss} blind turn(s)')
            self.assertEqual(m.lost_sight, miss)
            self.assertEqual(m.x, x_before - 1, 'stopped closing in while still chasing')

        x_before = m.x
        m.take_turn(player, game_map, sees_player=False)  # the third miss
        self.assertEqual(m.x, x_before - 1, 'the third blind turn is still a chase step')
        self.assertFalse(m.chasing)
        self.assertEqual(m.lost_sight, 0)

    def test_gave_up_monster_wanders_instead_of_chasing(self):
        game_map = self.corridor()
        player = Entity(1, 1, '@')
        m = Monster(12, 1, 'goblin')
        m.chasing, m.lost_sight = True, GIVE_UP_AFTER - 1
        m.take_turn(player, game_map, sees_player=False)
        self.assertFalse(m.chasing)
        random.seed(64)
        moves = set()
        for _ in range(40):
            before = m.x
            m.take_turn(player, game_map, sees_player=False)
            moves.add(m.x - before)
            self.assertFalse(m.chasing)
        self.assertIn(1, moves, 'never stepped away from the player: still chasing?')

    def test_counter_resets_when_sight_returns(self):
        game_map = self.corridor()
        player = Entity(1, 1, '@')
        m = Monster(1 + CHASE_RANGE, 1, 'goblin')
        m.take_turn(player, game_map, sees_player=True)
        m.take_turn(player, game_map, sees_player=False)
        m.take_turn(player, game_map, sees_player=False)
        self.assertEqual(m.lost_sight, GIVE_UP_AFTER - 1)

        m.take_turn(player, game_map, sees_player=True)
        self.assertTrue(m.chasing)
        self.assertEqual(m.lost_sight, 0)

        # Two more misses would make four in total: still chasing, because
        # only *consecutive* blind turns count.
        m.take_turn(player, game_map, sees_player=False)
        m.take_turn(player, game_map, sees_player=False)
        self.assertTrue(m.chasing)
        self.assertEqual(m.lost_sight, GIVE_UP_AFTER - 1)

    def test_unseen_monster_does_not_start_chasing(self):
        game_map = self.corridor()
        player = Entity(1, 1, '@')
        m = Monster(5, 1, 'goblin')
        random.seed(65)
        for _ in range(10):
            m.take_turn(player, game_map, sees_player=False)
            self.assertFalse(m.chasing)

    def test_game_state_uses_the_players_fov_for_sight(self):
        """End to end: with FOV radius 2, a chaser 8 tiles away is out of
        sight on each of its next three turns (8, 7, 6 tiles off), so it
        gives up on exactly the third round; one in view keeps chasing."""
        with self.subTest('out of view: gives up on the third round'):
            state = open_floor_state(66, fov_radius=2)
            m = Monster(state.player.x + 8, state.player.y, 'goblin')
            m.chasing = True
            state.entities.append(m)
            self.assertFalse(state.is_visible(m.x, m.y))

            for rnd in range(1, GIVE_UP_AFTER):
                state.end_turn()
                self.assertTrue(m.chasing, f'gave up after round {rnd}')
                self.assertEqual(m.lost_sight, rnd)
            state.end_turn()
            self.assertFalse(m.chasing)
            self.assertEqual(m.x, state.player.x + 8 - GIVE_UP_AFTER)
        with self.subTest('in view: keeps chasing'):
            state = open_floor_state(67)
            m = Monster(state.player.x + 5, state.player.y, 'goblin')
            state.entities.append(m)
            self.assertTrue(state.is_visible(m.x, m.y))
            state.end_turn()
            self.assertTrue(m.chasing)
            self.assertEqual(m.lost_sight, 0)
            self.assertEqual(m.x, state.player.x + 4)


def room_with(w, h, walls=()):
    """A w x h map: wall border, floor inside, plus `walls` (x, y) tiles."""
    game_map = make_empty_map(w, h, WALL)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            game_map[y][x] = FLOOR
    for x, y in walls:
        game_map[y][x] = WALL
    return game_map


class LaneChaseTests(unittest.TestCase):
    """A chaser heads for the nearest tile on the player's row or column with
    a clear line to the player (where the archer's arrows fly), rather than
    closing in greedily and sliding past diagonally."""

    def in_clear_line(self, m, player, game_map, occupied=()):
        return (m.x, m.y) in lane_tiles(player, game_map, occupied)

    def test_off_line_monster_gets_in_line_first_and_stays_there(self):
        game_map = room_with(15, 11)
        player = Entity(4, 3, '@')
        m = Monster(8, 6, 'goblin')  # 4 across, 3 down: nearest lane is 3 moves
        for _ in range(3):
            m.take_turn(player, game_map)
        self.assertEqual((m.x, m.y), (8, 3), "on the player's row after 3 moves")
        while not m.is_adjacent(player):
            self.assertTrue(self.in_clear_line(m, player, game_map))
            m.take_turn(player, game_map)
        self.assertEqual(m.take_turn(player, game_map), 'attack')

    def test_two_diagonal_gets_in_line_within_two_moves(self):
        for dx, dy in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
            game_map = room_with(11, 11)
            player = Entity(5, 5, '@')
            m = Monster(5 + dx, 5 + dy, 'goblin')
            m.take_turn(player, game_map)
            m.take_turn(player, game_map)
            self.assertTrue(m.x == player.x or m.y == player.y, (dx, dy))
            self.assertTrue(self.in_clear_line(m, player, game_map), (dx, dy))

    def test_greedy_closing_would_not_have_lined_up(self):
        """The bug this fixes: greedily, a monster 3 across and 2 down closes
        x first and stays off the player's lanes until it is adjacent."""
        game_map = room_with(11, 11)
        player = Entity(5, 5, '@')
        m = Monster(8, 7, 'goblin')
        self.assertEqual(m._greedy_step(player, game_map), (-1, 0))
        self.assertEqual(m._chase_step(player, game_map), (0, -1))

    def test_routes_round_a_wall_by_the_shortest_way(self):
        """A wall right between the monster and the player used to stall the
        greedy chase; now it walks round to the nearest lane tile."""
        # Wall on row 5 from x=3 to x=9; player below it, monster above.
        game_map = room_with(15, 11, [(x, 5) for x in range(3, 10)])
        player = Entity(6, 8, '@')
        m = Monster(6, 2, 'goblin')
        # Lane tiles (2, 8) and (10, 8) are both 10 moves away; (2, 8) has
        # the lower x, the last tie-break.
        for turn in range(10):
            before = (m.x, m.y)
            self.assertIsNone(m.take_turn(player, game_map))
            self.assertNotEqual((m.x, m.y), before, f'stalled on turn {turn}')
            self.assertEqual(abs(m.x - before[0]) + abs(m.y - before[1]), 1)
        self.assertEqual((m.x, m.y), (2, 8))
        self.assertTrue(self.in_clear_line(m, player, game_map))

    def test_search_is_bounded_and_falls_back_to_the_greedy_step(self):
        # Wall on row 5 except a gap at x=13: the nearest lane tile, (13, 8),
        # is 13 moves away -- one past the search limit.
        game_map = room_with(15, 11, [(x, 5) for x in range(1, 13)])
        player = Entity(6, 8, '@')
        m = Monster(6, 2, 'goblin')
        self.assertEqual(LANE_SEARCH_LIMIT, 12)
        lanes = lane_tiles(player, game_map, {(6, 8)})
        self.assertIsNone(m._route_to_lane(lanes, game_map, {(6, 8)}))
        self.assertEqual(m._chase_step(player, game_map, {(6, 8)}), (0, 1), 'greedy: south')
        with mock.patch('game.monster.LANE_SEARCH_LIMIT', 13):
            self.assertIsNotNone(m._route_to_lane(lanes, game_map, {(6, 8)}))

    def test_a_lane_stops_at_walls_doors_and_creatures(self):
        game_map = room_with(11, 11, [(5, 2)])
        game_map[5][8] = DOOR
        player = Entity(5, 5, '@')
        lanes = lane_tiles(player, game_map, {(5, 5), (2, 5)})
        self.assertEqual(
            lanes,
            {(5, 4), (5, 3)}  # north, up to the wall at (5, 2)
            | {(5, 6), (5, 7), (5, 8), (5, 9)}  # south, to the border
            | {(4, 5), (3, 5)}  # west, up to the monster at (2, 5)
            | {(6, 5), (7, 5), (8, 5)},  # east: the door, and nothing past it
        )

    def test_converging_monsters_never_share_a_tile(self):
        state = open_floor_state(68)
        state.player.hp = state.player.max_hp = 10**6
        monsters = []
        for x, y in ((13, 13), (14, 13), (13, 14), (7, 7), (6, 7), (7, 13), (13, 7), (12, 12)):
            m = Monster(x, y, 'goblin')
            m.power = 1
            monsters.append(m)
        state.entities += monsters
        for turn in range(20):
            state.handle_action('wait')
            while state.step_monster_phase():
                spots = [(m.x, m.y) for m in monsters]
                self.assertEqual(len(spots), len(set(spots)), f'stacked on turn {turn}')
                self.assertNotIn((state.player.x, state.player.y), spots)
        self.assertEqual(sum(m.is_adjacent(state.player) for m in monsters), 4)

    def test_still_gives_up_after_three_blind_turns(self):
        game_map = room_with(15, 11)
        player = Entity(3, 3, '@')
        m = Monster(9, 7, 'goblin')
        m.take_turn(player, game_map, sees_player=True)
        for miss in range(1, GIVE_UP_AFTER):
            m.take_turn(player, game_map, sees_player=False)
            self.assertTrue(m.chasing)
            self.assertEqual(m.lost_sight, miss)
        m.take_turn(player, game_map, sees_player=False)
        self.assertFalse(m.chasing)
        self.assertEqual((m.x, m.y), (9, 3), 'the blind turns were lane-chase steps')

    def test_twenty_chasers_on_a_big_map_stay_fast(self):
        rng = random.Random(69)
        w, h = 120, 60
        pillars = {(rng.randrange(2, w - 2), rng.randrange(2, h - 2)) for _ in range(900)}
        player = Entity(60, 30, '@')
        pillars -= {(player.x, player.y)}
        game_map = room_with(w, h, pillars)
        monsters = []
        while len(monsters) < 20:
            x, y = rng.randrange(40, 81), rng.randrange(15, 46)
            if game_map[y][x] == FLOOR and (x, y) != (player.x, player.y):
                if all((m.x, m.y) != (x, y) for m in monsters):
                    monsters.append(Monster(x, y, 'goblin'))
        start = time.perf_counter()
        for turn in range(50):
            dx, dy = ORTHOGONAL_STEPS[turn % 4]
            player.move(dx, dy, game_map)
            for m in monsters:
                # Keep every one chasing, even beyond CHASE_RANGE.
                m.chasing, m.lost_sight = True, 0
                occupied = {(player.x, player.y)} | {(o.x, o.y) for o in monsters if o is not m}
                m.take_turn(player, game_map, occupied=occupied, sees_player=True)
            spots = [(m.x, m.y) for m in monsters]
            self.assertEqual(len(spots), len(set(spots)))
        self.assertTrue(all(m.chasing for m in monsters))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f'1000 monster turns took {elapsed:.3f}s')


class GameStateIntegrationTests(unittest.TestCase):
    def test_initial_state(self):
        state = GameState(50, 20, seed=7)
        self.assertTrue(state.running)
        self.assertFalse(state.game_over)
        self.assertEqual(state.depth, 1)
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertIn(state.player, state.entities)

    def test_player_combat_kills_monster(self):
        state = GameState(50, 20, seed=8)
        state.entities = [state.player]
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        m.hp = 1
        state.entities.append(m)
        state.try_move_player(1, 0)
        self.assertFalse(m.alive)
        self.assertEqual(
            (state.player.x, state.player.y), (m.x - 1, m.y)
        )  # player did not step onto corpse tile
        self.assertIn('dies', state.messages[-1])

    def test_monster_attack_reduces_player_hp_and_can_kill(self):
        state = GameState(50, 20, seed=9)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        state.entities = [state.player, m]
        state.player.hp = 1
        state.end_turn()
        self.assertTrue(state.game_over)
        self.assertEqual(state.messages[-1], 'You died.')

    def test_descend_regenerates_the_level_only_on_the_stairs(self):
        state = GameState(50, 20, seed=11)
        sx, sy = place_stairs(state.game_map, state.rooms)
        state.player.x, state.player.y = sx, sy
        old_rooms = state.rooms
        handled = state.handle_action('descend')
        self.assertTrue(handled)
        self.assertEqual(state.depth, 2)
        self.assertIsNot(state.rooms, old_rooms)
        self.assertEqual((state.player.x, state.player.y), state.rooms[0].center())
        # Off the stairs: nothing.
        state = GameState(50, 20, seed=12)
        state.game_map[state.player.y][state.player.x] = FLOOR
        handled = state.handle_action('descend')
        self.assertFalse(handled)
        self.assertEqual(state.depth, 1)

    def test_ability_key_parries_in_play(self):
        state = GameState(50, 20, seed=13)
        turn = state.turn
        self.assertTrue(state.handle_action('ability'))  # a warrior's Q: parry
        self.assertTrue(state.parry_armed)
        self.assertEqual(state.turn, turn + 1)
        self.assertTrue(state.running)

    def test_restart_does_nothing_during_play(self):
        state = GameState(50, 20, seed=13)
        pos, turn, log = (state.player.x, state.player.y), state.turn, list(state.messages)
        self.assertFalse(state.handle_action('restart'))
        self.assertTrue(state.running)
        self.assertFalse(state.restart_requested)
        self.assertEqual(state.turn, turn)
        self.assertEqual((state.player.x, state.player.y), pos)
        self.assertEqual(state.messages, log)
        self.assertFalse(state.monster_phase_pending())

    def test_on_game_over_movement_is_blocked_and_q_quit_and_restart_end_the_run(self):
        with self.subTest('movement is blocked, quit still quits'):
            state = GameState(50, 20, seed=13)
            state.game_over = True
            px, py = state.player.x, state.player.y
            state.handle_action('move_n')
            self.assertEqual((state.player.x, state.player.y), (px, py))
            state.handle_action('quit')
            self.assertFalse(state.running)
        with self.subTest('restart ends the run and asks for a restart'):
            state = GameState(50, 20, seed=13)
            state.game_over = True
            self.assertFalse(state.handle_action('restart'))
            self.assertFalse(state.running)
            self.assertTrue(state.restart_requested)
        with self.subTest("q ('press q to quit') quits, and is not a restart"):
            state = GameState(50, 20, seed=13)
            state.game_over = True
            self.assertFalse(state.handle_action('ability'))
            self.assertFalse(state.running)
            self.assertFalse(state.restart_requested)


class TurnPhaseTests(unittest.TestCase):
    """The round is two halves: the player's, then the monsters' one at a
    time. Before this split every monster acted against the pre-round world,
    so a dead player still took hits from everyone else in the list."""

    def swarmed_state(self, player_hp, monster_power=2, offsets=((1, 0), (-1, 0), (0, 1))):
        state = GameState(50, 20, seed=30)
        state.player.hp = player_hp
        state.entities = [state.player]
        for dx, dy in offsets:
            m = Monster(state.player.x + dx, state.player.y + dy, 'goblin')
            m.power = monster_power
            state.entities.append(m)
        return state

    def test_a_death_stops_the_rest_of_the_round_and_is_logged_once(self):
        for player_hp in (3, 1):  # 3: dies to the 2nd of 3 goblins; 1: to the 1st
            with self.subTest(player_hp=player_hp):
                state = self.swarmed_state(player_hp=player_hp)
                state.end_turn()
                self.assertTrue(state.game_over)
                self.assertEqual([m for m in state.messages if m == 'You died.'], ['You died.'])
                self.assertEqual(state.messages[-1], 'You died.')
                if player_hp == 3:
                    hits = [m for m in state.messages if 'hits you' in m]
                    self.assertEqual(len(hits), 2, 'the third goblin swung at a corpse')
                    self.assertEqual(state.player.hp, -1)

    def test_survivor_round_lets_every_monster_act(self):
        state = self.swarmed_state(player_hp=50)
        state.end_turn()
        self.assertFalse(state.game_over)
        self.assertEqual(len([m for m in state.messages if 'hits you' in m]), 3)

    def test_handle_action_defers_the_monster_half(self):
        """The point of the split: the caller can draw the player's own
        action before anything answers it."""
        state = self.swarmed_state(player_hp=50, offsets=((2, 0),))
        state.handle_action('wait')
        self.assertTrue(state.monster_phase_pending())
        self.assertNotIn('hits you', ' '.join(state.messages))
        while state.step_monster_phase():
            pass
        self.assertFalse(state.monster_phase_pending())

    def test_monster_killed_in_the_player_half_leaves_at_once_and_never_acts(self):
        """The renderer draws mid-round, so a corpse must stop being drawn the
        moment it dies rather than at the end of the round."""
        state = GameState(50, 20, seed=31)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        m.hp = 1
        state.entities = [state.player, m]
        state.handle_action('move_e')  # bump-attack kills it
        self.assertFalse(m.alive)
        self.assertNotIn(m, state.visible_entities())
        state.end_turn()
        self.assertNotIn('hits you', ' '.join(state.messages))

    def test_a_step_reports_a_frame_only_for_what_the_player_can_see(self):
        with self.subTest('an attack is visible'):
            state = self.swarmed_state(player_hp=50, offsets=((1, 0),))
            state.end_player_phase()
            self.assertTrue(state.step_monster_phase())  # the attack
            self.assertFalse(state.step_monster_phase())  # queue drained
        with self.subTest('a monster out of sight resolves without a frame'):
            # A monster shuffling around in the dark must not cost the player a
            # held frame, or walking an empty dungeon would crawl.
            state = GameState(50, 20, seed=33)
            # Pick a floor tile the player genuinely cannot see, so the assertion
            # below can't pass just because the monster happened to sit still.
            hidden = [
                (x, y)
                for y in range(1, state.height - 1)
                for x in range(1, state.width - 1)
                if is_walkable(state.game_map, x, y)
                and not state.is_visible(x, y)
                and state.player.distance_to(Entity(x, y, '.')) > state.fov_radius + 1
            ]
            self.assertTrue(hidden, 'no out-of-sight floor tile to test with')
            state.entities = [state.player, Monster(hidden[0][0], hidden[0][1], 'goblin')]
            state.end_player_phase()
            self.assertTrue(state.monster_phase_pending())
            self.assertFalse(state.step_monster_phase())  # acted, but nothing to show
            self.assertFalse(state.monster_phase_pending())

    def test_the_monster_half_does_not_recompute_fov(self):
        """What the player sees depends on the map and the player's tile
        only -- monsters don't block sight -- so the FOV end_player_phase
        computes holds for the whole monster half."""
        state = self.swarmed_state(player_hp=500, offsets=((3, 0), (0, 3), (-3, 0), (1, 0)))
        state.handle_action('wait')
        fresh = [row[:] for row in state.visible]
        with mock.patch.object(state, 'update_fov', wraps=state.update_fov) as update:
            frames = 0
            while state.step_monster_phase():
                frames += 1
                self.assertEqual(state.visible, fresh)
        self.assertGreater(frames, 0)
        update.assert_not_called()
        state.update_fov()
        self.assertEqual(state.visible, fresh)

    def test_descending_cancels_a_queued_monster_phase(self):
        state = GameState(50, 20, seed=34)
        state.end_player_phase()
        sx, sy = place_stairs(state.game_map, state.rooms)
        state.player.x, state.player.y = sx, sy
        state.handle_action('descend')
        self.assertFalse(state.monster_phase_pending())


class ClassAndArcherTests(unittest.TestCase):
    def test_default_and_unknown_class_is_warrior(self):
        self.assertEqual(GameState(50, 20, seed=20).player.char_class, 'warrior')
        state = GameState(50, 20, char_class='paladin', seed=21)
        self.assertEqual(state.player.char_class, 'warrior')

    def test_archer_has_different_stats_and_sees_two_farther(self):
        warrior = GameState(50, 20, char_class='warrior', seed=22)
        archer = GameState(50, 20, char_class='archer', seed=22)
        self.assertNotEqual(warrior.player.max_hp, archer.player.max_hp)
        self.assertNotEqual(warrior.player.power, archer.player.power)
        self.assertEqual(GameState(50, 20, fov_radius=6, seed=22).fov_radius, 6)
        archer = GameState(50, 20, fov_radius=6, char_class='archer', seed=22)
        self.assertEqual(archer.fov_radius, 6 + ARCHER_FOV_BONUS)
        self.assertEqual(ARCHER_FOV_BONUS, 2)

    def test_archer_arrow_kills_a_monster_in_line_and_never_moves_the_player(self):
        state = GameState(50, 20, char_class='archer', seed=24)
        m = Monster(state.player.x + 3, state.player.y, 'goblin')
        m.hp = 1
        state.entities = [state.player, m]
        px, py = state.player.x, state.player.y
        state.shoot_arrow(1, 0)
        self.assertFalse(m.alive)
        self.assertEqual((state.player.x, state.player.y), (px, py))  # arrow, not player, moved
        state = GameState(50, 20, char_class='archer', seed=26)
        state.entities = [state.player]
        px, py = state.player.x, state.player.y
        state.handle_action('shoot_n')
        self.assertEqual((state.player.x, state.player.y), (px, py))

    def test_archer_arrow_passes_over_empty_tiles_and_hits_wall(self):
        state = GameState(50, 20, char_class='archer', seed=25)
        state.entities = [state.player]
        state.shoot_arrow(1, 0)  # should not raise even with nothing in the way
        self.assertIn('wall', state.messages[-1])


class ArcherHopTests(unittest.TestCase):
    def _arena(self, monster_dx=-2, monster_dy=0):
        state = GameState(20, 20, char_class='archer', seed=0)
        state.game_map = make_empty_map(20, 20, WALL)
        for y in range(1, 19):
            for x in range(1, 19):
                state.game_map[y][x] = FLOOR
        state.player.x, state.player.y = 10, 10
        state.player.defense = 0
        mon = Monster(10 + monster_dx, 10 + monster_dy, 'goblin')
        state.entities = [state.player, mon]
        state.update_fov()
        return state, mon

    def hop(self, state, direction='move_e'):
        """Q, then `direction`: the directional hop. Returns what the
        direction key's handle_action returned."""
        self.assertFalse(state.handle_action('ability'))  # priming: no turn
        return state.handle_action(direction)

    def test_q_primes_the_hop_and_takes_no_turn(self):
        state, mon = self._arena()
        turn = state.turn
        self.assertFalse(state.handle_action('ability'))
        self.assertTrue(state.hop_primed)
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertEqual((state.player.x, state.player.y), (10, 10))
        self.assertEqual((mon.x, mon.y), (8, 10))
        self.assertEqual(state.messages[-1], 'Hop ready: pick a direction.')

    def test_hop_moves_two_tiles_or_stops_in_front_of_a_monster(self):
        # (monster offset, direction key) -> landing tile
        for offset, key, landing in (
            ((-2, 0), 'move_e', (12, 10)),
            ((-2, 0), 'move_n', (10, 8)),
            ((-3, 0), 'move_w', (8, 10)),  # toward the monster at (7, 10)
            ((-2, 0), 'shoot_s', (10, 12)),  # an arrow key picks a direction too
        ):
            with self.subTest(key=key, offset=offset):
                state, mon = self._arena(*offset)
                monster_at, hp, quiver = (mon.x, mon.y), mon.hp, state.player.quiver
                self.assertTrue(self.hop(state, key))
                self.assertEqual((state.player.x, state.player.y), landing)
                self.assertFalse(state.hop_primed)
                self.assertEqual((mon.x, mon.y), monster_at)
                # ... and shoots nothing.
                self.assertEqual((mon.hp, state.player.quiver), (hp, quiver))
                self.assertEqual(state.events_of(Shot), [])

    def test_hop_takes_a_turn_and_monsters_act(self):
        state, mon = self._arena()
        turn = state.turn
        self.hop(state)
        self.assertEqual(state.turn, turn + 1)
        while state.step_monster_phase():
            pass
        self.assertNotEqual((mon.x, mon.y), (8, 10))  # it acted after the hop

    def test_hop_stops_at_a_wall_a_door_a_chest_and_a_shrine(self):
        for blocker in ('wall', 'door', 'chest', 'shrine'):
            with self.subTest(blocker):
                state, _ = self._arena()
                chest = Chest(12, 10, kind='gear')
                if blocker == 'wall':
                    state.game_map[10][12] = WALL
                elif blocker == 'door':
                    state.game_map[10][12] = DOOR
                elif blocker == 'chest':
                    state.entities.append(chest)
                else:
                    state.entities.append(Shrine(12, 10))
                self.hop(state)
                self.assertEqual((state.player.x, state.player.y), (11, 10))
                if blocker == 'chest':
                    self.assertIn(chest, state.entities)  # not opened
                if blocker == 'shrine':
                    self.assertFalse(state.is_choosing)

    def test_priming_needs_no_monster_in_range(self):
        state, _ = self._arena(-5, 0)
        state.entities = [state.player]  # nobody at all
        self.assertFalse(state.handle_action('ability'))
        self.assertTrue(state.hop_primed)
        self.assertNotIn('Nothing to hop from.', state.messages)
        self.assertTrue(state.handle_action('move_e'))
        self.assertEqual(state.player.x, 12)

    def test_a_non_movement_key_or_a_second_q_cancels_the_prime_with_no_turn(self):
        for action in ('wait', 'drink', 'descend', 'choose_1', 'skip'):
            with self.subTest(action):
                state, mon = self._arena()
                state.handle_action('ability')
                turn = state.turn
                self.assertFalse(state.handle_action(action))
                self.assertFalse(state.hop_primed)
                self.assertEqual(state.turn, turn)
                self.assertFalse(state.monster_phase_pending())
                self.assertEqual(state.messages[-1], 'Hop cancelled.')
                self.assertEqual((state.player.x, state.player.y), (10, 10))
                # The key after that is an ordinary move again.
                self.assertTrue(state.handle_action('move_e'))
                self.assertEqual(state.player.x, 11)
        with self.subTest('ability'):
            state, _ = self._arena()
            turn = state.turn
            self.assertFalse(state.handle_action('ability'))
            self.assertFalse(state.handle_action('ability'))
            self.assertFalse(state.hop_primed)
            self.assertEqual(state.turn, turn)
            self.assertEqual(state.messages[-1], 'Hop cancelled.')
            self.assertIsNone(state.last_hop_turn)  # no cooldown started
            self.assertTrue(self.hop(state))  # and Q primes again

    def test_cooldown_four_turns(self):
        state, mon = self._arena()
        self.hop(state)
        state.cancel_monster_phase()
        for left in (4, 3, 2, 1):
            turn = state.turn
            self.assertFalse(state.handle_action('ability'))
            self.assertEqual(state.messages[-1], f'Hop recovering ({left} turns).')
            self.assertFalse(state.hop_primed)
            self.assertEqual(state.turn, turn)
            state.handle_action('wait')
            state.cancel_monster_phase()
            mon.x, mon.y = 1, 1  # out of the way
        px = state.player.x
        self.assertTrue(self.hop(state, 'move_w'))
        self.assertEqual(state.player.x, px - 2)

    def test_warrior_q_parries_instead_of_hopping(self):
        state, _ = self._arena()
        state.player.char_class = 'warrior'
        turn = state.turn
        self.assertTrue(state.handle_action('ability'))
        self.assertEqual((state.turn, state.player.x), (turn + 1, 10))
        self.assertTrue(state.parry_armed)
        self.assertFalse(state.hop_crit)
        self.assertFalse(state.hop_primed)
        self.assertTrue(state.handle_action('move_e'))  # an ordinary step
        self.assertEqual(state.player.x, 11)

    def test_successful_hop_arms_a_crit_for_the_next_shot_only(self):
        state, mon = self._arena()
        mon.hp = mon.max_hp = 1000
        mon.defense = 0
        # round_damage rounds a fractional hit up or down at random, in the game
        # and again in the expectation below: pin the state's random() so both
        # round alike.
        with (
            mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0),
            mock.patch.object(state.rng, 'random', return_value=0.0),
        ):
            self.assertFalse(state.handle_action('ability'))
            self.assertFalse(state.hop_crit)  # primed, not hopped yet
            self.assertTrue(state.handle_action('move_e'))
            self.assertTrue(state.hop_crit)
            state.cancel_monster_phase()
            power = state.player.power
            self.assertTrue(state.handle_action('shoot_w'))
            (hit,) = state.hits()
            self.assertTrue(hit.crit)
            self.assertEqual(
                hit.damage, round_damage(mitigate(power * CRIT_MULTIPLIER, 0), state.rng)
            )
            self.assertIn('Critical hit!', state.messages)
            self.assertFalse(state.hop_crit)
            state.cancel_monster_phase()
            state.handle_action('shoot_w')  # the one after: no crit
            (hit,) = state.hits()
            self.assertFalse(hit.crit)
        # Q while the hop recovers is refused and arms nothing.
        state.cancel_monster_phase()
        self.assertFalse(state.handle_action('ability'))  # on cooldown
        self.assertFalse(state.hop_primed)
        self.assertFalse(state.hop_crit)

    def test_hop_crit_is_spent_by_a_missed_shot(self):
        state, mon = self._arena()
        mon.hp = mon.max_hp = 1000
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):
            self.hop(state)
            state.cancel_monster_phase()
            state.handle_action('shoot_n')  # into the wall: nothing hit
            self.assertEqual(state.hits(), [])
            self.assertFalse(state.hop_crit)
            state.cancel_monster_phase()
            state.handle_action('shoot_w')
            (hit,) = state.hits()
            self.assertFalse(hit.crit)

    def test_a_refused_direction_keeps_the_prime_and_arms_no_crit(self):
        state, _ = self._arena()
        state.game_map[10][11] = WALL
        turn = state.turn
        self.assertFalse(self.hop(state, 'move_e'))
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertEqual(state.messages[-1], 'Nowhere to hop.')
        self.assertEqual(state.player.x, 10)
        self.assertFalse(state.hop_crit)
        self.assertTrue(state.hop_primed)
        self.assertIsNone(state.last_hop_turn)
        # Another direction still hops.
        self.assertTrue(state.handle_action('move_s'))
        self.assertEqual((state.player.x, state.player.y), (10, 12))
        self.assertFalse(state.hop_primed)

    def test_pending_choice_blocks_hop(self):
        state, _ = self._arena()
        state.pending_choice = [Item(0, 0, 'weapon', 'common')]
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.hop_primed)
        self.assertEqual(state.player.x, 10)


class WarriorParryTests(unittest.TestCase):
    """A warrior at (10, 10) in an open arena, with an adjacent goblin to the
    west unless a test says otherwise."""

    def _arena(self, monster=True):
        state = GameState(20, 20, char_class='warrior', seed=0)
        state.game_map = make_empty_map(20, 20, WALL)
        for y in range(1, 19):
            for x in range(1, 19):
                state.game_map[y][x] = FLOOR
        p = state.player
        p.x, p.y = 10, 10
        p.hp = p.max_hp = 1000
        p.defense = 0
        state.entities = [p]
        mon = None
        if monster:
            mon = Monster(9, 10, 'goblin')
            mon.hp = mon.max_hp = 1000
            mon.power = 5
            mon.defense = 2
            state.entities.append(mon)
        state.update_fov()
        return state, mon

    def run_monsters(self, state):
        while state.step_monster_phase():
            pass

    def test_q_arms_a_parry_and_takes_a_turn_and_a_second_q_is_refused(self):
        state, _ = self._arena(monster=False)
        self.assertTrue(state.handle_action('ability'))
        self.assertTrue(state.parry_armed)
        self.assertEqual(state.turn, 1)
        self.assertEqual(state.messages[-1], 'You ready a parry.')
        turn = state.turn
        self.assertFalse(state.handle_action('ability'))
        self.assertEqual(state.turn, turn)
        self.assertEqual(state.messages[-1], 'Your parry is already ready.')
        self.assertFalse(state.monster_phase_pending())

    # The riposte's fractional damage is rounded at random, in the game and again
    # in the expectation below: pin the state's random() so both round the same way.
    def test_next_monster_hit_is_nullified_and_returns_crit_damage(self):
        state, mon = self._arena()
        self.enterContext(mock.patch.object(state.rng, 'random', return_value=0.0))
        assert mon is not None
        p = state.player
        state.handle_action('ability')
        self.run_monsters(state)
        self.assertFalse(state.parry_armed)
        # The goblin's blow is nullified: no damage, no Hit for it ...
        self.assertEqual(p.hp, 1000)
        (riposte,) = state.hits()
        # ... and the goblin takes raw power x CRIT_MULTIPLIER, less its defence.
        self.assertIs(riposte.attacker, p)
        self.assertIs(riposte.defender, mon)
        self.assertFalse(riposte.crit)
        expected = round_damage(mitigate(p.power * CRIT_MULTIPLIER, 2), state.rng)
        self.assertEqual(riposte.damage, expected)
        self.assertEqual(mon.hp, 1000 - expected)
        # The Parry names its riposte, which follows it in the stream.
        (parry,) = state.events_of(Parry)
        self.assertIs(parry.riposte, riposte)
        self.assertLess(state.events.index(parry), state.events.index(riposte))
        parried = state.messages.index("You parry the goblin's attack!")
        returned = state.messages.index('Your parry returns the blow to the goblin!')
        self.assertEqual(returned, parried + 1)
        self.assertEqual(state.messages[returned + 1], f'You hit goblin for {expected}.')
        self.assertNotIn('Goblin hits you', ' '.join(state.messages))
        # Spent: the next hit lands in full and is not answered.
        state.handle_action('wait')
        self.run_monsters(state)
        self.assertEqual([h.defender for h in state.hits()], [p])
        self.assertEqual(p.hp, 1000 - round_damage(mitigate(5, 0)))

    def test_a_parry_absorbs_a_blow_that_would_kill(self):
        state, mon = self._arena()
        assert mon is not None
        state.player.hp = 1
        state.handle_action('ability')
        self.run_monsters(state)
        self.assertEqual(state.player.hp, 1)
        self.assertFalse(state.game_over)
        self.assertEqual([h.defender for h in state.hits()], [mon])

    def test_only_the_first_of_two_blows_is_parried(self):
        state, mon = self._arena()
        assert mon is not None
        p = state.player
        other = Monster(11, 10, 'goblin')
        other.hp = other.max_hp = 1000
        other.power = 5
        state.entities.append(other)
        state.update_fov()
        state.handle_action('ability')
        self.run_monsters(state)
        self.assertEqual([(h.attacker, h.defender) for h in state.hits()], [(p, mon), (other, p)])
        self.assertEqual(other.hp, 1000)
        self.assertEqual(p.hp, 1000 - round_damage(mitigate(5, 0)))

    def test_parry_progress_fills_over_the_cooldown(self):
        state, _ = self._arena(monster=False)
        self.assertEqual(state.parry_progress(), PARRY_COOLDOWN)  # never used: ready
        state.handle_action('ability')
        self.assertEqual(state.parry_progress(), PARRY_COOLDOWN)  # armed: full
        state.parry_armed = False  # as if a monster's hit had spent it
        seen = [state.parry_progress()]
        for _ in range(PARRY_COOLDOWN + 2):
            state.handle_action('wait')
            seen.append(state.parry_progress())
        self.assertEqual(seen, [0, 1, 2, 3, 4, 4, 4])

    def test_parry_progress_is_empty_when_spent_on_the_turn_it_was_armed(self):
        state, _ = self._arena()
        state.handle_action('ability')
        self.run_monsters(state)  # the adjacent goblin swings at once
        self.assertFalse(state.parry_armed)
        self.assertEqual(state.parry_progress(), 0)
        for expected in (1, 2, 3, 4):
            state.handle_action('wait')
            state.cancel_monster_phase()
            self.assertEqual(state.parry_progress(), expected)
        self.assertTrue(state.handle_action('ability'))

    def test_the_parry_stays_armed_until_a_monster_blow_lands(self):
        with self.subTest("the warrior's own attack"):
            state, mon = self._arena()
            assert mon is not None
            state.handle_action('ability')
            state.cancel_monster_phase()
            state.handle_action('move_w')  # bump the goblin
            state.cancel_monster_phase()
            self.assertEqual([h.defender for h in state.hits()], [mon])
            self.assertTrue(state.parry_armed)
        with self.subTest('a dodged hit'):
            state, mon = self._arena()
            assert mon is not None
            state.player.armor = Item(0, 0, 'leather', 'epic')
            state.handle_action('ability')
            with mock.patch.object(state.rng, 'random', return_value=0.0):
                self.run_monsters(state)
            self.assertEqual(state.hits(), [])
            self.assertEqual(mon.hp, 1000)
            self.assertTrue(state.parry_armed)
        with self.subTest('no monster for ten turns'):
            state, _ = self._arena(monster=False)
            state.handle_action('ability')
            for _ in range(10):
                state.handle_action('wait')
                self.run_monsters(state)
            self.assertTrue(state.parry_armed)

    def test_cooldown_four_turns(self):
        state, _ = self._arena(monster=False)
        state.handle_action('ability')
        state.parry_armed = False  # as if a monster's hit had spent it
        for left in (4, 3, 2, 1):
            turn = state.turn
            self.assertFalse(state.handle_action('ability'))
            self.assertEqual(state.messages[-1], f'Parry recovering ({left} turns).')
            self.assertEqual(state.turn, turn)
            state.handle_action('wait')
        self.assertTrue(state.handle_action('ability'))
        self.assertTrue(state.parry_armed)

    def test_pending_choice_and_game_over_block_it(self):
        state, _ = self._arena(monster=False)
        state.pending_choice = [Item(0, 0, 'weapon', 'common')]
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.parry_armed)
        state.pending_choice = None
        state.game_over = True
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.parry_armed)
        self.assertFalse(state.running)  # Q quits on the death screen


class GearTests(unittest.TestCase):
    def test_invalid_rarity_rejected(self):
        with self.assertRaises(ValueError):
            Item(0, 0, 'weapon', 'legendary')

    def test_roll_rarity_always_valid(self):
        rng = random.Random(40)
        for depth in (1, 5, 10, 25):
            for _ in range(25):
                self.assertIn(roll_rarity(depth, rng), RARITIES)

    def test_potion_heal_scales_with_rarity(self):
        state = GameState(50, 20, seed=41)
        state.player.hp = 1
        common = Item(0, 0, 'potion', 'common')
        common.apply(state.player, state.log)
        common_hp = state.player.hp

        state.player.hp = 1
        epic = Item(0, 0, 'potion', 'epic')
        epic.apply(state.player, state.log)

        self.assertGreater(state.player.hp, common_hp)

    def test_equipping_a_weapon_replaces_the_old_one_without_stacking(self):
        state = GameState(50, 20, char_class='warrior', seed=42)
        base_power = state.player.base_power
        weapon = Item(0, 0, 'weapon', 'rare')
        weapon.apply(state.player, state.log)
        self.assertIs(state.player.weapon, weapon)
        self.assertEqual(state.player.power, base_power + cast(int, weapon.bonus))
        # A better one: swapped, its bonus alone.
        w2 = Item(state.player.x, state.player.y, 'weapon', 'epic')
        w2.apply(state.player, state.log)
        self.assertEqual(state.player.power, base_power + cast(int, w2.bonus))
        self.assertIs(state.player.weapon, w2)
        self.assertIn('swap', state.messages[-1])
        # Gear is chosen now (GameState.choose), so applying it always
        # equips -- a worse one replaces it too.
        common = Item(state.player.x, state.player.y, 'weapon', 'common')
        common.apply(state.player, state.log)
        self.assertIs(state.player.weapon, common)
        self.assertEqual(state.player.power, base_power + cast(int, common.bonus))
        self.assertIn('swap', state.messages[-1])

    def test_equipping_armor_sets_defense_from_the_table_even_if_worse(self):
        state = GameState(50, 20, seed=54)
        Item(0, 0, 'armor', 'epic').apply(state.player, state.log)
        self.assertEqual(state.player.defense, 21)
        for rarity in ('common', 'uncommon', 'rare', 'common'):
            armor = Item(state.player.x, state.player.y, 'armor', rarity)
            armor.apply(state.player, state.log)
            self.assertIs(state.player.armor, armor)
            self.assertEqual(state.player.defense, ARMOR_DEFENSE[rarity])

    def test_armor_defense_table(self):
        self.assertEqual(ARMOR_DEFENSE, {'common': 3, 'uncommon': 6, 'rare': 12, 'epic': 21})
        for rarity in RARITIES:
            self.assertEqual(Item(0, 0, 'armor', rarity).bonus, ARMOR_DEFENSE[rarity])
            # Weapons keep the old power table.
            self.assertEqual(Item(0, 0, 'weapon', rarity).bonus, GEAR_BONUS[rarity])
        self.assertEqual(GEAR_BONUS, {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7})

    def test_junk_item_has_no_stats(self):
        junk = Item(0, 0, JUNK)
        self.assertEqual(junk.name, JUNK_NAME)
        self.assertEqual(junk.name, 'Rusty scrap')
        self.assertIsNone(junk.rarity)
        self.assertIsNone(junk.bonus)
        self.assertNotIn(junk.kind, GEAR_SLOTS)

    def test_armor_reduces_incoming_damage_with_floor_of_one(self):
        state = GameState(50, 20, seed=44)
        armor = Item(state.player.x, state.player.y, 'armor', 'epic')  # 21 defense
        armor.apply(state.player, state.log)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')  # power 2, less than defense
        state.entities = [state.player, m]
        hp_before = state.player.hp
        state.attack(m, state.player)
        self.assertEqual(state.player.hp, hp_before - 1)  # damage floors at 1


class DifficultyScalingTests(unittest.TestCase):
    def test_tiers_of_three_floors_compound_hp_and_add_flat_power(self):
        self.assertEqual(tier_for_depth(1), 0)
        self.assertEqual(tier_for_depth(3), 0)
        self.assertEqual(tier_for_depth(4), 1)
        self.assertEqual(tier_for_depth(6), 1)
        self.assertEqual(tier_for_depth(7), 2)
        hp0, power0 = scale_stats(10, 5, depth=1)
        hp1, power1 = scale_stats(10, 5, depth=4)
        hp2, power2 = scale_stats(10, 5, depth=7)
        self.assertEqual((hp0, power0), (10, 5))
        self.assertEqual(power1, 6)
        self.assertEqual(power2, 7)
        self.assertGreater(hp1, hp0)
        self.assertGreater(hp2, hp1)
        # A spawned monster's stats are scale_stats of its base.
        base_hp, base_power = MONSTER_TYPES['goblin'][2], MONSTER_TYPES['goblin'][3]
        expected_hp, expected_power = scale_stats(base_hp, base_power, depth=10)
        m = Monster(0, 0, 'goblin', depth=10)
        self.assertEqual((m.hp, m.power), (expected_hp, expected_power))

    def test_orcs_have_20_percent_less_hp_through_floor_8_only(self):
        base, power = MONSTER_TYPES['orc'][2], MONSTER_TYPES['orc'][3]
        for depth in (1, 8):
            full, _ = scale_stats(base, power, depth)
            self.assertEqual(Monster(0, 0, 'orc', depth=depth).hp, round(full * 0.8))
        self.assertEqual(Monster(0, 0, 'orc', depth=1).hp, 22)
        self.assertEqual(Monster(0, 0, 'orc', depth=8).hp, 31)
        # Normal from floor 9.
        full, _ = scale_stats(base, power, 9)
        self.assertEqual(Monster(0, 0, 'orc', depth=9).hp, full)
        self.assertEqual(full, 39)
        # Goblins are untouched by it.
        base, power = MONSTER_TYPES['goblin'][2], MONSTER_TYPES['goblin'][3]
        for depth in (1, 9):
            full, _ = scale_stats(base, power, depth)
            self.assertEqual(Monster(0, 0, 'goblin', depth=depth).hp, full)

    def test_is_boss_level_every_eighth_floor(self):
        for d in (8, 16, 24):
            self.assertTrue(is_boss_level(d))
        for d in (1, 7, 9, 15):
            self.assertFalse(is_boss_level(d))

    def test_boss_stats_scale_off_reference_monster(self):
        depth = 8
        base_hp, base_power = (
            MONSTER_TYPES[BOSS_REFERENCE_KIND][2],
            MONSTER_TYPES[BOSS_REFERENCE_KIND][3],
        )
        reg_hp, reg_power = scale_stats(base_hp, base_power, depth)
        boss = spawn_boss(Rect(1, 1, 10, 10), depth)
        self.assertTrue(boss.is_boss)
        self.assertEqual(boss.hp, max(1, round(reg_hp * 2.0)))
        self.assertEqual(boss.power, max(1, round(reg_power * 1.5)))
        # The boss ignores the early orc reduction: 2 x 39 on floor 8.
        self.assertEqual(boss.hp, 78)

    def test_boss_spawns_on_boss_level_only(self):
        state = GameState(50, 20, seed=45)
        state.depth = 8
        monsters = state._spawn_level_monsters()
        self.assertTrue(any(getattr(m, 'is_boss', False) for m in monsters))

        state2 = GameState(50, 20, seed=46)
        state2.depth = 7
        monsters2 = state2._spawn_level_monsters()
        self.assertFalse(any(getattr(m, 'is_boss', False) for m in monsters2))

    def test_boss_death_drops_a_guaranteed_rare_or_epic_chest(self):
        state = GameState(50, 20, seed=47)
        boss = Monster(state.player.x + 1, state.player.y, 'orc', depth=8, is_boss=True)
        boss.hp = 1
        state.entities = [state.player, boss]
        state.try_move_player(1, 0)
        self.assertFalse(boss.alive)
        drops = [e for e in state.entities if isinstance(e, Chest)]
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].guaranteed_min_rarity, 'rare')
        self.assertTrue(drops[0].offers_choice)
        # Even opened at depth 1, a boss chest ignores the depth-scaled table.
        for _ in range(20):
            for item in drops[0].open(depth=1):
                self.assertIn(item.rarity, ('rare', 'epic'))


class ChestTests(unittest.TestCase):
    def test_spawn_chests_places_chests_not_items(self):
        random.seed(50)
        rooms = [Rect(1, 1, 10, 10), Rect(20, 1, 10, 10), Rect(1, 15, 10, 4)]
        chests = spawn_chests(rooms)
        self.assertTrue(all(isinstance(c, Chest) for c in chests))
        # Skips the player's starting room, same rule as monster spawning.
        for c in chests:
            self.assertFalse(rooms[0].x1 <= c.x < rooms[0].x2 and rooms[0].y1 <= c.y < rooms[0].y2)

    def test_chest_kind_sets_its_color_choice_and_contents(self):
        potion = Chest(0, 0, kind='potion')
        gear = Chest(0, 0, kind='gear')
        self.assertEqual(potion.color, POTION_CHEST_COLOR)
        self.assertEqual(gear.color, CHEST_COLOR)
        self.assertFalse(potion.offers_choice)
        self.assertTrue(gear.offers_choice)
        rng = random.Random(55)
        for depth in (1, 10):
            potions = potion.open(depth, rng=rng)
            self.assertEqual([i.kind for i in potions], ['potion'])
            for item in gear.open(depth, rng=rng):
                self.assertIn(item.kind, [JUNK] + GEAR_KINDS)
        # Every opened item has a valid kind, and a rarity unless it is junk.
        rng = random.Random(51)
        for kind in ('potion', 'gear'):
            chest = Chest(0, 0, kind=kind)
            for depth in (1, 5, 10, 25):
                for item in chest.open(depth, rng=rng):
                    self.assertIn(item.kind, ['potion', JUNK] + GEAR_KINDS)
                    if item.kind != JUNK:
                        self.assertIn(item.rarity, RARITIES)
        # A gear chest opens to three choices.
        rng = random.Random(57)
        chest = Chest(0, 0, kind='gear')
        for depth in (1, 8, 30):
            self.assertEqual(len(chest.open(depth, rng=rng)), 3)
        self.assertEqual(GEAR_CHEST_DROPS, 3)

    def test_boss_chest_offers_three_rare_or_epic_gear_and_no_junk_at_any_depth(self):
        chest = Chest(0, 0, guaranteed_min_rarity='rare')
        rng = random.Random(52)
        for _ in range(30):
            for item in chest.open(depth=1, rng=rng):
                self.assertIn(item.rarity, ('rare', 'epic'))
        chest = spawn_boss_chest(0, 0)
        self.assertEqual(chest.kind, 'gear')
        rng = random.Random(58)
        for depth in (1, 8, 30):
            for _ in range(200):
                items = chest.open(depth, rng=rng)
                self.assertEqual(len(items), 3)
                for item in items:
                    self.assertNotEqual(item.kind, JUNK)
                    self.assertIn(item.kind, GEAR_KINDS)
                    self.assertIn(item.rarity, ('rare', 'epic'))

    def test_junk_rate_is_about_fifteen_percent_and_flat_with_depth(self):
        self.assertEqual(JUNK_CHANCE, 0.15)
        chest = Chest(0, 0, kind='gear')
        rates = {}
        for depth in (1, MAX_SCALING_DEPTH, 50):
            rng = random.Random(59 + depth)
            drops = [item for _ in range(3000) for item in chest.open(depth, rng=rng)]
            rates[depth] = sum(1 for i in drops if i.kind == JUNK) / len(drops)
        # 9000 drops each: the standard error is ~0.004, so 0.02 is generous.
        for depth, rate in rates.items():
            self.assertAlmostEqual(rate, JUNK_CHANCE, delta=0.02, msg=f'depth {depth}')

    def test_gear_chests_spawn_about_point_four_per_floor(self):
        # Synthetic floors of 4-6 rooms (what generate_dungeon produces on the
        # default maps) -- real levels (4-11 ms each) are too slow for 5000.
        rng = random.Random(60)
        floors = 5000
        gear = potion = 0
        for _ in range(floors):
            rooms = [Rect(1 + 7 * i, 1, 6, 6) for i in range(rng.randint(4, 6))]
            for chest in spawn_chests(rooms, rng=rng):
                if chest.kind == 'gear':
                    gear += 1
                elif chest.kind == 'potion':
                    potion += 1
        self.assertAlmostEqual(gear / floors, 0.4, delta=0.05)
        # Potion chests keep the old rate: 0.25 per room past the first.
        self.assertAlmostEqual(potion / floors, 1.0, delta=0.1)

    def test_real_floors_have_at_most_one_gear_chest_and_depth_one_always_has_one(self):
        random.seed(61)
        for _ in range(100):
            _, rooms = generate_dungeon(40, 20)
            gear = [c for c in spawn_chests(rooms) if c.kind == 'gear']
            self.assertLessEqual(len(gear), 1)
            # Depth 1 always has one, outside the start room and off the stairs.
            chests = spawn_chests(rooms, depth=1)
            gear = [c for c in chests if c.kind == 'gear']
            self.assertEqual(len(gear), 1)
            start = rooms[0]
            in_start = start.x1 <= gear[0].x < start.x2 and start.y1 <= gear[0].y < start.y2
            self.assertFalse(in_start)
            self.assertNotEqual((gear[0].x, gear[0].y), rooms[-1].center())
            self.assertEqual(len({(c.x, c.y) for c in chests}), len(chests))
        for seed in range(20):
            state = GameState(40, 20, seed=seed)
            self.assertTrue(any(isinstance(e, Chest) and e.kind == 'gear' for e in state.entities))

    def test_deeper_floors_do_not_force_a_gear_chest(self):
        rng = random.Random(63)
        rooms = [Rect(1 + 7 * i, 1, 6, 6) for i in range(5)]
        counts = [
            sum(c.kind == 'gear' for c in spawn_chests(rooms, rng=rng, depth=2))
            for _ in range(300)
        ]
        self.assertIn(0, counts)

    def test_rarity_shifts_toward_better_loot_with_depth(self):
        shallow = rarity_weights_for_depth(1)
        deep = rarity_weights_for_depth(MAX_SCALING_DEPTH)
        beyond = rarity_weights_for_depth(MAX_SCALING_DEPTH + 50)
        common_idx, epic_idx = 0, 3
        self.assertGreater(shallow[common_idx], deep[common_idx])
        self.assertLess(shallow[epic_idx], deep[epic_idx])
        # Scaling holds steady past MAX_SCALING_DEPTH rather than running away.
        self.assertEqual(deep, beyond)
        # Statistical, not exact: a large sample at max depth should skew
        # toward rare/epic far more than the same sample at depth 1.
        shallow_epics = sum(1 for _ in range(500) if roll_rarity(1, random.Random()) == 'epic')
        deep_epics = sum(
            1 for _ in range(500) if roll_rarity(MAX_SCALING_DEPTH, random.Random()) == 'epic'
        )
        self.assertGreater(deep_epics, shallow_epics)


class PotionBeltTests(unittest.TestCase):
    """Potions found at full HP go on a 3-slot belt; 'drink' drinks slot 1."""

    def setUp(self):
        self.state = GameState(50, 20, seed=70)
        self.state.entities = [self.state.player]
        self.start = (self.state.player.x, self.state.player.y)

    def chest_east(self):
        state = self.state
        chest = Chest(state.player.x + 1, state.player.y, kind='potion')
        state.entities.append(chest)
        return chest

    def full_belt(self):
        self.state.belt[:] = [Item(0, 0, 'potion', r) for r in ('common', 'rare', 'uncommon')]

    def test_belt_starts_empty(self):
        self.assertEqual(self.state.belt, [])
        self.assertEqual(GameState(50, 20, char_class='archer', seed=0).belt, [])

    def test_hurt_pickup_drinks_at_once(self):
        for missing in ('all but 1 HP', '1 HP'):
            with self.subTest(missing=missing):
                self.setUp()
                state = self.state
                state.player.hp = 1 if missing == 'all but 1 HP' else state.player.max_hp - 1
                hp = state.player.hp
                chest = self.chest_east()
                self.assertTrue(state.handle_action('move_e'))
                self.assertGreater(state.player.hp, hp)
                self.assertEqual(state.belt, [])
                self.assertNotIn(chest, state.entities)
                self.assertEqual(len(state.player.items_used), 1)
                self.assertIn('You open the chest.', state.messages)
                self.assertFalse(state.is_choosing)

    def test_full_hp_pickup_goes_in_the_first_free_slot(self):
        state = self.state
        state.belt.append(Item(0, 0, 'potion', 'epic'))
        chest = self.chest_east()
        turn = state.turn
        self.assertTrue(state.handle_action('move_e'))
        self.assertEqual(state.turn, turn + 1)  # the move, nothing more
        self.assertEqual(len(state.belt), 2)
        self.assertEqual(state.belt[0].rarity, 'epic')
        self.assertEqual(state.belt[1].kind, 'potion')
        self.assertNotIn(chest, state.entities)
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertEqual((state.player.x, state.player.y), (self.start[0] + 1, self.start[1]))
        self.assertIn('belt', state.messages[-1])
        self.assertIn('slot 2', state.messages[-1])

    def test_open_chest_drinks_when_hurt_and_belts_at_full_hp(self):
        with self.subTest('hurt: drunk at once'):
            state = self.state
            chest = Chest(state.player.x, state.player.y, kind='potion')
            state.entities.append(chest)
            state.player.hp -= 1
            state.open_chest(chest)
            self.assertNotIn(chest, state.entities)
            self.assertEqual(len(state.player.items_used), 1)
            self.assertEqual(state.belt, [])
            self.assertIsNone(state.pending_choice)
        with self.subTest('full HP: belted'):
            self.setUp()
            state = self.state
            chest = Chest(state.player.x, state.player.y, kind='potion')
            state.entities.append(chest)
            self.assertTrue(state.open_chest(chest))
            self.assertEqual(len(state.belt), 1)
            self.assertNotIn(chest, state.entities)
            self.assertEqual(state.player.items_used, [])  # stored, not drunk

    def test_full_belt_at_full_hp_refuses_the_chest(self):
        state = self.state
        self.full_belt()
        monster = Monster(state.player.x, state.player.y + 1, 'goblin')
        state.entities.append(monster)
        chest = self.chest_east()
        turn, monster_hp = state.turn, monster.hp
        self.assertFalse(state.handle_action('move_e'))
        self.assertEqual((state.player.x, state.player.y), self.start)
        self.assertIn(chest, state.entities)
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertEqual(state.messages[-1], 'Your potion belt is full.')
        self.assertEqual(len(state.belt), 3)
        self.assertEqual(monster.hp, monster_hp)
        # open_chest refuses it too.
        under = Chest(state.player.x, state.player.y, kind='potion')
        state.entities.append(under)
        self.assertFalse(state.open_chest(under))
        self.assertIn(under, state.entities)

    def test_full_belt_while_hurt_still_drinks(self):
        state = self.state
        self.full_belt()
        state.player.hp = 1
        chest = self.chest_east()
        self.assertTrue(state.handle_action('move_e'))
        self.assertNotIn(chest, state.entities)
        self.assertGreater(state.player.hp, 1)
        self.assertEqual(len(state.belt), 3)

    def test_walking_onto_a_gear_chest_offers_a_choice_whatever_the_belt(self):
        for belt in ('empty', 'full'):
            with self.subTest(belt=belt):
                self.setUp()
                state = self.state
                if belt == 'full':
                    self.full_belt()
                chest = Chest(state.player.x + 1, state.player.y, kind='gear')
                state.entities.append(chest)
                self.assertTrue(state.handle_action('move_e'))
                self.assertNotIn(chest, state.entities)
                self.assertTrue(state.is_choosing)
                self.assertEqual(len(cast(list[Item], state.pending_choice)), GEAR_CHEST_DROPS)
                self.assertEqual(state.player.items_used, [])  # nothing auto-equipped

    def test_after_drinking_the_chest_can_be_entered(self):
        state = self.state
        self.full_belt()
        chest = self.chest_east()
        self.assertFalse(state.handle_action('move_e'))
        state.player.hp -= 1
        self.assertTrue(state.handle_action('drink'))
        state.end_turn()  # (no monsters) finish the round
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertEqual(len(state.belt), 2)
        self.assertTrue(state.handle_action('move_e'))
        self.assertNotIn(chest, state.entities)
        self.assertEqual(len(state.belt), 3)
        self.assertEqual((state.player.x, state.player.y), (self.start[0] + 1, self.start[1]))

    def test_drink_takes_the_first_slot_shifts_the_rest_and_caps_at_max_hp(self):
        state = self.state
        self.full_belt()
        second, third = state.belt[1], state.belt[2]
        state.player.hp = 1
        self.assertTrue(state.handle_action('drink'))
        self.assertEqual(state.player.hp, 1 + POTION_HEAL['common'])
        self.assertEqual(state.belt, [second, third])
        self.assertEqual(state.player.items_used, ['potion of healing'])
        self.setUp()
        state = self.state
        state.belt.append(Item(0, 0, 'potion', 'epic'))
        state.player.hp = state.player.max_hp - 5
        self.assertTrue(state.handle_action('drink'))
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertEqual(state.belt, [])

    def test_drink_takes_a_turn_and_monsters_act(self):
        state = self.state
        state.belt.append(Item(0, 0, 'potion', 'rare'))
        state.player.hp = 5
        monster = Monster(state.player.x, state.player.y + 1, 'goblin')
        state.entities.append(monster)
        turn = state.turn
        self.assertTrue(state.handle_action('drink'))
        self.assertEqual(state.turn, turn + 1)
        self.assertEqual(state.player.hp, min(state.player.max_hp, 5 + POTION_HEAL['rare']))
        self.assertTrue(state.monster_phase_pending())
        healed = state.player.hp
        while state.step_monster_phase():
            pass
        self.assertLess(state.player.hp, healed)  # the goblin answered

    def test_a_refused_drink_takes_no_turn(self):
        with self.subTest('empty belt'):
            state = self.state
            state.entities.append(Monster(state.player.x, state.player.y + 1, 'goblin'))
            turn = state.turn
            self.assertFalse(state.handle_action('drink'))
            self.assertEqual(state.turn, turn)
            self.assertFalse(state.monster_phase_pending())
            self.assertEqual(state.messages[-1], 'No potions')
        with self.subTest('full HP'):
            self.setUp()
            state = self.state
            potion = Item(0, 0, 'potion', 'common')
            state.belt.append(potion)
            state.entities.append(Monster(state.player.x, state.player.y + 1, 'goblin'))
            turn = state.turn
            self.assertFalse(state.handle_action('drink'))
            self.assertEqual(state.belt, [potion])
            self.assertEqual(state.turn, turn)
            self.assertFalse(state.monster_phase_pending())
            self.assertEqual(state.player.items_used, [])
            self.assertEqual(state.messages[-1], 'You are already at full health.')
        with self.subTest('while choosing'):
            self.setUp()
            state = self.state
            state.belt.append(Item(0, 0, 'potion', 'common'))
            state.player.hp = 1
            state.pending_choice = [Item(0, 0, 'armor', 'common')] * 3
            turn = state.turn
            self.assertFalse(state.handle_action('drink'))
            self.assertEqual(state.player.hp, 1)
            self.assertEqual(len(state.belt), 1)
            self.assertEqual(state.turn, turn)


class ChestChoiceTests(unittest.TestCase):
    """A gear chest offers three items; the player must choose() one."""

    def state_with_choice(self, items, seed=62):
        state = GameState(50, 20, seed=seed)
        state.entities = [state.player]
        state.pending_choice = items
        return state

    def test_open_gear_chest_sets_pending_choice_and_equips_nothing(self):
        state = GameState(50, 20, seed=63)
        starting = state.player.weapon
        chest = Chest(state.player.x, state.player.y, kind='gear')
        state.entities = [state.player, chest]
        state.open_chest(chest)
        self.assertNotIn(chest, state.entities)
        self.assertTrue(state.is_choosing)
        self.assertEqual(len(cast(list[Item], state.pending_choice)), 3)
        self.assertIs(state.player.weapon, starting)  # the starting weapon, untouched
        self.assertIsNone(state.player.armor)
        self.assertTrue(state.messages[-1].startswith('Choose one:'))

    def test_choose_equips_the_chosen_item_and_discards_the_rest(self):
        old = Item(0, 0, 'weapon', 'epic')
        state = self.state_with_choice(
            [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'common'), Item(0, 0, JUNK)]
        )
        old.apply(state.player, state.log)
        new = state.pending_choice[1]
        state.choose(1)
        self.assertFalse(state.is_choosing)
        self.assertIsNone(state.pending_choice)
        # Equipped even though it is worse: the player picked it.
        self.assertIs(state.player.weapon, new)
        self.assertEqual(state.player.power, state.player.base_power + GEAR_BONUS['common'])
        self.assertIsNone(state.player.armor)  # the unchosen armor is lost
        # Chosen armor sets defence from the table.
        state = self.state_with_choice(
            [Item(0, 0, 'armor', 'uncommon'), Item(0, 0, JUNK), Item(0, 0, JUNK)]
        )
        state.choose(0)
        self.assertEqual(state.player.defense, ARMOR_DEFENSE['uncommon'])

    def test_choosing_junk_only_logs(self):
        state = self.state_with_choice(
            [Item(0, 0, JUNK), Item(0, 0, 'weapon', 'epic'), Item(0, 0, 'armor', 'epic')]
        )
        before = (
            state.player.power,
            state.player.defense,
            state.player.weapon,
            state.player.armor,
            list(state.player.items_used),
            state.player.hp,
        )
        n_messages = len(state.messages)
        state.choose(0)
        after = (
            state.player.power,
            state.player.defense,
            state.player.weapon,
            state.player.armor,
            list(state.player.items_used),
            state.player.hp,
        )
        self.assertEqual(before, after)
        self.assertFalse(state.is_choosing)
        self.assertEqual(len(state.messages), n_messages + 1)
        self.assertIn(JUNK_NAME, state.messages[-1])

    def test_a_bad_index_raises_for_direct_callers_and_is_harmless_from_input(self):
        state = self.state_with_choice([Item(0, 0, JUNK)] * 3)
        with self.assertRaises(ValueError):
            state.choose(3)
        self.assertTrue(state.is_choosing)  # still pending: no cancel
        state.choose(2)
        with self.assertRaises(ValueError):
            state.choose(0)  # no pending choice
        # Fewer offers than keys: '3' must not raise out of handle_action.
        state = self.state_with_choice([Item(0, 0, JUNK), Item(0, 0, JUNK)])
        self.assertFalse(state.handle_action('choose_3'))
        self.assertTrue(state.is_choosing)
        with self.assertRaises(ValueError):
            state.choose(2)  # direct callers still get the error

    def test_pending_choice_blocks_movement_and_turns_but_not_quit(self):
        state = self.state_with_choice([Item(0, 0, JUNK)] * 3)
        state.game_map[state.player.y][state.player.x + 1] = FLOOR
        start = (state.player.x, state.player.y)
        for action in ('move_e', 'shoot_e', 'wait', 'descend'):
            self.assertFalse(state.handle_action(action))
            self.assertEqual((state.player.x, state.player.y), start)
            self.assertFalse(state.monster_phase_pending())
        state.choose(0)
        self.assertTrue(state.handle_action('move_e'))
        self.assertEqual((state.player.x, state.player.y), (start[0] + 1, start[1]))
        state = self.state_with_choice([Item(0, 0, JUNK)] * 3)
        state.handle_action('quit')
        self.assertFalse(state.running)

    def test_digit_while_choosing_picks_that_card(self):
        items = [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'epic'), Item(0, 0, JUNK)]
        state = self.state_with_choice(list(items))
        self.assertFalse(state.handle_action('choose_2'))  # takes no turn
        self.assertFalse(state.is_choosing)
        self.assertIs(state.player.weapon, items[1])
        self.assertIsNone(state.player.armor)
        self.assertFalse(state.monster_phase_pending())

        state = self.state_with_choice(list(items))
        state.handle_action('choose_1')
        self.assertIs(state.player.armor, items[0])

        state = self.state_with_choice(list(items))
        state.handle_action('choose_3')
        self.assertFalse(state.is_choosing)
        self.assertIsNone(state.player.armor)
        self.assertIsNot(state.player.weapon, items[1])

    def test_skip_leaves_the_chest_with_no_item_and_takes_no_turn(self):
        state = GameState(50, 20, seed=66)
        good = Item(0, 0, 'weapon', 'epic')
        good.apply(state.player, state.log)
        power, armor = state.player.power, state.player.armor
        chest = Chest(state.player.x, state.player.y, kind='gear')
        state.entities = [state.player, chest]
        state.open_chest(chest)
        self.assertTrue(state.is_choosing)
        turn = state.turn
        self.assertFalse(state.handle_action('skip'))  # takes no turn
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertFalse(state.is_choosing)
        self.assertNotIn(chest, state.entities)  # used up all the same
        self.assertIs(state.player.weapon, good)  # the good weapon is kept
        self.assertEqual((state.player.power, state.player.armor), (power, armor))
        self.assertEqual(state.messages[-1], 'You walk away from the chest.')

    def test_skip_and_digits_while_not_choosing_do_nothing(self):
        state = GameState(50, 20, seed=67)
        n = len(state.messages)
        self.assertFalse(state.handle_action('skip'))
        self.assertEqual(len(state.messages), n)
        with self.assertRaises(ValueError):
            state.skip_choice()
        state = GameState(50, 20, seed=65)
        start = (state.player.x, state.player.y, state.player.weapon, len(state.messages))
        for action in ('choose_1', 'choose_2', 'choose_3'):
            self.assertFalse(state.handle_action(action))
        self.assertEqual(
            (state.player.x, state.player.y, state.player.weapon, len(state.messages)), start
        )
        self.assertFalse(state.monster_phase_pending())

    def test_boss_chest_in_play_offers_rare_or_epic_without_junk(self):
        state = GameState(50, 20, seed=64)
        chest = spawn_boss_chest(state.player.x, state.player.y)
        state.entities = [state.player, chest]
        state.open_chest(chest)
        self.assertEqual(len(cast(list[Item], state.pending_choice)), 3)
        for item in state.pending_choice:
            self.assertIn(item.kind, GEAR_KINDS)
            self.assertIn(item.rarity, ('rare', 'epic'))


class CombatEventTests(unittest.TestCase):
    """What GameState records for a renderer to stage (game/combat.py)."""

    def setUp(self):
        self.state = GameState(50, 20, seed=7)
        p = self.state.player
        self.goblin = Monster(p.x + 1, p.y, 'goblin')
        self.state.game_map[p.y][p.x + 1] = FLOOR
        self.state.entities = [p, self.goblin]
        self.state.update_fov()

    def test_attack_records_a_hit(self):
        self.goblin.hp = 2
        self.state.player.power = 5
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0):  # no random crit
            self.state.attack(self.state.player, self.goblin)
        (hit,) = self.state.hits()
        self.assertIs(hit.attacker, self.state.player)
        self.assertIs(hit.defender, self.goblin)
        self.assertEqual((hit.damage, hit.killed), (5, True))
        self.assertEqual((hit.x, hit.y), (self.goblin.x, self.goblin.y))

    def test_events_last_one_round_but_serials_keep_counting(self):
        self.state.attack(self.goblin, self.state.player)
        first = self.state.hits()[0].serial
        self.state.handle_action('wait')
        self.assertTrue(all(h.serial > first for h in self.state.hits()))
        self.state.handle_action('descend')  # not on the stairs: no turn, no blows
        self.assertEqual(self.state.hits(), [])

    def test_melee_opponents_are_orthogonal_neighbours_only(self):
        self.assertEqual(self.state.melee_opponents(), [self.goblin])
        self.goblin.y += 1  # now diagonal
        self.assertEqual(self.state.melee_opponents(), [])
        self.goblin.y -= 1
        self.goblin.alive = False
        self.assertEqual(self.state.melee_opponents(), [])


class CritAndReductionTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(50, 20, seed=0)
        p = self.state.player
        self.goblin = Monster(p.x + 1, p.y, 'goblin')
        self.goblin.hp = self.goblin.max_hp = 10**6
        p.hp = p.max_hp = 10**6
        self.state.entities = [p, self.goblin]

    def hit(self, attacker, defender, crit):
        """One attack with the crit forced either way."""
        self.state.attack(attacker, defender, crit=crit)
        return self.state.hits()[-1]

    def test_constants(self):
        self.assertEqual(BASE_CRIT_CHANCE, 0.10)
        self.assertEqual(CRIT_MULTIPLIER, 1.5)
        self.assertEqual(crit_chance(self.state.player), BASE_CRIT_CHANCE)
        # Monsters have no weapon bonus (a dagger's crit is the player's only).
        self.assertEqual(crit_chance(Monster(0, 0, 'goblin')), BASE_CRIT_CHANCE)

    def test_a_forced_hit_on_no_defence_is_full_power_or_a_logged_crit(self):
        with self.subTest('no crit: full power, a whole number'):
            self.state.player.power = 7
            self.goblin.defense = 0
            hit = self.hit(self.state.player, self.goblin, False)
            self.assertEqual(hit.damage, 7)
            self.assertFalse(hit.crit)
            self.assertIsInstance(hit.damage, int)
        with self.subTest('crit: flagged and logged'):
            self.setUp()
            self.state.player.power = 4
            hit = self.hit(self.state.player, self.goblin, True)
            self.assertTrue(hit.crit)
            self.assertEqual(hit.damage, 6)
            self.assertIn('Critical hit!', self.state.messages)
            self.assertIn('You hit goblin for 6.', self.state.messages)

    def test_monster_hit_on_armored_player_is_reduced(self):
        p = self.state.player
        p.defense = 10  # 50% reduction
        self.goblin.power = 7  # 3.5 -> probabilistic
        expected = []
        rng_probe = random.Random()
        rng_probe.setstate(self.state.rng.getstate())
        for _ in range(5):
            expected.append(round_damage(mitigate(7, 10), rng_probe))
        got = []
        for _ in range(5):
            before = p.hp
            self.state.attack(self.goblin, p)
            got.append(before - p.hp)
        self.assertEqual(got, expected)
        self.assertTrue(all(d in (3, 4) for d in got))

    def test_player_crit_chance_is_about_ten_percent(self):
        self.state.rng.seed(123)
        self.state.player.power = 10
        crits = 0
        n = 4000
        for _ in range(n):
            self.state.attack(self.state.player, self.goblin)
            crits += self.state.hits()[-1].crit
        self.assertTrue(0.07 < crits / n < 0.13, crits / n)

    def test_monsters_never_crit(self):
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 1.0):
            for _ in range(300):
                self.state.attack(self.goblin, self.state.player)
                self.assertFalse(self.state.hits()[-1].crit)
        self.assertNotIn('Critical hit!', self.state.messages)

    def test_crit_multiplies_raw_before_reduction(self):
        self.state.player.power = 10
        self.goblin.defense = 10  # 50%: 10 -> 5, crit 15 -> 7.5
        self.state.rng.seed(9)
        hits = [self.hit(self.state.player, self.goblin, True).damage for _ in range(200)]
        self.assertTrue(all(d in (7, 8) for d in hits))
        self.assertGreater(len(set(hits)), 1)
        self.assertAlmostEqual(sum(hits) / len(hits), 7.5, delta=0.5)

    def test_arrow_can_crit(self):
        self.state.player.char_class = 'archer'
        self.state.player.power = 4
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 1.0):
            self.state.shoot_arrow(1, 0)
        self.assertTrue(self.state.hits()[-1].crit)


class WeaponTypeTests(unittest.TestCase):
    """The six weapon types (game/item.py WEAPON_TYPES) and their effects."""

    EXPECTED_BONUS = {
        'war_axe': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'rapier': {'common': -1, 'uncommon': 0, 'rare': 2, 'epic': 5},
        'great_sword': {'common': 2, 'uncommon': 3, 'rare': 5, 'epic': 8},
        'sword_shield': {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7},
        'dagger': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'spear': {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7},
        'fencing_sword': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
    }

    def setUp(self):
        self.state = GameState(50, 20, char_class='warrior', seed=90)
        # An open arena: floor everywhere inside the border, player at (10, 10).
        for y in range(1, 19):
            for x in range(1, 49):
                self.state.game_map[y][x] = FLOOR
        p = self.state.player
        p.x, p.y = 10, 10
        p.hp = p.max_hp = 1000
        self.state.entities = [p]
        self.state.update_fov()

    def equip(self, kind, rarity='common'):
        item = Item(0, 0, kind, rarity)
        item.apply(self.state.player, self.state.log)
        return item

    def monster(self, x, y, hp=1000):
        m = Monster(x, y, 'goblin')
        m.hp = m.max_hp = hp
        self.state.entities.append(m)
        self.state.update_fov()
        return m

    def no_crit(self):
        return mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0)

    # -- data ----------------------------------------------------------------

    def test_six_new_kinds_are_weapon_slot_gear_and_drop(self):
        self.assertEqual(set(WARRIOR_WEAPONS), set(self.EXPECTED_BONUS))
        self.assertEqual(set(WEAPON_TYPES), set(WARRIOR_WEAPONS) | set(ARCHER_WEAPONS))
        for kind in WEAPON_TYPES:
            self.assertEqual(GEAR_SLOTS[kind], 'weapon')
            self.assertIn(kind, GEAR_KINDS)
            self.assertIn(kind, GEAR_DROP_KINDS)
            for rarity in RARITIES:
                item = Item(0, 0, kind, rarity)
                self.assertIn(item.kind, GEAR_SLOTS)
                self.assertTrue(item.name)
                self.assertEqual(item.char, ITEM_CHARS['weapon'])
        self.assertIn('armor', GEAR_DROP_KINDS)
        # The plain weapon is the starting weapon, never a drop.
        self.assertNotIn('weapon', GEAR_DROP_KINDS)

    def test_drop_shares_armor_twenty_percent_junk_fifteen(self):
        # Armor is 20% of ALL gear-chest drops (junk included); the rest are
        # weapon types, evenly. Boss drops have no junk, so armor is 20% there.
        rng = random.Random(7)
        n = 20000
        gear = [roll_gear_drop(1, rng) for _ in range(n)]
        junk = sum(1 for d in gear if d.kind == JUNK) / n
        armor = sum(1 for d in gear if d.kind in ARMOR_KINDS) / n
        self.assertTrue(abs(junk - 0.15) < 0.01, junk)
        self.assertTrue(abs(armor - ARMOR_DROP_CHANCE) < 0.01, armor)
        boss = [roll_boss_drop(rng) for _ in range(n)]
        self.assertTrue(
            abs(sum(1 for d in boss if d.kind in ARMOR_KINDS) / n - ARMOR_DROP_CHANCE) < 0.01
        )
        self.assertNotIn('weapon', {d.kind for d in gear + boss})

    def test_damage_bonus_by_rarity_and_the_power_it_gives(self):
        p = self.state.player
        for kind, table in self.EXPECTED_BONUS.items():
            for rarity, bonus in table.items():
                self.assertEqual(Item(0, 0, kind, rarity).bonus, bonus, (kind, rarity))
                self.equip(kind, rarity)
                self.assertEqual(p.power, p.base_power + bonus, (kind, rarity))
        # Each is GEAR_BONUS with an offset.
        for rarity in RARITIES:
            self.assertEqual(Item(0, 0, 'spear', rarity).bonus, GEAR_BONUS[rarity])

    def test_effect_values_by_rarity(self):
        for rarity, hp, shield, crit in zip(
            RARITIES, (3, 6, 9, 15), (3, 6, 9, 12), (0.05, 0.10, 0.15, 0.20)
        ):
            self.assertEqual(Item(0, 0, 'war_axe', rarity).max_hp_bonus, hp)
            self.assertEqual(Item(0, 0, 'sword_shield', rarity).defense_bonus, shield)
            self.assertAlmostEqual(Item(0, 0, 'dagger', rarity).crit_bonus, crit)
            self.assertEqual(Item(0, 0, 'rapier', rarity).strikes, 2)
            self.assertTrue(Item(0, 0, 'great_sword', rarity).cleave)
            self.assertEqual(Item(0, 0, 'spear', rarity).reach, 2)
        plain = Item(0, 0, 'weapon', 'epic')
        self.assertEqual(
            (
                plain.max_hp_bonus,
                plain.strikes,
                plain.cleave,
                plain.defense_bonus,
                plain.crit_bonus,
                plain.reach,
            ),
            (0, 1, False, 0, 0.0, 1),
        )

    def test_power_never_drops_below_one(self):
        p = self.state.player
        p.base_power = 1
        self.equip('rapier', 'common')  # 1 - 1 = 0
        self.assertEqual(p.power, 1)
        p.base_power = 0
        self.equip('dagger', 'common')  # 0 + 0 = 0
        self.assertEqual(p.power, 1)
        p.base_power = 4
        self.equip('rapier', 'common')
        self.assertEqual(p.power, 3)

    # -- War Axe -------------------------------------------------------------

    def test_war_axe_adds_hp_and_losing_it_never_kills_or_overfills(self):
        p = self.state.player
        p.hp, p.max_hp = 20, 25
        self.equip('war_axe', 'rare')  # +9
        self.assertEqual((p.hp, p.max_hp), (29, 34))
        self.equip('war_axe', 'epic')  # -9 +15
        self.assertEqual((p.hp, p.max_hp), (35, 40))
        self.equip('spear', 'common')  # -15
        self.assertEqual((p.hp, p.max_hp), (20, 25))
        self.assertEqual(p.power, p.base_power + 1)
        p.hp, p.max_hp = 25, 25
        self.equip('war_axe', 'epic')
        self.assertEqual((p.hp, p.max_hp), (40, 40))
        p.hp = 5
        self.equip('weapon', 'common')
        self.assertEqual((p.hp, p.max_hp), (1, 25))  # 5 - 15 floors at 1
        for rarity, hp in zip(RARITIES, (3, 6, 9, 15)):
            p.hp, p.max_hp = 25, 25
            p.weapon = None
            self.equip('war_axe', rarity)
            self.assertEqual((p.hp, p.max_hp), (25 + hp, 25 + hp))
            self.assertLessEqual(p.hp, p.max_hp)

    # -- Rapier --------------------------------------------------------------

    def test_rapier_strikes_twice_each_reduced_separately(self):
        self.equip('rapier', 'epic')
        p = self.state.player
        p.power = 7
        goblin = self.monster(11, 10)
        goblin.defense = 10  # 50%: 7 -> 3.5
        probe = random.Random()
        probe.setstate(self.state.rng.getstate())
        expected = []
        for _ in range(2):
            probe.random()  # the crit roll
            expected.append(round_damage(mitigate(7, 10), probe))
        before = len(self.state.messages)
        with self.no_crit():
            self.state.handle_action('move_e')
            self.state.resolve_player_phase()
        hits = [h for h in self.state.hits() if h.attacker is p]
        self.assertEqual(len(hits), 2)
        self.assertEqual([h.damage for h in hits], expected)
        self.assertEqual(len({h.serial for h in hits}), 2)
        lines = [m for m in self.state.messages[before:] if m.startswith('You hit goblin')]
        self.assertEqual(lines, [f'You hit goblin for {d}.' for d in expected])
        self.assertEqual(goblin.hp, 1000 - sum(expected))
        self.assertEqual((p.x, p.y), (10, 10))

    def test_rapier_crits_roll_per_strike(self):
        self.equip('rapier', 'epic')
        self.state.player.power = 4
        goblin = self.monster(11, 10)
        goblin.defense = 0  # whole damage: no rounding roll
        for rolls, crits in (([0.0, 0.99], [True, False]), ([0.99, 0.0], [False, True])):
            with mock.patch.object(self.state.rng, 'random', side_effect=rolls):
                self.state.handle_action('move_e')
                self.state.resolve_player_phase()
            hits = [h for h in self.state.hits() if h.attacker is self.state.player]
            self.assertEqual([h.crit for h in hits], crits)
            self.assertEqual([h.damage for h in hits], [6 if c else 4 for c in crits])

    def test_rapier_stops_when_the_first_strike_kills(self):
        with self.subTest('melee'):
            self.equip('rapier', 'epic')
            goblin = self.monster(11, 10, hp=1)
            with self.no_crit():
                self.state.melee(goblin)
            self.assertEqual(len(self.state.hits()), 1)
            self.assertFalse(goblin.alive)
        with self.subTest('handle_action ends the half at once'):
            self.setUp()
            self.equip('rapier', 'epic')
            goblin = self.monster(11, 10, hp=1)
            other = self.monster(20, 10)
            with self.no_crit():
                self.state.handle_action('move_e')
            self.assertFalse(goblin.alive)
            self.assertEqual(len(self.state.hits()), 1)
            self.assertFalse(self.state.strike_pending())
            self.assertTrue(self.state.monster_phase_pending())
            self.assertEqual(other.hp, 1000)

    def test_rapier_second_strike_waits_until_stepped(self):
        # handle_action lands strike 1 only and leaves the player's half
        # open: no monster is queued until the second strike resolves.
        self.equip('rapier', 'epic')
        p = self.state.player
        goblin = self.monster(11, 10)
        with self.no_crit():
            self.assertTrue(self.state.handle_action('move_e'))
            self.assertEqual(len(self.state.hits()), 1)
            first = self.state.hits()[0].damage
            self.assertEqual(goblin.hp, 1000 - first)
            self.assertTrue(self.state.strike_pending())
            self.assertFalse(self.state.monster_phase_pending())
            self.assertTrue(self.state.step_strike())
        hits = self.state.hits()
        self.assertEqual([h.attacker for h in hits], [p, p])
        self.assertEqual([h.defender for h in hits], [goblin, goblin])
        self.assertLess(hits[0].serial, hits[1].serial)
        self.assertEqual(goblin.hp, 1000 - first - hits[1].damage)
        self.assertFalse(self.state.strike_pending())
        self.assertTrue(self.state.monster_phase_pending())  # now the monsters

    def test_rapier_second_strike_does_nothing_when_the_target_or_player_is_gone(self):
        with self.subTest('target vanished'):
            self.equip('rapier', 'epic')
            goblin = self.monster(11, 10)
            with self.no_crit():
                self.state.handle_action('move_e')
            self.state.entities.remove(goblin)  # gone before strike 2
            hp = goblin.hp
            self.assertFalse(self.state.step_strike())
            self.assertEqual(goblin.hp, hp)
            self.assertEqual(len(self.state.hits()), 1)
            self.assertFalse(self.state.strike_pending())
        with self.subTest('player dead'):
            self.setUp()
            self.equip('rapier', 'epic')
            goblin = self.monster(11, 10)
            with self.no_crit():
                self.state.handle_action('move_e')
            self.state.player.hp = 0
            self.state.player.alive = False
            self.state.game_over = True
            hp = goblin.hp
            self.assertFalse(self.state.step_strike())
            self.assertEqual(goblin.hp, hp)
            self.assertFalse(self.state.strike_pending())
            self.assertFalse(self.state.monster_phase_pending())

    def test_rapier_with_no_monster_just_moves(self):
        self.equip('rapier', 'epic')
        self.assertTrue(self.state.handle_action('move_e'))
        self.assertEqual((self.state.player.x, self.state.player.y), (11, 10))
        self.assertFalse(self.state.strike_pending())
        self.assertEqual(self.state.hits(), [])

    def test_rapier_end_turn_resolves_both_strikes_then_the_monsters(self):
        self.equip('rapier', 'epic')
        p = self.state.player
        goblin = self.monster(11, 10)
        goblin.power = 3
        turn = self.state.turn
        with self.no_crit():
            self.state.handle_action('move_e')
            self.state.end_turn()
        attackers = [h.attacker for h in self.state.hits()]
        # Both of the player's strikes, then the goblin's reply.
        self.assertEqual(attackers, [p, p, goblin])
        self.assertEqual(self.state.turn, turn + 1)
        self.assertFalse(self.state.strike_pending())
        self.assertFalse(self.state.monster_phase_pending())

    def test_warrior_single_strike_is_unchanged(self):
        goblin = self.monster(11, 10)
        with self.no_crit():
            self.state.handle_action('move_e')
        self.assertEqual(len(self.state.hits()), 1)
        self.assertFalse(self.state.strike_pending())
        self.assertTrue(self.state.monster_phase_pending())
        self.assertLess(goblin.hp, 1000)

    # -- Great Sword ---------------------------------------------------------

    def test_great_sword_hits_a_second_monster_next_to_the_player(self):
        self.equip('great_sword', 'rare')
        target = self.monster(11, 10)
        other = self.monster(10, 9)  # north of the player
        with self.no_crit():
            self.state.handle_action('move_e')
        defenders = [h.defender for h in self.state.hits() if h.attacker is self.state.player]
        self.assertEqual(defenders, [target, other])
        self.assertLess(other.hp, 1000)
        self.assertTrue(any('carries on into goblin' in m for m in self.state.messages))

    def test_great_sword_cleaves_only_one_monster_orthogonally_next_to_the_player(self):
        with self.subTest('not diagonal, two away or next to the target only'):
            self.equip('great_sword', 'rare')
            target = self.monster(11, 10)
            diagonal = self.monster(11, 9)
            two_away = self.monster(8, 10)
            beside_target = self.monster(12, 10)  # next to the target only
            with self.no_crit():
                self.state.handle_action('move_e')
            player_hits = [h for h in self.state.hits() if h.attacker is self.state.player]
            self.assertEqual([h.defender for h in player_hits], [target])
            for m in (diagonal, two_away, beside_target):
                self.assertEqual(m.hp, 1000)
        with self.subTest('one extra monster at most'):
            self.setUp()
            self.equip('great_sword', 'rare')
            target = self.monster(11, 10)
            self.monster(10, 9)
            self.monster(10, 11)
            with self.no_crit():
                self.state.melee(target)
            self.assertEqual(len(self.state.hits()), 2)

    def test_other_weapons_do_not_cleave(self):
        self.equip('spear', 'rare')
        target = self.monster(11, 10)
        other = self.monster(10, 9)
        self.state.melee(target)
        self.assertEqual(other.hp, 1000)

    # -- Sword & Shield ------------------------------------------------------

    def test_sword_and_shield_gives_defense_alone_and_stacks_with_armor(self):
        for rarity, shield in zip(RARITIES, (3, 6, 9, 12)):
            self.equip('sword_shield', rarity)
            self.assertEqual(self.state.player.defense, shield)
            self.assertIsNone(self.state.player.armor)
        self.setUp()
        p = self.state.player
        armor = self.equip('armor', 'rare')  # 12
        shield = self.equip('sword_shield', 'rare')  # +9 defence, +4 damage
        self.assertIs(p.weapon, shield)
        self.assertIs(p.armor, armor)
        self.assertEqual(p.defense, ARMOR_DEFENSE['rare'] + 9)
        self.assertEqual(p.power, p.base_power + GEAR_BONUS['rare'])
        self.equip('armor', 'epic')
        self.assertEqual(p.defense, 21 + 9)
        self.equip('spear', 'common')  # the shield goes with it
        self.assertEqual(p.defense, 21)

    # -- Dagger --------------------------------------------------------------

    def test_dagger_raises_crit_chance_by_rarity_capped_at_one(self):
        p = self.state.player
        self.assertEqual(crit_chance(p), BASE_CRIT_CHANCE)
        chances = []
        for rarity, bonus in zip(RARITIES, (0.05, 0.10, 0.15, 0.20)):
            self.equip('dagger', rarity)
            self.assertAlmostEqual(crit_chance(p), BASE_CRIT_CHANCE + bonus)
            chances.append(crit_chance(p))
        self.assertEqual(chances, sorted(chances))
        with mock.patch('game.fight.BASE_CRIT_CHANCE', 0.95):  # epic dagger: 0.95 + 0.20
            self.assertEqual(crit_chance(p), 1.0)
        self.equip('spear', 'epic')
        self.assertEqual(crit_chance(p), BASE_CRIT_CHANCE)

    def test_dagger_crit_shows_up_in_attacks(self):
        self.equip('dagger', 'epic')  # 30%
        goblin = self.monster(11, 10, hp=10**9)
        self.state.rng.seed(321)
        n = 3000
        crits = 0
        for _ in range(n):
            self.state.attack(self.state.player, goblin)
            crits += self.state.hits()[-1].crit
        self.assertTrue(0.26 < crits / n < 0.34, crits / n)

    # -- Spear ---------------------------------------------------------------

    def test_spear_reaches_a_monster_two_tiles_away_in_every_direction(self):
        self.equip('spear', 'rare')
        far = self.monster(12, 10)
        with self.no_crit():
            self.assertTrue(self.state.handle_action('move_e'))
        self.assertEqual((self.state.player.x, self.state.player.y), (10, 10))
        self.assertLess(far.hp, 1000)
        (hit,) = self.state.hits()
        self.assertIs(hit.defender, far)
        far.alive = False
        for action, (x, y) in (
            ('move_n', (10, 8)),
            ('move_s', (10, 12)),
            ('move_w', (8, 10)),
            ('shoot_e', (12, 10)),
        ):
            m = self.monster(x, y)
            self.state.handle_action(action)
            self.assertLess(m.hp, 1000, action)
            self.assertEqual((self.state.player.x, self.state.player.y), (10, 10))
            m.alive = False

    def test_spear_with_a_monster_in_the_middle_bumps_that_one(self):
        self.equip('spear', 'rare')
        near = self.monster(11, 10)
        far = self.monster(12, 10)
        self.state.handle_action('move_e')
        self.assertLess(near.hp, 1000)
        self.assertEqual(far.hp, 1000)

    def test_spear_does_not_reach_past_a_wall_or_through_a_door(self):
        with self.subTest('wall: no strike, no move'):
            self.equip('spear', 'rare')
            self.state.game_map[10][11] = WALL
            far = self.monster(12, 10)
            self.state.handle_action('move_e')
            self.assertEqual(far.hp, 1000)
            self.assertEqual((self.state.player.x, self.state.player.y), (10, 10))
        with self.subTest('door: no strike, a move into the doorway'):
            self.setUp()
            self.equip('spear', 'rare')
            self.state.game_map[10][11] = DOOR
            far = self.monster(12, 10)
            # Force the target visible so only the door rule can block the strike.
            self.state.visible[10][12] = True
            self.state.handle_action('move_e')
            self.assertEqual(far.hp, 1000)
            # The door is walkable, so the press is a normal move into it.
            self.assertEqual((self.state.player.x, self.state.player.y), (11, 10))

    def test_out_of_reach_is_just_a_move(self):
        with self.subTest('spear, diagonal'):
            self.equip('spear', 'rare')
            for x, y in ((12, 11), (12, 12), (11, 11)):
                m = self.monster(x, y)
                self.state.player.x, self.state.player.y = 10, 10
                self.state.update_fov()
                self.state.handle_action('move_e')
                self.assertEqual(m.hp, 1000)
                self.assertEqual((self.state.player.x, self.state.player.y), (11, 10))
                m.alive = False
        with self.subTest('spear, three tiles or unseen behind a door'):
            self.setUp()
            self.equip('spear', 'rare')
            far = self.monster(13, 10)
            self.state.handle_action('move_e')
            self.assertEqual(far.hp, 1000)
            self.assertEqual(self.state.player.x, 11)
            # A door in between hides what is behind it: move into the doorway.
            self.state.player.x = 10
            far.x = 12
            self.state.game_map[10][11] = DOOR
            self.state.update_fov()
            self.state.handle_action('move_e')
            self.assertEqual(far.hp, 1000)
            self.assertEqual(self.state.player.x, 11)
        with self.subTest('no spear, two tiles away'):
            self.setUp()
            self.equip('weapon', 'rare')
            far = self.monster(12, 10)
            self.state.handle_action('move_e')
            self.assertEqual(far.hp, 1000)
            self.assertEqual(self.state.player.x, 11)


class BossEnrageTests(unittest.TestCase):
    def _arena(self, depth=8):
        """Open 20x20 floor; player at (5,10), a boss orc at (7,10) with hp 20."""
        state = GameState(20, 20, seed=0)
        state.game_map = make_empty_map(20, 20, WALL)
        for y in range(1, 19):
            for x in range(1, 19):
                state.game_map[y][x] = FLOOR
        state.depth = depth
        state.player.x, state.player.y = 5, 10
        state.player.power = 1
        boss = Monster(7, 10, 'orc', depth=depth, is_boss=True)
        boss.max_hp, boss.hp = 20, 20
        state.entities = [state.player, boss]
        return state, boss

    def _goblins(self, state):
        return [e for e in state.entities if isinstance(e, Monster) and e.kind == 'goblin']

    def test_enrages_once_at_half_hp_not_before(self):
        state, boss = self._arena()
        state.attack(state.player, boss)  # 20 -> ~19, well above half
        self.assertFalse(boss.enraged)
        self.assertEqual(self._goblins(state), [])
        boss.hp = 11
        state.attack(state.player, boss)
        self.assertLessEqual(boss.hp, 10)
        self.assertTrue(boss.enraged)
        count = len(self._goblins(state))
        self.assertEqual(count, 2)
        self.assertTrue(any('calls for help' in m for m in state.messages))
        state.attack(state.player, boss)
        self.assertEqual(len(self._goblins(state)), count)

    def test_summon_count_follows_tier_capped_at_two(self):
        for depth, expected in ((1, 0), (4, 1), (7, 2), (16, 2)):
            state, boss = self._arena(depth)
            boss.hp = 10
            state.attack(state.player, boss)
            self.assertEqual(len(self._goblins(state)), expected, depth)

    def test_summons_on_free_floor_within_three_tiles(self):
        for seed in range(30):
            state, boss = self._arena()
            state.rng.seed(seed)
            blocker = Monster(8, 10, 'goblin')
            state.entities.append(blocker)
            boss.hp = 10
            state.attack(state.player, boss)
            new = [g for g in self._goblins(state) if g is not blocker]
            self.assertEqual(len(new), 2)
            spots = [(g.x, g.y) for g in new]
            self.assertEqual(len(set(spots)), 2)
            for x, y in spots:
                self.assertEqual(state.game_map[y][x], FLOOR)
                self.assertLessEqual(max(abs(x - boss.x), abs(y - boss.y)), 3)
                self.assertNotIn((x, y), [(5, 10), (boss.x, boss.y), (8, 10)])

    def test_no_free_tile_means_no_summons_and_no_crash(self):
        state, boss = self._arena()
        for y in range(20):
            for x in range(20):
                state.game_map[y][x] = WALL
        state.game_map[10][7] = FLOOR
        state.game_map[10][5] = FLOOR
        boss.hp = 10
        state.attack(state.player, boss)
        self.assertTrue(boss.enraged)
        self.assertEqual(self._goblins(state), [])


class GoblinArcherTests(unittest.TestCase):
    """The goblin archer: shoots along a clear row/column up to SHOOT_RANGE,
    backs off when the player is within 2, chases when it can't see."""

    def _arena(self):
        """Open 20x20 floor (walls on the border), player at (5, 10)."""
        state = GameState(20, 20, seed=0)
        state.game_map = make_empty_map(20, 20, WALL)
        for y in range(1, 19):
            for x in range(1, 19):
                state.game_map[y][x] = FLOOR
        state.player.x, state.player.y = 5, 10
        state.player.defense = 0
        state.entities = [state.player]
        return state

    def _add(self, state, x, y):
        shooter = Monster(x, y, 'goblin_archer')
        state.entities.append(shooter)
        state.update_fov()
        return shooter

    def _hits_by(self, state, attacker):
        return [h for h in state.hits() if h.attacker is attacker]

    def test_stats_are_weaker_than_a_goblin(self):
        for depth in (1, 4, 7, 13, 25):
            shooter, gob = Monster(0, 0, 'goblin_archer', depth), Monster(0, 0, 'goblin', depth)
            self.assertLess(shooter.power, gob.power, depth)
            self.assertLess(shooter.hp, gob.hp, depth)
            self.assertEqual((shooter.hp, shooter.power), scale_stats(7, 1, depth))

    def test_char_is_unique_among_monsters_and_items(self):
        # The three slime sizes share one placeholder char, used by nothing else.
        slime_chars = {MONSTER_TYPES[k][0] for k in SLIME_KINDS}
        chars = [c for k, (c, *_) in MONSTER_TYPES.items() if k not in SLIME_KINDS]
        chars += sorted(slime_chars)
        self.assertEqual(len(slime_chars), 1)
        self.assertEqual(len(chars), len(set(chars)))
        self.assertEqual(MONSTER_TYPES['goblin_archer'][0], 's')
        self.assertNotIn(
            's', set(ITEM_CHARS.values()) | {'=', WALL, FLOOR, DOOR, STAIRS_DOWN, '@'}
        )

    def test_shoots_from_three_to_five_tiles_in_a_clear_line(self):
        for gap in range(3, SHOOT_RANGE + 1):
            for dx, dy in ORTHOGONAL_STEPS:
                state = self._arena()
                state.player.x, state.player.y = 9, 9
                shooter = self._add(state, 9 + dx * gap, 9 + dy * gap)
                before = (shooter.x, shooter.y)
                hp = state.player.hp
                state.end_turn()
                self.assertEqual((shooter.x, shooter.y), before, 'a shooter stands still')
                hits = self._hits_by(state, shooter)
                self.assertEqual(len(hits), 1, (gap, dx, dy))
                self.assertEqual(hits[0].defender, state.player)
                self.assertEqual(state.player.hp, hp - hits[0].damage)
                self.assertGreater(hits[0].damage, 0)
                self.assertIn('Goblin archer hits you', state.messages[-1])

    def test_shoots_from_two_tiles_when_cornered(self):
        state = self._arena()
        state.game_map = make_empty_map(20, 20, WALL)
        for x in range(1, 8):  # a dead-end corridor; nowhere to back off to
            state.game_map[10][x] = FLOOR
        shooter = self._add(state, 7, 10)
        hp = state.player.hp
        state.end_turn()
        self.assertEqual((shooter.x, shooter.y), (7, 10))
        self.assertEqual(len(self._hits_by(state, shooter)), 1)
        self.assertLess(state.player.hp, hp)

    def test_out_of_range_or_off_line_it_does_not_shoot(self):
        state = self._arena()
        shooter = self._add(state, 5 + SHOOT_RANGE + 1, 10)
        state.end_turn()
        self.assertEqual(self._hits_by(state, shooter), [])
        self.assertEqual((shooter.x, shooter.y), (5 + SHOOT_RANGE, 10), 'closes in instead')

        state = self._arena()
        shooter = self._add(state, 9, 13)  # diagonal-ish: no straight line
        state.end_turn()
        self.assertEqual(self._hits_by(state, shooter), [])

    def test_never_shoots_through_a_wall_a_closed_door_or_another_monster(self):
        for blocker in (WALL, DOOR):
            state = self._arena()
            state.game_map[10][7] = blocker
            shooter = Monster(9, 10, 'goblin_archer')
            # Even if told it sees the player, the line itself is blocked.
            result = shooter.take_turn(state.player, state.game_map, sees_player=True)
            self.assertIsNone(result, blocker)
            self.assertFalse(shooter.clear_shot(state.player, state.game_map), blocker)

            state = self._arena()
            state.game_map[10][7] = blocker
            shooter = self._add(state, 9, 10)
            hp = state.player.hp
            state.end_turn()
            self.assertEqual(self._hits_by(state, shooter), [], blocker)
            self.assertEqual(state.player.hp, hp, blocker)
        state = self._arena()
        state.entities.append(Monster(8, 10, 'goblin'))
        shooter = Monster(10, 10, 'goblin_archer')
        self.assertFalse(shooter.clear_shot(state.player, state.game_map, {(8, 10)}))

    def test_steps_away_when_the_player_is_within_two(self):
        for start in ((7, 10), (6, 10), (6, 11), (5, 12)):
            state = self._arena()
            shooter = self._add(state, *start)
            gap = shooter.distance_to(state.player)
            hp = state.player.hp
            state.end_turn()
            self.assertNotEqual((shooter.x, shooter.y), start)
            self.assertEqual(shooter.distance_to(state.player), gap + 1, start)
            self.assertEqual(self._hits_by(state, shooter), [], 'retreating, not shooting')
            self.assertEqual(state.player.hp, hp)

    def test_chases_when_it_cannot_see_the_player(self):
        game_map = [list(r) for r in ['#' * 20, '#' + '.' * 18 + '#', '#' * 20]]
        player = Entity(1, 1, '@')
        shooter = Monster(5, 1, 'goblin_archer')
        shooter.chasing = True
        result = shooter.take_turn(player, game_map, sees_player=False)
        self.assertIsNone(result)
        self.assertEqual((shooter.x, shooter.y), (4, 1), 'stepped toward the player')

        # Through the game: a wall hides the player, so it walks round, not shoots.
        state = self._arena()
        for y in range(5, 16):
            state.game_map[y][8] = WALL
        shooter = self._add(state, 10, 10)
        shooter.chasing = True
        self.assertFalse(state.is_visible(10, 10))
        state.end_turn()
        self.assertEqual(self._hits_by(state, shooter), [])
        # The lane chase heads round the wall (x=8, y 5..15) for the player's
        # column: (5, 4) and (5, 16) are both 11 moves off; (5, 4) wins on
        # the (y, x) tie-break, so the first step is north.
        self.assertEqual((shooter.x, shooter.y), (10, 9), 'heads round the wall')

    def test_off_line_it_gets_in_line_then_shoots(self):
        state = self._arena()
        shooter = self._add(state, 9, 13)  # 4 off, no straight line
        with mock.patch('game.fight.dodge_chance', return_value=0):
            for _ in range(3):
                state.end_turn()
                self.assertEqual(self._hits_by(state, shooter), [])
            self.assertEqual((shooter.x, shooter.y), (9, 10), "on the player's row")
            state.end_turn()
        self.assertEqual((shooter.x, shooter.y), (9, 10), 'a shooter stands still')
        self.assertEqual(len(self._hits_by(state, shooter)), 1)

    def test_spawns_in_packs_per_room_from_depth_four(self):
        for depth in (1, 2, 3):
            for _rooms, monsters, _ in seeded_floors(depth, n=100):
                self.assertFalse([m for m in monsters if m.kind == 'goblin_archer'], depth)
        seen = 0
        for depth in (4, 5, 9, 12, 20):
            for rooms, monsters, _ in seeded_floors(depth, n=100):
                for room in rooms[1:]:
                    here = [m for m in monsters if in_room(room, m)]
                    shooters = [m for m in here if m.kind == 'goblin_archer']
                    if shooters:
                        seen += 1
                        self.assertEqual(len(shooters), archer_pack_size(depth))
                        self.assertEqual({m.kind for m in here}, {'goblin_archer'})
        self.assertGreater(seen, 0)

    def test_a_shot_is_named_logged_and_records_one_arrow_to_the_player(self):
        state = self._arena()
        shooter = self._add(state, 9, 10)
        self.assertEqual(shooter.name, 'goblin archer')
        with mock.patch('game.fight.dodge_chance', return_value=0):
            state.end_turn()
        self.assertIn('Goblin archer hits you', ' '.join(state.messages))
        (hit,) = self._hits_by(state, shooter)
        (shot,) = state.events_of(Shot)
        self.assertEqual(len(shot.arrows), 1)
        (arrow,) = shot.arrows
        self.assertEqual(arrow.path, ((9, 10), (8, 10), (7, 10), (6, 10), (5, 10)))
        self.assertEqual(arrow.hits, (hit,))
        self.assertIs(hit.defender, state.player)
        self.assertEqual((shot.path, shot.hits), (arrow.path, arrow.hits))
        self.assertLess(shot.serial, hit.serial, 'the shot sorts before its hit')

    def test_a_melee_blow_records_no_shot(self):
        state = self._arena()
        state.entities.append(Monster(6, 10, 'goblin'))
        state.update_fov()
        with mock.patch('game.fight.dodge_chance', return_value=0):
            state.end_turn()
        self.assertEqual(state.events_of(Shot), [])

    def test_a_dodged_shot_flies_past_the_player_to_the_wall(self):
        state = self._arena()
        shooter = self._add(state, 9, 10)
        hp = state.player.hp
        with mock.patch('game.fight.dodge_chance', return_value=100):
            state.end_turn()
        self.assertEqual(state.player.hp, hp)
        self.assertEqual(self._hits_by(state, shooter), [])
        self.assertIn("You dodge the goblin archer's attack.", state.messages)
        (shot,) = state.events_of(Shot)
        self.assertEqual(shot.hits, ())
        self.assertEqual(shot.path[0], (9, 10))
        self.assertIn((5, 10), shot.path)
        self.assertEqual(shot.path[-1], (1, 10), 'the last floor tile before the wall')


def _in_room(room, e):
    return room.x1 <= e.x < room.x2 and room.y1 <= e.y < room.y2


class ShrinePlacementTests(unittest.TestCase):
    """At most one shrine per floor, ~SHRINE_CHANCE of non-boss floors,
    never in rooms[0] or on a boss floor, never on the stairs or a chest."""

    def floors(self, depths, n):
        state = GameState(50, 20, seed=90)
        for depth in depths:
            for _ in range(n):
                state.depth = depth - 1
                state.next_level()
                yield state

    @staticmethod
    def synthetic_floor(rng):
        """A floor's rooms and occupancy without generating a level: 4-6
        rooms in a row, the stairs at rooms[-1].center() and a few chest-like
        occupied tiles, as place_shrine sees them after spawn_chests."""
        rooms, x = [], 1
        for _ in range(rng.randint(4, 6)):
            w, h = rng.randint(4, 8), rng.randint(4, 8)
            rooms.append(Rect(x, rng.randint(1, 4), w, h))
            x += w + rng.randint(2, 5)
        occupied = {rooms[-1].center()}
        for room in rooms[1:]:
            occupied.add((rng.randint(room.x1, room.x2 - 1), rng.randint(room.y1, room.y2 - 1)))
        return rooms, occupied

    def test_rate_and_rooms_of_place_shrine(self):
        # place_shrine on synthetic floors: never in rooms[0], never on an
        # occupied tile (stairs, chests), about SHRINE_CHANCE of floors.
        rng = random.Random(90)
        found = floors = 0
        for depth in (2, 3, 5, 9):
            for _ in range(500):
                rooms, occupied = self.synthetic_floor(rng)
                floors += 1
                shrine = place_shrine(rooms, depth, occupied, rng=rng)
                if shrine is None:
                    continue
                found += 1
                self.assertFalse(_in_room(rooms[0], shrine))
                self.assertTrue(any(_in_room(r, shrine) for r in rooms[1:]))
                self.assertNotIn((shrine.x, shrine.y), occupied)
        # 2000 floors: well inside +-0.05.
        self.assertGreater(found / floors, SHRINE_CHANCE - 0.05)
        self.assertLess(found / floors, SHRINE_CHANCE + 0.05)

    def test_at_most_one_and_never_on_start_stairs_or_chest(self):
        # The same rules on real floors, where the shrine comes after the
        # monsters and chests (the rate is checked above, on cheap rooms).
        found = 0
        for state in self.floors((2, 3, 5, 9), 15):
            shrines = [e for e in state.entities if isinstance(e, Shrine)]
            self.assertLessEqual(len(shrines), 1)
            if not shrines:
                continue
            found += 1
            shrine = shrines[0]
            self.assertFalse(_in_room(state.rooms[0], shrine))
            self.assertTrue(any(_in_room(r, shrine) for r in state.rooms[1:]))
            self.assertNotEqual(state.game_map[shrine.y][shrine.x], STAIRS_DOWN)
            self.assertIsNone(state.chest_at(shrine.x, shrine.y))
            self.assertIsNone(state.monster_at(shrine.x, shrine.y))
        self.assertGreater(found, 0, 'no shrine on 60 floors: nothing was checked')

    def test_never_on_a_boss_floor(self):
        self.assertTrue(is_boss_level(FIRST_BOSS_DEPTH))
        rng = random.Random(91)
        with mock.patch('game.shrine.SHRINE_CHANCE', 1.0):
            for depth in (FIRST_BOSS_DEPTH, 2 * FIRST_BOSS_DEPTH):
                for _ in range(100):
                    rooms, occupied = self.synthetic_floor(rng)
                    self.assertIsNone(place_shrine(rooms, depth, occupied, rng=rng))
        for state in self.floors((FIRST_BOSS_DEPTH, 2 * FIRST_BOSS_DEPTH), 5):
            self.assertFalse(any(isinstance(e, Shrine) for e in state.entities))

    def test_place_shrine_skips_start_boss_room_and_occupied_tiles(self):
        rooms = [Rect(1, 1, 4, 4), Rect(10, 1, 4, 4), Rect(20, 1, 4, 4)]
        rng = random.Random(3)
        occupied = {(x, y) for x in range(20, 24) for y in range(1, 5)}
        with mock.patch('game.shrine.SHRINE_CHANCE', 1.0):
            for _ in range(50):
                # rooms[0] is the start, rooms[1] the boss room, rooms[2] full.
                self.assertIsNone(place_shrine(rooms, 2, occupied, rooms[1], rng))
            shrine = place_shrine(rooms, 2, occupied, rng=rng)
        self.assertIsNotNone(shrine)
        self.assertTrue(_in_room(rooms[1], cast(Shrine, shrine)))


class ShrineBoonTests(unittest.TestCase):
    """Stepping onto a shrine offers three different boons; choosing one
    applies it once, permanently, and takes no turn."""

    def setUp(self):
        self.state = GameState(50, 20, seed=91)
        self.state.entities = [self.state.player]
        self.start = (self.state.player.x, self.state.player.y)

    def shrine_east(self):
        state = self.state
        state.game_map[state.player.y][state.player.x + 1] = FLOOR
        shrine = Shrine(state.player.x + 1, state.player.y)
        state.entities.append(shrine)
        return shrine

    def offer(self, *keys):
        self.state.pending_choice = [BOONS[k] for k in keys]

    def take(self, key):
        self.offer(key, *[k for k in BOONS if k != key][:2])
        self.state.choose(0)

    def test_every_boon_has_a_benefit_and_a_cost(self):
        self.assertGreaterEqual(len(BOONS), 5)
        for boon in BOONS.values():
            self.assertTrue(boon.benefit and boon.cost, boon.key)
            gains = [
                boon.power > 0,
                boon.max_hp > 0,
                boon.defense > 0,
                boon.crit > 0,
                boon.belt > 0,
            ]
            losses = [boon.power < 0, boon.max_hp < 0, boon.heal < 1]
            self.assertTrue(any(gains) and any(losses), boon.key)

    def test_stepping_onto_a_shrine_offers_three_different_boons(self):
        state = self.state
        shrine = self.shrine_east()
        turn = state.turn
        self.assertTrue(state.handle_action('move_e'))
        self.assertEqual(state.turn, turn + 1)  # the step itself, like a chest
        self.assertEqual((state.player.x, state.player.y), (self.start[0] + 1, self.start[1]))
        self.assertTrue(state.is_choosing)
        offers = cast(list[Boon], state.pending_choice)
        self.assertEqual(len(offers), BOONS_OFFERED)
        self.assertTrue(all(isinstance(b, Boon) for b in offers))
        self.assertEqual(len({b.key for b in offers}), BOONS_OFFERED)
        self.assertNotIn(shrine, state.entities)  # used up
        self.assertIn('shrine', ' '.join(state.messages[-2:]))

    def test_roll_boons_always_different_and_prefers_new_ones(self):
        rng = random.Random(5)
        for _ in range(200):
            keys = [b.key for b in roll_boons(rng=rng)]
            self.assertEqual(len(set(keys)), BOONS_OFFERED)
        held = ['blood_pact', 'iron_skin']
        for _ in range(50):
            keys = {b.key for b in roll_boons(held, rng)}
            self.assertFalse(keys & set(held))
        # Once fewer than three are new, repeats may come back, still distinct.
        keys = [b.key for b in roll_boons(list(BOONS)[:4], rng)]
        self.assertEqual(len(set(keys)), BOONS_OFFERED)

    def test_choose_key_applies_once_takes_no_turn_and_clears(self):
        state = self.state
        self.shrine_east()
        state.handle_action('move_e')
        state.end_turn()
        offers = cast(list[Boon], state.pending_choice)
        turn = state.turn
        self.assertFalse(state.handle_action('choose_2'))
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertIsNone(state.pending_choice)
        self.assertEqual(state.player.boons, [offers[1].key])
        self.assertIn(offers[1].name, ' '.join(state.messages[-2:]))
        # A later digit does nothing: there is no choice any more.
        self.assertFalse(state.handle_action('choose_1'))
        self.assertEqual(state.player.boons, [offers[1].key])

    def test_a_shrine_choice_can_be_skipped_with_no_boon(self):
        state = self.state
        shrine = self.shrine_east()
        state.handle_action('move_e')
        state.end_turn()
        player = state.player
        before = (player.power, player.defense, player.max_hp, player.hp)
        turn = state.turn
        self.assertFalse(state.handle_action('skip'))
        self.assertEqual(state.turn, turn)
        self.assertIsNone(state.pending_choice)
        self.assertEqual(player.boons, [])
        self.assertEqual((player.power, player.defense, player.max_hp, player.hp), before)
        self.assertNotIn(shrine, state.entities)  # gone, as when a boon is taken
        self.assertIn('without a boon', ' '.join(state.messages[-2:]))

    def test_blood_pact_power_up_max_hp_down_hp_clamped_and_never_kills(self):
        player = self.state.player
        power, max_hp = player.power, player.max_hp
        self.take('blood_pact')
        self.assertEqual(player.power, power + 3)
        self.assertEqual(player.max_hp, max_hp - 15)
        self.assertEqual(player.hp, player.max_hp)  # was full: clamped down
        self.setUp()
        player = self.state.player
        player.max_hp = 10
        player.hp = 4
        self.take('blood_pact')
        self.assertEqual(player.max_hp, 1)
        self.assertEqual(player.hp, 1)

    def test_power_boon_survives_a_weapon_swap_without_doubling(self):
        player = self.state.player
        self.take('blood_pact')
        Item(0, 0, 'weapon', 'epic').apply(player, self.state.log)
        self.assertEqual(player.power, player.base_power + GEAR_BONUS['epic'] + 3)
        Item(0, 0, 'weapon', 'epic').apply(player, self.state.log)
        self.assertEqual(player.power, player.base_power + GEAR_BONUS['epic'] + 3)

    def test_iron_skin_defence_up_potions_weaker(self):
        state, player = self.state, self.state.player
        self.take('iron_skin')
        self.assertEqual(player.defense, 2)
        Item(0, 0, 'armor', 'rare').apply(player, state.log)
        self.assertEqual(player.defense, ARMOR_DEFENSE['rare'] + 2)  # kept, not doubled
        player.hp = 1
        state.belt.append(Item(0, 0, 'potion', 'common'))
        state.handle_action('drink')
        self.assertEqual(player.hp, 1 + round(POTION_HEAL['common'] * 0.75))

    def test_quick_hands_adds_a_belt_slot_and_weakens_potions(self):
        state, player = self.state, self.state.player
        self.take('quick_hands')
        self.assertEqual(belt_capacity(player), BELT_SLOTS + 1)
        state.belt[:] = [Item(0, 0, 'potion', 'common') for _ in range(BELT_SLOTS)]
        state.game_map[player.y][player.x + 1] = FLOOR
        chest = Chest(player.x + 1, player.y, kind='potion')
        state.entities.append(chest)
        self.assertTrue(state.handle_action('move_e'))  # a 4th slot is free
        self.assertEqual(len(state.belt), BELT_SLOTS + 1)
        self.assertNotIn(chest, state.entities)
        heal = round(POTION_HEAL['common'] * 0.75)
        self.assertEqual(belt_slot_label(state.belt[0], player), f'+{heal}')
        self.assertEqual(belt_slot_label(state.belt[0]), f'+{POTION_HEAL["common"]}')

    def test_two_heal_costs_multiply(self):
        player = self.state.player
        self.take('iron_skin')
        self.take('quick_hands')
        self.assertAlmostEqual(heal_multiplier(player), 0.75 * 0.75)
        self.assertEqual(belt_capacity(player), BELT_SLOTS + 1)

    def test_keen_eye_crit_up_max_hp_down(self):
        player = self.state.player
        max_hp = player.max_hp
        before = crit_chance(player)
        self.take('keen_eye')
        self.assertAlmostEqual(crit_chance(player), before + 0.10)
        self.assertEqual(player.max_hp, max_hp - 10)

    def test_stone_heart_max_hp_up_power_down(self):
        player = self.state.player
        power, max_hp, hp = player.power, player.max_hp, player.hp
        self.take('stone_heart')
        self.assertEqual(player.power, power - 1)
        self.assertEqual(player.max_hp, max_hp + 15)
        self.assertEqual(player.hp, hp + 15)

    def test_boon_total_sums_the_held_boons(self):
        player = self.state.player
        self.take('blood_pact')
        self.take('keen_eye')
        self.assertEqual(boon_total(player, 'power'), 3)

    def test_a_shrine_does_not_open_while_a_chest_choice_is_pending(self):
        state = self.state
        self.shrine_east()
        state.pending_choice = [Item(0, 0, JUNK)] * 3
        self.assertFalse(state.handle_action('move_e'))
        self.assertEqual((state.player.x, state.player.y), self.start)


class DodgeAndArmorKindTests(unittest.TestCase):
    """Leather (defence + dodge) vs heavy armor (defence only), and the dodge
    roll on monster hits (game/item.py ARMOR_SPLIT / dodge_chance,
    GameState.attack)."""

    def setUp(self):
        self.state = GameState(50, 20, seed=0)
        p = self.state.player
        self.goblin = Monster(p.x + 1, p.y, 'goblin')
        p.hp = p.max_hp = 10**6
        self.state.entities = [p, self.goblin]

    def wear(self, kind, rarity='common'):
        armor = Item(0, 0, kind, rarity)
        armor.apply(self.state.player, self.state.log)
        return armor

    def test_numbers_by_rarity(self):
        heavy = {'common': (3, 0), 'uncommon': (6, 0), 'rare': (12, 0), 'epic': (21, 0)}
        leather = {'common': (2, 4), 'uncommon': (3, 6), 'rare': (6, 9), 'epic': (10, 12)}
        self.assertEqual(ARMOR_SPLIT, {'armor': heavy, 'leather': leather})
        for kind, table in ARMOR_SPLIT.items():
            for rarity, (defense, dodge) in table.items():
                item = Item(0, 0, kind, rarity)
                self.assertEqual((item.bonus, item.dodge), (defense, dodge), (kind, rarity))
                self.assertEqual(GEAR_SLOTS[kind], 'armor')
        # Leather has dodge and heavy has none, but heavy has more defence.
        for rarity in RARITIES:
            self.assertGreater(Item(0, 0, 'leather', rarity).dodge, 0)
            self.assertEqual(Item(0, 0, 'armor', rarity).dodge, 0)
            heavy, leather = ARMOR_SPLIT['armor'][rarity], ARMOR_SPLIT['leather'][rarity]
            self.assertGreater(heavy[0], leather[0])

    def test_dodge_chance_is_the_armors_dodge_capped(self):
        player = self.state.player
        self.assertEqual(dodge_chance(player), 0)
        self.wear('leather', 'rare')
        self.assertEqual(dodge_chance(player), 9)
        self.assertEqual(player.defense, 6)
        self.wear('armor', 'rare')
        self.assertEqual(dodge_chance(player), 0)
        player.armor.dodge = 80
        self.assertEqual(dodge_chance(player), MAX_DODGE)
        self.assertEqual(MAX_DODGE, 50)

    def test_the_dodge_roll_decides_whether_a_monster_blow_lands(self):
        self.wear('leather', 'epic')
        hp = self.state.player.hp
        self.state.events.clear()
        with mock.patch.object(self.state.rng, 'random', return_value=0.0):
            self.state.attack(self.goblin, self.state.player)
        # A dodge avoids the damage, records no Hit and logs.
        self.assertEqual(self.state.player.hp, hp)
        self.assertEqual(self.state.hits(), [])
        self.assertEqual(self.state.messages[-1], "You dodge the goblin's attack.")
        # A failed dodge roll still hits.
        with mock.patch.object(self.state.rng, 'random', return_value=0.99):
            self.state.attack(self.goblin, self.state.player)
        self.assertLess(self.state.player.hp, hp)
        self.assertEqual(len(self.state.hits()), 1)

    def test_seeded_dodges_happen_at_the_dodge_rate(self):
        self.wear('leather', 'epic')  # 12%
        self.state.rng.seed(3)
        n = 5000
        for _ in range(n):
            self.state.attack(self.goblin, self.state.player)
        # (The message log is capped, so count dodges as the blows with no Hit.)
        dodges = n - len(self.state.hits())
        self.assertAlmostEqual(dodges / n, 0.12, delta=0.02)

    def test_no_dodge_without_dodge_gear_nor_against_the_players_attacks(self):
        with self.subTest('heavy armor never dodges'):
            self.wear('armor', 'epic')
            for _ in range(500):
                self.state.attack(self.goblin, self.state.player)
            self.assertEqual(len(self.state.hits()), 500)
            self.assertFalse(any(m.startswith('You dodge') for m in self.state.messages))
        with self.subTest("the player's own attacks are never dodged"):
            self.setUp()
            self.wear('leather', 'epic')
            self.state.player.armor.dodge = 50
            self.goblin.hp = self.goblin.max_hp = 10**6
            for _ in range(200):
                self.state.attack(self.state.player, self.goblin)
            self.assertEqual(len(self.state.hits()), 200)

    def test_a_goblin_archers_shot_can_be_dodged(self):
        p = self.state.player
        shooter = Monster(p.x + 2, p.y, 'goblin_archer')
        self.wear('leather')
        hp = p.hp
        with mock.patch.object(self.state.rng, 'random', return_value=0.0):
            self.state.attack(shooter, p)
        self.assertEqual(p.hp, hp)
        self.assertIn(f"You dodge the {shooter.name}'s attack.", self.state.messages)

    def test_armor_drops_split_evenly_between_the_kinds(self):
        rng = random.Random(11)
        n = 40000
        drops = [roll_gear_drop(1, rng) for _ in range(n)]
        heavy = sum(1 for d in drops if d.kind == 'armor') / n
        leather = sum(1 for d in drops if d.kind == 'leather') / n
        self.assertAlmostEqual(heavy + leather, ARMOR_DROP_CHANCE, delta=0.01)
        self.assertAlmostEqual(heavy, ARMOR_DROP_CHANCE / 2, delta=0.01)
        self.assertAlmostEqual(leather, ARMOR_DROP_CHANCE / 2, delta=0.01)
        boss = [roll_boss_drop(rng) for _ in range(n)]
        self.assertAlmostEqual(
            sum(1 for d in boss if d.kind == 'leather') / n, ARMOR_DROP_CHANCE / 2, delta=0.01
        )
        self.assertEqual(set(ARMOR_KINDS), {'armor', 'leather'})
        self.assertIn('leather', GEAR_DROP_KINDS)

    def test_armor_kinds_found_by_class(self):
        with self.subTest('warriors find both kinds'):
            rng = random.Random(12)
            n = 20000
            drops = [roll_gear_drop(1, rng, char_class='warrior') for _ in range(n)]
            boss = [roll_boss_drop(rng, char_class='warrior') for _ in range(n)]
            for found in (drops, boss):
                kinds = {d.kind for d in found if d.kind in ARMOR_KINDS}
                self.assertEqual(kinds, {'armor', 'leather'})
        with self.subTest('archers find only leather, at the same armor share'):
            rng = random.Random(13)
            n = 40000
            drops = [roll_gear_drop(1, rng, char_class='archer') for _ in range(n)]
            self.assertFalse(any(d.kind == 'armor' for d in drops))
            leather = sum(1 for d in drops if d.kind == 'leather') / n
            self.assertAlmostEqual(leather, ARMOR_DROP_CHANCE, delta=0.01)
            boss = [roll_boss_drop(rng, char_class='archer') for _ in range(n)]
            self.assertFalse(any(d.kind == 'armor' for d in boss))
            leather = sum(1 for d in boss if d.kind == 'leather') / n
            self.assertAlmostEqual(leather, ARMOR_DROP_CHANCE, delta=0.01)
            chest = Chest(0, 0, kind='gear')
            for _ in range(500):
                for item in chest.open(5, rng, char_class='archer'):
                    self.assertNotEqual(item.kind, 'armor')


class ArcherArena(unittest.TestCase):
    """An archer in an open arena: floor inside the border, player at
    (10, 10), no other entities, crits off unless a test turns them on."""

    def setUp(self):
        self.state = GameState(50, 20, char_class='archer', seed=120)
        for y in range(1, 19):
            for x in range(1, 49):
                self.state.game_map[y][x] = FLOOR
        p = self.state.player
        p.x, p.y = 10, 10
        p.hp = p.max_hp = 1000
        # A plain single-target weapon, not the archer's starting longbow.
        p.weapon = Item(0, 0, 'weapon', 'common')
        self.state.entities = [p]
        self.state.update_fov()
        patcher = mock.patch('game.fight.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def equip(self, kind, rarity='common', power=None):
        Item(0, 0, kind, rarity).apply(self.state.player, self.state.log)
        if power is not None:
            self.state.player.power = power

    def monster(self, x, y, hp=1000):
        m = Monster(x, y, 'goblin')
        m.hp = m.max_hp = hp
        m.defense = 0
        self.state.entities.append(m)
        self.state.update_fov()
        return m

    def piles(self):
        return {(e.x, e.y): e.count for e in self.state.entities if isinstance(e, ArrowPile)}


class ArcherWeaponTests(ArcherArena):
    EXPECTED_BONUS = {
        'longbow': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'heavy_crossbow': {'common': 3, 'uncommon': 4, 'rare': 6, 'epic': 9},
        'volley_bow': {'common': -1, 'uncommon': 0, 'rare': 2, 'epic': 5},
        'sling': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'hunters_bow': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'quickdraw': {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7},
        'hand_crossbow': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
    }
    EXPECTED_EFFECT = {
        'longbow': ('pierce', (2, 2, 3, 4)),
        'heavy_crossbow': ('reload', (2, 2, 1, 1)),
        'volley_bow': ('spread', (2, 2, 3, 3)),
        'sling': ('knockback', (1, 1, 2, 2)),
        'hunters_bow': ('mark_bonus', (0.25, 0.50, 0.75, 1.00)),
        'quickdraw': ('tempo', (4, 4, 3, 2)),
        'hand_crossbow': ('hop_shot', (True, True, True, True)),
    }

    # -- data ----------------------------------------------------------------

    def test_archer_weapons_are_weapon_slot_gear_with_a_damage_bonus_by_rarity(self):
        self.assertEqual(set(ARCHER_WEAPONS), set(self.EXPECTED_BONUS))
        self.assertFalse(set(ARCHER_WEAPONS) & set(WARRIOR_WEAPONS))
        for kind in ARCHER_WEAPONS:
            self.assertEqual(GEAR_SLOTS[kind], 'weapon')
            self.assertIn(kind, GEAR_DROP_KINDS)
        p = self.state.player
        for kind, table in self.EXPECTED_BONUS.items():
            for rarity, bonus in table.items():
                self.assertEqual(Item(0, 0, kind, rarity).bonus, bonus, (kind, rarity))
                self.equip(kind, rarity)
                self.assertEqual(p.power, max(1, p.base_power + bonus), (kind, rarity))

    def test_effect_values_by_rarity(self):
        for kind, (attr, values) in self.EXPECTED_EFFECT.items():
            for rarity, value in zip(RARITIES, values):
                self.assertAlmostEqual(getattr(Item(0, 0, kind, rarity), attr), value)
        for rarity, factor in zip(RARITIES, (0.5, 0.5, 0.6, 0.7)):
            self.assertAlmostEqual(Item(0, 0, 'volley_bow', rarity).spread_factor, factor)
        plain = Item(0, 0, 'weapon', 'epic')
        self.assertEqual(
            (plain.pierce, plain.reload, plain.spread, plain.knockback, plain.tempo),
            (1, 0, 0, 0, 0),
        )
        self.assertEqual(plain.mark_bonus, 0.0)

    # -- longbow -------------------------------------------------------------

    def test_longbow_pierces_two_monsters_at_full_damage_in_one_arrow(self):
        self.equip('longbow', 'common', power=6)
        first, second, third = self.monster(12, 10), self.monster(14, 10), self.monster(16, 10)
        self.assertTrue(self.state.shoot_arrow(1, 0))
        self.assertEqual([h.defender for h in self.state.hits()], [first, second])
        self.assertEqual([h.damage for h in self.state.hits()], [6, 6])
        self.assertEqual(third.hp, 1000)
        self.assertEqual(self.piles(), {})  # both hits: the arrow is used up
        # A single-arrow bow records a one-arrow shot.
        (shot,) = self.state.events_of(Shot)
        self.assertEqual(len(shot.arrows), 1)
        self.assertEqual(shot.arrows[0].path[0], (10, 10))
        self.assertEqual([h.defender for h in shot.arrows[0].hits], [first, second])
        self.assertEqual((shot.path, shot.hits), tuple(shot.arrows[0]))

    def test_longbow_stops_at_a_wall(self):
        self.equip('longbow', 'epic')
        self.state.game_map[10][13] = WALL
        near, beyond = self.monster(12, 10), self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertLess(near.hp, 1000)
        self.assertEqual(beyond.hp, 1000)
        self.assertEqual(self.piles(), {})  # it hit the near monster: used up

    def test_a_plain_bow_stops_at_the_first_monster(self):
        first, second = self.monster(12, 10), self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertLess(first.hp, 1000)
        self.assertEqual(second.hp, 1000)

    # -- heavy crossbow ------------------------------------------------------

    def test_crossbow_refuses_a_shot_until_reloaded(self):
        self.equip('heavy_crossbow', 'common')  # reload 2
        state = self.state
        self.assertTrue(state.handle_action('shoot_e'))
        self.assertEqual(state.reload_turns, 2)
        turn = state.turn
        self.assertFalse(state.handle_action('shoot_e'))
        self.assertIn('reloading', state.messages[-1])
        self.assertEqual(state.turn, turn)  # a refused shot takes no turn
        self.assertTrue(state.handle_action('move_s'))  # moving still works
        self.assertEqual(state.reload_turns, 1)
        self.assertFalse(state.handle_action('shoot_e'))
        self.assertTrue(state.handle_action('wait'))  # so does waiting
        self.assertEqual(state.reload_turns, 0)
        self.assertTrue(state.handle_action('shoot_e'))
        self.assertEqual(state.reload_turns, 2)
        # An epic crossbow reloads in one turn.
        self.setUp()
        self.equip('heavy_crossbow', 'epic')
        self.assertTrue(self.state.handle_action('shoot_e'))
        self.assertFalse(self.state.handle_action('shoot_e'))
        self.state.handle_action('wait')
        self.assertTrue(self.state.handle_action('shoot_e'))

    # -- volley bow ----------------------------------------------------------

    def test_volley_hits_the_side_lanes_at_the_damage_factor(self):
        self.equip('volley_bow', 'common', power=10)  # 2 extras at 50%
        aim, left, right = self.monster(13, 10), self.monster(13, 9), self.monster(13, 11)
        self.state.shoot_arrow(1, 0)
        damage = {h.defender: h.damage for h in self.state.hits()}
        self.assertEqual(damage, {aim: 10, left: 5, right: 5})
        self.assertEqual(self.piles(), {})  # the aim arrow hit: used up
        self.assertEqual(self.state.player.quiver, QUIVER_CAPACITY - 1)

    def test_rare_volley_sends_a_third_extra_down_the_aim_line(self):
        self.equip('volley_bow', 'rare', power=10)  # 3 extras at 60%
        aim = self.monster(13, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.damage for h in self.state.hits()], [10, 6])
        self.assertEqual(aim.hp, 1000 - 16)

    def test_volley_side_lane_blocked_by_a_wall_does_not_fire(self):
        self.equip('volley_bow', 'common', power=10)
        self.state.game_map[9][11] = WALL  # the north lane's first tile
        left = self.monster(13, 9)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(left.hp, 1000)

    def test_a_volley_is_one_shot_with_all_its_arrows_from_the_player(self):
        self.equip('volley_bow', 'rare', power=10)  # aim + 3 extras
        aim, left, right = self.monster(13, 10), self.monster(13, 9), self.monster(13, 11)
        state = self.state
        self.assertTrue(state.handle_action('shoot_e'))  # one action, one turn
        self.assertEqual(len(state.events_of(Shot)), 1)  # one shot, not one per arrow
        shot = state.events_of(Shot)[0]
        self.assertEqual(len(shot.arrows), 4)
        for arrow in shot.arrows:
            self.assertEqual(arrow.path[0], (10, 10))  # all leave the player's cell
            for hit in arrow.hits:
                self.assertIn((hit.x, hit.y), arrow.path)
        # The aim arrow comes first and is also the shot's path / hits.
        self.assertEqual(shot.arrows[0].path[1], (11, 10))
        self.assertEqual((shot.path, shot.hits), tuple(shot.arrows[0]))
        # Side arrows step diagonally forward first; the third extra flies the aim line.
        self.assertEqual({a.path[1] for a in shot.arrows[1:3]}, {(11, 9), (11, 11)})
        self.assertEqual(shot.arrows[3].path[1], (11, 10))
        # Each arrow keeps its own hits and damage; all of them are this shot's.
        self.assertEqual(
            [[h.defender for h in a.hits] for a in shot.arrows], [[aim], [right], [left], [aim]]
        )
        self.assertEqual([[h.damage for h in a.hits] for a in shot.arrows], [[10], [6], [6], [6]])
        every = [h for a in shot.arrows for h in a.hits]
        self.assertEqual(sorted(every, key=lambda h: h.serial), state.hits())
        self.assertLess(shot.serial, min(h.serial for h in every))
        # The Shot owns its Hits: none of them is in the stream on its own,
        # and the stream stays in serial order with the Shot in its place.
        self.assertFalse([e for e in state.events if isinstance(e, Hit)])
        serials = [e.serial for e in state.events]
        self.assertEqual(serials, sorted(serials))
        self.assertEqual(state.player.quiver, QUIVER_CAPACITY - 1)  # one arrow spent
        self.assertEqual(state.turn, 1)  # all of it on the same turn

    def test_point_blank_volley_puts_every_arrow_into_the_adjacent_target(self):
        self.equip('volley_bow', 'common', power=10)  # 2 extras at 50%
        target = self.monster(11, 10)
        left, right = self.monster(11, 9), self.monster(11, 11)  # the side lanes
        state = self.state
        self.assertTrue(state.handle_action('shoot_e'))
        hits = state.hits()
        self.assertEqual(len(hits), 3)  # the aim arrow and both extras
        self.assertEqual([h.defender for h in hits], [target] * 3)
        # Point blank is halved: the aim arrow's 10 * 0.5 = 5 is whole before rounding.
        # No crit (BASE_CRIT_CHANCE is 0 here), so it is exactly 5.
        self.assertEqual(hits[0].damage, 5)
        # Each extra is 10 * 0.5 (volley) * 0.5 (point blank) = 2.5, rounded either way.
        for hit in hits[1:]:
            self.assertIn(hit.damage, (2, 3))
        self.assertEqual(target.hp, 1000 - sum(h.damage for h in hits))
        self.assertEqual((left.hp, right.hp), (1000, 1000))
        (shot,) = state.events_of(Shot)
        self.assertEqual(len(shot.arrows), 3)
        for arrow in shot.arrows:
            self.assertEqual(arrow.path, ((10, 10), (11, 10)))
            self.assertEqual([h.defender for h in arrow.hits], [target])
        self.assertEqual(state.player.quiver, QUIVER_CAPACITY - 1)  # one arrow spent
        self.assertEqual(self.piles(), {})
        # A rare volley lands all four arrows.
        self.setUp()
        self.equip('volley_bow', 'rare', power=10)  # 3 extras at 60%
        target = self.monster(11, 10)
        self.state.shoot_arrow(1, 0)
        hits = self.state.hits()
        self.assertEqual(len(hits), 4)  # the aim arrow and three extras
        self.assertEqual([h.defender for h in hits], [target] * 4)
        self.assertEqual(hits[0].damage, 5)  # 10 * 0.5, whole before rounding
        # Each extra is 10 * 0.6 * 0.5 = 3.0 before rounding; a float hair above 3 may round to 4.
        for hit in hits[1:]:
            self.assertIn(hit.damage, (3, 4))
        self.assertEqual(target.hp, 1000 - sum(h.damage for h in hits))

    def test_point_blank_volley_does_not_overkill(self):
        self.equip('volley_bow', 'common', power=10)
        target = self.monster(11, 10, hp=5)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.hits()], [target])
        self.assertFalse(target.alive)
        (shot,) = self.state.events_of(Shot)
        self.assertEqual([len(a.hits) for a in shot.arrows], [1, 0, 0])

    def test_volley_two_tiles_away_is_not_point_blank(self):
        self.equip('volley_bow', 'common', power=10)
        target = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.hits()], [target])
        self.assertEqual(target.hp, 990)

    def test_attack_factor_defaults_to_one(self):
        m = self.monster(11, 10)
        self.state.player.power = 8
        self.state.attack(self.state.player, m)
        self.state.attack(self.state.player, m, 0.5)
        self.assertEqual([h.damage for h in self.state.hits()], [8, 4])

    # -- sling ---------------------------------------------------------------

    def test_sling_pushes_the_target_away_by_its_knockback(self):
        for rarity, landing in (('common', (13, 10)), ('rare', (14, 10))):
            with self.subTest(rarity):
                self.setUp()
                self.equip('sling', rarity)
                m = self.monster(12, 10)
                self.state.shoot_arrow(1, 0)
                self.assertEqual((m.x, m.y), landing)
                self.assertEqual(len(self.state.hits()), 1)  # the push is no Hit
                self.assertEqual(self.piles(), {})  # the shot hit: used up

    def test_sling_push_stops_short_of_a_wall_or_a_monster(self):
        self.equip('sling', 'common')
        self.state.game_map[10][13] = WALL
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (12, 10))
        self.state.game_map[10][13] = FLOOR
        behind = self.monster(13, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(((m.x, m.y), (behind.x, behind.y)), ((12, 10), (13, 10)))
        # An epic sling (push 2) with a wall two tiles back moves it one.
        self.setUp()
        self.equip('sling', 'epic')
        self.state.game_map[10][14] = WALL
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (13, 10))

    # -- hunter's bow --------------------------------------------------------

    def test_a_mark_adds_damage_to_the_next_arrow_until_death_or_a_new_mark(self):
        with self.subTest('common: +25% on the next arrow, cleared on death'):
            self.equip('hunters_bow', 'common', power=8)  # +25%
            state = self.state
            m = self.monster(12, 10)
            state.shoot_arrow(1, 0)
            self.assertIs(state.marked, m)
            state.shoot_arrow(1, 0)
            self.assertEqual([h.damage for h in state.hits()], [8, 10])
            m.hp = 1
            state.shoot_arrow(1, 0)
            self.assertFalse(m.alive)
            self.assertIsNone(state.marked)
        with self.subTest('epic: a new mark replaces the old'):
            self.setUp()
            self.equip('hunters_bow', 'epic', power=8)  # +100%
            state = self.state
            east, west = self.monster(12, 10), self.monster(8, 10)
            state.shoot_arrow(1, 0)
            state.shoot_arrow(-1, 0)
            self.assertIs(state.marked, west)
            state.shoot_arrow(1, 0)  # east is no longer marked: plain damage
            self.assertEqual([h.damage for h in state.hits()], [8, 8, 8])
            self.assertIs(state.marked, east)

    # -- quickdraw -----------------------------------------------------------

    def test_every_tempo_th_quickdraw_shot_is_free(self):
        with self.subTest('common: every fourth'):
            self.equip('quickdraw', 'common')  # tempo 4
            state = self.state
            target = self.monster(14, 10)
            self.monster(40, 15)  # someone to queue
            with mock.patch.object(Monster, 'take_turn', return_value=None) as turn:
                for shot in range(1, 9):
                    self.assertTrue(state.handle_action('shoot_e'))
                    free = shot % 4 == 0
                    self.assertEqual(state.monster_phase_pending(), not free, shot)
                    calls = turn.call_count
                    state.end_turn()
                    self.assertEqual(turn.call_count == calls, free, shot)
            self.assertEqual(state.turn, 8)
            self.assertEqual(target.hp, 1000 - 8 * state.player.power)  # all real shots
        with self.subTest('epic: every second'):
            self.setUp()
            self.equip('quickdraw', 'epic')
            self.monster(40, 15)
            self.state.handle_action('shoot_e')
            self.assertTrue(self.state.monster_phase_pending())
            self.state.end_turn()
            self.state.handle_action('shoot_e')
            self.assertFalse(self.state.monster_phase_pending())

    # -- who finds what ------------------------------------------------------

    def test_weapons_drop_only_to_their_own_class(self):
        rng = random.Random(121)
        for char_class, own, other, armor in (
            ('archer', ARCHER_WEAPONS, WARRIOR_WEAPONS, {'leather'}),
            ('warrior', WARRIOR_WEAPONS, ARCHER_WEAPONS, set(ARMOR_KINDS)),
        ):
            drops = [roll_gear_drop(1, rng, char_class) for _ in range(3000)]
            drops += [roll_boss_drop(rng, char_class) for _ in range(3000)]
            kinds = {d.kind for d in drops}
            self.assertFalse(kinds & set(other), char_class)
            self.assertTrue(set(own) <= kinds, char_class)
            self.assertEqual(kinds & set(ARMOR_KINDS), armor, char_class)

    def test_chests_opened_in_game_follow_the_class(self):
        for char_class, other in (('archer', WARRIOR_WEAPONS), ('warrior', ARCHER_WEAPONS)):
            state = GameState(50, 20, char_class=char_class, seed=0)
            for seed in range(60):
                state.rng.seed(seed)
                chest = Chest(state.player.x, state.player.y, kind='gear')
                boss = spawn_boss_chest(state.player.x, state.player.y)
                for c in (chest, boss):
                    state.entities.append(c)
                    state.pending_choice = None
                    state.open_chest(c)
                    kinds = {item.kind for item in cast(list, state.pending_choice)}
                    self.assertFalse(kinds & set(other), char_class)


class ArrowDoorTests(ArcherArena):
    """A closed door stops an arrow the way a wall does (it blocks sight,
    tiles.is_transparent), so the player can't shoot what they can't see.
    A creature standing in the doorway itself is still hit: the rule
    matches Monster.clear_shot, where the far end may be a door tile."""

    def test_a_door_in_the_lane_stops_the_arrow_before_it(self):
        self.state.game_map[10][13] = DOOR
        beyond = self.monster(15, 10)
        self.assertTrue(self.state.shoot_arrow(1, 0))
        self.assertEqual(beyond.hp, 1000)
        self.assertEqual(self.state.hits(), [])
        self.assertEqual(self.piles(), {(12, 10): 1})  # the last free tile, as at a wall
        self.assertEqual(self.state.events_of(Shot)[-1].path, ((10, 10), (11, 10), (12, 10)))

    def test_a_monster_in_the_doorway_is_hit_and_the_arrow_stops_there(self):
        self.equip('longbow', 'epic')  # pierce 4: only the door stops it
        self.state.game_map[10][13] = DOOR
        in_door, beyond = self.monster(13, 10), self.monster(15, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.hits()], [in_door])
        self.assertEqual(beyond.hp, 1000)
        self.assertEqual(self.piles(), {})

    def test_a_volley_side_arrow_stops_at_a_door(self):
        with self.subTest('door two tiles out: the arrow stops before it'):
            self.equip('volley_bow', 'common', power=10)
            self.state.game_map[9][13] = DOOR  # the north lane, two tiles out
            left = self.monster(14, 9)
            self.state.shoot_arrow(1, 0)
            self.assertEqual(left.hp, 1000)
        with self.subTest('door on the lane start: that side arrow never fires'):
            self.setUp()
            self.equip('volley_bow', 'common', power=10)
            self.state.game_map[9][11] = DOOR  # the north lane's first tile
            left = self.monster(13, 9)
            self.state.shoot_arrow(1, 0)
            self.assertEqual(left.hp, 1000)
            self.assertEqual(len(self.state.events_of(Shot)[-1].arrows), 2)  # aim + south lane


class ArriveOnTileTests(ArcherArena):
    """Walking and the hop's landing share one 'arrive on a tile' rule:
    gold and arrows are picked up either way."""

    def test_a_hop_landing_picks_up_arrows_and_gold_but_not_what_it_passes(self):
        with self.subTest('arrows on the landing tile'):
            state = self.state
            state.player.quiver = 5
            state.entities.append(ArrowPile(12, 10, count=3))
            self.assertFalse(state.handle_action('ability'))
            self.assertTrue(state.handle_action('move_e'))
            self.assertEqual((state.player.x, state.player.y), (12, 10))
            self.assertEqual(state.player.quiver, 8)
            self.assertEqual(self.piles(), {})
        with self.subTest('gold on the landing tile'):
            self.setUp()
            state = self.state
            state.entities.append(GoldPile(12, 10, 7))
            gold = state.player.gold
            state.handle_action('ability')
            state.handle_action('move_e')
            self.assertEqual(state.player.gold, gold + 7)
        with self.subTest('arrows on the tile hopped over'):
            self.setUp()
            state = self.state
            state.player.quiver = 5
            state.entities.append(ArrowPile(11, 10, count=3))
            state.handle_action('ability')
            state.handle_action('move_e')
            self.assertEqual((state.player.x, state.player.y), (12, 10))
            self.assertEqual(state.player.quiver, 5)


class EndTurnTests(unittest.TestCase):
    """end_turn() runs exactly what main.run would after the last
    handle_action: nothing after an action that took no turn."""

    def chased_state(self):
        state = open_floor_state(41)
        p = state.player
        goblin = Monster(p.x + 3, p.y, 'goblin')
        state.entities = [p, goblin]
        state.update_fov()
        return state, goblin

    def test_end_turn_after_a_refused_action_moves_no_monster(self):
        state, goblin = self.chased_state()
        for action in ('choose_1', 'skip', 'drink', None):
            self.assertFalse(state.handle_action(action))
            state.end_turn()
            self.assertEqual((goblin.x, goblin.y), (state.player.x + 3, state.player.y), action)
        self.assertEqual(state.turn, 0)

    def test_end_turn_runs_the_owed_monster_half_exactly_once(self):
        def after_a_wait(state):
            self.assertTrue(state.handle_action('wait'))

        def after_a_round_stepped_through(state):
            self.assertTrue(state.handle_action('wait'))
            while state.step_monster_phase():  # main.run's way
                pass

        def with_no_action(state):
            pass

        for before in (after_a_wait, after_a_round_stepped_through, with_no_action):
            with self.subTest(before.__name__):
                state, goblin = self.chased_state()
                before(state)
                state.end_turn()  # a stepped-through round owes nothing more
                self.assertEqual((goblin.x, goblin.y), (state.player.x + 2, state.player.y))


class StartingKitTests(unittest.TestCase):
    def test_starting_weapon_and_armor_by_class(self):
        archer = GameState(50, 20, char_class='archer', seed=0).player
        self.assertEqual((archer.weapon.kind, archer.weapon.rarity), ('longbow', 'common'))
        self.assertEqual(archer.weapon.pierce, 2)
        # base 3 + common bonus 1 + longbow offset -1 = 3 (above MIN_POWER).
        self.assertEqual(archer.power, 3)
        self.assertEqual((archer.armor.kind, archer.armor.rarity), ('leather', 'common'))
        self.assertEqual(archer.defense, ARMOR_SPLIT['leather']['common'][0])
        self.assertEqual(dodge_chance(archer), ARMOR_SPLIT['leather']['common'][1])
        warrior = GameState(50, 20, char_class='warrior', seed=0).player
        self.assertEqual((warrior.weapon.kind, warrior.weapon.rarity), ('weapon', 'common'))
        self.assertIsNone(warrior.armor)
        self.assertEqual(warrior.defense, 0)


class QuiverTests(ArcherArena):
    def test_archer_starts_with_a_full_quiver_and_warrior_has_none(self):
        self.assertEqual(self.state.player.quiver, QUIVER_CAPACITY)
        self.assertEqual(QUIVER_CAPACITY, 12)
        self.assertIsNone(GameState(50, 20, char_class='warrior', seed=0).player.quiver)

    def test_a_shot_spends_one_arrow(self):
        self.state.handle_action('shoot_e')
        self.assertEqual(self.state.player.quiver, QUIVER_CAPACITY - 1)

    def test_no_arrows_refuses_the_shot_without_a_turn(self):
        state = self.state
        state.player.quiver = 0
        m = self.monster(12, 10)
        self.assertFalse(state.handle_action('shoot_e'))
        self.assertEqual(state.messages[-1], 'No arrows left.')
        self.assertEqual((state.turn, m.hp, self.piles()), (0, 1000, {}))
        self.assertFalse(state.monster_phase_pending())

    def test_pile_lies_where_the_arrow_stopped(self):
        state = self.state
        state.shoot_arrow(1, 0)  # nothing in the way: the tile before the wall
        state.shoot_arrow(1, 0)  # the same tile: one pile of two
        self.assertEqual(self.piles(), {(48, 10): 2})
        self.monster(10, 13)
        state.shoot_arrow(0, 1)  # a hit arrow is used up: no new pile
        self.assertEqual(self.piles(), {(48, 10): 2})

    def test_walking_onto_a_pile_picks_up_what_fits(self):
        # quiver before, pile size -> quiver after, pile left behind, message
        for quiver, count, after, left, message in (
            (10, 1, 11, {}, None),  # a pile does not block and is picked up
            (QUIVER_CAPACITY, 1, QUIVER_CAPACITY, {(11, 10): 1}, 'Your quiver is full.'),
            (QUIVER_CAPACITY - 1, 3, QUIVER_CAPACITY, {(11, 10): 2}, None),  # split
        ):
            with self.subTest(quiver=quiver, count=count):
                self.setUp()
                state = self.state
                state.player.quiver = quiver
                state.entities.append(ArrowPile(11, 10, count=count))
                self.assertTrue(state.handle_action('move_e'))
                self.assertEqual((state.player.x, state.player.y), (11, 10))
                self.assertEqual(state.player.quiver, after)
                self.assertEqual(self.piles(), left)
                if message:
                    self.assertIn(message, state.messages)

    def test_restock_adds_an_arrow_every_three_turns_up_to_capacity(self):
        state = self.state
        state.player.quiver = 5
        self.assertEqual(state.restock_progress, 0)
        seen = []
        for _ in range(6):
            state.handle_action('wait')
            seen.append((state.restock_progress, state.player.quiver))
        self.assertEqual(RESTOCK_TURNS, 3)
        self.assertEqual(seen, [(1, 5), (2, 5), (3, 6), (1, 6), (2, 6), (3, 7)])
        # It stops at capacity.
        self.setUp()
        state = self.state
        state.player.quiver = QUIVER_CAPACITY - 1
        for _ in range(3):
            state.handle_action('wait')
        self.assertEqual((state.player.quiver, state.restock_progress), (QUIVER_CAPACITY, 3))
        for _ in range(4):
            state.handle_action('wait')
        self.assertEqual((state.player.quiver, state.restock_progress), (QUIVER_CAPACITY, 0))

    def test_restock_counts_player_turns_not_the_monster_phase(self):
        state = self.state
        state.player.quiver = 5
        self.monster(40, 15)
        state.handle_action('wait')
        state.end_turn()
        state.end_turn()
        self.assertEqual(state.restock_progress, 1)

    def test_warrior_has_no_quiver_and_its_arrow_keys_move(self):
        state = GameState(50, 20, char_class='warrior', seed=122)
        state.entities = [state.player]
        px, py = state.player.x, state.player.y
        state.game_map[py][px + 1] = FLOOR
        state.handle_action('shoot_e')
        self.assertEqual((state.player.x, state.player.y), (px + 1, py))
        self.assertIsNone(state.player.quiver)
        self.assertEqual(state.restock_progress, 0)
        self.assertFalse(any(isinstance(e, ArrowPile) for e in state.entities))
        self.assertNotIn('You loose an arrow.', state.messages)


class DescentHealTests(unittest.TestCase):
    def _on_stairs(self):
        state = GameState(50, 20, seed=11)
        state.player.x, state.player.y = state.rooms[-1].center()
        return state

    @staticmethod
    def _line(n):
        return f'You descend the stairs and rest for a while, restoring {n} HP.'

    def test_descent_heals_a_fraction_of_max_hp_capped_and_logged(self):
        for name, missing, healed in (
            ('full HP restores nothing', lambda top: 0, lambda top: 0),
            (
                'half HP restores the fraction',
                lambda top: top - top // 2,
                lambda top: int(top * DESCENT_HEAL_FRACTION),
            ),
            ('near max caps at max', lambda top: 1, lambda top: 1),
        ):
            with self.subTest(name):
                state = self._on_stairs()
                top = state.player.max_hp
                state.player.hp = top - missing(top)
                before = state.player.hp
                self.assertTrue(state.try_descend())
                self.assertEqual(state.player.hp, before + healed(top))
                self.assertLessEqual(state.player.hp, top)
                self.assertIn(self._line(healed(top)), state.messages)

    def test_a_refused_or_dead_descent_heals_nothing(self):
        with self.subTest('off the stairs'):
            state = self._on_stairs()
            state.player.x, state.player.y = state.rooms[0].center()
            state.player.hp = 1
            self.assertFalse(state.try_descend())
            self.assertEqual(state.player.hp, 1)
            self.assertEqual(state.depth, 1)
        with self.subTest('game over'):
            state = self._on_stairs()
            state.player.hp = 0
            state.game_over = True
            self.assertFalse(state.try_descend())
            self.assertEqual(state.player.hp, 0)
            self.assertEqual(state.depth, 1)


class BossStairsTests(unittest.TestCase):
    """On a boss floor the stairs down are in the boss room, off the boss's
    tile and the arena's centre 3x3, on no entity, and reachable."""

    BOSS_DEPTHS = (8, 16, 24)
    SEEDS = range(25)

    @staticmethod
    def _floor(depth, seed):
        state = GameState(40, 20, seed=seed)
        state.depth = depth - 1
        state.next_level()
        return state

    @staticmethod
    def _stairs(state):
        found = [
            (x, y)
            for y, row in enumerate(state.game_map)
            for x, ch in enumerate(row)
            if ch == STAIRS_DOWN
        ]
        assert len(found) == 1, found
        return found[0]

    @staticmethod
    def _reachable(state, start, goal):
        seen = {start}
        frontier = [start]
        while frontier:
            x, y = frontier.pop()
            if (x, y) == goal:
                return True
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n not in seen and is_walkable(state.game_map, *n):
                    seen.add(n)
                    frontier.append(n)
        return False

    def test_stairs_in_boss_room_and_clear_of_everything(self):
        for depth in self.BOSS_DEPTHS:
            for seed in self.SEEDS:
                with self.subTest(depth=depth, seed=seed):
                    state = self._floor(depth, seed)
                    arena = state.boss_arena
                    self.assertIsNotNone(arena)
                    sx, sy = self._stairs(state)
                    self.assertTrue(arena.x1 <= sx < arena.x2 and arena.y1 <= sy < arena.y2)
                    boss = next(m for m in state.entities if getattr(m, 'is_boss', False))
                    # The boss keeps its centre tile.
                    self.assertEqual((boss.x, boss.y), arena.center())
                    cx, cy = arena.center()
                    self.assertGreater(max(abs(sx - cx), abs(sy - cy)), 1)
                    self.assertGreaterEqual(
                        max(abs(sx - boss.x), abs(sy - boss.y)), BOSS_STAIRS_MIN_DISTANCE
                    )
                    for e in state.entities:
                        self.assertNotEqual((e.x, e.y), (sx, sy), e)
                    self.assertTrue(is_walkable(state.game_map, sx, sy))
                    self.assertTrue(
                        self._reachable(state, (state.player.x, state.player.y), (sx, sy))
                    )
                    # The start room and the arrival are unchanged.
                    self.assertEqual((state.player.x, state.player.y), state.rooms[0].center())

    def test_non_boss_floor_keeps_last_room_centre(self):
        for depth in (1, 7, 9, 17):
            for seed in range(10):
                with self.subTest(depth=depth, seed=seed):
                    state = self._floor(depth, seed)
                    self.assertIsNone(state.boss_arena)
                    self.assertEqual(self._stairs(state), state.rooms[-1].center())

    def test_descending_from_boss_floor_stairs(self):
        state = self._floor(8, 0)
        state.player.x, state.player.y = self._stairs(state)
        state.try_descend()
        self.assertEqual(state.depth, 9)
        self.assertEqual((state.player.x, state.player.y), state.rooms[0].center())

    def test_small_room_falls_back_to_outside_the_centre(self):
        # A 4x4 room (tiles 1..4, centre (3, 3)) with the boss moved off the
        # centre to (2, 2): the only free tile outside the centre 3x3, (1, 1),
        # is next to the boss, so rule 2 takes it anyway.
        game_map = make_empty_map(8, 8, fill=FLOOR)
        arena = Rect(1, 1, 4, 4)
        cx, cy = arena.center()
        boss = (2, 2)
        occupied = {(x, y) for x in range(1, 5) for y in range(1, 5)} - {(1, 1), (cx, cy)}
        self.assertEqual(boss_stairs_tile(game_map, arena, boss, occupied), (1, 1))
        # Only the centre left (and not the boss's tile): rule 3.
        occupied.add((1, 1))
        self.assertEqual(boss_stairs_tile(game_map, arena, (1, 1), occupied), (cx, cy))
        occupied.add((cx, cy))
        self.assertIsNone(boss_stairs_tile(game_map, arena, boss, occupied))


if __name__ == '__main__':
    unittest.main()
