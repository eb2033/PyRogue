"""Items (spec §6, stretch goal #4) plus a gear/rarity system and chests.

Item kinds: potions (drunk on the spot), gear for the equipment slots --
weapon (bonus power) and armor (defense, see ARMOR_DEFENSE) -- and junk (a
dud drop with no stats). Every potion and gear item is tiered Common ->
Uncommon -> Rare -> Epic; rarity drives both the visual color (an int
color-pair number, same convention Entity.color already uses for
players/monsters) and the stat payoff.

Loot no longer sits on the floor as a bare Item: what actually spawns in a
room is a Chest. Its *kind* (potion or gear) is fixed at spawn so the map can
colour it (potion chests pink, gear chests cyan); opening one (walk onto it)
rolls the *rarity* fresh at that moment against the *current depth*, via
`roll_rarity`, so the quality isn't fixed until the player actually gets
there -- and the odds genuinely improve the deeper the run goes (see
`rarity_weights_for_depth`), not just at the moment of spawning.

A potion chest holds one potion, drunk at once. A gear chest holds
GEAR_CHEST_DROPS items, each independently junk (JUNK_CHANCE) or a random
GEAR_KINDS piece, and the player must pick one of them (GameState.choose);
the pick always equips, replacing whatever was in that slot.
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
# Weapon power bonus by rarity.
GEAR_BONUS = {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7}
# Armor defense by rarity. This is the value the damage-reduction system
# reads from player.defense.
ARMOR_DEFENSE = {'common': 3, 'uncommon': 6, 'rare': 12, 'epic': 21}

# Gear kinds a gear-chest drop can be, the player slot each one fills, and
# the rarity -> stat table it uses. Adding a gear kind is data: an entry in
# each of these, plus its GEAR_NAMES and ITEM_CHARS rows.
GEAR_KINDS = ['weapon', 'armor']
GEAR_SLOTS = {'weapon': 'weapon', 'armor': 'armor'}
GEAR_STATS = {'weapon': GEAR_BONUS, 'armor': ARMOR_DEFENSE}

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

# Junk: a dud chest drop. No rarity, no stats; picking it only logs a line.
# Its char is deliberately not in ITEM_CHARS -- junk only ever appears in a
# chest's choice list, never on the map, so it needs no tile.
JUNK = 'junk'
JUNK_NAME = 'Rusty scrap'
JUNK_CHAR = '%'
JUNK_COLOR = 7
# Chance that any one gear-chest drop is junk. Flat: does not scale with depth.
JUNK_CHANCE = 0.15

CHEST_CHAR = '='
CHEST_COLOR = 3         # gear chests: reuses the cyan pair the old flat "item" color used
POTION_CHEST_COLOR = 8  # potion chests: pink (pair 8 in render/curses_render.py)
CHEST_KINDS = ['potion', 'gear']
# How many items a gear chest (and a boss chest) offers to choose from.
GEAR_CHEST_DROPS = 3
BOSS_CHEST_MIN_RARITIES = ['rare', 'epic']
BOSS_CHEST_MIN_WEIGHTS = [0.75, 0.25]

# Spawn rates. Potion chests keep the old per-room rate (the old 50% chest
# chance x 50% potion kind = 0.25 per room past the first, ~1.0 per floor
# with the usual 4-6 rooms). Gear chests are deliberately sparse: at most one
# per floor, placed with this probability, so on average one turns up every
# 2-3 floors (0.4 per floor) whatever the room count. The old rate was ~1.0
# gear chest per floor.
POTION_CHEST_CHANCE_PER_ROOM = 0.25
GEAR_CHEST_CHANCE_PER_FLOOR = 0.4


def rarity_weights_for_depth(depth):
    t = min(1.0, max(0.0, (depth - 1) / (MAX_SCALING_DEPTH - 1)))
    return [shallow + (deep - shallow) * t
            for shallow, deep in zip(RARITY_WEIGHTS_SHALLOW, RARITY_WEIGHTS_DEEP)]


def roll_rarity(depth=1, rng=random):
    return rng.choices(RARITIES, weights=rarity_weights_for_depth(depth))[0]


def roll_kind(rng=random):
    """Potion or gear, 50/50. Only used for a chest loaded from a save that
    predates chest kinds; new chests get their kind from spawn_chests."""
    return rng.choice(CHEST_KINDS)


def roll_gear_drop(depth=1, rng=random):
    """One gear-chest drop: junk with JUNK_CHANCE, else a random GEAR_KINDS
    piece at a depth-scaled rarity."""
    if rng.random() < JUNK_CHANCE:
        return Item(0, 0, JUNK)
    return Item(0, 0, rng.choice(GEAR_KINDS), roll_rarity(depth, rng))


def roll_boss_drop(rng=random):
    """One boss-chest drop: always gear, always rare or epic, never junk."""
    rarity = rng.choices(BOSS_CHEST_MIN_RARITIES, weights=BOSS_CHEST_MIN_WEIGHTS)[0]
    return Item(0, 0, rng.choice(GEAR_KINDS), rarity)


class Item(Entity):
    def __init__(self, x, y, kind='potion', rarity='common'):
        if kind == JUNK:
            # Junk has no rarity and no stats, whatever rarity was passed.
            super().__init__(x, y, JUNK_CHAR, color=JUNK_COLOR, name=JUNK_NAME)
            self.kind = kind
            self.rarity = None
            self.bonus = None
            return
        if rarity not in RARITIES:
            raise ValueError(f'unknown rarity: {rarity!r}')
        char = ITEM_CHARS[kind]
        if kind == 'potion':
            name = POTION_NAMES[rarity]
            self.bonus = None
        else:
            name = GEAR_NAMES[(kind, rarity)]
            self.bonus = GEAR_STATS[kind][rarity]
        super().__init__(x, y, char, color=RARITY_COLOR[rarity], name=name)
        self.kind = kind
        self.rarity = rarity

    @property
    def is_gear(self):
        return self.kind in GEAR_SLOTS

    def apply(self, player, log):
        """Use the item on the player: drink a potion, equip gear into its
        slot (always -- the old piece is replaced and discarded), or, for
        junk, just log it."""
        if self.kind == JUNK:
            log(f'You toss the {self.name} aside. Worthless.')
            return

        if self.kind == 'potion':
            healed = min(POTION_HEAL[self.rarity], player.max_hp - player.hp)
            player.hp += healed
            player.inventory.append(self.name)
            log(f'You drink a {self.name} and recover {healed} HP.')
            return

        slot = GEAR_SLOTS[self.kind]
        old = getattr(player, slot)
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
    """A sealed container. Its kind ('potion' or 'gear') is fixed at spawn
    so the renderer can tell potion chests from gear chests by colour. What
    is inside isn't rolled until opened -- fresh against the depth it's
    opened at, so "the deeper you go the better the loot" holds for a chest
    you find early but open late, too.

    `guaranteed_min_rarity='rare'` marks a boss chest: a gear chest whose
    drops are all rare-or-epic gear regardless of depth, with no junk
    (spec-follow-up: "guaranteed rare drop").
    """

    def __init__(self, x, y, guaranteed_min_rarity=None, kind=None, rng=random):
        if kind is None:
            kind = 'gear' if guaranteed_min_rarity else roll_kind(rng)
        elif kind in GEAR_SLOTS:
            kind = 'gear'  # a save from when gear chests were 'weapon'/'armor'
        color = POTION_CHEST_COLOR if kind == 'potion' else CHEST_COLOR
        super().__init__(x, y, CHEST_CHAR, color=color, name='chest')
        self.guaranteed_min_rarity = guaranteed_min_rarity
        self.kind = kind

    @property
    def offers_choice(self):
        """True if opening this chest asks the player to pick one item."""
        return self.kind != 'potion'

    def open(self, depth, rng=random):
        """Roll the contents. Returns a list of Items: one potion for a
        potion chest, GEAR_CHEST_DROPS choices for a gear or boss chest."""
        if self.kind == 'potion':
            return [Item(self.x, self.y, 'potion', roll_rarity(depth, rng))]
        if self.guaranteed_min_rarity == 'rare':
            return [roll_boss_drop(rng) for _ in range(GEAR_CHEST_DROPS)]
        return [roll_gear_drop(depth, rng) for _ in range(GEAR_CHEST_DROPS)]


def _place_chest(room, kind, occupied, rng):
    for _ in range(10):  # a few tries to avoid stacking
        x = rng.randint(room.x1, room.x2 - 1)
        y = rng.randint(room.y1, room.y2 - 1)
        if (x, y) not in occupied:
            occupied.add((x, y))
            return Chest(x, y, kind=kind, rng=rng)
    return None


def spawn_chests(rooms, rng=random):
    """Chests for a fresh level, never in rooms[0] (the player's start): a
    potion chest per room with POTION_CHEST_CHANCE_PER_ROOM, and at most one
    gear chest per floor with GEAR_CHEST_CHANCE_PER_FLOOR."""
    chests = []
    occupied = set()
    candidates = rooms[1:]
    for room in candidates:
        if rng.random() < POTION_CHEST_CHANCE_PER_ROOM:
            chest = _place_chest(room, 'potion', occupied, rng)
            if chest is not None:
                chests.append(chest)
    if candidates and rng.random() < GEAR_CHEST_CHANCE_PER_FLOOR:
        chest = _place_chest(rng.choice(candidates), 'gear', occupied, rng)
        if chest is not None:
            chests.append(chest)
    return chests


def spawn_boss_chest(x, y):
    """Guaranteed rare-or-better gear chest for a defeated boss
    (spec-follow-up): three rare/epic choices, no junk."""
    return Chest(x, y, guaranteed_min_rarity='rare', kind='gear')
