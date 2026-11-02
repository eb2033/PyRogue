"""Combat resolution: one blow, and everything a blow can set off.

attack() is the single place damage is dealt -- the player's bump and
reach, every arrow (game/archery.py), a monster's melee blow or shot, a
parry's riposte -- so crits, the player's dodge, defence, the log line, the
Hit record (game/combat.py holds the records) and a death's consequences
(gold, a boss's chest, the hunter's mark, a slime's split) are the same for
all of them. A boss that drops to half HP enrages and summons goblins here
too.

The warrior's parry lives here as well: armed by Q (arm_parry), spent on
the next monster melee blow that would land (monster_melee), which it turns
into a riposte.

Free functions over a GameState, like game/archery.py; they use only its
public attributes and methods. The rolls (crit_chance, dodged) take their
inputs explicitly. Every roll goes through state.rng, in a fixed order, so
a seeded game replays exactly.
"""

from typing import TYPE_CHECKING

from game import level, loot, sound
from game.combat import Arrow, Hit, Parry
from game.damage import mitigate, round_damage
from game.item import dodge_chance, spawn_boss_chest
from game.monster import (
    MISS_CHANCE,
    ORTHOGONAL_STEPS,
    SLIME_KINDS,
    SLIME_SPLIT_COUNT,
    Monster,
    tier_for_depth,
)
from game.shrine import boon_total

if TYPE_CHECKING:
    from game.state import GameState

# Chance that a player hit is critical; an equipped weapon's crit_bonus
# (the dagger's) adds to it.
BASE_CRIT_CHANCE = 0.10
# A crit multiplies raw damage by this BEFORE defense reduction.
CRIT_MULTIPLIER = 1.5
MAX_CRIT_CHANCE = 1.0
MAX_SUMMONS = 2  # goblins a boss calls when it enrages
SUMMON_RADIUS = 3
SPLIT_RADIUS = 2  # a slime's split-offs land within this many tiles of it
# The warrior's parry (Q): turns from arming one before the next can be armed.
PARRY_COOLDOWN = 4


def crit_chance(attacker):
    """BASE_CRIT_CHANCE plus the attacker's weapon's crit_bonus and any
    shrine boon's crit (game/shrine.py), capped at MAX_CRIT_CHANCE. Only ever
    rolled for the player (see attack)."""
    weapon = getattr(attacker, 'weapon', None)
    bonus = weapon.crit_bonus if weapon is not None else 0.0
    return min(MAX_CRIT_CHANCE, BASE_CRIT_CHANCE + bonus + boon_total(attacker, 'crit'))


def dodged(player, attacker, rng, log):
    """Roll `player`'s dodge against `attacker`'s blow (melee or a goblin
    archer's shot: every monster hit comes through attack). On a dodge the
    blow does nothing -- no damage, no Hit -- and is logged. With no dodge
    nothing is rolled, so the rng sequence is untouched."""
    chance = dodge_chance(player)
    if chance <= 0 or rng.random() * 100 >= chance:
        return False
    log(f"You dodge the {attacker.name}'s attack.")
    return True


def attack(state: 'GameState', attacker, defender, factor=1.0, crit=None):
    """One blow. `factor` scales the attacker's raw power before crits and
    defence (a volley's extra arrows, the hunter's mark, a parry). `crit`
    None rolls for a crit as usual; True or False forces it (the shot after
    a hop always crits; a parry's riposte never rolls). Returns the blow's
    Hit (recorded in the stream, unless a shot is recording: then it is the
    Shot's), or None if it was dodged."""
    player = state.player
    if defender is player and dodged(player, attacker, state.rng, state.log):
        return None
    defense = getattr(defender, 'defense', 0)
    raw = attacker.power * factor
    # Only the player crits (monsters never do); arrows are player hits too.
    if crit is None:
        crit = attacker is player and state.rng.random() < crit_chance(attacker)
    if crit:
        raw = raw * CRIT_MULTIPLIER
    damage = round_damage(mitigate(raw, defense), state.rng)
    defender.hp -= damage
    subject = 'You' if attacker is player else attacker.name.capitalize()
    verb = 'hit' if attacker is player else 'hits'
    target = 'you' if defender is player else defender.name
    state.log(f'{subject} {verb} {target} for {damage}.')
    if crit:
        state.log('Critical hit!')
    hit = Hit(
        state.next_serial(),
        attacker,
        defender,
        damage,
        defender.hp <= 0,
        defender.x,
        defender.y,
        crit,
    )
    state.record_hit(hit)
    if defender.hp <= 0:
        _kill(state, defender)
    elif (
        getattr(defender, 'is_boss', False)
        and not defender.enraged
        and defender.hp <= defender.max_hp / 2
    ):
        defender.enraged = True
        state.log(f'The {defender.kind} boss roars and calls for help!')
        summon_goblins(state, defender)
    return hit


