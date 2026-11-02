"""The turn controller: what an action does, and the round's two halves.

A round has two halves. handle_action() resolves the player's half and then
*queues* the monsters rather than running them, so the caller can draw the
result of the player's own action before anything answers it; the caller
then drives step_monster_phase() until the queue drains. Monsters resolve
strictly one at a time against the current world -- if the player dies
partway through, the monsters still queued never act. end_turn() runs both
halves back to back for callers that don't care about the split (tests,
headless use).

The player's half can itself take more than one step: a rapier's second
strike is queued by melee() rather than swung at once, so the first hit is
drawn (and its beat played) before the second one's damage is rolled. The
caller drives step_strike() while strike_pending(); the last strike ends
the player's half (end_player_phase), and only then are the monsters
queued. resolve_player_phase() does that in one go for headless callers.

TurnController owns the round's bookkeeping (the monster queue, the owed
strikes, the free-turn and alert flags); GameState creates one and exposes
its methods under the same names. Everything else it reads or changes goes
through the state's public attributes and methods.
"""

from typing import TYPE_CHECKING

from game import fight, level, sound
from game.actions import Action
from game.monster import Monster
from game.quiver import QUIVER_CAPACITY, RESTOCK_TURNS

if TYPE_CHECKING:
    from game.state import GameState

# The archer's bump-attack damage factor (a point-blank arrow uses the same).
ARCHER_MELEE_FACTOR = 0.5

# Semantic action -> (dx, dy) in game coordinates. y grows downward.
MOVE_DELTAS = {
    Action.MOVE_N: (0, -1),
    Action.MOVE_S: (0, 1),
    Action.MOVE_W: (-1, 0),
    Action.MOVE_E: (1, 0),
}

# Arrow-key actions -> the same deltas. What they *do* depends on class: see
# handle_action. Kept as a separate dict (rather than reusing MOVE_DELTAS)
# so the two concerns -- "which direction" and "move or shoot" -- stay
# decoupled at the call site.
SHOOT_DELTAS = {
    Action.SHOOT_N: (0, -1),
    Action.SHOOT_S: (0, 1),
    Action.SHOOT_W: (-1, 0),
    Action.SHOOT_E: (1, 0),
}

# Keys 1-3 on a chest's choice screen -> index into pending_choice; keys
# 1-5 in the shop -> index into shop.offers.
CHOOSE_INDEX = {
    Action.CHOOSE_1: 0,
    Action.CHOOSE_2: 1,
    Action.CHOOSE_3: 2,
    Action.CHOOSE_4: 3,
    Action.CHOOSE_5: 4,
}

# Every Action handle_action acts on. QUIT is handled here too (it stops the
# loop); tests/test_actions.py checks this covers all of Action.
HANDLED_ACTIONS = frozenset(
    {
        Action.WAIT,
        Action.DESCEND,
        Action.QUIT,
        Action.RESTART,
        Action.ABILITY,
        Action.SKIP,
        Action.DRINK,
        *MOVE_DELTAS,
        *SHOOT_DELTAS,
        *CHOOSE_INDEX,
    }
)


