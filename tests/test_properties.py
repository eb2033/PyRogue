"""Property-based tests (Hypothesis) for the edges the example tests miss.

Each test states an invariant and lets Hypothesis hunt for a counterexample:
odd map sizes, maps where nothing fits, depths far past anything played,
hostile .env lines, and long random playthroughs. A failure prints the
smallest input that breaks the rule; pin it with an example test in
test_game.py once it is fixed.

Skips cleanly when hypothesis isn't installed (CI's stdlib-only job); the
pinned version is in requirements-test.txt.

`HYPOTHESIS_PROFILE=deep` runs ~20x the examples, for a local bug hunt.
"""

import os
import random
import sys
import tempfile
import unittest
from collections import deque
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from hypothesis import HealthCheck, assume, given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - stdlib-only checkout
    raise unittest.SkipTest('hypothesis not installed') from None

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

from game import settings as config
from game.dungeon import generate_dungeon, place_stairs
from game.fov import compute_fov
from game.item import RARITIES, rarity_weights_for_depth, roll_rarity
from game.monster import Monster, scale_stats
from game.save import apply_dict, load_game, save_game, state_to_dict
from game.state import GameState
from game.tiles import DOOR, WALL, is_walkable
from render import camera
from render.base import Action

if pygame is not None:
    from render import ui

# Everything a player can press that stays inside one game: SAVE/LOAD touch
# the user data dir and QUIT ends the loop, so they are tested elsewhere.
PLAY_ACTIONS = [
    Action.MOVE_N,
    Action.MOVE_S,
    Action.MOVE_W,
    Action.MOVE_E,
    Action.SHOOT_N,
    Action.SHOOT_S,
    Action.SHOOT_W,
    Action.SHOOT_E,
    Action.WAIT,
    Action.DESCEND,
]

# HYPOTHESIS_PROFILE=deep runs ~20x the examples for a local bug hunt.
settings.register_profile('deep', max_examples=2000)
settings.load_profile(os.environ.get('HYPOTHESIS_PROFILE', 'default'))
# Dungeon generation is ~8 ms a map, so a whole playthrough can blow the
# default 200 ms deadline on a slow CI runner; time isn't what we test. The
# slow tests also run fewer examples than the fast ones by default.
SLOW = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    max_examples=max(60, settings.default.max_examples // 10),
)
seeds = st.integers(min_value=0, max_value=2**32 - 1)
# Environment values can't hold NUL or lone surrogates.
env_text = st.text(st.characters(exclude_categories=('Cs',), exclude_characters='\x00'))


def reachable(game_map, start):
    """Every walkable (x, y) reachable from `start` by 4-way steps."""
    seen, queue = {start}, deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in seen and is_walkable(game_map, *nxt):
                seen.add(nxt)
                queue.append(nxt)
    return seen


def build_dungeon(w, h, seed):
    random.seed(seed)
    game_map, rooms = generate_dungeon(w, h)
    stairs = place_stairs(game_map, rooms)
    return game_map, rooms, stairs


class DungeonPropertyTests(unittest.TestCase):
    # Down to 3x3 -- the smallest map with an interior -- and well past the
    # 50x20 default, so the size clamping in generate_dungeon is exercised.
    sizes = given(w=st.integers(3, 90), h=st.integers(3, 45), seed=seeds)

    @SLOW
    @sizes
    def test_border_stays_solid(self, w, h, seed):
        """Entity.move doesn't bounds-check, so a gap in the border would let
        anything walk off the map (CLAUDE.md gotcha)."""
        game_map, _, _ = build_dungeon(w, h, seed)
        self.assertEqual(len(game_map), h)
        self.assertTrue(all(len(row) == w for row in game_map))
        for x in range(w):
            self.assertEqual(game_map[0][x], WALL)
            self.assertEqual(game_map[h - 1][x], WALL)
        for y in range(h):
            self.assertEqual(game_map[y][0], WALL)
            self.assertEqual(game_map[y][w - 1], WALL)

    @SLOW
    @sizes
    def test_every_room_and_the_stairs_are_reachable(self, w, h, seed):
        game_map, rooms, stairs = build_dungeon(w, h, seed)
        self.assertTrue(rooms)
        start = rooms[0].center()
        self.assertTrue(is_walkable(game_map, *start))
        region = reachable(game_map, start)
        for room in rooms:
            self.assertIn(room.center(), region, f'room at {room.center()} cut off')
        self.assertIn(stairs, region)

    @SLOW
    @sizes
    def test_every_door_sits_in_a_one_tile_gap(self, w, h, seed):
        """A door is flanked by wall on both sides along its wall, and open
        on the other axis -- never on a room's floor."""
        game_map, _, _ = build_dungeon(w, h, seed)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if game_map[y][x] != DOOR:
                    continue
                horizontal = game_map[y][x - 1] == WALL and game_map[y][x + 1] == WALL
                vertical = game_map[y - 1][x] == WALL and game_map[y + 1][x] == WALL
                self.assertTrue(horizontal or vertical, f'door at {(x, y)} not in a wall')


