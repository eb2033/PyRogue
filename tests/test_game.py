"""Headless tests for game/ logic (no window — this exercises GameState
and its collaborators directly, the same way the renderer would).

Run with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import random
import sys
import unittest
from typing import cast
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    MONSTER_TYPES,
    ORTHOGONAL_STEPS,
    SHOOT_RANGE,
    Monster,
    is_boss_level,
    scale_stats,
    spawn_boss,
    spawn_monsters,
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
    boons_text,
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
from game.state import (
    BASE_CRIT_CHANCE,
    CRIT_MULTIPLIER,
    DESCENT_HEAL_FRACTION,
    PARRY_COOLDOWN,
    GameState,
    crit_chance,
)
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, WALL, is_walkable


class DungeonGenerationTests(unittest.TestCase):
    def test_map_is_bordered_and_in_bounds(self):
        random.seed(1)
        game_map, rooms = generate_dungeon(50, 20)
        self.assertEqual(len(game_map), 20)
        self.assertEqual(len(game_map[0]), 50)
        for x in range(50):
            self.assertEqual(game_map[0][x], WALL)
            self.assertEqual(game_map[19][x], WALL)
        for y in range(20):
            self.assertEqual(game_map[y][0], WALL)
            self.assertEqual(game_map[y][49], WALL)

    def test_rooms_do_not_overlap(self):
        random.seed(2)
        _, rooms = generate_dungeon(50, 20)
        for i, r1 in enumerate(rooms):
            for r2 in rooms[i + 1 :]:
                self.assertFalse(r1.intersects(r2), 'rooms should not overlap')

    def test_rooms_are_carved_floor(self):
        random.seed(3)
        game_map, rooms = generate_dungeon(50, 20)
        for room in rooms:
            cx, cy = room.center()
            self.assertEqual(game_map[cy][cx], FLOOR)

    def test_place_stairs_marks_last_room_center(self):
        random.seed(4)
        game_map, rooms = generate_dungeon(50, 20)
        sx, sy = place_stairs(game_map, rooms)
        self.assertEqual(game_map[sy][sx], STAIRS_DOWN)
        self.assertEqual((sx, sy), rooms[-1].center())


class SizeByDepthTests(unittest.TestCase):
    """Rooms grow with depth (dungeon.room_growth) and the map with them
    (dungeon.map_size), keeping 4-6 rooms a floor."""

    DEPTHS = (1, 8, 9, 16, 17, 30)

    def test_room_growth_table(self):
        self.assertEqual([room_growth(d) for d in self.DEPTHS], [2, 2, 5, 5, 6, 6])

    def test_growth_is_added_on_every_side_of_the_base_room(self):
        for depth in self.DEPTHS:
            extra = 2 * room_growth(depth)
            self.assertEqual(room_size_range(depth), (4 + extra, 8 + extra))

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

    def test_next_level_rebuilds_the_map_size(self):
        random.seed(5)
        state = GameState(40, 20)
        self.assertEqual((state.width, state.height), map_size(40, 20, 1))
        while state.depth < 17:
            state.next_level()
            w, h = map_size(40, 20, state.depth)
            self.assertEqual((state.width, state.height), (w, h))
            for grid in (state.game_map, state.visible, state.seen):
                self.assertEqual((len(grid[0]), len(grid)), (w, h))
            self.assertTrue(state.visible[state.player.y][state.player.x])

    def test_no_entity_is_placed_outside_the_map(self):
        random.seed(6)
        state = GameState(40, 20)
        while state.depth <= 25:
            for entity in state.entities:
                self.assertTrue(0 < entity.x < state.width - 1, (state.depth, entity))
                self.assertTrue(0 < entity.y < state.height - 1, (state.depth, entity))
                self.assertNotEqual(state.game_map[entity.y][entity.x], WALL)
            if is_boss_level(state.depth):
                # A boss floor's arena is still one of its (grown) rooms.
                self.assertIn(state.boss_arena, state.rooms[1:])
                boss = next(m for m in state.entities if getattr(m, 'is_boss', False))
                self.assertEqual((boss.x, boss.y), state.boss_arena.center())
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
        # Shared, generated once: routing makes generation ~8 ms a map. Tests
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

    def test_every_single_tile_gap_is_a_door_flanked_by_wall(self):
        for game_map, rooms in self.maps():
            for room in rooms:
                for side in wall_sides(room):
                    tiles = [game_map[y][x] for x, y in side]
                    for i, tile in enumerate(tiles):
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

    def test_corridors_never_open_a_wall_wider_than_one_tile(self):
        # Corridors are routed after every room exists and cross walls only
        # head-on, so every opening is a doorway one door can close.
        for game_map, rooms in self.maps():
            for room in rooms:
                for side in wall_sides(room):
                    run = 0
                    for x, y in side:
                        run = run + 1 if game_map[y][x] != WALL else 0
                        self.assertLessEqual(run, 1, (room.x1, room.y1, (x, y)))

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


class EntityMovementTests(unittest.TestCase):
    def test_move_onto_floor_succeeds(self):
        game_map = [list(row) for row in ['#####', '#...#', '#####']]
        e = Entity(1, 1, '@')
        e.move(1, 0, game_map)
        self.assertEqual((e.x, e.y), (2, 1))

    def test_move_into_wall_is_blocked(self):
        game_map = [list(row) for row in ['#####', '#...#', '#####']]
        e = Entity(1, 1, '@')
        e.move(-1, 0, game_map)
        self.assertEqual((e.x, e.y), (1, 1))

    def test_is_walkable(self):
        game_map = [list(row) for row in ['###', '#.#', '###']]
        self.assertTrue(is_walkable(game_map, 1, 1))
        self.assertFalse(is_walkable(game_map, 0, 0))


class AdjacencyTests(unittest.TestCase):
    def test_is_adjacent_is_orthogonal_not_chebyshev(self):
        origin = Entity(5, 5, '@')
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            self.assertTrue(origin.is_adjacent(Entity(5 + dx, 5 + dy, 'g')))
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            other = Entity(5 + dx, 5 + dy, 'g')
            self.assertFalse(origin.is_adjacent(other))
            self.assertEqual(origin.distance_to(other), 1)  # still Chebyshev-1

    def test_is_adjacent_excludes_self_and_distant(self):
        origin = Entity(5, 5, '@')
        self.assertFalse(origin.is_adjacent(Entity(5, 5, 'g')))
        self.assertFalse(origin.is_adjacent(Entity(5, 7, 'g')))


class FovShadowcastingTests(unittest.TestCase):
    def _grid(self, w, h):
        return [[False] * w for _ in range(h)]

    def test_open_room_lights_up_to_radius(self):
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

    def test_wall_blocks_sight_behind_it(self):
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

    def test_adjacent_monster_attacks_instead_of_moving(self):
        game_map = [list(row) for row in ['#####', '#...#', '#####']]
        player = Entity(2, 1, '@')
        m = Monster(3, 1, 'goblin')
        result = m.take_turn(player, game_map)
        self.assertEqual(result, 'attack')
        self.assertEqual((m.x, m.y), (3, 1))  # did not move

    def test_diagonal_neighbour_is_not_attacked(self):
        """The bug: a diagonal monster used to get a free hit the player had
        no legal move to answer, since the player only moves 4-way."""
        game_map = self.room_map()
        player = Entity(3, 3, '@')
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            m = Monster(3 + dx, 3 + dy, 'goblin')
            self.assertNotEqual(
                m.take_turn(player, game_map), 'attack', f'diagonal offset {(dx, dy)} attacked'
            )

    def test_diagonal_neighbour_closes_in_instead_of_stalling(self):
        """Making the attack orthogonal is only half the fix: the monster
        must still be able to reach a square it can attack from."""
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            game_map = self.room_map()
            player = Entity(3, 3, '@')
            m = Monster(3 + dx, 3 + dy, 'goblin')
            m.take_turn(player, game_map)
            self.assertTrue(
                m.is_adjacent(player), f'diagonal offset {(dx, dy)} failed to close in'
            )
            self.assertEqual(m.take_turn(player, game_map), 'attack')

    def test_orthogonal_neighbour_still_attacks(self):
        game_map = self.room_map()
        player = Entity(3, 3, '@')
        for dx, dy in ORTHOGONAL_STEPS:
            m = Monster(3 + dx, 3 + dy, 'goblin')
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

    def test_spawn_monsters_skips_first_room(self):
        rooms = [Rect(1, 1, 8, 8), Rect(20, 1, 8, 8), Rect(1, 12, 8, 6)]
        for seed in range(50):
            for depth in (1, 8, 12):
                monsters = spawn_monsters(rooms, depth, rng=random.Random(seed))
                self.assertTrue(monsters)
                for m in monsters:
                    self.assertFalse(in_room(rooms[0], m))


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
        for d in range(1, 6):
            self.assertEqual(goblin_pack_size(d), 1)
        for d in range(6, 11):
            self.assertEqual(goblin_pack_size(d), 2)
        for d in range(11, 200):
            self.assertEqual(goblin_pack_size(d), 3)

    def test_every_non_start_room_has_exactly_one_kind(self):
        for depth in (1, 3, 6, 8, 9, 12, 16, 30):
            for rooms, monsters, boss_room in seeded_floors(depth, n=100):
                for room in rooms[1:]:
                    here = [m for m in monsters if in_room(room, m)]
                    self.assertTrue(here, f'empty room at depth {depth}')
                    kinds = {(m.kind, m.is_boss) for m in here if not m.is_boss}
                    if room is boss_room:
                        self.assertTrue(any(m.is_boss for m in here))
                        self.assertLessEqual(len(kinds), 1)
                    else:
                        self.assertEqual(len(kinds), 1)

    def test_start_room_is_empty(self):
        for depth in (1, 8, 9, 16):
            for rooms, monsters, _ in seeded_floors(depth, n=100):
                self.assertFalse([m for m in monsters if in_room(rooms[0], m)])

    def test_goblin_packs_follow_the_depth_size(self):
        for depth in (1, 5, 6, 10, 11, 15, 20):
            for _rooms, monsters, _boss_room in seeded_floors(depth, n=100):
                for room in _rooms[1:]:
                    gob = [m for m in monsters if in_room(room, m) and m.kind == 'goblin']
                    if gob:
                        self.assertEqual(len(gob), goblin_pack_size(depth))
                        self.assertLessEqual(len(gob), 3)

    def test_orcs_are_single_before_and_on_the_first_boss_floor(self):
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

    def test_orc_pairs_after_first_boss_never_touch(self):
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
        counts = {'goblin': 0, 'orc': 0}
        for rooms, monsters, _ in seeded_floors(3, n=300):
            for room in rooms[1:]:
                counts[[m for m in monsters if in_room(room, m)][0].kind] += 1
        total = sum(counts.values())
        self.assertLess(abs(counts['goblin'] / total - 0.5), 0.06)

    def test_first_boss_floor_has_boss_at_centre_with_one_adjacent_escort(self):
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

    def test_later_boss_floors_have_no_escort(self):
        self.assertNotIn(16, BOSS_ESCORTS)
        for depth in (16, 24):
            for _rooms, monsters, boss_room in seeded_floors(depth, n=100):
                here = [m for m in monsters if in_room(boss_room, m)]
                self.assertEqual(len(here), 1)
                self.assertTrue(here[0].is_boss)
                self.assertEqual((here[0].x, here[0].y), boss_room.center())

    def test_no_boss_off_boss_floors(self):
        for depth in (1, 7, 9, 15):
            for _, monsters, boss_room in seeded_floors(depth, n=30):
                self.assertIsNone(boss_room)
                self.assertFalse(any(m.is_boss for m in monsters))

    def test_boss_arena_attribute(self):
        random.seed(3)
        state = GameState(40, 20)
        self.assertIsNone(state.boss_arena)
        while state.depth < 16:
            state.next_level()
            if is_boss_level(state.depth):
                self.assertIn(state.boss_arena, state.rooms[1:])
                boss = next(m for m in state.entities if getattr(m, 'is_boss', False))
                self.assertEqual((boss.x, boss.y), state.boss_arena.center())
                cx, cy = state.boss_arena.center()
                # The 3x3 centre area is inside the room.
                for x in (cx - 1, cx + 1):
                    self.assertTrue(state.boss_arena.x1 <= x < state.boss_arena.x2)
                for y in (cy - 1, cy + 1):
                    self.assertTrue(state.boss_arena.y1 <= y < state.boss_arena.y2)
            else:
                self.assertIsNone(state.boss_arena)

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

    def test_spread_tiles_fit_in_the_smallest_room(self):
        for seed in range(200):
            tiles = pick_tiles(Rect(1, 1, 4, 4), 3, random.Random(seed), spread=True)
            self.assertEqual(len(tiles), 3)


def open_floor_state(seed, fov_radius=6):
    """A GameState whose whole interior is floor, emptied of entities, with
    the player at (10, 10). Lets a test place monsters without the random
    dungeon getting in the way."""
    random.seed(seed)
    state = GameState(50, 20, fov_radius=fov_radius)
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

    def test_blocked_chaser_does_not_step_onto_the_monster_ahead(self):
        """In a one-tile corridor there is no other axis: the rear monster
        just waits its turn rather than overlapping or swapping."""
        game_map = [list(r) for r in self.CORRIDOR]
        player = Entity(1, 1, '@')
        front, rear = Monster(5, 1, 'goblin'), Monster(6, 1, 'goblin')
        occupied = {(player.x, player.y), (front.x, front.y)}
        self.assertIsNone(rear.take_turn(player, game_map, occupied=occupied))
        self.assertEqual((rear.x, rear.y), (6, 1))
        self.assertEqual((front.x, front.y), (5, 1))

    def test_blocked_chaser_tries_its_other_axis(self):
        game_map = [list(r) for r in MonsterTests.ROOM]
        player = Entity(1, 1, '@')
        ahead = Monster(3, 3, 'goblin')
        m = Monster(4, 3, 'goblin')  # larger gap is x, but (3, 3) is taken
        m.take_turn(player, game_map, occupied={(1, 1), (ahead.x, ahead.y)})
        self.assertEqual((m.x, m.y), (4, 2))

    def test_boxed_in_wanderer_stays_put(self):
        game_map = [list(r) for r in MonsterTests.ROOM]
        player = Entity(5, 5, '@')
        m = Monster(2, 2, 'goblin')
        occupied = {(2 + dx, 2 + dy) for dx, dy in ORTHOGONAL_STEPS} | {(5, 5)}
        random.seed(62)
        for _ in range(30):
            self.assertIsNone(m.take_turn(player, game_map, occupied=occupied, sees_player=False))
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
        # The naive chase has no second axis when lined up with the player,
        # so the one behind queues up against a rather than overlapping it.
        self.assertEqual((behind.x, behind.y), (a.x + 1, a.y))

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

    def test_give_up_after_is_three(self):
        self.assertEqual(GIVE_UP_AFTER, 3)

    def test_stops_after_exactly_three_blind_turns_and_not_before(self):
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
        gives up on exactly the third round."""
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

    def test_game_state_monster_in_view_keeps_chasing(self):
        state = open_floor_state(67)
        m = Monster(state.player.x + 5, state.player.y, 'goblin')
        state.entities.append(m)
        self.assertTrue(state.is_visible(m.x, m.y))
        state.end_turn()
        self.assertTrue(m.chasing)
        self.assertEqual(m.lost_sight, 0)
        self.assertEqual(m.x, state.player.x + 4)