class TurnController:
    """Turn resolution for one GameState (see the module docstring)."""

    def __init__(self, state: 'GameState'):
        self.state = state
        # Monsters still owing a turn in the current round. See
        # end_player_phase.
        self.pending_monsters: list[Monster] = []
        # The player's melee strikes still owed this action (a rapier's
        # 2nd), and the monster they are aimed at. See melee and step_strike.
        self.strike_target: Monster | None = None
        self.strikes_owed = 0
        # True after a free (quickdraw) shot: that action queues no monsters.
        self.free_turn = False
        # True after a hand crossbow's hop-shot hop: the hop's monster half
        # is still owed, to the next action (see _aim_hop and _deferred_hop).
        self.hop_half_owed = False
        # What the last handle_action returned (did it take a turn?), or
        # None if none has run since the last end_turn. See end_turn.
        self.last_turn_taken: bool | None = None
        # True once a monster has noticed the player this round (one
        # enemy_alert a round); reset in end_player_phase.
        self.alerted_this_round = False
        # Monsters that appeared this round (a slime's split-offs): left out
        # of this round's queue, they first act in the next one. Cleared when
        # the round ends and when the player next acts.
        self.deferred: list[Monster] = []

    # -- the player's half --------------------------------------------------

    def handle_action(self, action):
        """Apply one semantic action. Returns True if a turn was consumed."""
        took = self._dispatch(action)
        self.last_turn_taken = took
        return took

    def _dispatch(self, action):
        state = self.state
        if action is None:
            return False
        if action == Action.RESTART:
            # Only on the death screen ('press r to restart'); mid-game it
            # does nothing at all and takes no turn.
            if state.game_over:
                state.restart_requested = True
                state.running = False
            return False
        # A strike left over from the last action (a headless caller that
        # never stepped it) lands first: the player's half of that round is
        # always finished before anything else happens.
        self.resolve_player_phase()
        state.events = []
        self.free_turn = False
        self.deferred = []

        if action == Action.QUIT:
            state.running = False
            return False

        if self.hop_half_owed:
            done = self._deferred_hop(action)
            if done is not None:
                return done
            if state.game_over:
                # The hop's monster half killed the player: the action that
                # followed does nothing (Q must not quit past the death screen).
                return False

        if state.shop_open and not state.game_over:
            # The shop screen: keys 1-5 buy, 'skip' leaves, everything else
            # is ignored. None of it takes a turn.
            if action in CHOOSE_INDEX:
                state.buy(CHOOSE_INDEX[action])
            elif action == Action.SKIP:
                state.shop_open = False
                state.log('You leave the shop.')
            return False

        if action == Action.ABILITY:
            return self._ability()

        if state.game_over:
            return False

        if state.hop_primed:
            return self._aim_hop(action)

        if action in CHOOSE_INDEX:
            # Only means something on a choice screen (or in the shop,
            # above); never takes a turn.
            index = CHOOSE_INDEX[action]
            if state.pending_choice is not None and index < len(state.pending_choice):
                state.choose(index)
            return False

        if action == Action.SKIP:
            # Key 4 (or Space, on the choice screen): leave every offer.
            # Only means something on a choice screen; never takes a turn.
            if state.pending_choice is not None:
                state.skip_choice()
            return False

        if state.is_choosing:
            return False  # a chest's choice must be made first: see choose()

        # A move refused by try_move_player (a potion chest while the belt is
        # full at full HP) takes no turn: nothing happened, so monsters don't
        # act and GameState.turn doesn't advance. Bumping a wall still does,
        # as it always has.
        if action in MOVE_DELTAS:
            return self._move(*MOVE_DELTAS[action])

        if action in SHOOT_DELTAS:
            dx, dy = SHOOT_DELTAS[action]
            if state.player.char_class != 'archer':
                return self._move(dx, dy)
            # A refused shot (no arrows, still reloading) takes no turn.
            if not state.shoot_arrow(dx, dy):
                return False
            self.spend_turn(shot=True)
            if self.free_turn:
                state.update_fov()  # a quickdraw's free shot: no monster half
            else:
                self.end_player_phase()
            return True

        if action == Action.DRINK:
            # Drink belt[0]. A turn, like any other action -- unless the
            # belt is empty or HP is full, which only logs.
            if not state.drink_from_belt():
                return False
            self.spend_turn()
            self.end_player_phase()
            return True

        if action == Action.WAIT:
            self.spend_turn()
            self.end_player_phase()
            return True

        if action == Action.DESCEND:
            if state.try_descend():
                self.spend_turn()
                return True
            return False

        return False

    def _ability(self):
        """Q. On the death screen ('press q to quit') it is the quit key.
        Mid-game it is the class's ability: the archer's hop, or (any other
        class, i.e. the warrior) the parry."""
        state = self.state
        if state.game_over:
            state.running = False
            return False
        if state.is_choosing:
            return False
        if state.player.char_class == 'archer':
            # Q primes the hop (or, pressed again, cancels it): no turn
            # either way. The direction key that follows is the hop.
            if state.hop_primed:
                state.cancel_hop()
            else:
                state.prime_hop()
            return False
        if not state.arm_parry():
            return False
        self.spend_turn()
        state.last_parry_turn = state.turn
        self.end_player_phase()
        return True

    def _aim_hop(self, action):
        """The archer primed a hop: a movement key (WASD or an arrow) is its
        direction; anything else cancels it. Neither moves the player the
        ordinary way or shoots."""
        state = self.state
        delta = MOVE_DELTAS.get(action) or SHOOT_DELTAS.get(action)
        if delta is None:
            state.cancel_hop()
            return False
        # Asked before the hop moves her: is it a hop-shot (moves.py)?
        hop_shot = state.hop_shot_ready(*delta)
        if not state.hop(*delta):
            return False  # nowhere to go that way: still primed
        state.hop_primed = False
        self.spend_turn()
        state.last_hop_turn = state.turn
        state.hop_crit = True
        if hop_shot:
            # The hand crossbow's hop-shot: the turn isn't over yet. No
            # monster half now; the next action decides (_deferred_hop).
            self.hop_half_owed = True
            state.update_fov()
            state.log('You hop clear: shoot before they answer!')
        else:
            self.end_player_phase()
        return True

    def _deferred_hop(self, action):
        """The action after a hop-shot hop. A shot that fires ends the
        turn the hop began: the monsters' half is queued after both, once,
        and the shot spends no turn of its own (the hop counted it). Anything
        else -- a refused shot included -- first resolves the hop's monster
        half all at once, then runs as a normal action. Returns True if the
        action was the hop-shot's shot, False if it was a refused shot (it
        took no turn and is not run again, so its log line appears once),
        and None if the caller should go on and run the action."""
        state = self.state
        self.hop_half_owed = False
        shot = action in SHOOT_DELTAS and state.player.char_class == 'archer'
        fired = shot and state.shoot_arrow(*SHOOT_DELTAS[action])
        self.end_player_phase()
        if fired:
            return True
        while self.step_monster_phase():
            pass
        return False if shot else None

    def _move(self, dx, dy):
        """A walk, bump or reach in (dx, dy). The player's half ends here --
        unless it started a multi-strike melee, whose last strike ends it
        (step_strike)."""
        if not self.state.try_move_player(dx, dy):
            return False
        self.spend_turn()
        if not self.strike_pending():
            self.end_player_phase()
        return True

    def spend_turn(self, shot=False):
        """A turn-taking player action happened: count it (GameState.turn),
        tick a heavy crossbow's reload down -- except on the shot that just
        started it -- and advance the quiver's restock."""
        state = self.state
        state.turn += 1
        if not shot and state.reload_turns > 0:
            state.reload_turns -= 1
        self._restock()

    def _restock(self):
        """One more turn towards a free arrow: every RESTOCK_TURNS turns the
        quiver gains one, up to QUIVER_CAPACITY. restock_progress shows how
        far along it is: 1, 2, 3 (the arrow is added), then 1 again; it sits
        at 0 while the quiver is full. No quiver (a warrior): nothing."""
        state = self.state
        player = state.player
        if player.quiver is None:
            return
        if player.quiver >= QUIVER_CAPACITY:
            state.restock_progress = 0
            return
        if state.restock_progress >= RESTOCK_TURNS:
            state.restock_progress = 0
        state.restock_progress += 1
        if state.restock_progress >= RESTOCK_TURNS:
            player.quiver += 1

    # -- melee strikes ---------------------------------------------------------

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
        state = self.state
        weapon = state.player.weapon
        strikes = weapon.strikes if weapon is not None else 1
        state.sound(sound.melee_slot(weapon))
        # An archer in melee is out of her element: half damage.
        factor = ARCHER_MELEE_FACTOR if state.player.char_class == 'archer' else 1.0
        fight.attack(state, state.player, target, factor)
        if strikes > 1 and target.alive:
            self.strike_target = target
            self.strikes_owed = strikes - 1
            return
        fight.cleave(state, target)

    def strike_pending(self):
        """True while the player's current action still owes a melee strike
        (a rapier's second) -- the player's half of the round isn't over."""
        return self.strike_target is not None

    def step_strike(self):
        """Land the next queued strike. Returns True if it hit something (so
        the caller should show it), False if it was skipped: the target died
        or is gone, or the player is dead. Once no strike is owed the
        player's half ends (end_player_phase) -- unless the player is dead,
        when nothing more happens at all."""
        state = self.state
        target = self.strike_target
        if target is None:
            return False
        if state.game_over or not state.player.alive:
            self.clear_strikes()
            return False
        hit = target.alive and target in state.entities
        if hit:
            state.sound(sound.melee_slot(state.player.weapon))
            fight.attack(state, state.player, target)
            self.strikes_owed -= 1
        if not hit or not target.alive or self.strikes_owed <= 0:
            self.clear_strikes()
            fight.cleave(state, target)
            self.end_player_phase()
        return hit

    def resolve_player_phase(self):
        """Land every queued strike at once, ending the player's half: the
        headless equivalent of main.resolve_player_strikes. Does nothing
        when no strike is owed."""
        while self.strike_pending():
            self.step_strike()

    def clear_strikes(self):
        """Drop any strikes still owed (the player died, or the level they
        were aimed at is gone)."""
        self.strike_target = None
        self.strikes_owed = 0

    # -- the monsters' half ----------------------------------------------------

    def defer_to_next_round(self, monster):
        """`monster` just appeared (a split-off slime): it isn't queued this
        round, even if the player's half is still running."""
        self.deferred.append(monster)

    def end_player_phase(self):
        """Close the player's half of the round and queue the monsters'.

        Resolves nothing on the monsters' behalf -- it only refreshes what
        the player can see, so a caller can draw the outcome of the player's
        own action before any monster answers it.
        """
        state = self.state
        state.update_fov()
        self.alerted_this_round = False
        self.pending_monsters = [
            e
            for e in state.entities
            if e is not state.player
            and getattr(e, 'alive', True)
            and getattr(e, 'take_turn', None) is not None
            and not any(e is d for d in self.deferred)
        ]

    def monster_phase_pending(self):
        return bool(self.pending_monsters)

    def cancel_monster_phase(self):
        """Drop any queued monsters -- used when the level they belong to is
        thrown away underneath them (descending to the next floor)."""
        self.pending_monsters = []
        self.hop_half_owed = False

    def step_monster_phase(self):
        """Resolve queued monsters until one of them does something the
        player can see, or the queue runs dry.

        Returns True if the caller should show the result (a monster
        attacked, or moved somewhere the player can see) and False once the
        round is over. Monsters acting out of sight are folded into the same
        call, so crossing an empty dungeon costs no extra frames.
        """
        state = self.state
        while self.pending_monsters:
            monster = self.pending_monsters.pop(0)
            if not getattr(monster, 'alive', True):
                continue  # killed earlier in this same round

            was_seen = state.is_visible(monster.x, monster.y)
            before = (monster.x, monster.y)
            was_chasing = monster.chasing
            # Built fresh for each monster, so it reflects the moves already
            # made earlier in the same round (game/level.py has the rules).
            result = monster.take_turn(
                state.player,
                state.game_map,
                occupied=level.blocker_tiles(state, level.MONSTER_MOVE, ignore=monster),
                sees_player=was_seen,
                rng=state.rng,
            )
            if not self.alerted_this_round and not was_chasing:
                if monster.chasing or result in ('attack', 'shoot'):
                    self.alerted_this_round = True
                    state.sound(sound.ENEMY_ALERT)
            if result == 'attack':
                fight.monster_melee(state, monster)
            elif result == 'shoot':
                fight.monster_shot(state, monster)
            # No FOV refresh here: it depends only on the map and the
            # player's tile, and no monster's turn changes either (monsters
            # don't block sight), so end_player_phase's is still current.

            if self._player_just_died():
                # Nothing swings at a corpse: whoever is still queued this
                # round simply never acts.
                self.cancel_monster_phase()
                self._finish_round()
                return True

            moved_in_view = (monster.x, monster.y) != before and (
                was_seen or state.is_visible(monster.x, monster.y)
            )
            if result in ('attack', 'shoot') or moved_in_view:
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

        After a handle_action it resolves exactly what main.run would: the
        strikes and monsters that action queued, and nothing else -- so an
        action that took no turn (a refused choice, an empty belt), a free
        quickdraw shot, a descent, or a round already stepped through gives
        the monsters no extra move. Called with no handle_action since the
        last end_turn (a test that set the board up by hand), it queues and
        runs a fresh monster half.
        """
        self.resolve_player_phase()
        last, self.last_turn_taken = self.last_turn_taken, None
        # A free (quickdraw) shot has no monster half to run.
        free, self.free_turn = self.free_turn, False
        if last is None and not self.monster_phase_pending() and not free:
            self.hop_half_owed = False  # a hop-shot's deferred half is this one
            self.end_player_phase()
        while self.step_monster_phase():
            pass

    def _player_just_died(self):
        """True only on the single step that kills the player, so the death
        is logged once and the round stops there."""
        state = self.state
        if state.player.hp > 0 or state.game_over:
            return False
        state.game_over = True
        state.shop_open = False
        state.log('You died.')
        return True

    def _finish_round(self):
        state = self.state
        self.deferred = []
        state.entities = [
            e for e in state.entities if e is state.player or getattr(e, 'alive', True)
        ]