class FovPropertyTests(unittest.TestCase):
    @SLOW
    @given(
        w=st.integers(3, 60),
        h=st.integers(3, 30),
        seed=seeds,
        radius=st.integers(0, 12),
        data=st.data(),
    )
    def test_fov_lights_the_origin_and_nothing_past_the_radius(self, w, h, seed, radius, data):
        game_map, _, _ = build_dungeon(w, h, seed)
        # Any cell at all, walls and corners included: compute_fov must not
        # index off the map from there.
        x = data.draw(st.integers(0, w - 1), label='x')
        y = data.draw(st.integers(0, h - 1), label='y')
        visible = [[False] * w for _ in range(h)]
        compute_fov(game_map, visible, x, y, radius)
        self.assertTrue(visible[y][x])
        for vy in range(h):
            for vx in range(w):
                if visible[vy][vx]:
                    self.assertLessEqual(
                        (vx - x) ** 2 + (vy - y) ** 2,
                        radius * radius,
                        f'{(vx, vy)} lit from {(x, y)} at radius {radius}',
                    )


class LootAndScalingPropertyTests(unittest.TestCase):
    depths = st.integers(-1000, 10**6)

    @given(depth=depths)
    def test_rarity_weights_are_a_valid_distribution(self, depth):
        weights = rarity_weights_for_depth(depth)
        self.assertEqual(len(weights), len(RARITIES))
        self.assertTrue(all(w >= 0 for w in weights), weights)
        self.assertGreater(sum(weights), 0)

    @given(a=depths, b=depths)
    def test_deeper_never_means_worse_loot(self, a, b):
        """The epic share never shrinks as depth grows."""
        shallow, deep = sorted((a, b))
        self.assertLessEqual(
            rarity_weights_for_depth(shallow)[-1], rarity_weights_for_depth(deep)[-1] + 1e-9
        )

    @given(depth=depths, seed=seeds)
    def test_roll_rarity_always_names_a_rarity(self, depth, seed):
        self.assertIn(roll_rarity(depth, random.Random(seed)), RARITIES)

    @given(
        hp=st.integers(1, 500),
        power=st.integers(0, 100),
        a=st.integers(1, 500),
        b=st.integers(1, 500),
    )
    def test_monsters_never_get_weaker_deeper(self, hp, power, a, b):
        shallow, deep = sorted((a, b))
        hp_a, power_a = scale_stats(hp, power, shallow)
        hp_b, power_b = scale_stats(hp, power, deep)
        self.assertGreaterEqual(hp_a, 1)
        self.assertLessEqual(hp_a, hp_b)
        self.assertLessEqual(power_a, power_b)


class SettingsPropertyTests(unittest.TestCase):
    @given(line=st.text())
    def test_parse_line_never_raises(self, line):
        parsed = config.parse_line(line)
        if parsed is not None:
            key, value = parsed
            self.assertTrue(key)
            self.assertFalse(any(c.isspace() for c in key), repr(key))
            self.assertIsInstance(value, str)

    @given(
        values=st.dictionaries(
            st.from_regex(r'[A-Za-z_][A-Za-z0-9_]*', fullmatch=True).filter(
                lambda k: k != 'export'
            ),
            # Quoted, a value keeps everything but line breaks, which end the line.
            st.text(st.characters(exclude_characters='\n\r\x0b\x0c\x1c\x1d\x1e\x85  ')),
        )
    )
    def test_quoted_values_round_trip(self, values):
        text = '\n'.join(f'{key}="{value}"' for key, value in values.items())
        self.assertEqual(config.parse(text), values)

    @given(value=env_text, default=st.integers())
    def test_env_int_never_raises(self, value, default):
        with mock.patch.dict(os.environ, {'PYROGUE_T_PROP': value}):
            result = config.env_int('PYROGUE_T_PROP', default)
        self.assertIsInstance(result, int)