class GameStateIntegrationTests(unittest.TestCase):
    def test_initial_state(self):
        random.seed(7)
        state = GameState(50, 20)
        self.assertTrue(state.running)
        self.assertFalse(state.game_over)
        self.assertEqual(state.depth, 1)
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertIn(state.player, state.entities)

    def test_player_combat_kills_monster(self):
        random.seed(8)
        state = GameState(50, 20)
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
        random.seed(9)
        state = GameState(50, 20)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        state.entities = [state.player, m]
        state.player.hp = 1
        state.end_turn()
        self.assertTrue(state.game_over)
        self.assertEqual(state.messages[-1], 'You died.')

    def test_potion_chest_pickup_rolls_a_potion_and_fills_inventory(self):
        random.seed(10)
        state = GameState(50, 20)
        chest = Chest(state.player.x + 1, state.player.y, kind='potion')
        state.entities = [state.player, chest]
        state.player.hp -= 1  # hurt: drunk at once, not belted
        state.try_move_player(1, 0)
        self.assertEqual(len(state.player.inventory), 1)
        self.assertNotIn(chest, state.entities)
        self.assertIn('You open the chest.', state.messages)
        self.assertFalse(state.is_choosing)

    def test_walking_onto_a_gear_chest_offers_a_choice(self):
        random.seed(15)
        state = GameState(50, 20)
        chest = Chest(state.player.x + 1, state.player.y, kind='gear')
        state.entities = [state.player, chest]
        state.try_move_player(1, 0)
        self.assertNotIn(chest, state.entities)
        self.assertTrue(state.is_choosing)
        self.assertEqual(len(cast(list[Item], state.pending_choice)), GEAR_CHEST_DROPS)
        self.assertEqual(state.player.inventory, [])  # nothing auto-equipped

    def test_descend_regenerates_level_and_moves_player(self):
        random.seed(11)
        state = GameState(50, 20)
        sx, sy = place_stairs(state.game_map, state.rooms)
        state.player.x, state.player.y = sx, sy
        old_rooms = state.rooms
        handled = state.handle_action('descend')
        self.assertTrue(handled)
        self.assertEqual(state.depth, 2)
        self.assertIsNot(state.rooms, old_rooms)
        self.assertEqual((state.player.x, state.player.y), state.rooms[0].center())

    def test_descend_without_stairs_does_nothing(self):
        random.seed(12)
        state = GameState(50, 20)
        state.game_map[state.player.y][state.player.x] = FLOOR
        handled = state.handle_action('descend')
        self.assertFalse(handled)
        self.assertEqual(state.depth, 1)

    def test_ability_key_parries_in_play_and_quits_on_game_over(self):
        random.seed(13)
        state = GameState(50, 20)
        turn = state.turn
        self.assertTrue(state.handle_action('ability'))  # a warrior's Q: parry
        self.assertTrue(state.parry_armed)
        self.assertEqual(state.turn, turn + 1)
        self.assertTrue(state.running)
        state.game_over = True
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.running)

    def test_game_over_blocks_movement_but_not_quit(self):
        random.seed(13)
        state = GameState(50, 20)
        state.game_over = True
        px, py = state.player.x, state.player.y
        state.handle_action('move_n')
        self.assertEqual((state.player.x, state.player.y), (px, py))
        state.handle_action('quit')
        self.assertFalse(state.running)

    def test_restart_does_nothing_during_play(self):
        random.seed(13)
        state = GameState(50, 20)
        pos, turn, log = (state.player.x, state.player.y), state.turn, list(state.messages)
        self.assertFalse(state.handle_action('restart'))
        self.assertTrue(state.running)
        self.assertFalse(state.restart_requested)
        self.assertEqual(state.turn, turn)
        self.assertEqual((state.player.x, state.player.y), pos)
        self.assertEqual(state.messages, log)
        self.assertFalse(state.monster_phase_pending())

    def test_restart_on_game_over_ends_the_run_and_asks_for_a_restart(self):
        random.seed(13)
        state = GameState(50, 20)
        state.game_over = True
        self.assertFalse(state.handle_action('restart'))
        self.assertFalse(state.running)
        self.assertTrue(state.restart_requested)

    def test_quit_on_game_over_is_not_a_restart(self):
        random.seed(13)
        state = GameState(50, 20)
        state.game_over = True
        state.handle_action('ability')  # 'press q to quit'
        self.assertFalse(state.running)
        self.assertFalse(state.restart_requested)


class TurnPhaseTests(unittest.TestCase):
    """The round is two halves: the player's, then the monsters' one at a
    time. Before this split every monster acted against the pre-round world,
    so a dead player still took hits from everyone else in the list."""

    def swarmed_state(self, player_hp, monster_power=2, offsets=((1, 0), (-1, 0), (0, 1))):
        random.seed(30)
        state = GameState(50, 20)
        state.player.hp = player_hp
        state.entities = [state.player]
        for dx, dy in offsets:
            m = Monster(state.player.x + dx, state.player.y + dy, 'goblin')
            m.power = monster_power
            state.entities.append(m)
        return state

    def test_death_stops_the_rest_of_the_round(self):
        state = self.swarmed_state(player_hp=3)  # dies to the 2nd of 3 goblins
        state.end_turn()
        self.assertTrue(state.game_over)
        hits = [m for m in state.messages if 'hits you' in m]
        self.assertEqual(len(hits), 2, 'the third goblin swung at a corpse')
        self.assertEqual(state.player.hp, -1)

    def test_death_is_logged_exactly_once(self):
        state = self.swarmed_state(player_hp=1)
        state.end_turn()
        self.assertEqual([m for m in state.messages if m == 'You died.'], ['You died.'])
        self.assertEqual(state.messages[-1], 'You died.')

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

    def test_monster_killed_in_the_player_half_never_acts(self):
        random.seed(31)
        state = GameState(50, 20)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        m.hp = 1
        state.entities = [state.player, m]
        state.handle_action('move_e')  # bump-attack kills it
        self.assertFalse(m.alive)
        state.end_turn()
        self.assertNotIn('hits you', ' '.join(state.messages))

    def test_dead_monster_leaves_the_screen_before_the_monster_half(self):
        """The renderer now draws mid-round, so a corpse must stop being
        drawn the moment it dies rather than at the end of the round."""
        random.seed(32)
        state = GameState(50, 20)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')
        m.hp = 1
        state.entities = [state.player, m]
        state.handle_action('move_e')
        self.assertNotIn(m, state.visible_entities())

    def test_step_reports_attacks_as_visible(self):
        state = self.swarmed_state(player_hp=50, offsets=((1, 0),))
        state.end_player_phase()
        self.assertTrue(state.step_monster_phase())  # the attack
        self.assertFalse(state.step_monster_phase())  # queue drained

    def test_unseen_monsters_resolve_without_reporting_a_frame(self):
        """A monster shuffling around in the dark must not cost the player a
        held frame, or walking an empty dungeon would crawl."""
        random.seed(33)
        state = GameState(50, 20)
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

    def test_descending_cancels_a_queued_monster_phase(self):
        random.seed(34)
        state = GameState(50, 20)
        state.end_player_phase()
        sx, sy = place_stairs(state.game_map, state.rooms)
        state.player.x, state.player.y = sx, sy
        state.handle_action('descend')
        self.assertFalse(state.monster_phase_pending())


