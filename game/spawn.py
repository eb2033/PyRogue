"""Which enemies a floor gets, and where they stand.

The rules are data (SPAWN_RULES, BOSS_ESCORTS) so a new enemy kind is a new
row rather than new code. Shared code enforces the two invariants:

* **One enemy kind per room.** Every room except rooms[0] (the player's
  start) gets exactly one pack, picked from the rules that cover the depth,
  weighted by `weight`. Rooms[0] gets nothing.
* **Spread packs.** A rule with `spread=True` never puts two of its members
  next to each other, diagonals included (Chebyshev distance >= 2).

Boss floors (monster.is_boss_level) put the boss at the centre of one
non-start room -- the "boss arena" -- with whatever BOSS_ESCORTS lists for
that depth orthogonally adjacent to it, and no regular pack in that room.
Every other room on a boss floor follows the normal rules for its depth.

Standard library only, like the rest of game/.
"""

import random
from collections import namedtuple
from typing import cast

from game.level import free_tiles, room_tiles
from game.monster import (
    BOSS_LEVEL_INTERVAL,
    ORTHOGONAL_STEPS,
    SLIME_BANDS,
    Monster,
    is_boss_level,
    spawn_boss,
)
from game.rng import Rng

FIRST_BOSS_DEPTH = BOSS_LEVEL_INTERVAL

GOBLIN_PACK_MAX = 5
# (first floor, pack size) steps: 1 on floors 1-4, 2 on 5-7, 3 on 8-10, 4 on 11-12, 5 from 13.
GOBLIN_PACK_STEPS = ((1, 1), (5, 2), (8, 3), (11, 4), (13, 5))
# Goblin archers start on floor 4: 1 on floors 4-7, 2 on 8-11, 3 from 12.
ARCHER_PACK_STEPS = ((4, 1), (8, 2), (12, 3))


def _step_size(steps, depth):
    size = steps[0][1]
    for first, n in steps:
        if depth >= first:
            size = n
    return size


def goblin_pack_size(depth):
    """1 on floors 1-4, 2 on 5-7, 3 on 8-10, 4 on 11-12, 5 from 13 (capped)."""
    return min(GOBLIN_PACK_MAX, _step_size(GOBLIN_PACK_STEPS, depth))


def goblin_archer_pack_size(depth):
    """1 on floors 4-7, 2 on 8-11, 3 from 12."""
    return _step_size(ARCHER_PACK_STEPS, depth)


def _slime_bands():
    """(kind, first floor, last floor or None) for each of
    monster.SLIME_BANDS: a band runs to the floor before the next one starts."""
    starts = [first for first, _ in SLIME_BANDS[1:]] + [None]
    return [
        (kind, first, None if nxt is None else nxt - 1)
        for (first, kind), nxt in zip(SLIME_BANDS, starts, strict=True)
    ]


# kind: a monster.MONSTER_TYPES key. min_depth/max_depth: inclusive range
# (max_depth None = no upper bound). count: depth -> pack size. weight:
# relative chance among the rules that cover a depth. spread: members are
# never adjacent, diagonals included.
SpawnRule = namedtuple('SpawnRule', 'kind min_depth max_depth count weight spread')

SPAWN_RULES = (
    SpawnRule('goblin', 1, None, goblin_pack_size, 1, False),
    # Before (and on) the first boss floor an orc comes alone...
    SpawnRule('orc', 1, FIRST_BOSS_DEPTH, lambda depth: 1, 1, True),
    # ...after it, in a pair that never stands side by side.
    SpawnRule('orc', FIRST_BOSS_DEPTH + 1, None, lambda depth: 2, 1, True),
    # A goblin archer shoots from range; from floor 4 on, in a spread pack.
    SpawnRule('goblin_archer', 4, None, goblin_archer_pack_size, 1, True),
    # A lone slime, its size by floor (one rule per monster.SLIME_BANDS band):
    # it splits on death.
    *(
        SpawnRule(kind, first, last, lambda depth: 1, 1, True)
        for kind, first, last in _slime_bands()
    ),
)

# Boss depth -> (kind, count) standing guard beside the boss. Boss floors
# not listed here have the boss alone.
BOSS_ESCORTS = {
    FIRST_BOSS_DEPTH: ('orc', 1),
}


