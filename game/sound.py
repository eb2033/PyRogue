"""Named sound slots, and what game logic records for a renderer to play.

GameState.sound(slot) appends a `SoundEvent` to `GameState.events` (the one
event stream, see game/combat.py) at each hook point (a step, a swing, a
door...). Plain data, cleared when the player acts; its serial comes from the
stream's counter, so a renderer that sees the same round several times can
tell which sounds it has already played. No audio happens here. Standard
library only.
"""

from collections import namedtuple

ATTACK_HEAVY = 'attack_heavy'
ATTACK_LIGHT = 'attack_light'
ATTACK_BOW = 'attack_bow'
ATTACK_CROSSBOW = 'attack_crossbow'
MONSTER_ATTACK_GOBLIN = 'monster_attack_goblin'
MONSTER_ATTACK_ORC = 'monster_attack_orc'
DOOR = 'door'
DESCEND = 'descend'
CHEST_OPEN = 'chest_open'
ENEMY_ALERT = 'enemy_alert'
GOLD_PICKUP = 'gold_pickup'  # GameState.pick_up_gold
FOOTSTEPS = 'footsteps'

SLOTS: tuple[str, ...] = (
    ATTACK_HEAVY,
    ATTACK_LIGHT,
    ATTACK_BOW,
    ATTACK_CROSSBOW,
    MONSTER_ATTACK_GOBLIN,
    MONSTER_ATTACK_ORC,
    DOOR,
    DESCEND,
    CHEST_OPEN,
    ENEMY_ALERT,
    GOLD_PICKUP,
    FOOTSTEPS,
)

SoundEvent = namedtuple('SoundEvent', 'serial slot')

LIGHT_MELEE = frozenset({'dagger', 'rapier', 'fencing_sword'})
CROSSBOWS = frozenset({'heavy_crossbow', 'hand_crossbow'})

MONSTER_ATTACK_SLOTS = {
    'goblin': MONSTER_ATTACK_GOBLIN,
    'orc': MONSTER_ATTACK_ORC,
    'goblin_archer': ATTACK_BOW,
}


def melee_slot(weapon) -> str:
    """The slot for a player melee swing with `weapon` (None: bare hands)."""
    if weapon is not None and weapon.kind in LIGHT_MELEE:
        return ATTACK_LIGHT
    return ATTACK_HEAVY


def shot_slot(weapon) -> str:
    """The slot for a player shot with `weapon`."""
    if weapon is not None and weapon.kind in CROSSBOWS:
        return ATTACK_CROSSBOW
    return ATTACK_BOW


def monster_attack_slot(monster) -> str:
    """The slot for `monster`'s blow or shot; a boss uses its kind's slot."""
    return MONSTER_ATTACK_SLOTS.get(monster.kind, MONSTER_ATTACK_GOBLIN)
