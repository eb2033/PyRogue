"""The whole world in one object: GameState, the composition root.

GameState knows nothing about pygame or keys. It takes semantic actions (see
game.actions.Action) and advances the world, so the game loop never sees a
keycode.

It holds the world's state -- the floor, the entities, the player, the
round's event stream, the abilities' cooldowns, the belt, the shop -- and
is the one object main.py and the renderer talk to. The rules live in
focused modules, and GameState's methods of the same names delegate to
them:

- game/turns.py -- the turn controller: handle_action's dispatch, the
  player's half (melee strikes), the monsters' half (end_player_phase,
  step_monster_phase), end_turn. The round's two halves are described
  there.
- game/fight.py -- attack(), crits, the player's dodge, the warrior's
  parry and riposte, monster melee and shots, a boss's summons.
- game/moves.py -- walking, bumping, a spear's reach, the archer's hop.
- game/loot.py -- chests, shrines, choices, the shop, boons, gold and
  arrows, the potion belt.
- game/floor.py -- building and populating a floor, descending.
- game/archery.py -- the player's bow shots.

The constants imported `as` themselves below (PARRY_COOLDOWN,
HANDLED_ACTIONS, BASE_CRIT_CHANCE...) are re-exported for the renderer and
the tests, which import them from here. Patch them where they live
(game.fight.BASE_CRIT_CHANCE), not here.
"""

import random
from contextlib import contextmanager
from typing import Any

from game import archery, fight, floor, loot, moves, sound
from game.combat import Hit, Shot
from game.dungeon import map_size
from game.entity import Player
from game.fight import BASE_CRIT_CHANCE as BASE_CRIT_CHANCE
from game.fight import CRIT_MULTIPLIER as CRIT_MULTIPLIER
from game.fight import PARRY_COOLDOWN as PARRY_COOLDOWN
from game.fight import crit_chance as crit_chance
from game.floor import DESCENT_HEAL_FRACTION as DESCENT_HEAL_FRACTION
from game.fov import update_visibility
from game.gold import GoldPile
from game.item import STARTING_ARMOR, STARTING_WEAPON, Chest, Item, gear_defense, gear_power
from game.monster import Monster
from game.quiver import QUIVER_CAPACITY, ArrowPile
from game.rect import Rect
from game.shop import Shop, Shopkeeper
from game.shrine import Shrine
from game.turns import HANDLED_ACTIONS as HANDLED_ACTIONS
from game.turns import TurnController

# class name -> (hp, power). Archers hit softer but get a free ranged option;
# warriors are the straightforward melee bruiser the spec describes.
CLASS_STATS = {
    'warrior': (60, 4),
    'archer': (45, 3),
}
DEFAULT_CLASS = 'warrior'
# The message log keeps this many lines; the log board shows a dozen at most.
MAX_MESSAGES = 200
# The archer sees this many tiles farther than the base fov_radius (a warrior
# sees exactly the base): a ranged class needs to spot targets earlier.
ARCHER_FOV_BONUS = 2


