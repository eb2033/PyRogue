"""The player's movement: walking, bumping, a spear's reach, the archer's hop.

try_move_player decides what a direction key does on the map -- walk (and
open the chest, kneel at the shrine, pick up what lies there), bump-attack
a monster, reach past an empty tile with a spear, or open the shop -- and
hop() is the archer's two-tile jump (primed by Q, aimed by the next
movement key). What blocks each of them is game/level.py's.

Free functions over a GameState, like game/archery.py; they use only its
public attributes and methods. Whether an action takes a turn is decided
by the turn controller (game/turns.py), from what these return.
"""

from typing import TYPE_CHECKING

from game import level, loot, sound
from game.monster import Monster
from game.tiles import DOOR, is_walkable

if TYPE_CHECKING:
    from game.state import GameState

# The archer's hop (Q, then a direction): reach, and turns before the next one.
HOP_DISTANCE = 2
HOP_COOLDOWN = 4


def try_move_player(state: 'GameState', dx, dy):
    """Walk, bump-attack, or reach-attack in (dx, dy). Returns False only if
    the move is refused and must take no turn: the target tile holds a
    potion chest the player can neither drink (HP is full) nor store (the
    belt is full). The player stays put, the chest stays closed, and the log
    says why; drinking from the belt frees a slot, and then the same move
    succeeds. Anything else -- including bumping a wall -- returns True.
    Walking into the shopkeeper opens the shop: the player stays put, and it
    takes the turn like a bump."""
    player = state.player
    nx, ny = player.x + dx, player.y + dy
    if not is_walkable(state.game_map, nx, ny):
        return True

    # A creature there (game/level.py): the shopkeeper opens the shop, a
    # monster takes the blow.
    who = level.occupant(state, nx, ny)
    if who is not None and who is state.shopkeeper:
        state.shop_open = True
        state.log('The shopkeeper shows you their wares.')
        return True
    if isinstance(who, Monster):
        state.melee(who)
        return True

    target = reach_target(state, dx, dy)
    if target is not None:
        state.melee(target)
        return True

    chest = state.chest_at(nx, ny)
    if chest is not None and loot.belt_refuses(state, chest):
        state.log('Your potion belt is full.')
        return False

    player.move(dx, dy, state.game_map)
    state.sound(sound.FOOTSTEPS)
    if state.game_map[ny][nx] == DOOR:
        state.sound(sound.DOOR)

    if chest is not None:
        loot.open_chest(state, chest)
    shrine = state.shrine_at(nx, ny)
    if shrine is not None:
        loot.visit_shrine(state, shrine)
    arrive(state, nx, ny)
    return True


def arrive(state: 'GameState', x, y):
    """The player has just landed on (x, y), by walking or by a hop: pick up
    the arrows and the gold lying there. (Chests, shrines and the shopkeeper
    are walking-only, in try_move_player; a hop stops short of them.)"""
    pile = state.arrows_at(x, y)
    if pile is not None:
        loot.pick_up_arrows(state, pile)
    coins = state.gold_at(x, y)
    if coins is not None:
        loot.pick_up_gold(state, coins)


def reach_target(state: 'GameState', dx, dy):
    """The monster a reach weapon (the spear, reach 2) hits when the player
    presses (dx, dy) and the adjacent tile holds no monster, or None to move
    as usual.

    Only exactly `reach` tiles away, straight along the pressed direction
    (so never diagonally -- movement is 4-way). No tile in between may block
    level.REACH: no wall, no creature (the player is behind, never in
    between; a chest or pile is not an obstacle), and no door -- a reach
    attack can't pass through one. The target must also be in the player's
    view, so a spear can't strike an unseen monster through a closed door
    (doors are walkable but opaque).
    """
    weapon = state.player.weapon
    reach = weapon.reach if weapon is not None else 1
    if reach < 2:
        return None
    px, py = state.player.x, state.player.y
    for step in range(1, reach):
        if level.blocking_at(state, px + dx * step, py + dy * step, level.REACH):
            return None
    tx, ty = px + dx * reach, py + dy * reach
    if not (0 <= ty < state.height and 0 <= tx < state.width) or not state.visible[ty][tx]:
        return None
    return state.monster_at(tx, ty)


# -- the archer's hop ------------------------------------------------------


def prime_hop(state: 'GameState'):
    """The archer's Q: ready a hop, whose direction the next movement key
    picks (the turn controller). Refused, with the cooldown's log line,
    until HOP_COOLDOWN turns have passed since the last hop. Takes no turn.
    Returns True if the hop is now primed."""
    if state.last_hop_turn is not None:
        left = HOP_COOLDOWN - (state.turn - state.last_hop_turn)
        if left > 0:
            state.log(f'Hop recovering ({left} turns).')
            return False
    state.hop_primed = True
    state.log('Hop ready: pick a direction.')
    return True


def cancel_hop(state: 'GameState'):
    """Drop a primed hop (Q again, or a key that isn't a direction)."""
    state.hop_primed = False
    state.log('Hop cancelled.')


def hop(state: 'GameState', dx, dy):
    """The archer's hop: up to HOP_DISTANCE tiles in direction (dx, dy), one
    tile at a time, stopping before anything level.HOP lists: a wall, a
    door, a creature, a chest or a shrine. Returns False, with a log line
    and no position change, if it is refused (not even one tile free); the
    caller spends the turn and starts the cooldown."""
    player = state.player
    hopped = 0
    for _ in range(HOP_DISTANCE):
        nx, ny = player.x + dx, player.y + dy
        if level.blocking_at(state, nx, ny, level.HOP):
            break
        player.x, player.y = nx, ny
        hopped += 1
    if not hopped:
        state.log('Nowhere to hop.')
        return False
    state.sound(sound.FOOTSTEPS)
    arrive(state, player.x, player.y)
    return True


def hop_shot_ready(state: 'GameState', dx, dy):
    """True if a hop in (dx, dy) is a hand crossbow's hop-shot: the weapon
    has hop_shot and a monster stands orthogonally adjacent on the far side,
    so the hop moves the archer directly away from it. Asked before the hop
    moves her; the turn controller then defers the hop's monster half."""
    weapon = state.player.weapon
    if weapon is None or not weapon.hop_shot:
        return False
    return state.monster_at(state.player.x - dx, state.player.y - dy) is not None