def rules_for_depth(depth, rules=SPAWN_RULES):
    return [
        r for r in rules if r.min_depth <= depth and (r.max_depth is None or depth <= r.max_depth)
    ]


def choose_rule(depth, rng: Rng = random, rules=SPAWN_RULES):
    """The one pack a room gets at this depth, or None if no rule covers it."""
    options = rules_for_depth(depth, rules)
    if not options:
        return None
    return rng.choices(options, weights=[r.weight for r in options])[0]


def _chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def pick_tiles(room, count, rng: Rng = random, occupied=(), spread=False):
    """Up to `count` free tiles of `room`. With spread=True no two picked
    tiles touch, diagonals included. Fewer come back only if the room cannot
    hold them (never for a 4x4+ room and a pack of 3 or less)."""
    free = free_tiles(room, occupied)
    rng.shuffle(free)
    picked = []
    for tile in free:
        if len(picked) == count:
            break
        if spread and any(_chebyshev(tile, p) < 2 for p in picked):
            continue
        picked.append(tile)
    return picked


def spawn_pack(room, rule, depth, rng: Rng = random, occupied=None):
    """One rule's pack in one room. Adds the tiles it uses to `occupied`."""
    occupied = set() if occupied is None else occupied
    tiles = pick_tiles(room, rule.count(depth), rng, occupied, spread=rule.spread)
    occupied.update(tiles)
    return [Monster(x, y, rule.kind, depth=depth) for x, y in tiles]


def spawn_boss_room(room, depth, rng: Rng = random, occupied=None):
    """The boss at room.center(), plus BOSS_ESCORTS[depth] orthogonally
    adjacent to it. Adds the tiles used to `occupied`."""
    occupied = set() if occupied is None else occupied
    cx, cy = room.center()
    if (cx, cy) in occupied:  # only on a one-room map, where it is the player's tile
        free = [
            t
            for t in room_tiles(room)
            if t not in occupied and min(_chebyshev(t, o) for o in occupied) >= 2
        ]
        free = free or free_tiles(room, occupied)
        cx, cy = rng.choice(free) if free else (cx, cy)
    boss = spawn_boss(room, depth, at=(cx, cy))
    occupied.add((cx, cy))
    monsters = [boss]

    kind, count = BOSS_ESCORTS.get(depth, (None, 0))
    if count:
        spots = [(cx + dx, cy + dy) for dx, dy in ORTHOGONAL_STEPS]
        spots = [
            s
            for s in spots
            if room.x1 <= s[0] < room.x2 and room.y1 <= s[1] < room.y2 and s not in occupied
        ]
        rng.shuffle(spots)
        for x, y in spots[:count]:
            occupied.add((x, y))
            monsters.append(Monster(x, y, cast(str, kind), depth=depth))
    return monsters


def pick_boss_room(rooms, depth, rng: Rng = random):
    """The boss arena on a boss floor (any room but rooms[0], unless it is
    the only one), else None."""
    if not is_boss_level(depth):
        return None
    return rng.choice(rooms[1:]) if len(rooms) > 1 else rooms[-1]


def spawn_level(
    rooms, depth, rng: Rng = random, rules=SPAWN_RULES, exclude=(), boss_room=None, occupied=None
):
    """Every enemy on a floor. Returns (monsters, boss_room), boss_room being
    None off boss floors. Rooms in `exclude` (the shop's) get no enemies. A
    caller that must know the boss room before spawning (to keep the shop out
    of it) picks it with pick_boss_room and passes it in; left None, it is
    picked here (and stays None off boss floors).

    `occupied` is the floor's shared occupancy set (game/level.py): tiles
    already taken, which no monster is put on, and to which every monster's
    tile is added, so the spawners after this one (chests, the shrine) keep
    off them. Left None, it starts as the player's start tile alone."""
    if occupied is None:
        occupied = {rooms[0].center()}  # the player's start tile
    if boss_room is None:
        boss_room = pick_boss_room(rooms, depth, rng)

    monsters = []
    for room in rooms[1:]:
        if room is boss_room or any(room is ex for ex in exclude):
            continue
        rule = choose_rule(depth, rng, rules)
        if rule is not None:
            monsters += spawn_pack(room, rule, depth, rng, occupied)
    if boss_room is not None:
        monsters += spawn_boss_room(boss_room, depth, rng, occupied)
    return monsters, boss_room