class ClassAndArcherTests(unittest.TestCase):
    def test_default_class_is_warrior(self):
        random.seed(20)
        state = GameState(50, 20)
        self.assertEqual(state.player.char_class, 'warrior')

    def test_unknown_class_falls_back_to_warrior(self):
        random.seed(21)
        state = GameState(50, 20, char_class='paladin')
        self.assertEqual(state.player.char_class, 'warrior')

    def test_archer_has_different_stats_than_warrior(self):
        random.seed(22)
        warrior = GameState(50, 20, char_class='warrior')
        archer = GameState(50, 20, char_class='archer')
        self.assertNotEqual(warrior.player.max_hp, archer.player.max_hp)
        self.assertNotEqual(warrior.player.power, archer.player.power)

    def test_warriors_shoot_action_just_moves(self):
        random.seed(23)
        state = GameState(50, 20, char_class='warrior')
        state.entities = [state.player]
        px, py = state.player.x, state.player.y
        state.handle_action('shoot_e')
        self.assertEqual((state.player.x, state.player.y), (px + 1, py))

    def test_archer_arrow_kills_monster_in_line(self):
        random.seed(24)
        state = GameState(50, 20, char_class='archer')
        m = Monster(state.player.x + 3, state.player.y, 'goblin')
        m.hp = 1
        state.entities = [state.player, m]
        px, py = state.player.x, state.player.y
        state.shoot_arrow(1, 0)
        self.assertFalse(m.alive)
        self.assertEqual((state.player.x, state.player.y), (px, py))  # arrow, not player, moved

    def test_archer_arrow_passes_over_empty_tiles_and_hits_wall(self):
        random.seed(25)
        state = GameState(50, 20, char_class='archer')
        state.entities = [state.player]
        state.shoot_arrow(1, 0)  # should not raise even with nothing in the way
        self.assertIn('wall', state.messages[-1])

    def test_archer_shoot_action_does_not_move_player(self):
        random.seed(26)
        state = GameState(50, 20, char_class='archer')
        state.entities = [state.player]
        px, py = state.player.x, state.player.y
        state.handle_action('shoot_n')
        self.assertEqual((state.player.x, state.player.y), (px, py))


class ArcherHopTests(unittest.TestCase):
    def _arena(self, monster_dx=-2, monster_dy=0):
        state = GameState(20, 20, char_class='archer')
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

    def test_hop_moves_two_tiles_away(self):
        state, _ = self._arena()
        self.assertTrue(state.handle_action('ability'))
        self.assertEqual((state.player.x, state.player.y), (12, 10))

    def test_hop_takes_a_turn_and_monsters_act(self):
        state, mon = self._arena()
        turn = state.turn
        state.handle_action('ability')
        self.assertEqual(state.turn, turn + 1)
        while state.step_monster_phase():
            pass
        self.assertNotEqual((mon.x, mon.y), (8, 10))  # it acted after the hop

    def test_hop_vertical_on_tie(self):
        state, _ = self._arena(-2, -2)
        state.handle_action('ability')
        self.assertEqual((state.player.x, state.player.y), (10, 12))

    def test_hop_stops_at_wall(self):
        state, _ = self._arena()
        state.game_map[10][12] = WALL
        state.handle_action('ability')
        self.assertEqual((state.player.x, state.player.y), (11, 10))

    def test_no_monster_in_range_refuses(self):
        state, _ = self._arena(-5, 0)
        turn = state.turn
        self.assertFalse(state.handle_action('ability'))
        self.assertEqual(state.turn, turn)
        self.assertEqual(state.messages[-1], 'Nothing to hop from.')

    def test_cooldown_four_turns(self):
        state, mon = self._arena()
        state.handle_action('ability')
        state.cancel_monster_phase()
        mon.x, mon.y = state.player.x - 2, state.player.y
        for left in (4, 3, 2, 1):
            self.assertFalse(state.handle_action('ability'))
            self.assertEqual(state.messages[-1], f'Hop recovering ({left} turns).')
            state.handle_action('wait')
            state.cancel_monster_phase()
            mon.x, mon.y = state.player.x - 2, state.player.y
        px = state.player.x
        self.assertTrue(state.handle_action('ability'))
        self.assertEqual(state.player.x, px + 2)

    def test_warrior_q_parries_instead_of_hopping(self):
        state, _ = self._arena()
        state.player.char_class = 'warrior'
        turn = state.turn
        self.assertTrue(state.handle_action('ability'))
        self.assertEqual((state.turn, state.player.x), (turn + 1, 10))
        self.assertTrue(state.parry_armed)
        self.assertFalse(state.hop_crit)

    def test_successful_hop_arms_a_crit_for_the_next_shot_only(self):
        state, mon = self._arena()
        mon.hp = mon.max_hp = 1000
        mon.defense = 0
        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.0):
            self.assertTrue(state.handle_action('ability'))
            self.assertTrue(state.hop_crit)
            state.cancel_monster_phase()
            power = state.player.power
            self.assertTrue(state.handle_action('shoot_w'))
            (hit,) = state.combat_events
            self.assertTrue(hit.crit)
            self.assertEqual(hit.damage, round_damage(mitigate(power * CRIT_MULTIPLIER, 0)))
            self.assertIn('Critical hit!', state.messages)
            self.assertFalse(state.hop_crit)
            state.cancel_monster_phase()
            state.handle_action('shoot_w')  # the one after: no crit
            (hit,) = state.combat_events
            self.assertFalse(hit.crit)

    def test_hop_crit_is_spent_by_a_missed_shot(self):
        state, mon = self._arena()
        mon.hp = mon.max_hp = 1000
        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.0):
            state.handle_action('ability')
            state.cancel_monster_phase()
            state.handle_action('shoot_n')  # into the wall: nothing hit
            self.assertEqual(state.combat_events, [])
            self.assertFalse(state.hop_crit)
            state.cancel_monster_phase()
            state.handle_action('shoot_w')
            (hit,) = state.combat_events
            self.assertFalse(hit.crit)

    def test_refused_hop_does_not_arm_the_crit(self):
        state, _ = self._arena(-5, 0)  # nothing to hop from
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.hop_crit)
        state, _ = self._arena()
        state.game_map[10][11] = WALL  # nowhere to hop
        self.assertFalse(state.handle_action('ability'))
        self.assertFalse(state.hop_crit)
        state, mon = self._arena()
        state.handle_action('ability')
        state.cancel_monster_phase()
        state.handle_action('shoot_w')  # spends it
        state.cancel_monster_phase()
        mon.x, mon.y = state.player.x - 2, state.player.y
        self.assertFalse(state.handle_action('ability'))  # on cooldown
        self.assertFalse(state.hop_crit)

    def test_nowhere_to_hop_refuses(self):
        state, _ = self._arena()
        state.game_map[10][11] = WALL
        turn = state.turn
        self.assertFalse(state.handle_action('ability'))
        self.assertEqual(state.turn, turn)
        self.assertEqual(state.messages[-1], 'Nowhere to hop.')
        self.assertEqual(state.player.x, 10)

    def test_pending_choice_blocks_hop(self):
        state, _ = self._arena()
        state.pending_choice = [Item(0, 0, 'weapon', 'common')]
        self.assertFalse(state.handle_action('ability'))
        self.assertEqual(state.player.x, 10)


