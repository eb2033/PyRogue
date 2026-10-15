"""The whole world in one object, plus turn resolution.

GameState knows nothing about pygame or keys. It takes semantic actions (see
render.base.Action) and advances the world, so the game loop never sees a
keycode.

A round has two halves. handle_action() resolves the player's half and then
*queues* the monsters rather than running them, so the caller can draw the
result of the player's own action before anything answers it; the caller then
drives step_monster_phase() until the queue drains. Monsters resolve strictly
one at a time against the current world -- if the player dies partway through,
the monsters still queued never act. end_turn() runs both halves back to back
for callers that don't care about the split (tests, headless use).

The player's half can itself take more than one step: a rapier's second
strike is queued by handle_action rather than swung at once, so the first hit
is drawn (and its beat played) before the second one's damage is rolled. The
caller drives step_strike() while strike_pending(); the last strike ends the
player's half (end_player_phase), and only then are the monsters queued.
resolve_player_phase() does that in one go for headless callers.
"""

import random
from typing import Any

from game import archery
from game.combat import Hit
from game.damage import mitigate, round_damage
from game.dungeon import generate_dungeon, place_stairs
from game.entity import Player
from game.fov import update_visibility
from game.item import (
    STARTING_ARMOR,
    STARTING_WEAPON_RARITY,
    Chest,
    Item,
    belt_capacity,
    dodge_chance,
    gear_defense,
    gear_power,
    spawn_boss_chest,
    spawn_chests,
)
from game.monster import Monster, is_boss_level, tier_for_depth
from game.quiver import QUIVER_CAPACITY, RESTOCK_TURNS, ArrowPile
from game.shrine import Boon, Shrine, boon_total, place_shrine, roll_boons
from game.spawn import spawn_level
from game.tiles import DOOR, FLOOR, STAIRS_DOWN, is_walkable

# Semantic action -> (dx, dy) in game coordinates. y grows downward.
MOVE_DELTAS = {
    'move_n': (0, -1),
    'move_s': (0, 1),
    'move_w': (-1, 0),
    'move_e': (1, 0),
}

# Arrow-key actions -> the same deltas. What they *do* depends on class: see
# handle_action. Kept as a separate dict (rather than reusing MOVE_DELTAS)
# so the two concerns -- "which direction" and "move or shoot" -- stay
# decoupled at the call site.
SHOOT_DELTAS = {
    'shoot_n': (0, -1),
    'shoot_s': (0, 1),
    'shoot_w': (-1, 0),
    'shoot_e': (1, 0),
}

# Keys 1-3 on a chest's choice screen -> index into pending_choice.
CHOOSE_INDEX = {
    'choose_1': 0,
    'choose_2': 1,
    'choose_3': 2,
}

# class name -> (hp, power). Archers hit softer but get a free ranged option;
# warriors are the straightforward melee bruiser the spec describes.
CLASS_STATS = {
    'warrior': (60, 4),
    'archer': (45, 3),
}
DEFAULT_CLASS = 'warrior'


def _describe(item):
    """Short label for an item offered in a chest choice, or a boon offered
    by a shrine."""
    if isinstance(item, Boon):
        return f'{item.name} ({item.benefit}, {item.cost})'
    if item.rarity is None:
        return item.name
    return f'{item.name} ({item.rarity})'


# Chance that a player hit is critical; an equipped weapon's crit_bonus
# (the dagger's) adds to it.
MAX_SUMMONS = 2  # goblins a boss calls when it enrages
SUMMON_RADIUS = 3
BASE_CRIT_CHANCE = 0.10
# A crit multiplies raw damage by this BEFORE defense reduction.
CRIT_MULTIPLIER = 1.5
MAX_CRIT_CHANCE = 1.0


def crit_chance(attacker):
    """BASE_CRIT_CHANCE plus the attacker's weapon's crit_bonus and any
    shrine boon's crit (game/shrine.py), capped at MAX_CRIT_CHANCE. Only ever
    rolled for the player (see attack)."""
    weapon = getattr(attacker, 'weapon', None)
    bonus = weapon.crit_bonus if weapon is not None else 0.0
    return min(MAX_CRIT_CHANCE, BASE_CRIT_CHANCE + bonus + boon_total(attacker, 'crit'))


