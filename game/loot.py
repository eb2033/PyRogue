"""What the player gains: chests, shrines, the shop, gold, arrows, the belt.

Opening a chest (a potion drunk or belted, gold, or a choice of gear),
kneeling at a shrine (a choice of boons), choosing from or skipping either
choice, buying from the shop, taking a boon, picking up gold and arrows,
dropping a dead monster's gold, and drinking from the potion belt.

Free functions over a GameState, like game/archery.py; they use only its
public attributes and methods. None of them takes a turn on its own -- the
turn controller (game/turns.py) decides that.
"""

from typing import TYPE_CHECKING

from game import sound
from game.gold import GoldPile, chest_amount, drop_amount
from game.item import belt_capacity, gear_defense, gear_power
from game.quiver import QUIVER_CAPACITY
from game.shop import heal_price
from game.shrine import Boon, roll_boons

if TYPE_CHECKING:
    from game.state import GameState


def describe(item):
    """Short label for an item offered in a chest choice, or a boon offered
    by a shrine."""
    if isinstance(item, Boon):
        return f'{item.name} ({item.benefit}, {item.cost})'
    if item.rarity is None:
        return item.name
    return f'{item.name} ({item.rarity})'


# -- gold and arrows -------------------------------------------------------


def pick_up_gold(state: 'GameState', pile):
    """Take all of `pile`: the gold goes to the player, the pile off the map."""
    state.player.gold += pile.amount
    state.entities.remove(pile)
    state.log(f'You pick up {pile.amount} gold.')
    state.sound(sound.GOLD_PICKUP)


def drop_gold(state: 'GameState', monster):
    """A dead monster's gold, on its tile -- added to a pile already there."""
    amount = drop_amount(monster, state.rng)
    pile = state.gold_at(monster.x, monster.y)
    if pile is not None:
        pile.amount += amount
    else:
        state.entities.append(GoldPile(monster.x, monster.y, amount))


def pick_up_arrows(state: 'GameState', pile):
    """Put as many of `pile`'s arrows in the quiver as it has room for;
    whatever doesn't fit stays on the floor. A full quiver takes none
    (logged); without a quiver (a warrior) the pile is left alone."""
    player = state.player
    if player.quiver is None:
        return
    room = QUIVER_CAPACITY - player.quiver
    if room <= 0:
        state.log('Your quiver is full.')
        return
    taken = min(room, pile.count)
    player.quiver += taken
    pile.count -= taken
    if pile.count <= 0:
        state.entities.remove(pile)
    state.log(f'You pick up {taken} arrow{"s" if taken != 1 else ""}.')


# -- the potion belt -------------------------------------------------------


def belt_refuses(state: 'GameState', chest):
    """True if a potion chest can't be taken now: full HP (so it wouldn't be
    drunk) and no free belt slot to store it in."""
    player = state.player
    return (
        chest.kind == 'potion'
        and player.hp >= player.max_hp
        and len(state.belt) >= belt_capacity(player)
    )


def drink_from_belt(state: 'GameState'):
    """Drink the first belt slot's potion (heals item.potion_heal --
    POTION_HEAL[rarity] after boons -- capped at max HP); the others shift
    forward. Returns False, logging why and drinking nothing, if the belt is
    empty or HP is already full (a potion would heal 0)."""
    if not state.belt:
        state.log('No potions')
        return False
    if state.player.hp >= state.player.max_hp:
        state.log('You are already at full health.')
        return False
    potion = state.belt.pop(0)
    potion.apply(state.player, state.log)
    return True


# -- chests, shrines and their choices -------------------------------------


def open_chest(state: 'GameState', chest):
    """Open a chest and remove it from the map. Its contents are rolled now,
    against the current depth (see game/item.py). A potion chest's potion is
    drunk at once if the player is hurt, or put in the next free belt slot
    at full HP; a gear or boss chest's drops become `pending_choice`, and
    the player must choose() one of them.

    Returns False, leaving the chest closed and in place, for a potion chest
    at full HP with a full belt (moves.try_move_player refuses that move
    before getting here); True otherwise."""
    player = state.player
    if belt_refuses(state, chest):
        state.log('Your potion belt is full.')
        return False
    state.sound(sound.CHEST_OPEN)
    state.log('You open the chest.')
    items = chest.open(state.depth, state.rng, char_class=player.char_class)
    state.entities.remove(chest)
    if chest.kind == 'gold':
        amount = chest_amount(state.depth, state.rng)
        player.gold += amount
        state.log(f'The chest holds {amount} gold.')
        return True
    if not chest.offers_choice:
        for item in items:
            if player.hp < player.max_hp:
                item.apply(player, state.log)
            else:
                state.belt.append(item)
                state.log(f'You put the {item.name} on your belt (slot {len(state.belt)}).')
        return True
    state.pending_choice = items
    state.log('Choose one: ' + ', '.join(describe(i) for i in items) + '.')
    return True


