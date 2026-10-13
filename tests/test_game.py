"""Headless tests for game/ logic (no curses — this exercises GameState
and its collaborators directly, the same way the renderer would).

Run with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.dungeon import generate_dungeon, make_empty_map, place_doors, place_stairs, wall_sides
from game.entity import Entity
from game.fov import compute_fov, update_visibility
from game.item import (CHEST_COLOR, Chest, ITEM_KIND_WEIGHTS, Item, MAX_SCALING_DEPTH,
                       POTION_CHEST_COLOR, RARITIES, rarity_weights_for_depth, roll_rarity,
                       spawn_chests)
from game.monster import (BOSS_REFERENCE_KIND, MONSTER_TYPES, ORTHOGONAL_STEPS, Monster,
                          is_boss_level, scale_stats, spawn_boss, spawn_monsters,
                          tier_for_depth)
from game.rect import Rect
from game.save import apply_dict, load_game, save_game, state_to_dict
from game.state import GameState
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
            for r2 in rooms[i + 1:]:
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
                        seen_inside = [(rx, ry) for ry in range(room.y1, room.y2)
                                       for rx in range(room.x1, room.x2) if visible[ry][rx]]
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
        game_map[6][4] = FLOOR                   # one-wide gap in the south wall
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
        game_map = [list(row) for row in [
            '###########',
            '#.........#',
            '#.........#',
            '#....@....#',
            '#.........#',
            '#.........#',
            '###########',
        ]]
        visible = self._grid(11, 7)
        compute_fov(game_map, visible, 5, 3, radius=4)
        self.assertTrue(visible[3][5])   # origin
        self.assertTrue(visible[3][1])   # 4 tiles west, in open room
        self.assertTrue(visible[1][5])   # 2 tiles north, open

    def test_wall_blocks_sight_behind_it(self):
        # A single wall segment directly east of the player should shadow
        # the tile directly behind it, while the open tile to its side
        # (not directly hidden by the wall) stays visible.
        game_map = [list(row) for row in [
            '###########',
            '#.........#',
            '#....@#...#',
            '#.........#',
            '###########',
        ]]
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
            self.assertNotEqual(m.take_turn(player, game_map), 'attack',
                                f'diagonal offset {(dx, dy)} attacked')

    def test_diagonal_neighbour_closes_in_instead_of_stalling(self):
        """Making the attack orthogonal is only half the fix: the monster
        must still be able to reach a square it can attack from."""
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            game_map = self.room_map()
            player = Entity(3, 3, '@')
            m = Monster(3 + dx, 3 + dy, 'goblin')
            m.take_turn(player, game_map)
            self.assertTrue(m.is_adjacent(player),
                            f'diagonal offset {(dx, dy)} failed to close in')
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
        random.seed(6)
        rooms = [Rect(1, 1, 8, 8), Rect(20, 1, 8, 8), Rect(1, 12, 8, 6)]
        monsters = spawn_monsters(rooms)
        for m in monsters:
            in_room0 = rooms[0].x1 <= m.x < rooms[0].x2 and rooms[0].y1 <= m.y < rooms[0].y2
            self.assertFalse(in_room0)


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
        self.assertEqual((state.player.x, state.player.y),
                         (m.x - 1, m.y))  # player did not step onto corpse tile
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

    def test_chest_pickup_rolls_an_item_and_fills_inventory(self):
        random.seed(10)
        state = GameState(50, 20)
        chest = Chest(state.player.x + 1, state.player.y)
        state.entities = [state.player, chest]
        state.try_move_player(1, 0)
        self.assertEqual(len(state.player.inventory), 1)
        self.assertNotIn(chest, state.entities)
        self.assertIn('You open the chest.', state.messages)

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

    def test_game_over_blocks_movement_but_not_quit(self):
        random.seed(13)
        state = GameState(50, 20)
        state.game_over = True
        px, py = state.player.x, state.player.y
        state.handle_action('move_n')
        self.assertEqual((state.player.x, state.player.y), (px, py))
        state.handle_action('quit')
        self.assertFalse(state.running)


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
        self.assertTrue(state.step_monster_phase())   # the attack
        self.assertFalse(state.step_monster_phase())  # queue drained

    def test_unseen_monsters_resolve_without_reporting_a_frame(self):
        """A monster shuffling around in the dark must not cost the player a
        held frame, or walking an empty dungeon would crawl."""
        random.seed(33)
        state = GameState(50, 20)
        # Pick a floor tile the player genuinely cannot see, so the assertion
        # below can't pass just because the monster happened to sit still.
        hidden = [(x, y)
                  for y in range(1, state.height - 1)
                  for x in range(1, state.width - 1)
                  if is_walkable(state.game_map, x, y) and not state.is_visible(x, y)
                  and state.player.distance_to(Entity(x, y, '.')) > state.fov_radius + 1]
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

    def test_loading_cancels_a_queued_monster_phase(self):
        random.seed(35)
        state = GameState(50, 20)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)
            state.end_player_phase()
            apply_dict(state, load_game(path))
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

    def test_char_class_round_trips_through_save_load(self):
        random.seed(27)
        state = GameState(50, 20, char_class='archer')
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)
            fresh = GameState(50, 20, char_class='warrior')
            apply_dict(fresh, load_game(path))
            self.assertEqual(fresh.player.char_class, 'archer')


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
        base_power = state.player.power
        weapon = Item(0, 0, 'weapon', 'rare')
        weapon.apply(state.player, state.log)
        self.assertIs(state.player.weapon, weapon)
        self.assertEqual(state.player.power, base_power + weapon.bonus)

    def test_swapping_weapon_does_not_stack_bonus(self):
        random.seed(43)
        state = GameState(50, 20)
        base_power = state.player.power
        w1 = Item(state.player.x, state.player.y, 'weapon', 'common')
        w1.apply(state.player, state.log)
        w2 = Item(state.player.x, state.player.y, 'weapon', 'epic')
        w2.apply(state.player, state.log)
        self.assertEqual(state.player.power, base_power + w2.bonus)
        self.assertIs(state.player.weapon, w2)
        self.assertIn('swap', state.messages[-1])

    def test_worse_weapon_is_left_behind(self):
        random.seed(53)
        state = GameState(50, 20)
        base_power = state.player.power
        epic = Item(state.player.x, state.player.y, 'weapon', 'epic')
        epic.apply(state.player, state.log)
        common = Item(state.player.x, state.player.y, 'weapon', 'common')
        common.apply(state.player, state.log)
        self.assertIs(state.player.weapon, epic)
        self.assertEqual(state.player.power, base_power + epic.bonus)
        self.assertNotIn(common.name, state.player.inventory)
        self.assertIn('leave', state.messages[-1])

    def test_equal_or_worse_armor_is_left_behind(self):
        random.seed(54)
        state = GameState(50, 20)
        rare = Item(state.player.x, state.player.y, 'armor', 'rare')
        rare.apply(state.player, state.log)
        for rarity in ('common', 'uncommon', 'rare'):
            Item(state.player.x, state.player.y, 'armor', rarity).apply(state.player, state.log)
            self.assertIs(state.player.armor, rare)
            self.assertEqual(state.player.defense, rare.bonus)

    def test_armor_reduces_incoming_damage_with_floor_of_one(self):
        random.seed(44)
        state = GameState(50, 20)
        armor = Item(state.player.x, state.player.y, 'armor', 'epic')  # +7 defense
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

    def test_is_boss_level_every_eighth_floor(self):
        for d in (8, 16, 24):
            self.assertTrue(is_boss_level(d))
        for d in (1, 7, 9, 15):
            self.assertFalse(is_boss_level(d))

    def test_boss_stats_scale_off_reference_monster(self):
        depth = 8
        base_hp, base_power = MONSTER_TYPES[BOSS_REFERENCE_KIND][2], MONSTER_TYPES[BOSS_REFERENCE_KIND][3]
        reg_hp, reg_power = scale_stats(base_hp, base_power, depth)
        boss = spawn_boss([Rect(1, 1, 10, 10)], depth, rng=random.Random(1))
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
        # Even opened at depth 1, a boss chest ignores the depth-scaled table.
        for _ in range(20):
            self.assertIn(drops[0].open(depth=1).rarity, ('rare', 'epic'))


class ChestTests(unittest.TestCase):
    def test_spawn_chests_places_chests_not_items(self):
        random.seed(50)
        rooms = [Rect(1, 1, 10, 10), Rect(20, 1, 10, 10), Rect(1, 15, 10, 4)]
        chests = spawn_chests(rooms)
        self.assertTrue(all(isinstance(c, Chest) for c in chests))
        # Skips the player's starting room, same rule as monster spawning.
        for c in chests:
            self.assertFalse(rooms[0].x1 <= c.x < rooms[0].x2 and rooms[0].y1 <= c.y < rooms[0].y2)

    def test_regular_chest_open_returns_valid_kind_and_rarity(self):
        chest = Chest(0, 0)
        rng = random.Random(51)
        for depth in (1, 5, 10, 25):
            item = chest.open(depth, rng=rng)
            self.assertIn(item.kind, ITEM_KIND_WEIGHTS)
            self.assertIn(item.rarity, RARITIES)

    def test_chest_kind_is_fixed_at_spawn_and_sets_its_color(self):
        potion = Chest(0, 0, kind='potion')
        weapon = Chest(0, 0, kind='weapon')
        armor = Chest(0, 0, kind='armor')
        self.assertEqual(potion.color, POTION_CHEST_COLOR)
        self.assertEqual(weapon.color, CHEST_COLOR)
        self.assertEqual(armor.color, CHEST_COLOR)
        rng = random.Random(55)
        for chest in (potion, weapon, armor):
            for depth in (1, 10):
                self.assertEqual(chest.open(depth, rng=rng).kind, chest.kind)

    def test_boss_chest_ignores_depth_scaling(self):
        chest = Chest(0, 0, guaranteed_min_rarity='rare')
        rng = random.Random(52)
        for _ in range(30):
            self.assertIn(chest.open(depth=1, rng=rng).rarity, ('rare', 'epic'))

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
        deep_epics = sum(1 for _ in range(500) if roll_rarity(MAX_SCALING_DEPTH, random.Random()) == 'epic')
        self.assertGreater(deep_epics, shallow_epics)

    def test_open_chest_removes_it_and_applies_the_item(self):
        random.seed(53)
        state = GameState(50, 20)
        chest = Chest(state.player.x, state.player.y)
        state.entities = [state.player, chest]
        before = len(state.player.inventory)
        state.open_chest(chest)
        self.assertNotIn(chest, state.entities)
        self.assertEqual(len(state.player.inventory), before + 1)


class SaveLoadTests(unittest.TestCase):
    def test_round_trip_preserves_state(self):
        random.seed(14)
        state = GameState(50, 20)
        state.player.hp = 7
        state.player.inventory.append('potion of healing')
        state.log('hello')

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)

            fresh = GameState(50, 20)
            data = load_game(path)
            self.assertIsNotNone(data)
            apply_dict(fresh, data)

            self.assertEqual(fresh.player.hp, 7)
            self.assertEqual(fresh.player.inventory, ['potion of healing'])
            self.assertEqual(fresh.depth, state.depth)
            self.assertEqual(fresh.game_map, state.game_map)
            self.assertEqual(fresh.messages[-1], 'hello')

    def test_load_missing_file_returns_none(self):
        self.assertIsNone(load_game('/nonexistent/path/save.json'))

    def test_equipped_gear_round_trips(self):
        random.seed(48)
        state = GameState(50, 20)
        weapon = Item(state.player.x, state.player.y, 'weapon', 'rare')
        weapon.apply(state.player, state.log)
        armor = Item(state.player.x, state.player.y, 'armor', 'uncommon')
        armor.apply(state.player, state.log)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)
            fresh = GameState(50, 20)
            apply_dict(fresh, load_game(path))

        self.assertEqual(fresh.player.weapon.rarity, 'rare')
        self.assertEqual(fresh.player.armor.rarity, 'uncommon')
        self.assertEqual(fresh.player.power, fresh.player.base_power + weapon.bonus)
        self.assertEqual(fresh.player.defense, armor.bonus)

    def test_chest_on_the_map_round_trips(self):
        random.seed(49)
        state = GameState(50, 20)
        chest = Chest(state.player.x + 1, state.player.y, guaranteed_min_rarity='rare',
                      kind='potion')
        state.entities = [state.player, chest]

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)
            fresh = GameState(50, 20)
            apply_dict(fresh, load_game(path))

        loaded_chests = [e for e in fresh.entities if isinstance(e, Chest)]
        self.assertEqual(len(loaded_chests), 1)
        self.assertEqual(loaded_chests[0].guaranteed_min_rarity, 'rare')
        self.assertEqual(loaded_chests[0].kind, 'potion')
        self.assertEqual(loaded_chests[0].color, POTION_CHEST_COLOR)
        self.assertEqual((loaded_chests[0].x, loaded_chests[0].y), (chest.x, chest.y))


if __name__ == '__main__':
    unittest.main()