class WarriorParryTests(unittest.TestCase):
    """A warrior at (10, 10) in an open arena, with an adjacent goblin to the
    west unless a test says otherwise."""

    def _arena(self, monster=True):
        state = GameState(20, 20, char_class='warrior')
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

    def test_q_arms_a_parry_and_takes_a_turn(self):
        state, _ = self._arena(monster=False)
        self.assertTrue(state.handle_action('ability'))
        self.assertTrue(state.parry_armed)
        self.assertEqual(state.turn, 1)
        self.assertEqual(state.messages[-1], 'You ready a parry.')

    def test_second_q_while_armed_is_refused_and_takes_no_turn(self):
        state, _ = self._arena(monster=False)
        state.handle_action('ability')
        turn = state.turn
        self.assertFalse(state.handle_action('ability'))
        self.assertEqual(state.turn, turn)
        self.assertEqual(state.messages[-1], 'Your parry is already ready.')
        self.assertFalse(state.monster_phase_pending())

    def test_next_monster_hit_is_nullified_and_returns_crit_damage(self):
        state, mon = self._arena()
        assert mon is not None
        p = state.player
        state.handle_action('ability')
        self.run_monsters(state)
        self.assertFalse(state.parry_armed)
        # The goblin's blow is nullified: no damage, no Hit for it ...
        self.assertEqual(p.hp, 1000)
        (riposte,) = state.combat_events
        # ... and the goblin takes raw power x CRIT_MULTIPLIER, less its defence.
        self.assertIs(riposte.attacker, p)
        self.assertIs(riposte.defender, mon)
        self.assertFalse(riposte.crit)
        expected = round_damage(mitigate(p.power * CRIT_MULTIPLIER, 2))
        self.assertEqual(riposte.damage, expected)
        self.assertEqual(mon.hp, 1000 - expected)
        parried = state.messages.index("You parry the goblin's attack!")
        returned = state.messages.index('Your parry returns the blow to the goblin!')
        self.assertEqual(returned, parried + 1)
        self.assertEqual(state.messages[returned + 1], f'You hit goblin for {expected}.')
        self.assertNotIn('Goblin hits you', ' '.join(state.messages))
        # Spent: the next hit lands in full and is not answered.
        state.handle_action('wait')
        self.run_monsters(state)
        self.assertEqual([h.defender for h in state.combat_events], [p])
        self.assertEqual(p.hp, 1000 - round_damage(mitigate(5, 0)))

    def test_a_parry_absorbs_a_blow_that_would_kill(self):
        state, mon = self._arena()
        assert mon is not None
        state.player.hp = 1
        state.handle_action('ability')
        self.run_monsters(state)
        self.assertEqual(state.player.hp, 1)
        self.assertFalse(state.game_over)
        self.assertEqual([h.defender for h in state.combat_events], [mon])

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
        self.assertEqual(
            [(h.attacker, h.defender) for h in state.combat_events], [(p, mon), (other, p)]
        )
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

    def test_parry_is_not_triggered_by_the_warriors_own_attack(self):
        state, mon = self._arena()
        assert mon is not None
        state.handle_action('ability')
        state.cancel_monster_phase()
        state.handle_action('move_w')  # bump the goblin
        state.cancel_monster_phase()
        self.assertEqual([h.defender for h in state.combat_events], [mon])
        self.assertTrue(state.parry_armed)

    def test_a_dodged_hit_does_not_trigger_it(self):
        state, mon = self._arena()
        assert mon is not None
        state.player.armor = Item(0, 0, 'leather', 'epic')
        state.handle_action('ability')
        with mock.patch('game.state.random.random', return_value=0.0):
            self.run_monsters(state)
        self.assertEqual(state.combat_events, [])
        self.assertEqual(mon.hp, 1000)
        self.assertTrue(state.parry_armed)

    def test_an_untriggered_parry_stays_armed(self):
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
        random.seed(41)
        state = GameState(50, 20)
        state.player.hp = 1
        common = Item(0, 0, 'potion', 'common')
        common.apply(state.player, state.log)
        common_hp = state.player.hp

        state.player.hp = 1
        epic = Item(0, 0, 'potion', 'epic')
        epic.apply(state.player, state.log)

        self.assertGreater(state.player.hp, common_hp)

    def test_equip_weapon_updates_power(self):
        random.seed(42)
        state = GameState(50, 20, char_class='warrior')
        base_power = state.player.base_power
        weapon = Item(0, 0, 'weapon', 'rare')
        weapon.apply(state.player, state.log)
        self.assertIs(state.player.weapon, weapon)
        self.assertEqual(state.player.power, base_power + cast(int, weapon.bonus))

    def test_swapping_weapon_does_not_stack_bonus(self):
        random.seed(43)
        state = GameState(50, 20)
        base_power = state.player.base_power
        w1 = Item(state.player.x, state.player.y, 'weapon', 'common')
        w1.apply(state.player, state.log)
        w2 = Item(state.player.x, state.player.y, 'weapon', 'epic')
        w2.apply(state.player, state.log)
        self.assertEqual(state.player.power, base_power + cast(int, w2.bonus))
        self.assertIs(state.player.weapon, w2)
        self.assertIn('swap', state.messages[-1])

    def test_worse_weapon_still_replaces_the_old_one(self):
        # Gear is chosen now (GameState.choose), so applying it always
        # equips -- the old "leave it if yours is better" rule is gone.
        random.seed(53)
        state = GameState(50, 20)
        base_power = state.player.base_power
        epic = Item(state.player.x, state.player.y, 'weapon', 'epic')
        epic.apply(state.player, state.log)
        common = Item(state.player.x, state.player.y, 'weapon', 'common')
        common.apply(state.player, state.log)
        self.assertIs(state.player.weapon, common)
        self.assertEqual(state.player.power, base_power + cast(int, common.bonus))
        self.assertIn('swap', state.messages[-1])

    def test_worse_armor_still_replaces_the_old_one(self):
        random.seed(54)
        state = GameState(50, 20)
        Item(state.player.x, state.player.y, 'armor', 'rare').apply(state.player, state.log)
        for rarity in ('common', 'uncommon', 'rare'):
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

    def test_equipping_armor_sets_defense_from_the_table(self):
        random.seed(56)
        state = GameState(50, 20)
        Item(0, 0, 'armor', 'epic').apply(state.player, state.log)
        self.assertEqual(state.player.defense, 21)

    def test_junk_item_has_no_stats(self):
        junk = Item(0, 0, JUNK)
        self.assertEqual(junk.name, JUNK_NAME)
        self.assertEqual(junk.name, 'Rusty scrap')
        self.assertIsNone(junk.rarity)
        self.assertIsNone(junk.bonus)
        self.assertFalse(junk.is_gear)

    def test_armor_reduces_incoming_damage_with_floor_of_one(self):
        random.seed(44)
        state = GameState(50, 20)
        armor = Item(state.player.x, state.player.y, 'armor', 'epic')  # 21 defense
        armor.apply(state.player, state.log)
        m = Monster(state.player.x + 1, state.player.y, 'goblin')  # power 2, less than defense
        state.entities = [state.player, m]
        hp_before = state.player.hp
        state.attack(m, state.player)
        self.assertEqual(state.player.hp, hp_before - 1)  # damage floors at 1


class DifficultyScalingTests(unittest.TestCase):
    def test_tier_for_depth_buckets_every_three_floors(self):
        self.assertEqual(tier_for_depth(1), 0)
        self.assertEqual(tier_for_depth(3), 0)
        self.assertEqual(tier_for_depth(4), 1)
        self.assertEqual(tier_for_depth(6), 1)
        self.assertEqual(tier_for_depth(7), 2)

    def test_scale_stats_compounds_hp_and_adds_flat_power(self):
        hp0, power0 = scale_stats(10, 5, depth=1)
        hp1, power1 = scale_stats(10, 5, depth=4)
        hp2, power2 = scale_stats(10, 5, depth=7)
        self.assertEqual((hp0, power0), (10, 5))
        self.assertEqual(power1, 6)
        self.assertEqual(power2, 7)
        self.assertGreater(hp1, hp0)
        self.assertGreater(hp2, hp1)

    def test_spawned_monster_stats_match_scale_stats(self):
        base_hp, base_power = MONSTER_TYPES['goblin'][2], MONSTER_TYPES['goblin'][3]
        expected_hp, expected_power = scale_stats(base_hp, base_power, depth=10)
        m = Monster(0, 0, 'goblin', depth=10)
        self.assertEqual((m.hp, m.power), (expected_hp, expected_power))

    def test_early_orcs_have_20_percent_less_hp(self):
        base, power = MONSTER_TYPES['orc'][2], MONSTER_TYPES['orc'][3]
        for depth in (1, 8):
            full, _ = scale_stats(base, power, depth)
            self.assertEqual(Monster(0, 0, 'orc', depth=depth).hp, round(full * 0.8))
        self.assertEqual(Monster(0, 0, 'orc', depth=1).hp, 22)
        self.assertEqual(Monster(0, 0, 'orc', depth=8).hp, 31)

    def test_orc_hp_is_normal_from_floor_nine(self):
        full, _ = scale_stats(MONSTER_TYPES['orc'][2], MONSTER_TYPES['orc'][3], 9)
        self.assertEqual(Monster(0, 0, 'orc', depth=9).hp, full)
        self.assertEqual(full, 39)

    def test_goblin_hp_unchanged_by_orc_reduction(self):
        base, power = MONSTER_TYPES['goblin'][2], MONSTER_TYPES['goblin'][3]
        for depth in (1, 9):
            full, _ = scale_stats(base, power, depth)
            self.assertEqual(Monster(0, 0, 'goblin', depth=depth).hp, full)

    def test_boss_hp_on_floor_eight_ignores_orc_reduction(self):
        self.assertEqual(spawn_boss(Rect(1, 1, 10, 10), 8).hp, 78)

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

    def test_boss_spawns_on_boss_level_only(self):
        random.seed(45)
        state = GameState(50, 20)
        state.depth = 8
        monsters = state._spawn_level_monsters()
        self.assertTrue(any(getattr(m, 'is_boss', False) for m in monsters))

        random.seed(46)
        state2 = GameState(50, 20)
        state2.depth = 7
        monsters2 = state2._spawn_level_monsters()
        self.assertFalse(any(getattr(m, 'is_boss', False) for m in monsters2))

    def test_boss_death_drops_a_guaranteed_rare_or_epic_chest(self):
        random.seed(47)
        state = GameState(50, 20)
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

    def test_regular_chest_open_returns_valid_kinds_and_rarities(self):
        rng = random.Random(51)
        for kind in ('potion', 'gear'):
            chest = Chest(0, 0, kind=kind)
            for depth in (1, 5, 10, 25):
                for item in chest.open(depth, rng=rng):
                    self.assertIn(item.kind, ['potion', JUNK] + GEAR_KINDS)
                    if item.kind != JUNK:
                        self.assertIn(item.rarity, RARITIES)

    def test_chest_kind_is_fixed_at_spawn_and_sets_its_color(self):
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

    def test_gear_chest_opens_to_three_choices(self):
        rng = random.Random(57)
        chest = Chest(0, 0, kind='gear')
        for depth in (1, 8, 30):
            self.assertEqual(len(chest.open(depth, rng=rng)), 3)
        self.assertEqual(GEAR_CHEST_DROPS, 3)

    def test_boss_chest_ignores_depth_scaling(self):
        chest = Chest(0, 0, guaranteed_min_rarity='rare')
        rng = random.Random(52)
        for _ in range(30):
            for item in chest.open(depth=1, rng=rng):
                self.assertIn(item.rarity, ('rare', 'epic'))

    def test_boss_chest_offers_three_rare_or_epic_gear_and_no_junk(self):
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
        # default maps) -- real generation is ~8 ms a map, too slow for 5000.
        rng = random.Random(60)
        floors = 5000
        gear = potion = 0
        for _ in range(floors):
            rooms = [Rect(1 + 7 * i, 1, 6, 6) for i in range(rng.randint(4, 6))]
            for chest in spawn_chests(rooms, rng=rng):
                if chest.kind == 'gear':
                    gear += 1
                else:
                    potion += 1
        self.assertAlmostEqual(gear / floors, 0.4, delta=0.05)
        # Potion chests keep the old rate: 0.25 per room past the first.
        self.assertAlmostEqual(potion / floors, 1.0, delta=0.1)

    def test_spawn_chests_on_real_floors_has_at_most_one_gear_chest(self):
        random.seed(61)
        for _ in range(100):
            _, rooms = generate_dungeon(40, 20)
            gear = [c for c in spawn_chests(rooms) if c.kind == 'gear']
            self.assertLessEqual(len(gear), 1)

    def test_depth_one_always_has_a_gear_chest_outside_the_start_room(self):
        random.seed(62)
        for _ in range(100):
            _, rooms = generate_dungeon(40, 20)
            chests = spawn_chests(rooms, depth=1)
            gear = [c for c in chests if c.kind == 'gear']
            self.assertEqual(len(gear), 1)
            start = rooms[0]
            in_start = start.x1 <= gear[0].x < start.x2 and start.y1 <= gear[0].y < start.y2
            self.assertFalse(in_start)
            self.assertNotEqual((gear[0].x, gear[0].y), rooms[-1].center())
            self.assertEqual(len({(c.x, c.y) for c in chests}), len(chests))

    def test_deeper_floors_do_not_force_a_gear_chest(self):
        rng = random.Random(63)
        rooms = [Rect(1 + 7 * i, 1, 6, 6) for i in range(5)]
        counts = [
            sum(c.kind == 'gear' for c in spawn_chests(rooms, rng=rng, depth=2))
            for _ in range(300)
        ]
        self.assertIn(0, counts)

    def test_game_state_depth_one_has_a_gear_chest(self):
        for seed in range(20):
            random.seed(seed)
            state = GameState(40, 20)
            self.assertTrue(any(isinstance(e, Chest) and e.kind == 'gear' for e in state.entities))

    def test_rarity_weights_shift_toward_better_loot_with_depth(self):
        shallow = rarity_weights_for_depth(1)
        deep = rarity_weights_for_depth(MAX_SCALING_DEPTH)
        beyond = rarity_weights_for_depth(MAX_SCALING_DEPTH + 50)
        common_idx, epic_idx = 0, 3
        self.assertGreater(shallow[common_idx], deep[common_idx])
        self.assertLess(shallow[epic_idx], deep[epic_idx])
        # Scaling holds steady past MAX_SCALING_DEPTH rather than running away.
        self.assertEqual(deep, beyond)

    def test_roll_rarity_uses_depth_scaled_weights(self):
        # Statistical, not exact: a large sample at max depth should skew
        # toward rare/epic far more than the same sample at depth 1.
        shallow_epics = sum(1 for _ in range(500) if roll_rarity(1, random.Random()) == 'epic')
        deep_epics = sum(
            1 for _ in range(500) if roll_rarity(MAX_SCALING_DEPTH, random.Random()) == 'epic'
        )
        self.assertGreater(deep_epics, shallow_epics)

    def test_open_potion_chest_removes_it_and_applies_the_potion(self):
        random.seed(53)
        state = GameState(50, 20)
        chest = Chest(state.player.x, state.player.y, kind='potion')
        state.entities = [state.player, chest]
        state.player.hp -= 1  # hurt: drunk at once, not belted
        before = len(state.player.inventory)
        state.open_chest(chest)
        self.assertNotIn(chest, state.entities)
        self.assertEqual(len(state.player.inventory), before + 1)
        self.assertIsNone(state.pending_choice)


