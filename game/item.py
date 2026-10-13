"""Items (spec §6, stretch goal #4) plus a gear/rarity system and chests.

Three item kinds: potions (consumed on pickup), and two equipment slots --
weapon (bonus power) and armor (bonus defense) -- that auto-equip on pickup
when they beat what is already in that slot, and are left behind otherwise. Every kind is tiered Common -> Uncommon
-> Rare -> Epic; rarity drives both the visual color (an int color-pair
number, same convention Entity.color already uses for players/monsters) and
the stat payoff.

Loot no longer sits on the floor as a bare Item: what actually spawns in a
room is a Chest. Its *kind* is fixed at spawn so the map can colour it
(potion chests pink, gear chests cyan); opening one (walk onto it) rolls the
*rarity* fresh at that moment against the *current depth*, via `roll_rarity`,
so the quality isn't fixed until the player actually gets there -- and the odds genuinely
improve the deeper the run goes (see `rarity_weights_for_depth`), not just
at the moment of spawning.
"""

import random

from game.entity import Entity

RARITIES = ['common', 'uncommon', 'rare', 'epic']

# Loot quality scales with depth: interpolate linearly from the depth-1
# weights to the depth-MAX_SCALING_DEPTH weights, then hold steady past that
# so it doesn't run away to "everything is epic" on an endless run.
RARITY_WEIGHTS_SHALLOW = [0.60, 0.25, 0.12, 0.03]
RARITY_WEIGHTS_DEEP = [0.10, 0.25, 0.35, 0.30]
MAX_SCALING_DEPTH = 20

# Rarity -> curses color-pair number. Pairs 4-7 are reserved for this in
# render/curses_render.py's COLOR_PAIRS table.
RARITY_COLOR = {'common': 7, 'uncommon': 4, 'rare': 5, 'epic': 6}

POTION_HEAL = {'common': 8, 'uncommon': 14, 'rare': 22, 'epic': 35}
GEAR_BONUS = {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7}

GEAR_NAMES = {
    ('weapon', 'common'): 'Rusty Dagger',
    ('weapon', 'uncommon'): 'Iron Sword',
    ('weapon', 'rare'): 'Steel Blade',
    ('weapon', 'epic'): 'Dragon Fang',
    ('armor', 'common'): 'Cloth Vest',
    ('armor', 'uncommon'): 'Leather Armor',
    ('armor', 'rare'): 'Chainmail',
    ('armor', 'epic'): 'Plate of the Ancients',
}
POTION_NAMES = {
    'common': 'potion of healing',
    'uncommon': 'greater potion of healing',
    'rare': 'superior potion of healing',
    'epic': 'elixir of vitality',
}
ITEM_CHARS = {'potion': '!', 'weapon': '/', 'armor': '['}
ITEM_KIND_WEIGHTS = {'potion': 0.5, 'weapon': 0.25, 'armor': 0.25}

CHEST_CHAR = '='
CHEST_COLOR = 3         # gear chests: reuses the cyan pair the old flat "item" color used
POTION_CHEST_COLOR = 8  # potion chests: pink (pair 8 in render/curses_render.py)
BOSS_CHEST_MIN_RARITIES = ['rare', 'epic']
BOSS_CHEST_MIN_WEIGHTS = [0.75, 0.25]


def rarity_weights_for_depth(depth):
    t = min(1.0, max(0.0, (depth - 1) / (MAX_SCALING_DEPTH - 1)))
    return [shallow + (deep - shallow) * t
            for shallow, deep in zip(RARITY_WEIGHTS_SHALLOW, RARITY_WEIGHTS_DEEP)]


def roll_rarity(depth=1, rng=random):
    return rng.choices(RARITIES, weights=rarity_weights_for_depth(depth))[0]


def roll_kind(rng=random):
    return rng.choices(list(ITEM_KIND_WEIGHTS), weights=list(ITEM_KIND_WEIGHTS.values()))[0]


class Item(Entity):
    def __init__(self, x, y, kind='potion', rarity='common'):
        if rarity not in RARITIES:
            raise ValueError(f'unknown rarity: {rarity!r}')
        char = ITEM_CHARS[kind]
        if kind == 'potion':
            name = POTION_NAMES[rarity]
            self.bonus = None
        else:
            name = GEAR_NAMES[(kind, rarity)]
            self.bonus = GEAR_BONUS[rarity]
        super().__init__(x, y, char, color=RARITY_COLOR[rarity], name=name)
        self.kind = kind
        self.rarity = rarity

    def apply(self, player, log):
        if self.kind == 'potion':
            healed = min(POTION_HEAL[self.rarity], player.max_hp - player.hp)
            player.hp += healed
            player.inventory.append(self.name)
            log(f'You drink a {self.name} and recover {healed} HP.')
            return

        slot = 'weapon' if self.kind == 'weapon' else 'armor'
        old = getattr(player, slot)
        if old is not None and old.bonus >= self.bonus:
            log(f'You leave the {self.name} ({self.rarity}); '
                f'your {old.name} is better.')
            return
        setattr(player, slot, self)
        if slot == 'weapon':
            player.power = player.base_power + self.bonus
        else:
            player.defense = self.bonus
        player.inventory.append(self.name)
        if old is not None:
            log(f'You swap {old.name} for {self.name} ({self.rarity}).')
        else:
            log(f'You equip {self.name} ({self.rarity}).')


class Chest(Entity):
    """A sealed container. Its kind (potion/weapon/armor) is rolled at spawn
    so the renderer can tell potion chests from gear chests by colour. Its
    rarity isn't rolled until opened -- fresh against the depth it's opened
    at, so "the deeper you go the better the loot" holds for a chest you find
    early but open late, too.

    `guaranteed_min_rarity='rare'` marks a boss chest: it always contains
    rare-or-epic gear regardless of depth (spec-follow-up: "guaranteed rare
    drop"), rather than using the normal depth-scaled table.
    """

    def __init__(self, x, y, guaranteed_min_rarity=None, kind=None, rng=random):
        if kind is None:
            kind = roll_kind(rng)
        color = POTION_CHEST_COLOR if kind == 'potion' else CHEST_COLOR
        super().__init__(x, y, CHEST_CHAR, color=color, name='chest')
        self.guaranteed_min_rarity = guaranteed_min_rarity
        self.kind = kind

    def open(self, depth, rng=random):
        kind = self.kind
        if self.guaranteed_min_rarity == 'rare':
            rarity = rng.choices(BOSS_CHEST_MIN_RARITIES, weights=BOSS_CHEST_MIN_WEIGHTS)[0]
        else:
            rarity = roll_rarity(depth, rng)
        return Item(self.x, self.y, kind, rarity)


def spawn_chests(rooms, rng=random):
    chests = []
    occupied = set()
    for room in rooms[1:]:
        if rng.random() < 0.5:
            for _ in range(10):  # a few tries to avoid stacking
                x = rng.randint(room.x1, room.x2 - 1)
                y = rng.randint(room.y1, room.y2 - 1)
                if (x, y) not in occupied:
                    occupied.add((x, y))
                    chests.append(Chest(x, y, rng=rng))
                    break
    return chests


def spawn_boss_chest(x, y):
    """Guaranteed rare-or-better chest for a defeated boss (spec-follow-up)."""
    return Chest(x, y, guaranteed_min_rarity='rare')