def visit_shrine(state: 'GameState', shrine):
    """Kneel at a shrine: it is used up (removed from the map) and its
    BOONS_OFFERED different boons become `pending_choice`, chosen exactly
    like a gear chest's items (choose)."""
    state.entities.remove(shrine)
    state.pending_choice = list(roll_boons(state.player.boons, state.rng))
    state.log('You kneel at the shrine. Choose a boon:')
    state.log(', '.join(describe(b) for b in state.pending_choice) + '.')


def choose(state: 'GameState', index):
    """Take offer `index` (0-based) of the pending choice.

    From a chest: gear always equips into its slot, replacing (and
    discarding) what was there -- the player chose it, so there is no "only
    if better" check. Junk only logs a line. From a shrine: the boon is
    taken for the rest of the run (take_boon). The other offers are lost. A
    choice stays pending until one is taken or the whole choice is skipped
    (skip_choice). Takes no turn.
    Raises ValueError if nothing is pending or `index` is out of range.
    """
    if state.pending_choice is None:
        raise ValueError('no chest choice is pending')
    if not 0 <= index < len(state.pending_choice):
        raise ValueError(f'choice index out of range: {index!r}')
    offer = state.pending_choice[index]
    state.pending_choice = None
    if isinstance(offer, Boon):
        take_boon(state, offer)
        return
    offer.x, offer.y = state.player.x, state.player.y
    offer.apply(state.player, state.log)


def skip_choice(state: 'GameState'):
    """Leave every offer of the pending choice: the chest (or shrine) is
    already used up, so this ends the choice with no item, no boon and
    nothing else changed. Takes no turn.
    Raises ValueError if nothing is pending."""
    if state.pending_choice is None:
        raise ValueError('no chest choice is pending')
    offers, state.pending_choice = state.pending_choice, None
    if offers and isinstance(offers[0], Boon):
        state.log('You leave the shrine without a boon.')
        state.log('The shrine crumbles to dust.')
    else:
        state.log('You walk away from the chest.')


# -- the shop and boons ----------------------------------------------------


def buy(state: 'GameState', index: int) -> bool:
    """Buy shop offer `index` (0-based, in key order). Refused -- a log line
    and nothing changed -- if it is sold, unaffordable, or (the heal) HP is
    already full. A weapon equips (replacing the old one), a boon is taken
    (take_boon), the heal restores HP to max. The price is paid, and the
    offer marked sold (never the heal). Takes no turn.
    Raises ValueError if there is no shop or `index` is out of range."""
    if state.shop is None:
        raise ValueError('there is no shop on this floor')
    if not 0 <= index < len(state.shop.offers):
        raise ValueError(f'shop offer index out of range: {index!r}')
    offer = state.shop.offers[index]
    player = state.player
    if offer.sold:
        state.log('That is sold out.')
        return False
    if offer.kind == 'heal':
        if player.hp >= player.max_hp:
            state.log('You are already at full health.')
            return False
        price = heal_price(player)
    else:
        price = offer.price
    if player.gold < price:
        state.log(f'You cannot afford that ({price} gold).')
        return False
    player.gold -= price
    if offer.item is not None:
        offer.item.x, offer.item.y = player.x, player.y
        offer.item.apply(player, state.log)
    elif offer.boon is not None:
        take_boon(state, offer.boon, source='shop')
    else:
        healed = player.max_hp - player.hp
        player.hp = player.max_hp
        state.log(f'The shopkeeper patches you up: +{healed} HP.')
    if offer.kind != 'heal':
        offer.sold = True
    state.log(f'You pay {price} gold.')
    return True


def take_boon(state: 'GameState', boon, source='shrine'):
    """Add `boon` to the player's boons and bring the stats up to date.

    Power and defence are recomputed from scratch (gear_power / gear_defense
    read Player.boons), crit, the belt's size and potion heals are read from
    Player.boons when used, so none of them can double-apply. Max HP is a
    running total (a War Axe changes it the same way): the boon's max_hp
    goes on here, once, and HP is clamped to [1, max_hp] -- a cost can lower
    HP but never kill. A belt that no longer fits (it can't today: no boon
    removes a slot) keeps its potions."""
    player = state.player
    player.boons.append(boon.key)
    if boon.max_hp:
        player.max_hp = max(1, player.max_hp + boon.max_hp)
        gained = max(0, boon.max_hp)
        player.hp = max(1, min(player.max_hp, player.hp + gained))
    player.power = gear_power(player)
    player.defense = gear_defense(player)
    if source == 'shrine':
        state.log(f'You take the {boon.name}: {boon.benefit}, {boon.cost}.')
        state.log('The shrine crumbles to dust.')
    else:
        state.log(f'You buy the {boon.name}: {boon.benefit}.')