class PotionBeltTests(unittest.TestCase):
    """Potions found at full HP go on a 3-slot belt; 'drink' drinks slot 1."""

    def setUp(self):
        random.seed(70)
        self.state = GameState(50, 20)
        self.state.entities = [self.state.player]
        self.start = (self.state.player.x, self.state.player.y)

    def chest_east(self):
        state = self.state
        chest = Chest(state.player.x + 1, state.player.y, kind='potion')
        state.entities.append(chest)
        return chest

    def test_belt_starts_empty(self):
        self.assertEqual(self.state.belt, [])
        self.assertEqual(GameState(50, 20, char_class='archer').belt, [])

    def test_hurt_pickup_drinks_at_once(self):
        state = self.state
        state.player.hp = 1
        chest = self.chest_east()
        self.assertTrue(state.handle_action('move_e'))
        self.assertGreater(state.player.hp, 1)
        self.assertEqual(state.belt, [])
        self.assertNotIn(chest, state.entities)

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

    def test_open_chest_at_full_hp_belts_the_potion(self):
        state = self.state
        chest = Chest(state.player.x, state.player.y, kind='potion')
        state.entities.append(chest)
        self.assertTrue(state.open_chest(chest))
        self.assertEqual(len(state.belt), 1)
        self.assertNotIn(chest, state.entities)
        self.assertEqual(state.player.inventory, [])  # stored, not drunk

    def full_belt(self):
        self.state.belt[:] = [Item(0, 0, 'potion', r) for r in ('common', 'rare', 'uncommon')]

    def test_full_belt_at_full_hp_refuses_the_move(self):
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

    def test_full_belt_refuses_open_chest_too(self):
        state = self.state
        self.full_belt()
        chest = Chest(state.player.x, state.player.y, kind='potion')
        state.entities.append(chest)
        self.assertFalse(state.open_chest(chest))
        self.assertIn(chest, state.entities)

    def test_full_belt_while_hurt_still_drinks(self):
        state = self.state
        self.full_belt()
        state.player.hp = 1
        chest = self.chest_east()
        self.assertTrue(state.handle_action('move_e'))
        self.assertNotIn(chest, state.entities)
        self.assertGreater(state.player.hp, 1)
        self.assertEqual(len(state.belt), 3)

    def test_full_belt_does_not_block_gear_chests(self):
        state = self.state
        self.full_belt()
        state.entities.append(Chest(state.player.x + 1, state.player.y, kind='gear'))
        self.assertTrue(state.handle_action('move_e'))
        self.assertTrue(state.is_choosing)

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

    def test_drink_takes_the_first_slot_and_shifts_the_rest(self):
        state = self.state
        self.full_belt()
        second, third = state.belt[1], state.belt[2]
        state.player.hp = 1
        self.assertTrue(state.handle_action('drink'))
        self.assertEqual(state.player.hp, 1 + POTION_HEAL['common'])
        self.assertEqual(state.belt, [second, third])
        self.assertEqual(state.player.inventory, ['potion of healing'])

    def test_drink_is_capped_at_max_hp(self):
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

    def test_drink_with_an_empty_belt_takes_no_turn(self):
        state = self.state
        state.entities.append(Monster(state.player.x, state.player.y + 1, 'goblin'))
        turn = state.turn
        self.assertFalse(state.handle_action('drink'))
        self.assertEqual(state.turn, turn)
        self.assertFalse(state.monster_phase_pending())
        self.assertEqual(state.messages[-1], 'No potions')

    def test_drink_is_ignored_while_choosing(self):
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
        random.seed(seed)
        state = GameState(50, 20)
        state.entities = [state.player]
        state.pending_choice = items
        return state

    def test_open_gear_chest_sets_pending_choice_and_equips_nothing(self):
        random.seed(63)
        state = GameState(50, 20)
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

    def test_choose_equips_the_chosen_item_and_discards_the_old_one(self):
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

    def test_choose_armor_sets_defense_from_the_table(self):
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
            list(state.player.inventory),
            state.player.hp,
        )
        n_messages = len(state.messages)
        state.choose(0)
        after = (
            state.player.power,
            state.player.defense,
            state.player.weapon,
            state.player.armor,
            list(state.player.inventory),
            state.player.hp,
        )
        self.assertEqual(before, after)
        self.assertFalse(state.is_choosing)
        self.assertEqual(len(state.messages), n_messages + 1)
        self.assertIn(JUNK_NAME, state.messages[-1])

    def test_choose_rejects_bad_index_and_no_pending_choice(self):
        state = self.state_with_choice([Item(0, 0, JUNK)] * 3)
        with self.assertRaises(ValueError):
            state.choose(3)
        self.assertTrue(state.is_choosing)  # still pending: no cancel
        state.choose(2)
        with self.assertRaises(ValueError):
            state.choose(0)

    def test_pending_choice_blocks_movement_and_turns(self):
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

    def test_pending_choice_still_allows_quit(self):
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

    def test_digit_while_not_choosing_does_nothing(self):
        random.seed(65)
        state = GameState(50, 20)
        start = (state.player.x, state.player.y, state.player.weapon, len(state.messages))
        for action in ('choose_1', 'choose_2', 'choose_3'):
            self.assertFalse(state.handle_action(action))
        self.assertEqual(
            (state.player.x, state.player.y, state.player.weapon, len(state.messages)), start
        )
        self.assertFalse(state.monster_phase_pending())

    def test_bad_index_from_input_is_harmless(self):
        # Fewer offers than keys: '3' must not raise out of handle_action.
        state = self.state_with_choice([Item(0, 0, JUNK), Item(0, 0, JUNK)])
        self.assertFalse(state.handle_action('choose_3'))
        self.assertTrue(state.is_choosing)
        with self.assertRaises(ValueError):
            state.choose(2)  # direct callers still get the error

    def test_boss_chest_in_play_offers_rare_or_epic_without_junk(self):
        random.seed(64)
        state = GameState(50, 20)
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
        random.seed(7)
        self.state = GameState(50, 20)
        p = self.state.player
        self.goblin = Monster(p.x + 1, p.y, 'goblin')
        self.state.game_map[p.y][p.x + 1] = FLOOR
        self.state.entities = [p, self.goblin]
        self.state.update_fov()

    def test_attack_records_a_hit(self):
        self.goblin.hp = 2
        self.state.player.power = 5
        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.0):  # no random crit
            self.state.attack(self.state.player, self.goblin)
        (hit,) = self.state.combat_events
        self.assertIs(hit.attacker, self.state.player)
        self.assertIs(hit.defender, self.goblin)
        self.assertEqual((hit.damage, hit.killed), (5, True))
        self.assertEqual((hit.x, hit.y), (self.goblin.x, self.goblin.y))

    def test_events_last_one_round_but_serials_keep_counting(self):
        self.state.attack(self.goblin, self.state.player)
        first = self.state.combat_events[0].serial
        self.state.handle_action('wait')
        self.assertTrue(all(h.serial > first for h in self.state.combat_events))
        self.state.handle_action('descend')  # not on the stairs: no turn, no blows
        self.assertEqual(self.state.combat_events, [])

    def test_melee_opponents_are_orthogonal_neighbours_only(self):
        self.assertEqual(self.state.melee_opponents(), [self.goblin])
        self.goblin.y += 1  # now diagonal
        self.assertEqual(self.state.melee_opponents(), [])
        self.goblin.y -= 1
        self.goblin.alive = False
        self.assertEqual(self.state.melee_opponents(), [])


class CritAndReductionTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(50, 20)
        p = self.state.player
        self.goblin = Monster(p.x + 1, p.y, 'goblin')
        self.goblin.hp = self.goblin.max_hp = 10**6
        p.hp = p.max_hp = 10**6
        self.state.entities = [p, self.goblin]

    def hit(self, attacker, defender, crit):
        """One attack with the crit roll forced either way."""
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0 if crit else 0.0):
            self.state.attack(attacker, defender)
        return self.state.combat_events[-1]

    def test_constants(self):
        self.assertEqual(BASE_CRIT_CHANCE, 0.10)
        self.assertEqual(CRIT_MULTIPLIER, 1.5)
        self.assertEqual(crit_chance(self.state.player), BASE_CRIT_CHANCE)

    def test_defense_zero_non_crit_is_full_power(self):
        self.state.player.power = 7
        self.goblin.defense = 0
        hit = self.hit(self.state.player, self.goblin, False)
        self.assertEqual(hit.damage, 7)
        self.assertFalse(hit.crit)
        self.assertIsInstance(hit.damage, int)

    def test_monster_hit_on_armored_player_is_reduced(self):
        p = self.state.player
        p.defense = 10  # 50% reduction
        self.goblin.power = 7  # 3.5 -> probabilistic
        random.seed(5)
        expected = []
        rng_probe = random.Random()
        rng_probe.setstate(random.getstate())
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
        random.seed(123)
        self.state.player.power = 10
        crits = 0
        n = 4000
        for _ in range(n):
            self.state.attack(self.state.player, self.goblin)
            crits += self.state.combat_events[-1].crit
        self.assertTrue(0.07 < crits / n < 0.13, crits / n)

    def test_monsters_never_crit(self):
        random.seed(1)
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            for _ in range(300):
                self.state.attack(self.goblin, self.state.player)
                self.assertFalse(self.state.combat_events[-1].crit)
        self.assertNotIn('Critical hit!', self.state.messages)

    def test_crit_multiplies_raw_before_reduction(self):
        self.state.player.power = 10
        self.goblin.defense = 10  # 50%: 10 -> 5, crit 15 -> 7.5
        random.seed(9)
        hits = [self.hit(self.state.player, self.goblin, True).damage for _ in range(200)]
        self.assertTrue(all(d in (7, 8) for d in hits))
        self.assertGreater(len(set(hits)), 1)
        self.assertAlmostEqual(sum(hits) / len(hits), 7.5, delta=0.5)

    def test_crit_hit_is_flagged_and_logged(self):
        self.state.player.power = 4
        hit = self.hit(self.state.player, self.goblin, True)
        self.assertTrue(hit.crit)
        self.assertEqual(hit.damage, 6)
        self.assertIn('Critical hit!', self.state.messages)
        self.assertIn('You hit goblin for 6.', self.state.messages)

    def test_arrow_can_crit(self):
        self.state.player.char_class = 'archer'
        self.state.player.power = 4
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            self.state.shoot_arrow(1, 0)
        self.assertTrue(self.state.combat_events[-1].crit)


