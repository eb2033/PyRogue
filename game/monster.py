"""Monsters (spec §6, stretch goal #3), plus difficulty scaling and a boss.

Monster.take_turn mirrors the spec's naive AI: chase when the player is
within range, otherwise wander randomly. It returns 'attack' rather than
stepping onto the player's tile; the caller (GameState's monster phase)
resolves the damage, so combat math lives in one place.

Monsters move and strike in the four cardinal directions only, matching the
player's own movement. They used to move and attack diagonally (Chebyshev
adjacency), which let a monster sitting on a diagonal hit a player who had
no legal move to hit back.

Difficulty: every 3 floors (a "tier") regular monsters get 1.2x hp and +1
power, compounding (tier 2 is 1.2x *that*, not 1.2x the base). Every 8th
floor also spawns exactly one boss: 2x the hp and 1.5x the power of the
toughest regular monster at that depth's tier, flagged is_boss so GameState
knows to guarantee a rare+ drop on its death.
"""

import random

from game.entity import Entity
from game.tiles import is_walkable

# name -> (char, color, hp, power)
MONSTER_TYPES = {
    'goblin': ('g', 2, 5, 2),
    'orc': ('o', 2, 8, 4),
}

# The only steps anything in this game takes. Order is north/south/west/east
# to match state.MOVE_DELTAS; (0, 0) is in the wander set so a monster can
# also just stand still.
ORTHOGONAL_STEPS = ((0, -1), (0, 1), (-1, 0), (1, 0))
WANDER_STEPS = ORTHOGONAL_STEPS + ((0, 0),)

CHASE_RANGE = 8
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

    def take_turn(self, player, game_map):
        """Chase or wander. Returns 'attack' when standing orthogonally
        adjacent to the player, else None after (maybe) taking one step.

        Because both the adjacency test and every step are orthogonal, a
        step can never land on the player's tile: reaching it would mean
        the monster was already adjacent and had returned 'attack'.
        """
        if self.is_adjacent(player):
            return 'attack'

        if self.distance_to(player) <= CHASE_RANGE:
            step = self._chase_step(player, game_map)
        else:
            step = random.choice(WANDER_STEPS)

        if step is not None:
            self.move(step[0], step[1], game_map)
        return None

    def _chase_step(self, player, game_map):
        """Pick a greedy 4-way step toward the player.

        Closes the larger of the two gaps first and falls back to the other
        axis when that step is walled off. The old diagonal step was rejected
        outright if either component hit a wall, so a monster cut off by a
        corner just stopped; trying the second axis gets it moving again.

        This is still the spec's naive chase, not pathfinding: a monster
        lined up with the player on one axis has no second axis to fall back
        to, so a wall directly between them stalls it until the player moves.
        Returns None in that case, and whenever both candidates are blocked.
        """
        dx = (player.x > self.x) - (player.x < self.x)
        dy = (player.y > self.y) - (player.y < self.y)
        if abs(player.x - self.x) >= abs(player.y - self.y):
            candidates = ((dx, 0), (0, dy))
        else:
            candidates = ((0, dy), (dx, 0))

        for sx, sy in candidates:
            if (sx or sy) and is_walkable(game_map, self.x + sx, self.y + sy):
                return (sx, sy)
        return None


def spawn_monsters(rooms, depth=1, rng=random):
    """One roll per room (skipping the player's starting room) for 0-2 monsters."""
    monsters = []
    occupied = set()
    for room in rooms[1:]:
        count = rng.choice([0, 0, 1, 1, 2])
        for _ in range(count):
            kind = rng.choice(list(MONSTER_TYPES))
            for _ in range(10):  # a few tries to avoid stacking
                x = rng.randint(room.x1, room.x2 - 1)
                y = rng.randint(room.y1, room.y2 - 1)
                if (x, y) not in occupied:
                    occupied.add((x, y))
                    monsters.append(Monster(x, y, kind, depth=depth))
                    break
    return monsters


def spawn_boss(rooms, depth, rng=random):
    """One boss, placed in a room other than the player's start when possible."""
    room = rng.choice(rooms[1:]) if len(rooms) > 1 else rooms[-1]
    x = rng.randint(room.x1, room.x2 - 1)
    y = rng.randint(room.y1, room.y2 - 1)
    return Monster(x, y, BOSS_REFERENCE_KIND, depth=depth, is_boss=True)
