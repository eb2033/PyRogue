"""Items (spec §6, stretch goal #4) plus a gear/rarity system and chests.

Item kinds: potions (drunk on the spot), gear for the equipment slots --
the weapon slot (bonus power: the plain 'weapon' kind and the six
WEAPON_TYPES, each with a special effect from WEAPON_EFFECTS) and armor
(defense, see ARMOR_DEFENSE) -- and junk (a dud drop with no stats). Every potion and gear item is tiered Common ->
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

A potion chest holds one potion, drunk at once when the player is hurt, or
put on the potion belt (BELT_SLOTS) at full HP. A gear chest holds
GEAR_CHEST_DROPS items, each independently junk (JUNK_CHANCE) or a random
GEAR_KINDS piece, and the player must pick one of them (GameState.choose);
the pick always equips, replacing whatever was in that slot.
"""

import random
from typing import cast

from game.entity import Entity
from game.rng import Rng
from game.shrine import boon_total, heal_multiplier

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

POTION_HEAL = {'common': 20, 'uncommon': 35, 'rare': 55, 'epic': 88}
# The potion belt (GameState.belt): potions picked up at full HP wait here,
# in order. Only the first is drinkable ('h'); the rest shift up after it.
# A shrine's Quick hands boon adds a slot: see belt_capacity.
BELT_SLOTS = 3
# Weapon power bonus by rarity.
GEAR_BONUS = {'common': 1, 'uncommon': 2, 'rare': 4, 'epic': 7}
# Armor defense by rarity. This is the value the damage-reduction system
# reads from player.defense.
ARMOR_DEFENSE = {'common': 3, 'uncommon': 6, 'rare': 12, 'epic': 21}

# The six weapon types (each fills the weapon slot). Their damage bonus is the
# GEAR_BONUS table plus a per-kind offset; their special effect is data in
# WEAPON_EFFECTS below. The plain 'weapon' kind is the original sword line
# with no effect (old saves hold it, and it still drops).
WEAPON_TYPES = ['war_axe', 'rapier', 'great_sword', 'sword_shield', 'dagger', 'spear']
WEAPON_DAMAGE_OFFSET = {
    'war_axe': -1,
    'rapier': -2,
    'great_sword': 1,
    'sword_shield': 0,
    'dagger': -1,
    'spear': 0,
}
AXE_MAX_HP = {'common': 3, 'uncommon': 6, 'rare': 9, 'epic': 15}
# The requested 1/2/3 shield defense, x3 for the ARMOR_DEFENSE rescale, with
# epic continuing the step as the 4th value.
SHIELD_DEFENSE = {'common': 3, 'uncommon': 6, 'rare': 9, 'epic': 12}
# Added to the player's crit chance (game.state.crit_chance), capped at 1.0 there.
DAGGER_CRIT = {'common': 0.05, 'uncommon': 0.10, 'rare': 0.15, 'epic': 0.20}
RAPIER_STRIKES = 2
SPEAR_REACH = 2
# Whatever the weapon's bonus, the player's power never drops below this.
MIN_POWER = 1

# What a weapon does beyond its damage bonus. Every Item carries all of
# these attributes (EFFECT_DEFAULTS for anything not listed), so code reads
# player.weapon.reach and friends directly. A value is either a constant or a
# rarity table. Effects come from (kind, rarity) when the Item is built, so
# a save only needs the kind and rarity.
EFFECT_DEFAULTS = {
    'max_hp_bonus': 0,
    'strikes': 1,
    'cleave': False,
    'defense_bonus': 0,
    'crit_bonus': 0.0,
    'reach': 1,
}
WEAPON_EFFECTS = {
    'war_axe': {'max_hp_bonus': AXE_MAX_HP},
    'rapier': {'strikes': RAPIER_STRIKES},
    'great_sword': {'cleave': True},
    'sword_shield': {'defense_bonus': SHIELD_DEFENSE},
    'dagger': {'crit_bonus': DAGGER_CRIT},
    'spear': {'reach': SPEAR_REACH},
}

# Gear kinds, the player slot each one fills, and the rarity -> stat table it
# uses (for anything in the weapon slot, the stat is its power bonus). Adding
# a gear kind is data: an entry in each of these, plus its GEAR_NAMES and
# ITEM_CHARS rows.
GEAR_KINDS = ['weapon', 'armor'] + WEAPON_TYPES
GEAR_SLOTS = {'weapon': 'weapon', 'armor': 'armor'}
GEAR_SLOTS.update({kind: 'weapon' for kind in WEAPON_TYPES})
GEAR_STATS = {'weapon': GEAR_BONUS, 'armor': ARMOR_DEFENSE}
GEAR_STATS.update(
    {
        kind: {r: GEAR_BONUS[r] + WEAPON_DAMAGE_OFFSET[kind] for r in RARITIES}
        for kind in WEAPON_TYPES
    }
)