def _kill(state: 'GameState', defender):
    """`defender` has just dropped to 0 HP: it dies, and a monster leaves
    its gold (unless it split off a slime), a boss its chest, and a medium or
    large slime splits."""
    defender.alive = False
    if defender is state.marked:
        state.marked = None
    if defender is state.player:
        # The player's own death message is logged once by the turn
        # controller, which also flips game_over -- no duplicate line here.
        return
    state.log(f'{defender.name.capitalize()} dies.')
    if isinstance(defender, Monster):
        if defender.drops_gold:
            loot.drop_gold(state, defender)
        split_slime(state, defender)
    if getattr(defender, 'is_boss', False):
        state.entities.append(spawn_boss_chest(defender.x, defender.y))
        state.log('The boss drops a chest!')


def summon_goblins(state: 'GameState', boss):
    """Enrage helper: put min(tier, 2) goblins within SUMMON_RADIUS tiles of
    `boss`, on bare floor that blocks nothing for level.SUMMON and that the
    boss could walk to without leaving that square (so never through a wall
    into the next room). They join the entity list only; the round's queue
    is built after the player's half (end_player_phase), so they act in the
    same round's monster phase like any other monster."""
    count = min(tier_for_depth(state.depth), MAX_SUMMONS)
    near = level.reachable_within(state.game_map, (boss.x, boss.y), SUMMON_RADIUS)
    free = [
        (x, y)
        for y in range(boss.y - SUMMON_RADIUS, boss.y + SUMMON_RADIUS + 1)
        for x in range(boss.x - SUMMON_RADIUS, boss.x + SUMMON_RADIUS + 1)
        if (x, y) in near and not level.blocking_at(state, x, y, level.SUMMON)
    ]
    state.rng.shuffle(free)
    for x, y in free[:count]:
        state.entities.append(Monster(x, y, 'goblin', depth=state.depth))


def split_tiles(state: 'GameState', slime, count):
    """Up to `count` tiles for `slime`'s split-offs: free tiles orthogonally
    next to it first, then any within SPLIT_RADIUS, each group shuffled. A
    tile qualifies if level.SUMMON finds nothing in its way there (bare
    floor, no creature, fixture or pile) and it can be walked to from the
    slime without leaving that square, so never through a wall."""
    sx, sy = slime.x, slime.y
    near = level.reachable_within(state.game_map, (sx, sy), SPLIT_RADIUS)

    def free(tile):
        return (
            tile != (sx, sy)
            and tile in near
            and not level.blocking_at(state, tile[0], tile[1], level.SUMMON)
        )

    beside = [(sx + dx, sy + dy) for dx, dy in ORTHOGONAL_STEPS]
    first = [t for t in beside if free(t)]
    rest = [
        (x, y)
        for y in range(sy - SPLIT_RADIUS, sy + SPLIT_RADIUS + 1)
        for x in range(sx - SPLIT_RADIUS, sx + SPLIT_RADIUS + 1)
        if (x, y) not in beside and free((x, y))
    ]
    state.rng.shuffle(first)
    state.rng.shuffle(rest)
    return (first + rest)[:count]


def split_slime(state: 'GameState', slime):
    """A dead medium or large slime splits into SLIME_SPLIT_COUNT of the
    next size down (SLIME_KINDS), at the floor's depth, on split_tiles --
    fewer if there's no room. They drop no gold, and join the next round's
    monster queue, not this one's (GameState.defer_to_next_round). Anything
    else does nothing."""
    child = SLIME_KINDS.get(slime.kind, (None, None))[1]
    if child is None:
        return
    tiles = split_tiles(state, slime, SLIME_SPLIT_COUNT)
    if not tiles:
        return
    state.log(f'The {slime.name} splits apart!')
    for x, y in tiles:
        kid = Monster(x, y, child, depth=state.depth)
        kid.drops_gold = False
        kid.split_from = slime
        state.entities.append(kid)
        state.defer_to_next_round(kid)


def cleave(state: 'GameState', target):
    """The Great Sword's extra swing (see TurnController.melee): one more
    living monster orthogonally adjacent to the player -- not to the target
    -- other than `target`, the first in entity order, takes its own
    attack()."""
    player = state.player
    weapon = player.weapon
    if weapon is None or not weapon.cleave:
        return
    other = next(
        (
            e
            for e in state.entities
            if isinstance(e, Monster) and e.alive and e is not target and e.is_adjacent(player)
        ),
        None,
    )
    if other is not None:
        state.log(f'Your swing carries on into {other.name}.')
        attack(state, player, other)


# -- the warrior's parry ---------------------------------------------------