class GameState:
    def __init__(self, width, height, fov_radius=6, char_class=DEFAULT_CLASS, seed=None):
        """`width` x `height`: the base map size (MAP_WIDTH/MAP_HEIGHT), the
        map for ungrown rooms. Each floor's map is bigger -- dungeon.map_size
        -- and self.width/self.height are the current floor's, reset by
        next_level.

        `seed` seeds self.rng, the one random generator every roll of this
        game goes through (level generation, spawning, chests, shrines,
        shops, monster AI, crits, dodges, summons, gold). The same seed and
        the same actions give the same game; None seeds it from the OS. The
        global `random` module is never used."""
        char_class = char_class if char_class in CLASS_STATS else DEFAULT_CLASS
        self.rng = random.Random(seed)
        self.base_width = width
        self.base_height = height
        # This floor's size, map, rooms and FOV/fog grids: floor.build_map
        # fills them in (and again on every new floor).
        self.width, self.height = map_size(width, height, 1)
        self.game_map: list[list[str]] = []
        self.rooms: list[Rect] = []
        self.visible: list[list[bool]] = []
        self.seen: list[list[bool]] = []
        # The cells update_fov lit last, and the `visible` grid they're in.
        self._lit: set[tuple[int, int]] = set()
        self._lit_grid: list[list[bool]] | None = None
        self.fov_radius = fov_radius + (ARCHER_FOV_BONUS if char_class == 'archer' else 0)
        self.running = True
        self.game_over = False
        # Set by 'restart' on the game-over screen: the run has ended and the
        # caller (main.play) goes back to the title screen instead of quitting.
        self.restart_requested = False
        self.depth = 1
        self.messages = []
        # This round's events (Hit, Shot, Parry, SoundEvent), oldest first,
        # in serial order -- see game/combat.py. Cleared when the player acts;
        # the serial keeps counting across rounds and levels.
        self.events = []
        self._serial = 0
        # True while a shot is in flight (recording_shot): its Hits belong to
        # the Shot, not to the stream.
        self._shot_open = False
        # Player actions taken so far (+1 per turn-consuming action in
        # handle_action; never per frame or per monster). The combat zoom's
        # hold (render/camera.py) counts turns with it.
        self.turn = 0
        # GameState.turn when the archer last hopped (None: never). Not saved.
        self.last_hop_turn: int | None = None
        # True after a successful hop until the archer's next shot, which
        # always crits (archery.shoot spends it, hit or miss). Not saved.
        self.hop_crit = False
        # True after the archer's Q primed a hop: the next movement key (WASD
        # or an arrow) picks its direction; any other key cancels it. Priming
        # takes no turn. Not saved.
        self.hop_primed = False
        # The warrior's parry (Q): armed until the next monster melee hit that
        # would land on the player, which it nullifies (fight.monster_melee);
        # parry_progress() is its recharge for the bar. last_parry_turn is
        # GameState.turn when Q armed it (None: never). Neither is saved.
        self.parry_armed = False
        self.last_parry_turn: int | None = None
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
        # floor.spawn_level_monsters on every new floor.
        self.boss_arena: Rect | None = None
        # This floor's shop and its shopkeeper (game/shop.py), or None off
        # shop floors; shop_open is True while the shop screen is up (from
        # walking into the shopkeeper until 'skip'). Set by
        # floor.populate_level.
        self.shop: Shop | None = None
        self.shopkeeper: Shopkeeper | None = None
        self.shop_open = False
        # The round's bookkeeping: the monster queue, owed strikes, the free
        # turn (game/turns.py).
        self.controller = TurnController(self)

        floor.build_map(self)

        hp, power = CLASS_STATS[char_class]

        px, py = self.rooms[0].center()
        self.player = Player(px, py, '@', color=1, name='you')
        self.player.char_class = char_class
        self.player.hp = hp
        self.player.max_hp = hp
        self.player.base_power = power
        self.player.power = power
        self.player.defense = 0
        self.player.weapon = Item(0, 0, *STARTING_WEAPON.get(char_class, ('weapon', 'common')))
        self.player.armor = None
        if char_class in STARTING_ARMOR:
            self.player.armor = Item(0, 0, *STARTING_ARMOR[char_class])
        self.player.power = gear_power(self.player)
        self.player.defense = gear_defense(self.player)
        self.player.items_used = []
        self.player.quiver = QUIVER_CAPACITY if char_class == 'archer' else None
        self.player.alive = True

        # The archer's bookkeeping (see shoot_arrow and TurnController.
        # spend_turn). restock_progress: player turns towards the next free
        # arrow, 0..RESTOCK_TURNS (it reads RESTOCK_TURNS on the turn one is
        # added, and stays 0 while the quiver is full). reload_turns: turns
        # until a heavy crossbow can shoot again. marked: the hunter's bow's
        # quarry. tempo_shots: quickdraw shots since its last free one.
        self.restock_progress = 0
        self.reload_turns = 0
        self.marked: Monster | None = None
        self.tempo_shots = 0

        self.entities: list[Any] = floor.populate_level(self)

        self.update_fov()

    # -- turn resolution (game/turns.py) -------------------------------------

    def handle_action(self, action):
        """Apply one semantic action. Returns True if a turn was consumed."""
        return self.controller.handle_action(action)

    def grant_free_turn(self):
        """Make the current player action free: it queues no monster half
        (a quickdraw's free shot). Cleared when the next action starts."""
        self.controller.free_turn = True

    @property
    def free_turn(self):
        """True if the current action was made free by grant_free_turn."""
        return self.controller.free_turn

    def melee(self, target):
        """The player's melee attack on `target` (TurnController.melee)."""
        self.controller.melee(target)

    def strike_pending(self):
        """True while the player's current action still owes a melee strike."""
        return self.controller.strike_pending()

    def step_strike(self):
        """Land the next queued strike (TurnController.step_strike)."""
        return self.controller.step_strike()

    def resolve_player_phase(self):
        """Land every queued strike at once, ending the player's half."""
        self.controller.resolve_player_phase()

    def cancel_strikes(self):
        """Drop any strikes still owed (the level they were aimed at is gone)."""
        self.controller.clear_strikes()

    def end_player_phase(self):
        """Close the player's half of the round and queue the monsters'."""
        self.controller.end_player_phase()

    def defer_to_next_round(self, monster):
        """Keep a monster that just appeared out of this round's queue
        (TurnController.defer_to_next_round)."""
        self.controller.defer_to_next_round(monster)

    def monster_phase_pending(self):
        return self.controller.monster_phase_pending()

    def cancel_monster_phase(self):
        """Drop any queued monsters (the level they belong to is gone)."""
        self.controller.cancel_monster_phase()

    def step_monster_phase(self):
        """Resolve queued monsters until one does something the player can
        see; False once the round is over (TurnController.step_monster_phase)."""
        return self.controller.step_monster_phase()

    def end_turn(self):
        """Run the rest of the round in one go (TurnController.end_turn)."""
        self.controller.end_turn()

    # -- the player's actions (game/moves.py, game/loot.py, game/fight.py) -----

    def try_move_player(self, dx, dy):
        """Walk, bump-attack, or reach-attack in (dx, dy); False only if the
        move is refused and takes no turn (moves.try_move_player)."""
        return moves.try_move_player(self, dx, dy)

    def prime_hop(self):
        """The archer's Q: ready a hop (moves.prime_hop)."""
        return moves.prime_hop(self)

    def cancel_hop(self):
        """Drop a primed hop (moves.cancel_hop)."""
        moves.cancel_hop(self)

    def hop(self, dx, dy):
        """The archer's hop in (dx, dy) (moves.hop)."""
        return moves.hop(self, dx, dy)

    def hop_shot_ready(self, dx, dy):
        """Would a hop in (dx, dy) be a hand crossbow's hop-shot
        (moves.hop_shot_ready)?"""
        return moves.hop_shot_ready(self, dx, dy)

    def arm_parry(self):
        """The warrior's Q: ready a parry (fight.arm_parry)."""
        return fight.arm_parry(self)

    def parry_progress(self):
        """The parry's recharge, 0..PARRY_COOLDOWN, for the renderer's bar."""
        return fight.parry_progress(self)

    def shoot_arrow(self, dx, dy):
        """Archer-only ranged attack: travels in a straight line until it
        hits a wall or the first monster in its path (more with a longbow),
        with the equipped bow's effects -- see game/archery.py. Returns
        False, taking nothing, if the shot is refused (no arrows, or a
        crossbow still reloading)."""
        return archery.shoot(self, dx, dy)

    def drink_from_belt(self):
        """Drink belt[0]; False, logging why, if it can't (loot.drink_from_belt)."""
        return loot.drink_from_belt(self)

    def pick_up_gold(self, pile):
        """Take all of `pile` (loot.pick_up_gold)."""
        loot.pick_up_gold(self, pile)

    def pick_up_arrows(self, pile):
        """Take as many of `pile`'s arrows as fit (loot.pick_up_arrows)."""
        loot.pick_up_arrows(self, pile)

    def open_chest(self, chest):
        """Open `chest` (loot.open_chest)."""
        return loot.open_chest(self, chest)

    def visit_shrine(self, shrine):
        """Kneel at `shrine`: its boons become the pending choice."""
        loot.visit_shrine(self, shrine)

    @property
    def is_choosing(self):
        """True while an opened chest is waiting for the player to pick an
        item, or a shrine for a boon. Movement and every other turn action
        are blocked meanwhile."""
        return self.pending_choice is not None

    def choose(self, index):
        """Take offer `index` of the pending choice (loot.choose)."""
        loot.choose(self, index)

    def skip_choice(self):
        """Leave every offer of the pending choice (loot.skip_choice)."""
        loot.skip_choice(self)

    def buy(self, index: int) -> bool:
        """Buy shop offer `index` (loot.buy)."""
        return loot.buy(self, index)

    def take_boon(self, boon, source='shrine'):
        """Add `boon` to the player's boons (loot.take_boon)."""
        loot.take_boon(self, boon, source)

    def attack(self, attacker, defender, factor=1.0, crit=None):
        """One blow; returns its Hit, or None if dodged (fight.attack)."""
        return fight.attack(self, attacker, defender, factor, crit)

    # Kept for the tests that drive one monster's attack or a boss's summons
    # directly.
    def _monster_melee(self, monster):
        fight.monster_melee(self, monster)

    def _monster_shot(self, monster):
        fight.monster_shot(self, monster)

    def _summon_goblins(self, boss):
        fight.summon_goblins(self, boss)

    # -- floors (game/floor.py) ------------------------------------------------

    def try_descend(self):
        """The stairs key (floor.try_descend)."""
        return floor.try_descend(self)

    def next_level(self):
        """Build the next floor and move the player there (floor.next_level)."""
        floor.next_level(self)

    def _spawn_level_monsters(self, exclude=(), boss_room=None, occupied=None):
        return floor.spawn_level_monsters(self, exclude, boss_room, occupied)

    # -- the event stream --------------------------------------------------

    def sound(self, slot: str) -> None:
        """Record that `slot` (game.sound.SLOTS) should play now."""
        self.events.append(sound.SoundEvent(self.next_serial(), slot))

    def next_serial(self):
        """The next serial for an event record: one counter for every kind,
        so the stream sorts in the order things happened."""
        self._serial += 1
        return self._serial

    def record_hit(self, hit):
        """Put `hit` in the stream -- unless a shot is recording
        (recording_shot), whose Arrows own their Hits."""
        if not self._shot_open:
            self.events.append(hit)

    def events_since(self, serial):
        """This round's events newer than `serial` (a reader's cursor: the
        last serial it handled), oldest first."""
        return [event for event in self.events if event.serial > serial]

    def events_of(self, kind):
        """This round's stream records of type `kind` (Shot, Parry,
        SoundEvent...), oldest first. For every Hit, Shots' included, see
        hits()."""
        return [event for event in self.events if isinstance(event, kind)]

    def hits(self):
        """Every Hit this round, oldest first: the stream's own (melee) and
        those its Shots own (arrows)."""
        found = []
        for event in self.events:
            if isinstance(event, Hit):
                found.append(event)
            elif isinstance(event, Shot):
                found.extend(event.all_hits())
        return found

    @contextmanager
    def recording_shot(self):
        """Record one shot: yields a list for the caller to append each
        arrow's Arrow to as it flies. The Shot's serial and place in the
        stream are taken before any arrow flies, so it sorts before
        everything it caused; the Hits made meanwhile (attack() returns them)
        belong to the Shot and don't go into the stream themselves."""
        index, serial = len(self.events), self.next_serial()
        arrows = []
        self._shot_open = True
        try:
            yield arrows
        finally:
            self._shot_open = False
        self.events.insert(index, Shot(serial, tuple(arrows)))

    def update_fov(self):
        """Recompute what the player sees. Depends only on the map, the
        player's tile and fov_radius -- monsters don't block sight -- so
        game/turns.py calls it once per player half (and on a new floor),
        never per monster. Only the cells lit last time are cleared, as long
        as `visible` is still the grid they were lit in (a new floor builds
        a new one, which is cleared whole). So only update_fov may write
        `visible`: a cell set anywhere else would never be cleared."""
        previous = self._lit if self._lit_grid is self.visible else None
        self._lit = update_visibility(
            self.game_map,
            self.visible,
            self.seen,
            self.player.x,
            self.player.y,
            self.fov_radius,
            previous,
        )
        self._lit_grid = self.visible

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
        reach weapon (the spear) -- every monster moves.reach_target would
        hit in one of the four directions. Adjacent ones come first."""
        found = self.melee_opponents()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            target = moves.reach_target(self, dx, dy)
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

    def gold_at(self, x, y):
        for e in self.entities:
            if isinstance(e, GoldPile) and e.x == x and e.y == y:
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
        if len(self.messages) > MAX_MESSAGES:
            del self.messages[:-MAX_MESSAGES]