class WeaponTypeTests(unittest.TestCase):
    """The six weapon types (game/item.py WEAPON_TYPES) and their effects."""

    EXPECTED_BONUS = {
        'war_axe': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'rapier': {'common': -1, 'uncommon': 0, 'rare': 2, 'epic': 5},
        'great_sword': {'common': 2, 'uncommon': 3, 'rare': 5, 'epic': 8},
        'sword_shield': {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7},
        'dagger': {'common': 0, 'uncommon': 1, 'rare': 3, 'epic': 6},
        'spear': {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7},
    }

    def setUp(self):
        random.seed(90)
        self.state = GameState(50, 20, char_class='warrior')
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
        return mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)

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
                self.assertTrue(item.is_gear)
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

    def test_damage_bonus_by_rarity(self):
        for kind, table in self.EXPECTED_BONUS.items():
            for rarity, bonus in table.items():
                self.assertEqual(Item(0, 0, kind, rarity).bonus, bonus, (kind, rarity))
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

    def test_power_uses_the_bonus_at_each_rarity(self):
        p = self.state.player
        for kind, table in self.EXPECTED_BONUS.items():
            for rarity, bonus in table.items():
                self.equip(kind, rarity)
                self.assertEqual(p.power, p.base_power + bonus, (kind, rarity))

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

    def test_war_axe_adds_hp_and_replacing_it_removes_it(self):
        p = self.state.player
        p.hp, p.max_hp = 20, 25
        self.equip('war_axe', 'rare')  # +9
        self.assertEqual((p.hp, p.max_hp), (29, 34))
        self.equip('war_axe', 'epic')  # -9 +15
        self.assertEqual((p.hp, p.max_hp), (35, 40))
        self.equip('spear', 'common')  # -15
        self.assertEqual((p.hp, p.max_hp), (20, 25))
        self.assertEqual(p.power, p.base_power + 1)

    def test_losing_the_axe_never_kills_or_overfills(self):
        p = self.state.player
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
        random.seed(5)
        probe = random.Random()
        probe.setstate(random.getstate())
        expected = []
        for _ in range(2):
            probe.random()  # the crit roll
            expected.append(round_damage(mitigate(7, 10), probe))
        before = len(self.state.messages)
        with self.no_crit():
            self.state.handle_action('move_e')
            self.state.resolve_player_phase()
        hits = [h for h in self.state.combat_events if h.attacker is p]
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
            with mock.patch('game.state.random.random', side_effect=rolls):
                self.state.handle_action('move_e')
                self.state.resolve_player_phase()
            hits = [h for h in self.state.combat_events if h.attacker is self.state.player]
            self.assertEqual([h.crit for h in hits], crits)
            self.assertEqual([h.damage for h in hits], [6 if c else 4 for c in crits])

    def test_rapier_stops_when_the_first_strike_kills(self):
        self.equip('rapier', 'epic')
        goblin = self.monster(11, 10, hp=1)
        with self.no_crit():
            self.state.melee(goblin)
        self.assertEqual(len(self.state.combat_events), 1)
        self.assertFalse(goblin.alive)

    def test_rapier_second_strike_waits_until_stepped(self):
        # handle_action lands strike 1 only and leaves the player's half
        # open: no monster is queued until the second strike resolves.
        self.equip('rapier', 'epic')
        p = self.state.player
        goblin = self.monster(11, 10)
        with self.no_crit():
            self.assertTrue(self.state.handle_action('move_e'))
            self.assertEqual(len(self.state.combat_events), 1)
            first = self.state.combat_events[0].damage
            self.assertEqual(goblin.hp, 1000 - first)
            self.assertTrue(self.state.strike_pending())
            self.assertFalse(self.state.monster_phase_pending())
            self.assertTrue(self.state.step_strike())
        hits = self.state.combat_events
        self.assertEqual([h.attacker for h in hits], [p, p])
        self.assertEqual([h.defender for h in hits], [goblin, goblin])
        self.assertLess(hits[0].serial, hits[1].serial)
        self.assertEqual(goblin.hp, 1000 - first - hits[1].damage)
        self.assertFalse(self.state.strike_pending())
        self.assertTrue(self.state.monster_phase_pending())  # now the monsters

    def test_rapier_kill_on_the_first_strike_ends_the_half_at_once(self):
        self.equip('rapier', 'epic')
        goblin = self.monster(11, 10, hp=1)
        other = self.monster(20, 10)
        with self.no_crit():
            self.state.handle_action('move_e')
        self.assertFalse(goblin.alive)
        self.assertEqual(len(self.state.combat_events), 1)
        self.assertFalse(self.state.strike_pending())
        self.assertTrue(self.state.monster_phase_pending())
        self.assertEqual(other.hp, 1000)

    def test_rapier_second_strike_skips_a_vanished_target(self):
        self.equip('rapier', 'epic')
        goblin = self.monster(11, 10)
        with self.no_crit():
            self.state.handle_action('move_e')
        self.state.entities.remove(goblin)  # gone before strike 2
        hp = goblin.hp
        self.assertFalse(self.state.step_strike())
        self.assertEqual(goblin.hp, hp)
        self.assertEqual(len(self.state.combat_events), 1)
        self.assertFalse(self.state.strike_pending())

    def test_rapier_second_strike_does_nothing_once_the_player_is_dead(self):
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
        self.assertEqual(self.state.combat_events, [])

    def test_rapier_end_turn_resolves_both_strikes_then_the_monsters(self):
        self.equip('rapier', 'epic')
        p = self.state.player
        goblin = self.monster(11, 10)
        goblin.power = 3
        turn = self.state.turn
        with self.no_crit():
            self.state.handle_action('move_e')
            self.state.end_turn()
        attackers = [h.attacker for h in self.state.combat_events]
        # Both of the player's strikes, then the goblin's reply.
        self.assertEqual(attackers, [p, p, goblin])
        self.assertEqual(self.state.turn, turn + 1)
        self.assertFalse(self.state.strike_pending())
        self.assertFalse(self.state.monster_phase_pending())

    def test_warrior_single_strike_is_unchanged(self):
        goblin = self.monster(11, 10)
        with self.no_crit():
            self.state.handle_action('move_e')
        self.assertEqual(len(self.state.combat_events), 1)
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
        defenders = [
            h.defender for h in self.state.combat_events if h.attacker is self.state.player
        ]
        self.assertEqual(defenders, [target, other])
        self.assertLess(other.hp, 1000)
        self.assertTrue(any('carries on into goblin' in m for m in self.state.messages))

    def test_great_sword_ignores_monsters_not_orthogonally_next_to_the_player(self):
        self.equip('great_sword', 'rare')
        target = self.monster(11, 10)
        diagonal = self.monster(11, 9)
        two_away = self.monster(8, 10)
        beside_target = self.monster(12, 10)  # next to the target only
        with self.no_crit():
            self.state.handle_action('move_e')
        player_hits = [h for h in self.state.combat_events if h.attacker is self.state.player]
        self.assertEqual([h.defender for h in player_hits], [target])
        for m in (diagonal, two_away, beside_target):
            self.assertEqual(m.hp, 1000)

    def test_great_sword_hits_only_one_extra_monster(self):
        self.equip('great_sword', 'rare')
        target = self.monster(11, 10)
        self.monster(10, 9)
        self.monster(10, 11)
        with self.no_crit():
            self.state.melee(target)
        self.assertEqual(len(self.state.combat_events), 2)

    def test_other_weapons_do_not_cleave(self):
        self.equip('spear', 'rare')
        target = self.monster(11, 10)
        other = self.monster(10, 9)
        self.state.melee(target)
        self.assertEqual(other.hp, 1000)

    # -- Sword & Shield ------------------------------------------------------

    def test_sword_and_shield_defense_stacks_with_armor(self):
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

    def test_sword_and_shield_alone_gives_defense(self):
        for rarity, shield in zip(RARITIES, (3, 6, 9, 12)):
            self.equip('sword_shield', rarity)
            self.assertEqual(self.state.player.defense, shield)
            self.assertIsNone(self.state.player.armor)

    # -- Dagger --------------------------------------------------------------

    def test_dagger_raises_crit_chance_by_rarity(self):
        p = self.state.player
        self.assertEqual(crit_chance(p), BASE_CRIT_CHANCE)
        chances = []
        for rarity, bonus in zip(RARITIES, (0.05, 0.10, 0.15, 0.20)):
            self.equip('dagger', rarity)
            self.assertAlmostEqual(crit_chance(p), BASE_CRIT_CHANCE + bonus)
            chances.append(crit_chance(p))
        self.assertEqual(chances, sorted(chances))
        self.equip('spear', 'epic')
        self.assertEqual(crit_chance(p), BASE_CRIT_CHANCE)

    def test_crit_chance_is_capped_at_one(self):
        self.equip('dagger', 'epic')
        with mock.patch('game.state.BASE_CRIT_CHANCE', 0.95):
            self.assertEqual(crit_chance(self.state.player), 1.0)

    def test_dagger_crit_shows_up_in_attacks(self):
        self.equip('dagger', 'epic')  # 30%
        goblin = self.monster(11, 10, hp=10**9)
        random.seed(321)
        n = 3000
        crits = 0
        for _ in range(n):
            self.state.attack(self.state.player, goblin)
            crits += self.state.combat_events[-1].crit
        self.assertTrue(0.26 < crits / n < 0.34, crits / n)

    def test_monsters_do_not_get_the_dagger_bonus(self):
        self.assertEqual(crit_chance(Monster(0, 0, 'goblin')), BASE_CRIT_CHANCE)

    # -- Spear ---------------------------------------------------------------

    def test_spear_reaches_a_monster_two_tiles_away(self):
        self.equip('spear', 'rare')
        far = self.monster(12, 10)
        with self.no_crit():
            self.assertTrue(self.state.handle_action('move_e'))
        self.assertEqual((self.state.player.x, self.state.player.y), (10, 10))
        self.assertLess(far.hp, 1000)
        (hit,) = self.state.combat_events
        self.assertIs(hit.defender, far)

    def test_spear_reaches_in_every_direction(self):
        self.equip('spear', 'rare')
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

    def test_spear_with_a_wall_in_the_middle_is_a_normal_move(self):
        self.equip('spear', 'rare')
        self.state.game_map[10][11] = WALL
        far = self.monster(12, 10)
        self.state.handle_action('move_e')
        self.assertEqual(far.hp, 1000)
        self.assertEqual((self.state.player.x, self.state.player.y), (10, 10))

    def test_spear_does_not_reach_through_a_door(self):
        self.equip('spear', 'rare')
        self.state.game_map[10][11] = DOOR
        far = self.monster(12, 10)
        # Force the target visible so only the door rule can block the strike.
        self.state.visible[10][12] = True
        self.state.handle_action('move_e')
        self.assertEqual(far.hp, 1000)
        # The door is walkable, so the press is a normal move into it.
        self.assertEqual((self.state.player.x, self.state.player.y), (11, 10))

    def test_spear_does_not_reach_diagonally(self):
        self.equip('spear', 'rare')
        for x, y in ((12, 11), (12, 12), (11, 11)):
            m = self.monster(x, y)
            self.state.player.x, self.state.player.y = 10, 10
            self.state.update_fov()
            self.state.handle_action('move_e')
            self.assertEqual(m.hp, 1000)
            self.assertEqual((self.state.player.x, self.state.player.y), (11, 10))
            m.alive = False

    def test_spear_does_not_reach_three_tiles_or_an_unseen_monster(self):
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

    def test_without_a_spear_two_away_is_just_a_move(self):
        self.equip('weapon', 'rare')
        far = self.monster(12, 10)
        self.state.handle_action('move_e')
        self.assertEqual(far.hp, 1000)
        self.assertEqual(self.state.player.x, 11)


