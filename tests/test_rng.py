"""Seeded reproducibility: GameState owns one random generator (state.rng),
built from its `seed`, and every roll of a running game -- level generation,
spawning, chests, shrines, shops, monster AI, crits, dodges, summons, gold --
goes through it. Two games with the same seed and the same actions are the
same game, and a game never touches the global `random` module."""

import random
import unittest
from collections import deque

from game.monster import Monster
from game.state import GameState
from game.tiles import is_walkable

MOVES = ('move_e', 'move_e', 'move_s', 'move_e', 'move_n', 'move_w', 'move_s', 'move_s', 'wait')
STEP_TOWARD = {(1, 0): 'move_e', (-1, 0): 'move_w', (0, 1): 'move_s', (0, -1): 'move_n'}
DESCEND_EVERY = 30
STEPS = 150


def _stairs(state):
    for y, row in enumerate(state.game_map):
        for x, ch in enumerate(row):
            if ch == '>':
                return x, y
    return None


def _first_step_toward(state, goals):
    """The first (dx, dy) of a shortest walk to the nearest tile next to one
    of `goals`, or None if none is reachable."""
    start = (state.player.x, state.player.y)
    first: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in STEP_TOWARD:
            nxt = (x + dx, y + dy)
            if nxt in goals:
                return first[(x, y)] or (dx, dy)
            if nxt not in first and is_walkable(state.game_map, *nxt):
                first[nxt] = first[(x, y)] or (dx, dy)
                queue.append(nxt)
    return None


def _next_action(state, step):
    """A scripted action that depends only on the state, so two identical
    games stay in lockstep: take a chest's first card, leave a shop, hit an
    adjacent monster, walk towards the nearest one (three steps in four), take the stairs every DESCEND_EVERY steps (stepping onto
    them first), else walk a fixed pattern."""
    if state.pending_choice:
        return 'choose_1'
    if state.shop_open:
        return 'skip'
    player = state.player
    monsters = [e for e in state.entities if isinstance(e, Monster) and e.alive]
    for e in monsters:
        if e.is_adjacent(player):
            return STEP_TOWARD[(e.x - player.x, e.y - player.y)]
    if step % DESCEND_EVERY == DESCEND_EVERY - 1:
        stairs = _stairs(state)
        if stairs is not None:
            player.x, player.y = stairs
            return 'descend'
    step_to = _first_step_toward(state, {(m.x, m.y) for m in monsters})
    if step_to is not None and step % 4:
        return STEP_TOWARD[step_to]
    return MOVES[step % len(MOVES)]


def _snapshot(state):
    entities = tuple(
        (
            type(e).__name__,
            e.char,
            e.x,
            e.y,
            getattr(e, 'hp', None),
            getattr(e, 'alive', None),
            getattr(e, 'kind', None),
            getattr(e, 'amount', None),
        )
        for e in state.entities
    )
    return (
        state.depth,
        tuple(''.join(row) for row in state.game_map),
        entities,
        state.player.gold,
        state.player.hp,
        tuple(state.messages),
        state.turn,
    )


def _play(seed):
    """Every snapshot of a scripted game with `seed`."""
    state = GameState(50, 20, seed=seed)
    # Tough enough to live through the whole script, so it keeps fighting.
    state.player.max_hp = state.player.hp = 10_000
    snapshots = [_snapshot(state)]
    for step in range(STEPS):
        if state.game_over:
            break
        state.handle_action(_next_action(state, step))
        state.end_turn()
        snapshots.append(_snapshot(state))
    return state, snapshots


class SeededReproducibilityTest(unittest.TestCase):
    def test_the_same_seed_and_actions_give_the_same_game(self):
        for seed in (2, 3, 2024):
            with self.subTest(seed=seed):
                first, a = _play(seed)
                _, b = _play(seed)
                self.assertEqual(a, b)
                # The script really fought and went down the stairs.
                seen = {m for snap in a for m in snap[5]}
                self.assertTrue(any(m.startswith('You hit') for m in seen))
                self.assertGreater(first.depth, 1)

    def test_a_different_seed_gives_a_different_first_map(self):
        maps = {tuple(''.join(r) for r in GameState(50, 20, seed=s).game_map) for s in range(5)}
        self.assertEqual(len(maps), 5)

    def test_a_game_never_touches_the_global_random_module(self):
        random.seed(99)
        before = random.getstate()
        _play(3)
        self.assertEqual(random.getstate(), before)

    def test_the_state_owns_its_generator(self):
        state = GameState(50, 20, seed=5)
        self.assertIsInstance(state.rng, random.Random)
        self.assertEqual(GameState(50, 20, seed=5).rng.getstate(), state.rng.getstate())


if __name__ == '__main__':
    unittest.main()
