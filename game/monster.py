"""Monsters (spec §6, stretch goal #3), plus difficulty scaling and a boss.

Monster.take_turn mirrors the spec's naive AI: chase when the player is
within range, otherwise wander randomly. It returns 'attack' rather than
stepping onto the player's tile; the caller (GameState's monster phase)
resolves the damage, so combat math lives in one place.

Monsters move and strike in the four cardinal directions only, matching the
player's own movement. They used to move and attack diagonally (Chebyshev
adjacency), which let a monster sitting on a diagonal hit a player who had
no legal move to hit back.

Monsters never share a tile: GameState hands take_turn the tiles held by
the player and every other living monster, and a step into one is skipped.
A chasing monster that goes GIVE_UP_AFTER (3) turns in a row without seeing
the player gives up and wanders until it sees the player again.

Difficulty: every 3 floors (a "tier") regular monsters get 1.2x hp and +1
power, compounding (tier 2 is 1.2x *that*, not 1.2x the base). Every 8th
floor also spawns exactly one boss: 2x the hp and 1.5x the power of the
toughest regular monster at that depth's tier, flagged is_boss so GameState
knows to guarantee a rare+ drop on its death.

Who spawns where (one enemy kind per room, pack sizes, the boss room) is
decided by game/spawn.py.
"""

import random

from game.entity import Entity
from game.tiles import is_walkable

# name -> (char, color, hp, power)
MONSTER_TYPES = {
    'goblin': ('g', 2, 12, 2),
    'orc': ('o', 2, 30, 4),
}

# The only steps anything in this game takes. Order is north/south/west/east
# to match state.MOVE_DELTAS; (0, 0) is in the wander set so a monster can
# also just stand still.
ORTHOGONAL_STEPS = ((0, -1), (0, 1), (-1, 0), (1, 0))
WANDER_STEPS = ORTHOGONAL_STEPS + ((0, 0),)

CHASE_RANGE = 8
GIVE_UP_AFTER = 3     # blind chasing turns before a monster gives up
TIER_SIZE = 3           # floors per difficulty tier
TIER_HP_MULT = 1.2
TIER_POWER_BONUS = 1

BOSS_LEVEL_INTERVAL = 8
BOSS_REFERENCE_KIND = 'orc'  # the toughest regular kind; boss stats scale off it
BOSS_HP_MULT = 2.0
BOSS_POWER_MULT = 1.5


def tier_for_depth(depth):
    return (depth - 1) // TIER_SIZE


def scale_stats(base_hp, base_power, depth):
    """Apply this depth's difficulty tier to a base (hp, power) pair."""
    tier = tier_for_depth(depth)
    hp = max(1, round(base_hp * (TIER_HP_MULT ** tier)))
    power = base_power + TIER_POWER_BONUS * tier
    return hp, power


def is_boss_level(depth):
    return depth > 0 and depth % BOSS_LEVEL_INTERVAL == 0


class Monster(Entity):
    def __init__(self, x, y, kind='goblin', depth=1, is_boss=False):
        char, color, base_hp, base_power = MONSTER_TYPES[kind]
        hp, power = scale_stats(base_hp, base_power, depth)
        if is_boss:
            hp = max(1, round(hp * BOSS_HP_MULT))
            power = max(1, round(power * BOSS_POWER_MULT))
            char = char.upper()

        name = f'boss {kind}' if is_boss else kind
        super().__init__(x, y, char, color=color, name=name)
        self.kind = kind
        self.max_hp = hp
        self.hp = hp
        self.power = power
        self.alive = True
        self.is_boss = is_boss
        self.chasing = False   # pursuing the player (see take_turn)
        self.lost_sight = 0    # consecutive chasing turns without sight of the player

    def take_turn(self, player, game_map, occupied=(), sees_player=True):
        """Chase or wander. Returns 'attack' when standing orthogonally
        adjacent to the player, else None after (maybe) taking one step.

        `occupied` is the set of (x, y) tiles this monster may not step onto
        because something else stands there -- other living monsters and the
        player. A step into one is simply not taken (the chase tries its
        other axis first; a wander just stays put), so monsters never stack
        and never swap places.

        `sees_player` is whether the player is in line of sight this turn.
        GameState passes "the monster's tile is in the player's FOV", so a
        monster sees you exactly when you see it. The default (True) keeps
        the old distance-only behaviour for callers that don't track sight.

        Pursuit: a monster starts chasing when it sees the player within
        CHASE_RANGE. Every turn it spends chasing without seeing the player
        counts one toward `lost_sight` (it still steps toward the player on
        that turn); on the GIVE_UP_AFTER-th consecutive blind turn it stops
        pursuing and wanders until it sees the player again. Seeing the
        player resets the count.

        Because both the adjacency test and every step are orthogonal, a
        step can never land on the player's tile: reaching it would mean
        the monster was already adjacent and had returned 'attack'.
        """
        if self.is_adjacent(player):
            self.chasing = True
            self.lost_sight = 0
            return 'attack'

        sees = sees_player and self.distance_to(player) <= CHASE_RANGE
        if sees:
            self.chasing = True
            self.lost_sight = 0
        elif self.chasing:
            self.lost_sight += 1

        if self.chasing:
            step = self._chase_step(player, game_map, occupied)
            if self.lost_sight >= GIVE_UP_AFTER:
                self.chasing = False
                self.lost_sight = 0
        else:
            step = random.choice(WANDER_STEPS)
            if (self.x + step[0], self.y + step[1]) in occupied:
                step = None

        if step is not None:
            self.move(step[0], step[1], game_map)
        return None

    def _chase_step(self, player, game_map, occupied=()):
        """Pick a greedy 4-way step toward the player.

        Closes the larger of the two gaps first and falls back to the other
        axis when that step is walled off or occupied. The old diagonal step
        was rejected outright if either component hit a wall, so a monster
        cut off by a corner just stopped; trying the second axis gets it
        moving again.

        This is still the spec's naive chase, not pathfinding: a monster
        lined up with the player on one axis has no second axis to fall back
        to, so a wall (or another monster) directly between them stalls it
        until the way clears. Returns None in that case, and whenever both
        candidates are blocked.
        """
        dx = (player.x > self.x) - (player.x < self.x)
        dy = (player.y > self.y) - (player.y < self.y)
        if abs(player.x - self.x) >= abs(player.y - self.y):
            candidates = ((dx, 0), (0, dy))
        else:
            candidates = ((0, dy), (dx, 0))

        for sx, sy in candidates:
            tx, ty = self.x + sx, self.y + sy
            if (sx or sy) and is_walkable(game_map, tx, ty) and (tx, ty) not in occupied:
                return (sx, sy)
        return None


def spawn_monsters(rooms, depth=1, rng=random):
    """Every enemy on a floor -- one kind per non-start room, plus the boss
    (and its escort) on a boss floor. The rules live in game/spawn.py; this
    is the old entry point, kept for callers that only want the list."""
    from game.spawn import spawn_level   # spawn imports this module
    return spawn_level(rooms, depth, rng)[0]


def spawn_boss(room, depth, at=None):
    """The boss, standing at `at` or else at the centre of `room` (its
    arena). Stats scale off BOSS_REFERENCE_KIND at this depth."""
    x, y = at if at is not None else room.center()
    return Monster(x, y, BOSS_REFERENCE_KIND, depth=depth, is_boss=True)