def arm_parry(state: 'GameState'):
    """The warrior's parry: ready it for the next monster melee hit that
    would land, which it nullifies (see monster_melee). Returns False, with
    a log line and nothing armed, if it is refused -- one is already armed,
    or PARRY_COOLDOWN turns haven't passed since the last one was armed; the
    caller spends the turn."""
    if state.parry_armed:
        state.log('Your parry is already ready.')
        return False
    if state.last_parry_turn is not None:
        left = PARRY_COOLDOWN - (state.turn - state.last_parry_turn)
        if left > 0:
            state.log(f'Parry recovering ({left} turns).')
            return False
    state.parry_armed = True
    state.log('You ready a parry.')
    return True


def parry_progress(state: 'GameState'):
    """How far the warrior's parry has recharged, 0..PARRY_COOLDOWN, for the
    renderer's bar: turns since Q last armed it, capped. Full when it is
    ready (never used, or the cooldown is over) and while it is armed, so a
    full bar means "a parry is available or armed"."""
    if state.parry_armed or state.last_parry_turn is None:
        return PARRY_COOLDOWN
    return max(0, min(PARRY_COOLDOWN, state.turn - state.last_parry_turn))


def riposte(state: 'GameState', monster):
    """An armed parry spent on `monster`'s melee blow, which is nullified
    (the caller rolled the dodge already): the monster takes the player's
    crit damage (raw power x CRIT_MULTIPLIER, or the weapon's riposte_mult
    when it has one -- the fencing sword's -- with no crit roll of its own)
    through attack(), so its defence reduces it and a Hit is recorded for
    the riposte only. Returns that Hit."""
    state.parry_armed = False
    state.log(f"You parry the {monster.name}'s attack!")
    state.log(f'Your parry returns the blow to the {monster.name}!')
    weapon = state.player.weapon
    mult = weapon.riposte_mult if weapon is not None and weapon.riposte_mult else CRIT_MULTIPLIER
    return attack(state, state.player, monster, mult, crit=False)


# -- monster attacks -------------------------------------------------------


def monster_melee(state: 'GameState', monster):
    """`monster`'s melee blow at the player. With a parry armed, the dodge
    is rolled first (a dodged blow does nothing and leaves the parry armed);
    a blow that would land is parried instead: no damage, no Hit (a Parry in
    state.events instead, for the renderer), and the monster takes the
    riposte. Unarmed, it is an ordinary attack()."""
    player = state.player
    state.sound(sound.monster_attack_slot(monster))
    if not state.parry_armed:
        attack(state, monster, player)
        return
    if dodged(player, monster, state.rng, state.log):
        return
    # The Parry's serial and place come before the riposte's Hit; it is
    # filled in once the riposte has landed, so it can name it.
    x, y = player.x, player.y
    index, serial = len(state.events), state.next_serial()
    hit = riposte(state, monster)
    state.events.insert(index, Parry(serial, monster, player, x, y, hit))


def monster_shot(state: 'GameState', monster):
    """A ranged monster's arrow at the player (it has a clear shot, see
    Monster.clear_shot). The damage goes through attack, so dodge, defence
    and the log work as for a melee blow; the flight is recorded as a
    one-Arrow Shot in state.events, like the player's bow shots
    (GameState.recording_shot), which owns its Hit.

    The path runs from the monster's cell to the player's. A dodged arrow
    (no Hit) flies on past the player and stops on the last tile before
    anything level.MONSTER_SHOT lists: a wall, a closed door or another
    creature.

    A ranged monster misses MISS_CHANCE[kind] (30%) of its shots, rolled before
    the player's dodge; a miss takes the same dodged-arrow path."""
    state.sound(sound.monster_attack_slot(monster))
    with state.recording_shot() as arrows:
        if state.rng.random() < MISS_CHANCE.get(monster.kind, 0.0):
            state.log(f'The {monster.name} misses you.')
            hit = None
        else:
            hit = attack(state, monster, state.player)
        arrows.append(_monster_arrow(state, monster, hit))


def _monster_arrow(state: 'GameState', monster, hit):
    """The Arrow of `monster`'s shot at the player, which made `hit` (None:
    dodged)."""
    player = state.player
    hits = () if hit is None else (hit,)
    dx = (player.x > monster.x) - (player.x < monster.x)
    dy = (player.y > monster.y) - (player.y < monster.y)
    x, y = monster.x, monster.y
    path = [(x, y)]
    while (x, y) != (player.x, player.y):
        x, y = x + dx, y + dy
        path.append((x, y))
    if not hits:
        while not level.blocking_at(state, x + dx, y + dy, level.MONSTER_SHOT):
            x, y = x + dx, y + dy
            path.append((x, y))
    return Arrow(tuple(path), hits)