class CameraPropertyTests(unittest.TestCase):
    @given(
        view=st.builds(
            camera.View,
            st.integers(-50, 50),
            st.integers(-50, 50),
            st.integers(1, 80),
            st.integers(1, 40),
        ),
        rect=st.tuples(
            st.integers(-100, 100),
            st.integers(-100, 100),
            st.integers(1, 4000),
            st.integers(1, 3000),
        ),
        cell=st.tuples(st.integers(1, 64), st.integers(1, 64)),
    )
    def test_project_fits_the_view_and_centres_it(self, view, rect, cell):
        cell_w, cell_h, ox, oy = camera.project(view, rect, cell)
        rx, ry, rw, rh = rect
        self.assertGreaterEqual(cell_w, 1)
        self.assertGreaterEqual(cell_h, 1)
        # Unless the rect is too small for even 1 px cells, the view fits.
        if cell_w * view.width > rw or cell_h * view.height > rh:
            self.assertTrue(cell_w == 1 or cell_h == 1, (cell_w, cell_h))
        else:
            cx, cy = view.center
            self.assertAlmostEqual(ox + cx * cell_w, rx + rw / 2, delta=1)
            self.assertAlmostEqual(oy + cy * cell_h, ry + rh / 2, delta=1)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class LogRowsPropertyTests(unittest.TestCase):
    @given(messages=st.lists(st.text()), width=st.integers(-2, 60), rows=st.integers(-2, 14))
    def test_log_fits_its_box(self, messages, width, rows):
        lines = ui.log_rows(messages, width, rows)
        self.assertLessEqual(len(lines), max(rows, 0))
        for line in lines:
            self.assertLessEqual(len(line), width, repr(line))
        if messages and width > 0 and rows > 0:
            self.assertTrue(lines, 'newest message dropped entirely')


class PlaythroughPropertyTests(unittest.TestCase):
    """Random games: the rules hold after every single action."""

    playthroughs = given(
        seed=seeds,
        char_class=st.sampled_from(['warrior', 'archer']),
        actions=st.lists(st.sampled_from(PLAY_ACTIONS), max_size=120),
    )

    def new_game(self, seed, char_class):
        random.seed(seed)
        return GameState(40, 20, char_class=char_class)

    def check_invariants(self, state):
        player = state.player
        self.assertTrue(is_walkable(state.game_map, player.x, player.y), 'player in a wall')
        self.assertLessEqual(player.hp, player.max_hp)
        self.assertEqual(state.game_over, player.hp <= 0)
        self.assertTrue(state.visible[player.y][player.x], 'player not in their own FOV')
        living = [e for e in state.entities if isinstance(e, Monster) and e.alive]
        for monster in living:
            self.assertTrue(
                is_walkable(state.game_map, monster.x, monster.y), f'{monster.name} in a wall'
            )
            self.assertNotEqual(
                (monster.x, monster.y), (player.x, player.y), f'{monster.name} on the player'
            )
        self.assertNotIn(None, state.entities)

    @SLOW
    @playthroughs
    def test_invariants_hold_after_every_action(self, seed, char_class, actions):
        state = self.new_game(seed, char_class)
        self.check_invariants(state)
        for action in actions:
            state.handle_action(action)
            state.end_turn()
            self.check_invariants(state)

    @SLOW
    @playthroughs
    def test_save_and_load_round_trip_any_game(self, seed, char_class, actions):
        state = self.new_game(seed, char_class)
        for action in actions:
            state.handle_action(action)
            state.end_turn()
        assume(not state.game_over)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'save.json')
            save_game(state, path)
            fresh = GameState(40, 20)
            apply_dict(fresh, load_game(path))
        self.assertEqual(state_to_dict(fresh), state_to_dict(state))


if __name__ == '__main__':
    unittest.main()