class GameState:
    def __init__(self, width, height, fov_radius=6, char_class=DEFAULT_CLASS):
        self.width = width
        self.height = height
        self.fov_radius = fov_radius
        self.running = True
        self.game_over = False
        self.depth = 1
        self.messages = []
        # This round's blows, oldest first -- see game/combat.py. Cleared when
        # the player acts; the serial keeps counting across rounds and levels.
        self.combat_events = []
        self._hit_serial = 0
        # Player actions taken so far (+1 per turn-consuming action in
        # handle_action; never per frame or per monster). The combat zoom's
        # hold (render/camera.py) counts turns with it.
        self.turn = 0
        # Items an opened gear chest is offering, or the Boons a shrine is
        # (game/shrine.py), or None. While set, the player must choose() one
        # before anything else happens. Typed Any, not Item | Boon: a choice
        # is all one kind (chest or shrine), and callers that set or read a
        # chest's items shouldn't have to narrow every element.
        self.pending_choice: list[Any] | None = None
        # The potion belt: up to belt_capacity(player) potion Items (3, or
        # more with a shrine's Quick hands), in order. Potions
        # found at full HP go here; 'drink' takes only belt[0] and the rest
        # shift forward. Empty at the start of a run; kept across floors.
        self.belt = []
        # The boss's room (a game.rect.Rect: x1, y1 inclusive, x2, y2
        # exclusive, as carved) on a boss floor, else None. The boss starts at
        # boss_arena.center(); the 3x3 block centred there is the arena's
        # centre area. An overlay for the renderer -- not a map char. Set by
        # _spawn_level_monsters on every new floor.
        self.boss_arena = None

        self.game_map, self.rooms = generate_dungeon(width, height)
        place_stairs(self.game_map, self.rooms)
        self.visible = [[False] * width for _ in range(height)]
        self.seen = [[False] * width for _ in range(height)]

        char_class = char_class if char_class in CLASS_STATS else DEFAULT_CLASS
        hp, power = CLASS_STATS[char_class]

        px, py = self.rooms[0].center()
        self.player = Player(px, py, '@', color=1, name='you')
        self.player.char_class = char_class
        self.player.hp = hp
        self.player.max_hp = hp
        self.player.base_power = power
        self.player.power = power
        self.player.defense = 0
        self.player.weapon = Item(0, 0, 'weapon', STARTING_WEAPON_RARITY)
        self.player.armor = None
        if char_class in STARTING_ARMOR:
            self.player.armor = Item(0, 0, *STARTING_ARMOR[char_class])
        self.player.power = gear_power(self.player)
        self.player.defense = gear_defense(self.player)
        self.player.inventory = []
        self.player.quiver = QUIVER_CAPACITY if char_class == 'archer' else None
        self.player.alive = True

        # The archer's bookkeeping (see shoot_arrow and _spend_turn).
        # restock_progress: player turns towards the next free arrow, 0..
        # RESTOCK_TURNS (it reads RESTOCK_TURNS on the turn one is added,
        # and stays 0 while the quiver is full). reload_turns: turns until a
        # heavy crossbow can shoot again. marked: the hunter's bow's quarry.
        # tempo_shots: quickdraw shots since its last free one.
        self.restock_progress = 0
        self.reload_turns = 0
        self.marked: Monster | None = None
        self.tempo_shots = 0
        # True after a free (quickdraw) shot: that action queues no monsters.
        self._free_turn = False

        self.entities: list[Any] = self._populate_level()

        # Monsters still owing a turn in the current round. See end_player_phase.
        self._pending_monsters: list[Monster] = []
        # The player's melee strikes still owed this action (a rapier's 2nd),
        # and the monster they are aimed at. See melee and step_strike.
        self._strike_target: Monster | None = None
        self._strikes_owed = 0

        self.update_fov()

    def _spawn_level_monsters(self):
        """This floor's enemies (game/spawn.py has the rules). Also sets
        self.boss_arena."""
        monsters, self.boss_arena = spawn_level(self.rooms, self.depth)
        return monsters

    def _populate_level(self):
        """The player, then this floor's monsters, chests and (maybe) shrine.
        The shrine avoids the stairs and every tile already taken."""
        monsters = self._spawn_level_monsters()
        chests = spawn_chests(self.rooms, depth=self.depth)
        taken = {(e.x, e.y) for e in monsters + chests}
        taken.add(self.rooms[-1].center())  # the stairs (place_stairs)
        taken.add((self.player.x, self.player.y))
        shrine = place_shrine(self.rooms, self.depth, taken, self.boss_arena)
        # The shrine goes before the monsters so one standing on it is drawn
        # on top (renderers paint in entity order).
        return [self.player] + ([shrine] if shrine is not None else []) + monsters + chests

    # -- turn resolution ---------------------------------------------------

    def handle_action(self, action):
        """Apply one semantic action. Returns True if a turn was consumed."""
        if action is None:
            return False
        # A strike left over from the last action (a headless caller that
        # never stepped it) lands first: the player's half of that round is
        # always finished before anything else happens.
        self.resolve_player_phase()
        self.combat_events = []
        self._free_turn = False

        if action == 'quit':
            self.running = False
            return False

        if action == 'ability':
            # The class ability is not wired yet, so mid-game this is a no-op.
            # On the death screen ('press q to quit') it is the quit key.
            if self.game_over:
                self.running = False
            return False

        if self.game_over:
            return False

        if action in CHOOSE_INDEX:
            # Only means something on a choice screen; never takes a turn.
            index = CHOOSE_INDEX[action]
            if self.pending_choice is not None and index < len(self.pending_choice):
                self.choose(index)
            return False

        if self.is_choosing:
            return False  # a chest's choice must be made first: see choose()

        # A move refused by try_move_player (a potion chest while the belt is
        # full at full HP) takes no turn: nothing happened, so monsters don't
        # act and GameState.turn doesn't advance. Bumping a wall still does,
        # as it always has.
        if action in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[action]
            if not self.try_move_player(dx, dy):
                return False
            self._spend_turn()
            self._close_player_action()
            return True

        if action in SHOOT_DELTAS:
            dx, dy = SHOOT_DELTAS[action]
            if self.player.char_class != 'archer':
                if not self.try_move_player(dx, dy):
                    return False
                self._spend_turn()
                self._close_player_action()
                return True
            # A refused shot (no arrows, still reloading) takes no turn.
            if not self.shoot_arrow(dx, dy):
                return False
            self._spend_turn(shot=True)
            if self._free_turn:
                self.update_fov()  # a quickdraw's free shot: no monster half
            else:
                self.end_player_phase()
            return True

        if action == 'drink':
            # Drink belt[0]. A turn, like any other action -- unless the
            # belt is empty, which only logs.
            if not self.drink_from_belt():
                return False
            self._spend_turn()
            self.end_player_phase()
            return True

        if action == 'wait':
            self._spend_turn()
            self.end_player_phase()
            return True

        if action == 'descend':
            if self.try_descend():
                self._spend_turn()
                return True
            return False

        return False

    def _spend_turn(self, shot=False):
        """A turn-taking player action happened: count it (GameState.turn),
        tick a heavy crossbow's reload down -- except on the shot that just
        started it -- and advance the quiver's restock."""
        self.turn += 1
        if not shot and self.reload_turns > 0:
            self.reload_turns -= 1
        self._restock()

    def _restock(self):
        """One more turn towards a free arrow: every RESTOCK_TURNS turns the
        quiver gains one, up to QUIVER_CAPACITY. restock_progress shows how
        far along it is: 1, 2, 3 (the arrow is added), then 1 again; it sits
        at 0 while the quiver is full. No quiver (a warrior): nothing."""
        player = self.player
        if player.quiver is None:
            return
        if player.quiver >= QUIVER_CAPACITY:
            self.restock_progress = 0
            return
        if self.restock_progress >= RESTOCK_TURNS:
            self.restock_progress = 0
        self.restock_progress += 1
        if self.restock_progress >= RESTOCK_TURNS:
            player.quiver += 1

    def try_move_player(self, dx, dy):
        """Walk, bump-attack, or reach-attack in (dx, dy). Returns False
        only if the move is refused and must take no turn: the target tile
        holds a potion chest the player can neither drink (HP is full) nor
        store (the belt is full). The player stays put, the chest stays
        closed, and the log says why; drinking from the belt frees a slot,
        and then the same move succeeds. Anything else -- including bumping
        a wall -- returns True."""
        nx, ny = self.player.x + dx, self.player.y + dy
        if not is_walkable(self.game_map, nx, ny):
            return True

        monster = self.monster_at(nx, ny)
        if monster is not None:
            self.melee(monster)
            return True

        reach_target = self._reach_target(dx, dy)
        if reach_target is not None:
            self.melee(reach_target)
            return True

        chest = self.chest_at(nx, ny)
        if chest is not None and self._belt_refuses(chest):
            self.log('Your potion belt is full.')
            return False

        self.player.move(dx, dy, self.game_map)

        if chest is not None:
            self.open_chest(chest)
        shrine = self.shrine_at(nx, ny)
        if shrine is not None:
            self.visit_shrine(shrine)
        pile = self.arrows_at(nx, ny)
        if pile is not None:
            self.pick_up_arrows(pile)
        return True

    def pick_up_arrows(self, pile):
        """Put as many of `pile`'s arrows in the quiver as it has room for;
        whatever doesn't fit stays on the floor. A full quiver takes none
        (logged); without a quiver (a warrior) the pile is left alone."""
        player = self.player
        if player.quiver is None:
            return
        room = QUIVER_CAPACITY - player.quiver
        if room <= 0:
            self.log('Your quiver is full.')
            return
        taken = min(room, pile.count)
        player.quiver += taken
        pile.count -= taken
        if pile.count <= 0:
            self.entities.remove(pile)
        self.log(f'You pick up {taken} arrow{"s" if taken != 1 else ""}.')

    def _belt_refuses(self, chest):
        """True if a potion chest can't be taken now: full HP (so it
        wouldn't be drunk) and no free belt slot to store it in."""
        return (
            not chest.offers_choice
            and self.player.hp >= self.player.max_hp
            and len(self.belt) >= belt_capacity(self.player)
        )

    def drink_from_belt(self):
        """Drink the first belt slot's potion (heals item.potion_heal --
        POTION_HEAL[rarity] after boons -- capped at max HP); the others
        shift forward. Returns False, logging
        'No potions', if the belt is empty."""
        if not self.belt:
            self.log('No potions')
            return False
        potion = self.belt.pop(0)
        potion.apply(self.player, self.log)
        return True

    def _reach_target(self, dx, dy):
        """The monster a reach weapon (the spear, reach 2) hits when the
        player presses (dx, dy) and the adjacent tile holds no monster, or
        None to move as usual.

        Only exactly `reach` tiles away, straight along the pressed
        direction (so never diagonally -- movement is 4-way). Every tile in
        between must be walkable and unoccupied: no wall, no monster (the
        player is behind, never in between; a chest is not an obstacle), and
        no door -- a reach attack can't pass through one. The target must
        also be in the player's view, so a spear can't strike an unseen
        monster through a closed door (doors are walkable but opaque).
        """
        weapon = self.player.weapon
        reach = weapon.reach if weapon is not None else 1
        if reach < 2:
            return None
        px, py = self.player.x, self.player.y
        for step in range(1, reach):
            x, y = px + dx * step, py + dy * step
            if (
                not is_walkable(self.game_map, x, y)
                or self.game_map[y][x] == DOOR
                or self.monster_at(x, y) is not None
            ):
                return None
        tx, ty = px + dx * reach, py + dy * reach
        if not (0 <= ty < self.height and 0 <= tx < self.width) or not self.visible[ty][tx]:
            return None
        return self.monster_at(tx, ty)

    def melee(self, target):
        """The player's melee attack on `target` (a bump, or a spear's
        reach), with the equipped weapon's effects. Arrows don't come
        through here: a bow shot is one plain attack().

        - strikes (the rapier's 2): that many separate attack() calls --
          each its own crit roll, damage reduction, log line and Hit --
          stopping early if the target dies. Only the first lands here; the
          rest are queued (strike_pending) and land one per step_strike()
          call, so each hit is drawn before the next one's damage is rolled.
        - cleave (the Great Sword): one more living monster is hit by the
          same blow, with its own attack(). "Nearby" means ORTHOGONALLY
          ADJACENT TO THE PLAYER (Entity.is_adjacent) -- not to the target,
          and never diagonal or two tiles off -- i.e. a monster the player
          could have bumped instead. If several qualify, only the first in
          entity order is hit ("a 2nd adjacent foe"). It still swings
          through if the main target died, after the last strike.
        """
        weapon = self.player.weapon
        strikes = weapon.strikes if weapon is not None else 1
        self.attack(self.player, target)
        if strikes > 1 and target.alive:
            self._strike_target = target
            self._strikes_owed = strikes - 1
            return
        self._cleave(target)

    def strike_pending(self):
        """True while the player's current action still owes a melee strike
        (a rapier's second) -- the player's half of the round isn't over."""
        return self._strike_target is not None

    def step_strike(self):
        """Land the next queued strike. Returns True if it hit something
        (so the caller should show it), False if it was skipped: the target
        died or is gone, or the player is dead. Once no strike is owed the
        player's half ends (end_player_phase) -- unless the player is dead,
        when nothing more happens at all."""
        target = self._strike_target
        if target is None:
            return False
        if self.game_over or not self.player.alive:
            self._clear_strikes()
            return False
        hit = target.alive and target in self.entities
        if hit:
            self.attack(self.player, target)
            self._strikes_owed -= 1
        if not hit or not target.alive or self._strikes_owed <= 0:
            self._clear_strikes()
            self._cleave(target)
            self.end_player_phase()
        return hit

    def resolve_player_phase(self):
        """Land every queued strike at once, ending the player's half: the
        headless equivalent of main.resolve_player_strikes. Does nothing
        when no strike is owed."""
        while self.strike_pending():
            self.step_strike()

    def _clear_strikes(self):
        self._strike_target = None
        self._strikes_owed = 0

    def _close_player_action(self):
        """End the player's half after a move -- unless it started a
        multi-strike melee, whose last strike ends it (step_strike)."""
        if not self.strike_pending():
            self.end_player_phase()

    def _cleave(self, target):
        """The Great Sword's extra swing (see melee)."""
        weapon = self.player.weapon
        if weapon is not None and weapon.cleave:
            other = next(
                (
                    e
                    for e in self.entities
                    if isinstance(e, Monster)
                    and e.alive
                    and e is not target
                    and e.is_adjacent(self.player)
                ),
                None,
            )
            if other is not None:
                self.log(f'Your swing carries on into {other.name}.')
                self.attack(self.player, other)

    def open_chest(self, chest):
        """Open a chest and remove it from the map. Its contents are rolled
        now, against the current depth (see game/item.py). A potion chest's
        potion is drunk at once if the player is hurt, or put in the next
        free belt slot at full HP; a gear or boss chest's drops become
        `pending_choice`, and the player must choose() one of them.

        Returns False, leaving the chest closed and in place, for a potion
        chest at full HP with a full belt (try_move_player refuses that move
        before getting here); True otherwise."""
        if self._belt_refuses(chest):
            self.log('Your potion belt is full.')
            return False
        self.log('You open the chest.')
        items = chest.open(self.depth, char_class=self.player.char_class)
        self.entities.remove(chest)
        if not chest.offers_choice:
            for item in items:
                if self.player.hp < self.player.max_hp:
                    item.apply(self.player, self.log)
                else:
                    self.belt.append(item)
                    self.log(f'You put the {item.name} on your belt (slot {len(self.belt)}).')
            return True
        self.pending_choice = items
        self.log('Choose one: ' + ', '.join(_describe(i) for i in items) + '.')
        return True

    def visit_shrine(self, shrine):
        """Kneel at a shrine: it is used up (removed from the map) and its
        BOONS_OFFERED different boons become `pending_choice`, chosen
        exactly like a gear chest's items (choose)."""
        self.entities.remove(shrine)
        self.pending_choice = list(roll_boons(self.player.boons))
        self.log('You kneel at the shrine. Choose a boon:')
        self.log(', '.join(_describe(b) for b in self.pending_choice) + '.')

    @property
    def is_choosing(self):
        """True while an opened chest is waiting for the player to pick an
        item, or a shrine for a boon. Movement and every other turn action
        are blocked meanwhile."""
        return self.pending_choice is not None

    def choose(self, index):
        """Take offer `index` (0-based) of the pending choice.

        From a chest: gear always equips into its slot, replacing (and
        discarding) what was there -- the player chose it, so there is no
        "only if better" check. Junk only logs a line. From a shrine: the
        boon is taken for the rest of the run (take_boon). The other offers
        are lost. There is no cancel: a choice stays pending until one is
        taken. Takes no turn.
        Raises ValueError if nothing is pending or `index` is out of range.
        """
        if self.pending_choice is None:
            raise ValueError('no chest choice is pending')
        if not 0 <= index < len(self.pending_choice):
            raise ValueError(f'choice index out of range: {index!r}')
        offer = self.pending_choice[index]
        self.pending_choice = None
        if isinstance(offer, Boon):
            self.take_boon(offer)
            return
        offer.x, offer.y = self.player.x, self.player.y
        offer.apply(self.player, self.log)

    def take_boon(self, boon):
        """Add `boon` to the player's boons and bring the stats up to date.

        Power and defence are recomputed from scratch (gear_power /
        gear_defense read Player.boons), crit, the belt's size and potion
        heals are read from Player.boons when used, so none of them can
        double-apply. Max HP is a running total (a War Axe changes it the
        same way): the boon's max_hp goes on here, once, and HP is clamped
        to [1, max_hp] -- a cost can lower HP but never kill. A belt that
        no longer fits (it can't today: no boon removes a slot) keeps its
        potions."""
        player = self.player
        player.boons.append(boon.key)
        if boon.max_hp:
            player.max_hp = max(1, player.max_hp + boon.max_hp)
            gained = max(0, boon.max_hp)
            player.hp = max(1, min(player.max_hp, player.hp + gained))
        player.power = gear_power(player)
        player.defense = gear_defense(player)
        self.log(f'You take the {boon.name}: {boon.benefit}, {boon.cost}.')
        self.log('The shrine crumbles to dust.')

    def shoot_arrow(self, dx, dy):
        """Archer-only ranged attack: travels in a straight line until it
        hits a wall or the first monster in its path (more with a longbow),
        with the equipped bow's effects -- see game/archery.py. Returns
        False, taking nothing, if the shot is refused (no arrows, or a
        crossbow still reloading)."""
        return archery.shoot(self, dx, dy)

    def try_descend(self):
        if self.game_map[self.player.y][self.player.x] != STAIRS_DOWN:
            self.log('There are no stairs here.')
            return False
        self.next_level()
        return True

    def next_level(self):
        self.depth += 1
        self.game_map, self.rooms = generate_dungeon(self.width, self.height)
        place_stairs(self.game_map, self.rooms)

        px, py = self.rooms[0].center()
        self.player.x, self.player.y = px, py

        self.visible = [[False] * self.width for _ in range(self.height)]
        self.seen = [[False] * self.width for _ in range(self.height)]

        self.cancel_monster_phase()
        self._clear_strikes()
        self.marked = None
        self.pending_choice = None
        self.entities = self._populate_level()
        if is_boss_level(self.depth):
            self.log(f'You descend to level {self.depth}. Something powerful lurks here...')
        else:
            self.log(f'You descend to level {self.depth}.')
        self.update_fov()

    def attack(self, attacker, defender, factor=1.0):
        """One blow. `factor` scales the attacker's raw power before crits
        and defence (a volley's extra arrows, the hunter's mark)."""
        if defender is self.player and self._dodged(attacker):
            return
        defense = getattr(defender, 'defense', 0)
        raw = attacker.power * factor
        # Only the player crits (monsters never do); arrows are player hits too.
        crit = attacker is self.player and random.random() < crit_chance(attacker)
        if crit:
            raw = raw * CRIT_MULTIPLIER
        damage = round_damage(mitigate(raw, defense))
        defender.hp -= damage
        subject = 'You' if attacker is self.player else attacker.name.capitalize()
        verb = 'hit' if attacker is self.player else 'hits'
        target = 'you' if defender is self.player else defender.name
        self.log(f'{subject} {verb} {target} for {damage}.')
        if crit:
            self.log('Critical hit!')
        self._hit_serial += 1
        self.combat_events.append(
            Hit(
                self._hit_serial,
                attacker,
                defender,
                damage,
                defender.hp <= 0,
                defender.x,
                defender.y,
                crit,
            )
        )
        if defender.hp <= 0:
            defender.alive = False
            if defender is self.marked:
                self.marked = None
            if defender is not self.player:
                # The player's own death message is logged once by end_turn,
                # which also flips game_over -- avoid a duplicate line here.
                self.log(f'{defender.name.capitalize()} dies.')
                if getattr(defender, 'is_boss', False):
                    self.entities.append(spawn_boss_chest(defender.x, defender.y))
                    self.log('The boss drops a chest!')
        elif (
            getattr(defender, 'is_boss', False)
            and not defender.enraged
            and defender.hp <= defender.max_hp / 2
        ):
            defender.enraged = True
            self.log(f'The {defender.kind} boss roars and calls for help!')
            self._summon_goblins(defender)

    def _dodged(self, attacker):
        """Roll the player's dodge against `attacker`'s blow (melee or a
        slinger's shot: every monster hit comes through attack). On a dodge
        the blow does nothing -- no damage, no Hit -- and is logged. With no
        dodge nothing is rolled, so the rng sequence is untouched."""
        chance = dodge_chance(self.player)
        if chance <= 0 or random.random() * 100 >= chance:
            return False
        self.log(f"You dodge the {attacker.name}'s attack.")
        return True

    def _summon_goblins(self, boss):
        """Enrage helper: put min(tier, 2) goblins on free floor within 3
        tiles of `boss`. They join the entity list only; the round's queue is
        built after the player's half (end_player_phase), so they act in the
        same round's monster phase like any other monster."""
        count = min(tier_for_depth(self.depth), MAX_SUMMONS)
        taken = {(self.player.x, self.player.y)}
        taken.update((e.x, e.y) for e in self.entities if isinstance(e, Monster) and e.alive)
        free = [
            (x, y)
            for y in range(boss.y - SUMMON_RADIUS, boss.y + SUMMON_RADIUS + 1)
            for x in range(boss.x - SUMMON_RADIUS, boss.x + SUMMON_RADIUS + 1)
            if 0 <= y < self.height
            and 0 <= x < self.width
            and self.game_map[y][x] == FLOOR
            and (x, y) not in taken
        ]
        random.shuffle(free)
        for x, y in free[:count]:
            self.entities.append(Monster(x, y, 'goblin', depth=self.depth))

    # -- the round, in two halves ------------------------------------------

    def end_player_phase(self):
        """Close the player's half of the round and queue the monsters'.

        Resolves nothing on the monsters' behalf -- it only refreshes what
        the player can see, so a caller can draw the outcome of the player's
        own action before any monster answers it.
        """
        self.update_fov()
        self._pending_monsters = [
            e
            for e in self.entities
            if e is not self.player
            and getattr(e, 'alive', True)
            and getattr(e, 'take_turn', None) is not None
        ]

    def monster_phase_pending(self):
        return bool(self._pending_monsters)

    def cancel_monster_phase(self):
        """Drop any queued monsters — used when the level they belong to is
        thrown away underneath them (descending to the next floor)."""
        self._pending_monsters = []

    def step_monster_phase(self):
        """Resolve queued monsters until one of them does something the
        player can see, or the queue runs dry.

        Returns True if the caller should show the result (a monster
        attacked, or moved somewhere the player can see) and False once the
        round is over. Monsters acting out of sight are folded into the same
        call, so crossing an empty dungeon costs no extra frames.
        """
        while self._pending_monsters:
            monster = self._pending_monsters.pop(0)
            if not getattr(monster, 'alive', True):
                continue  # killed earlier in this same round

            was_seen = self.is_visible(monster.x, monster.y)
            before = (monster.x, monster.y)
            result = monster.take_turn(
                self.player,
                self.game_map,
                occupied=self._occupied_except(monster),
                sees_player=was_seen,
            )
            if result == 'attack':
                self.attack(monster, self.player)
            self.update_fov()

            if self._player_just_died():
                # Nothing swings at a corpse: whoever is still queued this
                # round simply never acts.
                self.cancel_monster_phase()
                self._finish_round()
                return True

            moved_in_view = (monster.x, monster.y) != before and (
                was_seen or self.is_visible(monster.x, monster.y)
            )
            if result == 'attack' or moved_in_view:
                return True

        self._finish_round()
        return False

    def end_turn(self):
        """Run the monster half of the round in one go.

        The renderer-driven loop in main.py steps the phase frame by frame
        instead; this is the all-at-once equivalent for tests and any
        headless caller. Any strike the player still owes lands first
        (resolve_player_phase), so the player's half is always over before
        the monsters' starts.
        """
        self.resolve_player_phase()
        # A free (quickdraw) shot has no monster half to run.
        free, self._free_turn = self._free_turn, False
        if not self.monster_phase_pending() and not free:
            self.end_player_phase()
        while self.step_monster_phase():
            pass

    def _occupied_except(self, monster):
        """Tiles `monster` may not step onto: the player's and every other
        living monster's. Built fresh for each monster, so it reflects the
        moves already made earlier in the same round."""
        occupied = {(self.player.x, self.player.y)}
        for e in self.entities:
            if e is not monster and e is not self.player and isinstance(e, Monster) and e.alive:
                occupied.add((e.x, e.y))
        return occupied

    def _player_just_died(self):
        """True only on the single step that kills the player, so the death
        is logged once and the round stops there."""
        if self.player.hp > 0 or self.game_over:
            return False
        self.game_over = True
        self.log('You died.')
        return True

    def _finish_round(self):
        self.entities = [e for e in self.entities if e is self.player or getattr(e, 'alive', True)]
        self.update_fov()

    def update_fov(self):
        update_visibility(
            self.game_map, self.visible, self.seen, self.player.x, self.player.y, self.fov_radius
        )

    # -- queries the renderer uses ----------------------------------------

    def monster_at(self, x, y):
        for e in self.entities:
            if isinstance(e, Monster) and e.alive and e.x == x and e.y == y:
                return e
        return None

    def melee_opponents(self):
        """Living monsters in view that are orthogonally adjacent to the
        player, i.e. close enough that one of the two can hit the other."""
        return [
            e
            for e in self.entities
            if isinstance(e, Monster)
            and e.alive
            and e.is_adjacent(self.player)
            and self.visible[e.y][e.x]
        ]

    def zoom_opponents(self):
        """Who the combat zoom frames: melee_opponents(), plus -- for a
        reach weapon (the spear) -- every monster _reach_target would hit
        in one of the four directions. Adjacent ones come first."""
        found = self.melee_opponents()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            target = self._reach_target(dx, dy)
            if target is not None and target not in found:
                found.append(target)
        return found

    def visible_monsters(self):
        """Living monsters in the player's view."""
        return [
            e
            for e in self.entities
            if isinstance(e, Monster) and e.alive and self.visible[e.y][e.x]
        ]

    def monsters_within(self, radius):
        """Living monsters in view within `radius` of the player, by
        Chebyshev distance (a loose "nearby" check, like chase range -- not
        an adjacency test). The combat zoom holds while any is this close."""
        return [m for m in self.visible_monsters() if m.distance_to(self.player) <= radius]

    def chest_at(self, x, y):
        for e in self.entities:
            if isinstance(e, Chest) and e.x == x and e.y == y:
                return e
        return None

    def arrows_at(self, x, y):
        for e in self.entities:
            if isinstance(e, ArrowPile) and e.x == x and e.y == y:
                return e
        return None

    def shrine_at(self, x, y):
        for e in self.entities:
            if isinstance(e, Shrine) and e.x == x and e.y == y:
                return e
        return None

    def is_visible(self, x, y):
        return self.visible[y][x]

    def visible_entities(self):
        """Living entities in view. The `alive` filter matters now that the
        renderer draws mid-round: a monster killed during the player's half
        must not still be on screen while the monster half plays out."""
        return [e for e in self.entities if getattr(e, 'alive', True) and self.visible[e.y][e.x]]

    def log(self, text):
        self.messages.append(text)