class BossEnrageTests(unittest.TestCase):
    def _arena(self, depth=8):
        """Open 20x20 floor; player at (5,10), a boss orc at (7,10) with hp 20."""
        state = GameState(20, 20)
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
            random.seed(seed)
            state, boss = self._arena()
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
        state = GameState(20, 20)
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
        return [h for h in state.combat_events if h.attacker is attacker]

    def test_stats_are_weaker_than_a_goblin(self):
        for depth in (1, 4, 7, 13, 25):
            shooter, gob = Monster(0, 0, 'goblin_archer', depth), Monster(0, 0, 'goblin', depth)
            self.assertLess(shooter.power, gob.power, depth)
            self.assertLess(shooter.hp, gob.hp, depth)
            self.assertEqual((shooter.hp, shooter.power), scale_stats(7, 1, depth))

    def test_char_is_unique_among_monsters_and_items(self):
        chars = [c for c, *_ in MONSTER_TYPES.values()]
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

    def test_never_shoots_through_a_wall_or_closed_door(self):
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

    def test_does_not_shoot_through_another_monster(self):
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
        self.assertEqual((shooter.x, shooter.y), (9, 10), 'stepped toward the player')

    def test_spawns_alone_per_room_from_depth_four(self):
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
                        self.assertEqual(len(shooters), 1)
                        self.assertEqual({m.kind for m in here}, {'goblin_archer'})
        self.assertGreater(seen, 0)

    def test_name_and_log_say_goblin_archer(self):
        state = self._arena()
        shooter = self._add(state, 9, 10)
        self.assertEqual(shooter.name, 'goblin archer')
        with mock.patch('game.state.dodge_chance', return_value=0):
            state.end_turn()
        self.assertIn('Goblin archer hits you', ' '.join(state.messages))

    def test_a_shot_records_one_arrow_from_its_cell_to_the_player(self):
        state = self._arena()
        shooter = self._add(state, 9, 10)
        with mock.patch('game.state.dodge_chance', return_value=0):
            state.end_turn()
        (hit,) = self._hits_by(state, shooter)
        (shot,) = state.shots
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
        with mock.patch('game.state.dodge_chance', return_value=0):
            state.end_turn()
        self.assertEqual(state.shots, [])

    def test_a_dodged_shot_flies_past_the_player_to_the_wall(self):
        state = self._arena()
        shooter = self._add(state, 9, 10)
        hp = state.player.hp
        with mock.patch('game.state.dodge_chance', return_value=100):
            state.end_turn()
        self.assertEqual(state.player.hp, hp)
        self.assertEqual(self._hits_by(state, shooter), [])
        self.assertIn("You dodge the goblin archer's attack.", state.messages)
        (shot,) = state.shots
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
        random.seed(90)
        state = GameState(50, 20)
        for depth in depths:
            for _ in range(n):
                state.depth = depth - 1
                state.next_level()
                yield state

    def test_at_most_one_and_never_on_start_stairs_or_chest(self):
        found = floors = 0
        for state in self.floors((2, 3, 5, 9), 100):
            floors += 1
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
        # About SHRINE_CHANCE of floors (400 floors: well inside +-0.1).
        self.assertGreater(found / floors, SHRINE_CHANCE - 0.1)
        self.assertLess(found / floors, SHRINE_CHANCE + 0.1)

    def test_never_on_a_boss_floor(self):
        self.assertTrue(is_boss_level(FIRST_BOSS_DEPTH))
        for state in self.floors((FIRST_BOSS_DEPTH, 2 * FIRST_BOSS_DEPTH), 60):
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
        random.seed(91)
        self.state = GameState(50, 20)
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

    def test_blood_pact_power_up_max_hp_down_and_hp_clamped(self):
        player = self.state.player
        power, max_hp = player.power, player.max_hp
        self.take('blood_pact')
        self.assertEqual(player.power, power + 3)
        self.assertEqual(player.max_hp, max_hp - 15)
        self.assertEqual(player.hp, player.max_hp)  # was full: clamped down

    def test_blood_pact_never_kills(self):
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

    def test_boons_text_lists_the_short_names(self):
        player = self.state.player
        self.assertEqual(boons_text(player), '')
        self.take('blood_pact')
        self.take('keen_eye')
        self.assertEqual(boons_text(player), 'Boons: Blood Keen')
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
        self.state = GameState(50, 20)
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

    def test_leather_has_dodge_and_heavy_has_none(self):
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

    def test_a_dodge_avoids_damage_records_no_hit_and_logs(self):
        self.wear('leather', 'epic')
        hp = self.state.player.hp
        self.state.combat_events.clear()
        with mock.patch('game.state.random.random', return_value=0.0):
            self.state.attack(self.goblin, self.state.player)
        self.assertEqual(self.state.player.hp, hp)
        self.assertEqual(self.state.combat_events, [])
        self.assertEqual(self.state.messages[-1], "You dodge the goblin's attack.")

    def test_seeded_dodges_happen_at_the_dodge_rate(self):
        self.wear('leather', 'epic')  # 12%
        random.seed(3)
        n = 5000
        for _ in range(n):
            self.state.attack(self.goblin, self.state.player)
        dodges = sum(1 for m in self.state.messages if m.startswith('You dodge'))
        self.assertAlmostEqual(dodges / n, 0.12, delta=0.02)
        self.assertEqual(len(self.state.combat_events), n - dodges)

    def test_a_failed_dodge_roll_still_hits(self):
        self.wear('leather', 'epic')
        hp = self.state.player.hp
        with mock.patch('game.state.random.random', return_value=0.99):
            self.state.attack(self.goblin, self.state.player)
        self.assertLess(self.state.player.hp, hp)
        self.assertEqual(len(self.state.combat_events), 1)

    def test_no_dodge_without_dodge(self):
        self.wear('armor', 'epic')
        random.seed(1)
        for _ in range(500):
            self.state.attack(self.goblin, self.state.player)
        self.assertEqual(len(self.state.combat_events), 500)
        self.assertFalse(any(m.startswith('You dodge') for m in self.state.messages))

    def test_the_players_own_attacks_are_never_dodged(self):
        self.wear('leather', 'epic')
        self.state.player.armor.dodge = 50
        self.goblin.hp = self.goblin.max_hp = 10**6
        for _ in range(200):
            self.state.attack(self.state.player, self.goblin)
        self.assertEqual(len(self.state.combat_events), 200)

    def test_a_goblin_archers_shot_can_be_dodged(self):
        p = self.state.player
        shooter = Monster(p.x + 2, p.y, 'goblin_archer')
        self.wear('leather')
        hp = p.hp
        with mock.patch('game.state.random.random', return_value=0.0):
            self.state.attack(shooter, p)
        self.assertEqual(p.hp, hp)
        self.assertIn(f"You dodge the {shooter.name}'s attack.", self.state.messages)

    def test_starting_armor_by_class(self):
        archer = GameState(50, 20, char_class='archer').player
        self.assertEqual((archer.armor.kind, archer.armor.rarity), ('leather', 'common'))
        self.assertEqual(archer.defense, ARMOR_SPLIT['leather']['common'][0])
        self.assertEqual(dodge_chance(archer), ARMOR_SPLIT['leather']['common'][1])
        warrior = GameState(50, 20, char_class='warrior').player
        self.assertIsNone(warrior.armor)
        self.assertEqual(warrior.defense, 0)

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

    def test_warriors_find_both_armor_kinds(self):
        rng = random.Random(12)
        n = 20000
        drops = [roll_gear_drop(1, rng, char_class='warrior') for _ in range(n)]
        boss = [roll_boss_drop(rng, char_class='warrior') for _ in range(n)]
        for found in (drops, boss):
            kinds = {d.kind for d in found if d.kind in ARMOR_KINDS}
            self.assertEqual(kinds, {'armor', 'leather'})

    def test_archers_only_find_leather_at_the_same_armor_share(self):
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
        random.seed(120)
        self.state = GameState(50, 20, char_class='archer')
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
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
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
    }
    EXPECTED_EFFECT = {
        'longbow': ('pierce', (2, 2, 3, 4)),
        'heavy_crossbow': ('reload', (2, 2, 1, 1)),
        'volley_bow': ('spread', (2, 2, 3, 3)),
        'sling': ('knockback', (1, 1, 2, 2)),
        'hunters_bow': ('mark_bonus', (0.25, 0.50, 0.75, 1.00)),
        'quickdraw': ('tempo', (4, 4, 3, 2)),
    }

    # -- data ----------------------------------------------------------------

    def test_six_archer_weapons_are_weapon_slot_gear(self):
        self.assertEqual(set(ARCHER_WEAPONS), set(self.EXPECTED_BONUS))
        self.assertFalse(set(ARCHER_WEAPONS) & set(WARRIOR_WEAPONS))
        for kind in ARCHER_WEAPONS:
            self.assertEqual(GEAR_SLOTS[kind], 'weapon')
            self.assertIn(kind, GEAR_DROP_KINDS)

    def test_damage_bonus_by_rarity(self):
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

    def test_longbow_pierces_two_monsters_at_full_damage(self):
        self.equip('longbow', 'common', power=6)
        first, second, third = self.monster(12, 10), self.monster(14, 10), self.monster(16, 10)
        self.assertTrue(self.state.shoot_arrow(1, 0))
        self.assertEqual([h.defender for h in self.state.combat_events], [first, second])
        self.assertEqual([h.damage for h in self.state.combat_events], [6, 6])
        self.assertEqual(third.hp, 1000)
        self.assertEqual(self.piles(), {(14, 10): 1})  # where it stopped

    def test_longbow_stops_at_a_wall(self):
        self.equip('longbow', 'epic')
        self.state.game_map[10][13] = WALL
        near, beyond = self.monster(12, 10), self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        self.assertLess(near.hp, 1000)
        self.assertEqual(beyond.hp, 1000)
        self.assertEqual(self.piles(), {(12, 10): 1})  # last free tile before the wall

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

    def test_epic_crossbow_reloads_in_one_turn(self):
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
        damage = {h.defender: h.damage for h in self.state.combat_events}
        self.assertEqual(damage, {aim: 10, left: 5, right: 5})
        self.assertEqual(self.piles(), {(13, 10): 1})  # one arrow spent, one pile
        self.assertEqual(self.state.player.quiver, QUIVER_CAPACITY - 1)

    def test_rare_volley_sends_a_third_extra_down_the_aim_line(self):
        self.equip('volley_bow', 'rare', power=10)  # 3 extras at 60%
        aim = self.monster(13, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.damage for h in self.state.combat_events], [10, 6])
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
        self.assertEqual(len(state.shots), 1)  # one shot, not one per arrow
        shot = state.shots[0]
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
        self.assertEqual(sorted(every, key=lambda h: h.serial), state.combat_events)
        self.assertLess(shot.serial, min(h.serial for h in every))
        self.assertEqual(state.player.quiver, QUIVER_CAPACITY - 1)  # one arrow spent
        self.assertEqual(state.turn, 1)  # all of it on the same turn

    def test_point_blank_volley_puts_every_arrow_into_the_adjacent_target(self):
        self.equip('volley_bow', 'common', power=10)  # 2 extras at 50%
        target = self.monster(11, 10)
        left, right = self.monster(11, 9), self.monster(11, 11)  # the side lanes
        state = self.state
        self.assertTrue(state.handle_action('shoot_e'))
        self.assertEqual([h.defender for h in state.combat_events], [target] * 3)
        self.assertEqual([h.damage for h in state.combat_events], [10, 5, 5])
        self.assertEqual(target.hp, 1000 - 20)
        self.assertEqual((left.hp, right.hp), (1000, 1000))
        (shot,) = state.shots
        self.assertEqual(len(shot.arrows), 3)
        for arrow in shot.arrows:
            self.assertEqual(arrow.path, ((10, 10), (11, 10)))
            self.assertEqual([h.defender for h in arrow.hits], [target])
        self.assertEqual(state.player.quiver, QUIVER_CAPACITY - 1)  # one arrow spent
        self.assertEqual(self.piles(), {(11, 10): 1})

    def test_point_blank_rare_volley_lands_all_four_arrows(self):
        self.equip('volley_bow', 'rare', power=10)  # 3 extras at 60%
        target = self.monster(11, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.damage for h in self.state.combat_events], [10, 6, 6, 6])
        self.assertEqual(target.hp, 1000 - 28)

    def test_point_blank_volley_does_not_overkill(self):
        self.equip('volley_bow', 'common', power=10)
        target = self.monster(11, 10, hp=5)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.combat_events], [target])
        self.assertFalse(target.alive)
        (shot,) = self.state.shots
        self.assertEqual([len(a.hits) for a in shot.arrows], [1, 0, 0])

    def test_volley_two_tiles_away_is_not_point_blank(self):
        self.equip('volley_bow', 'common', power=10)
        target = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual([h.defender for h in self.state.combat_events], [target])
        self.assertEqual(target.hp, 990)

    def test_a_single_arrow_bow_records_a_one_arrow_shot(self):
        self.equip('longbow', 'common', power=6)
        first, second = self.monster(12, 10), self.monster(14, 10)
        self.state.shoot_arrow(1, 0)
        (shot,) = self.state.shots
        self.assertEqual(len(shot.arrows), 1)
        self.assertEqual(shot.arrows[0].path[0], (10, 10))
        self.assertEqual([h.defender for h in shot.arrows[0].hits], [first, second])
        self.assertEqual((shot.path, shot.hits), tuple(shot.arrows[0]))

    def test_attack_factor_defaults_to_one(self):
        m = self.monster(11, 10)
        self.state.player.power = 8
        self.state.attack(self.state.player, m)
        self.state.attack(self.state.player, m, 0.5)
        self.assertEqual([h.damage for h in self.state.combat_events], [8, 4])

    # -- sling ---------------------------------------------------------------

    def test_sling_pushes_the_target_away(self):
        self.equip('sling', 'common')
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (13, 10))
        self.assertEqual(len(self.state.combat_events), 1)  # the push is no Hit
        self.assertEqual(self.piles(), {(12, 10): 1})  # where the shot hit

    def test_rare_sling_pushes_two_tiles(self):
        self.equip('sling', 'rare')
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (14, 10))

    def test_sling_never_pushes_into_a_wall_or_onto_a_monster(self):
        self.equip('sling', 'common')
        self.state.game_map[10][13] = WALL
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (12, 10))
        self.state.game_map[10][13] = FLOOR
        behind = self.monster(13, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual(((m.x, m.y), (behind.x, behind.y)), ((12, 10), (13, 10)))

    def test_sling_push_stops_short_of_a_blocker(self):
        self.equip('sling', 'epic')
        self.state.game_map[10][14] = WALL
        m = self.monster(12, 10)
        self.state.shoot_arrow(1, 0)
        self.assertEqual((m.x, m.y), (13, 10))

    # -- hunter's bow --------------------------------------------------------

    def test_mark_adds_damage_to_the_next_arrow_and_clears_on_death(self):
        self.equip('hunters_bow', 'common', power=8)  # +25%
        state = self.state
        m = self.monster(12, 10)
        state.shoot_arrow(1, 0)
        self.assertIs(state.marked, m)
        state.shoot_arrow(1, 0)
        self.assertEqual([h.damage for h in state.combat_events], [8, 10])
        m.hp = 1
        state.shoot_arrow(1, 0)
        self.assertFalse(m.alive)
        self.assertIsNone(state.marked)

    def test_a_new_mark_replaces_the_old(self):
        self.equip('hunters_bow', 'epic', power=8)  # +100%
        state = self.state
        east, west = self.monster(12, 10), self.monster(8, 10)
        state.shoot_arrow(1, 0)
        state.shoot_arrow(-1, 0)
        self.assertIs(state.marked, west)
        state.shoot_arrow(1, 0)  # east is no longer marked: plain damage
        self.assertEqual([h.damage for h in state.combat_events], [8, 8, 8])
        self.assertIs(state.marked, east)

    # -- quickdraw -----------------------------------------------------------

    def test_every_fourth_quickdraw_shot_is_free(self):
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

    def test_epic_quickdraw_frees_every_second_shot(self):
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
            state = GameState(50, 20, char_class=char_class)
            for seed in range(60):
                random.seed(seed)
                chest = Chest(state.player.x, state.player.y, kind='gear')
                boss = spawn_boss_chest(state.player.x, state.player.y)
                for c in (chest, boss):
                    state.entities.append(c)
                    state.pending_choice = None
                    state.open_chest(c)
                    kinds = {item.kind for item in cast(list, state.pending_choice)}
                    self.assertFalse(kinds & set(other), char_class)


class StartingWeaponTests(unittest.TestCase):
    def test_archer_starts_with_a_common_longbow_and_warrior_the_plain_weapon(self):
        archer = GameState(50, 20, char_class='archer').player
        self.assertEqual((archer.weapon.kind, archer.weapon.rarity), ('longbow', 'common'))
        self.assertEqual(archer.weapon.pierce, 2)
        # base 3 + common bonus 1 + longbow offset -1 = 3 (above MIN_POWER).
        self.assertEqual(archer.power, 3)
        warrior = GameState(50, 20, char_class='warrior').player
        self.assertEqual((warrior.weapon.kind, warrior.weapon.rarity), ('weapon', 'common'))


class QuiverTests(ArcherArena):
    def test_archer_starts_with_a_full_quiver_and_warrior_has_none(self):
        self.assertEqual(self.state.player.quiver, QUIVER_CAPACITY)
        self.assertEqual(QUIVER_CAPACITY, 12)
        self.assertIsNone(GameState(50, 20, char_class='warrior').player.quiver)

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
        state.shoot_arrow(0, 1)  # on the hit monster's tile
        self.assertEqual(self.piles(), {(48, 10): 2, (10, 13): 1})

    def test_a_pile_does_not_block_and_is_picked_up(self):
        state = self.state
        state.player.quiver = 10
        state.entities.append(ArrowPile(11, 10))
        self.assertTrue(state.handle_action('move_e'))
        self.assertEqual((state.player.x, state.player.y), (11, 10))
        self.assertEqual(state.player.quiver, 11)
        self.assertEqual(self.piles(), {})

    def test_full_quiver_leaves_the_pile(self):
        state = self.state
        state.entities.append(ArrowPile(11, 10))
        state.handle_action('move_e')
        self.assertEqual((state.player.x, state.player.y), (11, 10))
        self.assertEqual(self.piles(), {(11, 10): 1})
        self.assertIn('Your quiver is full.', state.messages)

    def test_a_pile_bigger_than_the_room_is_split(self):
        state = self.state
        state.player.quiver = QUIVER_CAPACITY - 1
        state.entities.append(ArrowPile(11, 10, count=3))
        state.handle_action('move_e')
        self.assertEqual(state.player.quiver, QUIVER_CAPACITY)
        self.assertEqual(self.piles(), {(11, 10): 2})

    def test_restock_adds_an_arrow_every_three_turns(self):
        state = self.state
        state.player.quiver = 5
        self.assertEqual(state.restock_progress, 0)
        seen = []
        for _ in range(6):
            state.handle_action('wait')
            seen.append((state.restock_progress, state.player.quiver))
        self.assertEqual(RESTOCK_TURNS, 3)
        self.assertEqual(seen, [(1, 5), (2, 5), (3, 6), (1, 6), (2, 6), (3, 7)])

    def test_restock_stops_at_capacity(self):
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
        random.seed(122)
        state = GameState(50, 20, char_class='warrior')
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
        random.seed(11)
        state = GameState(50, 20)
        state.player.x, state.player.y = state.rooms[-1].center()
        return state

    @staticmethod
    def _line(n):
        return f'You descend the stairs and rest for a while, restoring {n} HP.'

    def test_full_hp_restores_nothing(self):
        state = self._on_stairs()
        top = state.player.max_hp
        self.assertTrue(state.try_descend())
        self.assertEqual(state.player.hp, top)
        self.assertIn(self._line(0), state.messages)

    def test_half_hp_restores_twenty_percent(self):
        state = self._on_stairs()
        state.player.hp = state.player.max_hp // 2
        before = state.player.hp
        expected = int(state.player.max_hp * DESCENT_HEAL_FRACTION)
        state.try_descend()
        self.assertEqual(state.player.hp, before + expected)
        self.assertIn(self._line(expected), state.messages)

    def test_near_max_caps_and_logs_capped_amount(self):
        state = self._on_stairs()
        state.player.hp = state.player.max_hp - 1
        state.try_descend()
        self.assertEqual(state.player.hp, state.player.max_hp)
        self.assertIn(self._line(1), state.messages)

    def test_refused_descent_heals_nothing(self):
        state = self._on_stairs()
        state.player.x, state.player.y = state.rooms[0].center()
        state.player.hp = 1
        self.assertFalse(state.try_descend())
        self.assertEqual(state.player.hp, 1)
        self.assertEqual(state.depth, 1)

    def test_game_over_descent_heals_nothing(self):
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
        random.seed(seed)
        state = GameState(40, 20)
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