# The kinds a gear-chest (or boss-chest) drop can be. The plain 'weapon' is
# not among them: it is the starting weapon every run begins with (see
# GameState), so it never drops. Armor's share of drops is ARMOR_DROP_CHANCE;
# the rest are weapons, split evenly across WEAPON_TYPES (roll_gear_kind).
GEAR_DROP_KINDS = ['armor'] + WEAPON_TYPES
# The starting weapon, equipped at the start of every run.
STARTING_WEAPON_RARITY = 'common'

GEAR_NAMES = {
    ('weapon', 'common'): 'Rusty Dagger',
    ('weapon', 'uncommon'): 'Iron Sword',
    ('weapon', 'rare'): 'Steel Blade',
    ('weapon', 'epic'): 'Dragon Fang',
    ('armor', 'common'): 'Cloth Vest',
    ('armor', 'uncommon'): 'Leather Armor',
    ('armor', 'rare'): 'Chainmail',
    ('armor', 'epic'): 'Plate of the Ancients',
    ('war_axe', 'common'): 'Worn War Axe',
    ('war_axe', 'uncommon'): 'Iron War Axe',
    ('war_axe', 'rare'): 'Steel War Axe',
    ('war_axe', 'epic'): 'Skullsplitter Axe',
    ('rapier', 'common'): 'Bent Rapier',
    ('rapier', 'uncommon'): 'Iron Rapier',
    ('rapier', 'rare'): "Duelist's Rapier",
    ('rapier', 'epic'): 'Whisperthorn Rapier',
    ('great_sword', 'common'): 'Notched Great Sword',
    ('great_sword', 'uncommon'): 'Iron Great Sword',
    ('great_sword', 'rare'): 'Steel Great Sword',
    ('great_sword', 'epic'): 'Oathbreaker Great Sword',
    ('sword_shield', 'common'): 'Sword & Buckler',
    ('sword_shield', 'uncommon'): 'Sword & Shield',
    ('sword_shield', 'rare'): "Knight's Sword & Shield",
    ('sword_shield', 'epic'): 'Aegis Sword & Shield',
    ('dagger', 'common'): 'Chipped Dagger',
    ('dagger', 'uncommon'): 'Iron Dagger',
    ('dagger', 'rare'): "Assassin's Dagger",
    ('dagger', 'epic'): 'Nightfang Dagger',
    ('spear', 'common'): 'Wooden Spear',
    ('spear', 'uncommon'): 'Iron Spear',
    ('spear', 'rare'): 'Steel Spear',
    ('spear', 'epic'): 'Skypiercer Spear',
}
POTION_NAMES = {
    'common': 'potion of healing',
    'uncommon': 'greater potion of healing',
    'rare': 'superior potion of healing',
    'epic': 'elixir of vitality',
}
# The weapon types never lie on the map (they only appear in a chest's
# choice), but share the weapon glyph so every Item still has a tiled char.
ITEM_CHARS = {'potion': '!', 'weapon': '/', 'armor': '['}
ITEM_CHARS.update({kind: '/' for kind in WEAPON_TYPES})

# Junk: a dud chest drop. No rarity, no stats; picking it only logs a line.
# Its char is deliberately not in ITEM_CHARS -- junk only ever appears in a
# chest's choice list, never on the map, so it needs no tile.
JUNK = 'junk'
JUNK_NAME = 'Rusty scrap'
JUNK_CHAR = '%'
JUNK_COLOR = 7
# Chance that any one gear-chest drop is junk. Flat: does not scale with depth.
JUNK_CHANCE = 0.15
# Share of every drop (junk not counted separately, boss drops included) that
# is armor. Armor is the more impactful drop, so it gets a fixed 20%; the
# remainder of non-junk drops are weapons.
ARMOR_DROP_CHANCE = 0.20

CHEST_CHAR = '='
CHEST_COLOR = 3  # gear chests: reuses the cyan pair the old flat "item" color used
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
    return [
        shallow + (deep - shallow) * t
        for shallow, deep in zip(RARITY_WEIGHTS_SHALLOW, RARITY_WEIGHTS_DEEP)
    ]


def roll_rarity(depth=1, rng: Rng = random):
    return rng.choices(RARITIES, weights=rarity_weights_for_depth(depth))[0]


def roll_kind(rng: Rng = random):
    """Potion or gear, 50/50. Only used for a chest loaded from a save that
    predates chest kinds; new chests get their kind from spawn_chests."""
    return rng.choice(CHEST_KINDS)


def roll_gear_kind(armor_chance, rng: Rng = random):
    """Armor with probability armor_chance, otherwise a weapon type picked evenly."""
    if rng.random() < armor_chance:
        return 'armor'
    return rng.choice(WEAPON_TYPES)


def roll_gear_drop(depth=1, rng: Rng = random):
    """One gear-chest drop: junk with JUNK_CHANCE, else a gear piece at a
    depth-scaled rarity. Armor is ARMOR_DROP_CHANCE of ALL drops, so among the
    non-junk ones it is ARMOR_DROP_CHANCE / (1 - JUNK_CHANCE)."""
    if rng.random() < JUNK_CHANCE:
        return Item(0, 0, JUNK)
    armor_of_gear = ARMOR_DROP_CHANCE / (1 - JUNK_CHANCE)
    return Item(0, 0, roll_gear_kind(armor_of_gear, rng), roll_rarity(depth, rng))


def roll_boss_drop(rng: Rng = random):
    """One boss-chest drop: always gear, always rare or epic, never junk, so
    armor is ARMOR_DROP_CHANCE of them directly."""
    rarity = rng.choices(BOSS_CHEST_MIN_RARITIES, weights=BOSS_CHEST_MIN_WEIGHTS)[0]
    return Item(0, 0, roll_gear_kind(ARMOR_DROP_CHANCE, rng), rarity)


def belt_capacity(player):
    """How many potions the belt holds: BELT_SLOTS plus any shrine boon's
    extra slots (game/shrine.py)."""
    return BELT_SLOTS + boon_total(player, 'belt')


def potion_heal(rarity, player=None):
    """What a potion of `rarity` heals `player`: POTION_HEAL scaled by the
    player's boons' heal multiplier (game/shrine.py), rounded. Without a
    player, the plain table value."""
    base = POTION_HEAL[rarity]
    if player is None:
        return base
    return round(base * heal_multiplier(player))


def belt_slot_label(item, player=None):
    """Short text for one belt slot: a potion's heal ('+35', after
    `player`'s boons if given), or '---' for an empty slot (None). Both
    renderers' panels use it."""
    if item is None:
        return '---'
    return f'+{potion_heal(item.rarity, player)}'


def _effect_value(value, rarity):
    return value[rarity] if isinstance(value, dict) else value


def gear_defense(player):
    """The player's defense from what is equipped: the armor's, plus a
    shield's (Sword & Shield, weapon slot) -- the two stack -- plus any
    shrine boon's (game/shrine.py)."""
    armor = player.armor.bonus if player.armor is not None else 0
    shield = player.weapon.defense_bonus if player.weapon is not None else 0
    return armor + shield + boon_total(player, 'defense')


def gear_power(player):
    """base_power plus the weapon's bonus (which can be negative: rapier,
    dagger and war axe) plus any shrine boon's (game/shrine.py), never below
    MIN_POWER."""
    bonus = player.weapon.bonus if player.weapon is not None else 0
    return max(MIN_POWER, player.base_power + bonus + boon_total(player, 'power'))


class Item(Entity):
    kind: str
    rarity: str | None
    bonus: int | None
    max_hp_bonus: int
    strikes: int
    cleave: bool
    defense_bonus: int
    crit_bonus: float
    reach: int

    def __init__(self, x, y, kind='potion', rarity='common'):
        # Weapon effects, defaulted for every item (see WEAPON_EFFECTS).
        for attr, default in EFFECT_DEFAULTS.items():
            setattr(self, attr, default)
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
        for attr, value in WEAPON_EFFECTS.get(kind, {}).items():
            setattr(self, attr, _effect_value(value, rarity))

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
            heal = potion_heal(cast(str, self.rarity), player)
            healed = min(heal, player.max_hp - player.hp)
            player.hp += healed
            player.inventory.append(self.name)
            log(f'You drink a {self.name} and recover {healed} HP.')
            return

        slot = GEAR_SLOTS[self.kind]
        old = getattr(player, slot)
        setattr(player, slot, self)
        # Max HP (War Axe): the old piece's bonus comes off and the new one's
        # goes on, to max_hp and to hp alike, so swapping is never a heal.
        # hp is then clamped to [1, max_hp]: losing an axe can't kill.
        delta = self.max_hp_bonus - (old.max_hp_bonus if old is not None else 0)
        if delta:
            player.max_hp += delta
            player.hp = max(1, min(player.max_hp, player.hp + delta))
        # Power and defense are recomputed from everything equipped, so no
        # effect of the replaced piece lingers. Crit, reach, strikes and
        # cleave are read off player.weapon when they are used.
        player.power = gear_power(player)
        player.defense = gear_defense(player)
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

    def __init__(self, x, y, guaranteed_min_rarity=None, kind=None, rng: Rng = random):
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

    def open(self, depth, rng: Rng = random):
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


def spawn_chests(rooms, rng: Rng = random):
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
