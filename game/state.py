"""The whole world in one object, plus turn resolution.

GameState knows nothing about curses, pygame, or keys. It takes semantic actions
(see render.base.Action) and advances the world. That is what lets one game loop
drive either renderer.

A round has two halves. handle_action() resolves the player's half and then
*queues* the monsters rather than running them, so the caller can draw the
result of the player's own action before anything answers it; the caller then
drives step_monster_phase() until the queue drains. Monsters resolve strictly
one at a time against the current world -- if the player dies partway through,
the monsters still queued never act. end_turn() runs both halves back to back
for callers that don't care about the split (tests, headless use).
"""

from game import paths
from game.combat import Hit
from game.dungeon import generate_dungeon, place_stairs
from game.entity import Entity, Player
from game.fov import update_visibility
from game.item import Chest, spawn_boss_chest, spawn_chests
from game.monster import Monster, is_boss_level, spawn_boss, spawn_monsters
from game.save import apply_dict, load_game, save_game
from game.tiles import STAIRS_DOWN, is_walkable

# None means "use paths.save_path()" (the per-user data dir), resolved at
# save/load time rather than import time. Tests -- or anything else that wants
# saves somewhere specific -- may set this to an explicit path instead.
SAVE_PATH = None


def current_save_path():
    """Where 's'/'l' write and read the save, migrating a legacy
    ./savegame.json into the user data dir on first use."""
    if SAVE_PATH is not None:
        return SAVE_PATH
    target = paths.save_path()
    paths.migrate_legacy_save(target)
    return target

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

# class name -> (hp, power). Archers hit softer but get a free ranged option;
# warriors are the straightforward melee bruiser the spec describes.
CLASS_STATS = {
    'warrior': (25, 4),
    'archer': (18, 3),
}
DEFAULT_CLASS = 'warrior'


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

        self.game_map, self.rooms = generate_dungeon(width, height)
        place_stairs(self.game_map, self.rooms)
        self.visible = [[False] * width for _ in range(height)]
        self.seen = [[False] * width for _ in range(height)]

        char_class = char_class if char_class in CLASS_STATS else DEFAULT_CLASS
        hp, power = CLASS_STATS[char_class]

        px, py = self.rooms[0].center()
        self.player = Player(px, py)
        self.player.char_class = char_class
        self.player.hp = hp
        self.player.max_hp = hp
        self.player.base_power = power
        self.player.power = power

        self.entities: list[Entity] = [
            self.player, *self._spawn_level_monsters(), *spawn_chests(self.rooms)]

        # Monsters still owing a turn in the current round. See end_player_phase.
        self._pending_monsters: list[Monster] = []

        self.update_fov()

    def _spawn_level_monsters(self):
        monsters = spawn_monsters(self.rooms, depth=self.depth)
        if is_boss_level(self.depth):
            monsters.append(spawn_boss(self.rooms, self.depth))
        return monsters

    # -- turn resolution ---------------------------------------------------

    def handle_action(self, action):
        """Apply one semantic action. Returns True if a turn was consumed."""
        if action is None:
            return False
        self.combat_events = []

        if action == 'quit':
            self.running = False
            return False

        if action == 'save':
            try:
                save_game(self, current_save_path())
            except OSError as exc:
                self.log(f'Save failed: {exc.strerror or exc}')
            else:
                self.log('Game saved.')
            return False

        if action == 'load':
            try:
                data = load_game(current_save_path())
            except (OSError, ValueError) as exc:
                self.log(f'Load failed: {getattr(exc, "strerror", None) or exc}')
                return False
            if data is None:
                self.log('No save file found.')
            else:
                apply_dict(self, data)
                self.log('Game loaded.')
            return False

        if self.game_over:
            return False

        if action in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[action]
            self.try_move_player(dx, dy)
            self.end_player_phase()
            return True

        if action in SHOOT_DELTAS:
            dx, dy = SHOOT_DELTAS[action]
            if self.player.char_class == 'archer':
                self.shoot_arrow(dx, dy)
            else:
                self.try_move_player(dx, dy)
            self.end_player_phase()
            return True

        if action == 'wait':
            self.end_player_phase()
            return True

        if action == 'descend':
            return self.try_descend()

        return False

    def try_move_player(self, dx, dy):
        nx, ny = self.player.x + dx, self.player.y + dy
        if not is_walkable(self.game_map, nx, ny):
            return

        monster = self.monster_at(nx, ny)
        if monster is not None:
            self.attack(self.player, monster)
            return

        self.player.move(dx, dy, self.game_map)

        chest = self.chest_at(self.player.x, self.player.y)
        if chest is not None:
            self.open_chest(chest)

    def open_chest(self, chest):
        """Roll the item table (depth-scaled -- see game/item.py) and apply
        whatever comes out immediately, same as walking onto a bare item
        used to work."""
        self.log('You open the chest.')
        item = chest.open(self.depth)
        item.apply(self.player, self.log)
        self.entities.remove(chest)

    def shoot_arrow(self, dx, dy):
        """Archer-only ranged attack: travels in a straight line until it
        hits a wall or the first monster in its path."""
        self.log('You loose an arrow.')
        x, y = self.player.x, self.player.y
        while True:
            x, y = x + dx, y + dy
            if not is_walkable(self.game_map, x, y):
                self.log('The arrow thuds into a wall.')
                return
            monster = self.monster_at(x, y)
            if monster is not None:
                self.attack(self.player, monster)
                return

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
        self.entities = [self.player, *self._spawn_level_monsters(), *spawn_chests(self.rooms)]
        if is_boss_level(self.depth):
            self.log(f'You descend to level {self.depth}. Something powerful lurks here...')
        else:
            self.log(f'You descend to level {self.depth}.')
        self.update_fov()

    def attack(self, attacker, defender):
        defense = getattr(defender, 'defense', 0)
        damage = max(1, attacker.power - defense)
        defender.hp -= damage
        subject = 'You' if attacker is self.player else attacker.name.capitalize()
        verb = 'hit' if attacker is self.player else 'hits'
        target = 'you' if defender is self.player else defender.name
        self.log(f'{subject} {verb} {target} for {damage}.')
        self._hit_serial += 1
        self.combat_events.append(Hit(self._hit_serial, attacker, defender, damage,
                                      defender.hp <= 0, defender.x, defender.y))
        if defender.hp <= 0:
            defender.alive = False
            if defender is not self.player:
                # The player's own death message is logged once by end_turn,
                # which also flips game_over -- avoid a duplicate line here.
                self.log(f'{defender.name.capitalize()} dies.')
                if getattr(defender, 'is_boss', False):
                    self.entities.append(spawn_boss_chest(defender.x, defender.y))
                    self.log('The boss drops a chest!')

    # -- the round, in two halves ------------------------------------------

    def end_player_phase(self):
        """Close the player's half of the round and queue the monsters'.

        Resolves nothing on the monsters' behalf -- it only refreshes what
        the player can see, so a caller can draw the outcome of the player's
        own action before any monster answers it.
        """
        self.update_fov()
        self._pending_monsters = [e for e in self.entities
                                  if isinstance(e, Monster) and e.alive]

    def monster_phase_pending(self):
        return bool(self._pending_monsters)

    def cancel_monster_phase(self):
        """Drop any queued monsters — used when the level they belong to is
        thrown away underneath them (descending, loading a save)."""
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
            result = monster.take_turn(self.player, self.game_map)
            if result == 'attack':
                self.attack(monster, self.player)
            self.update_fov()

            if self._player_just_died():
                # Nothing swings at a corpse: whoever is still queued this
                # round simply never acts.
                self.cancel_monster_phase()
                self._finish_round()
                return True

            moved_in_view = ((monster.x, monster.y) != before
                             and (was_seen or self.is_visible(monster.x, monster.y)))
            if result == 'attack' or moved_in_view:
                return True

        self._finish_round()
        return False

    def end_turn(self):
        """Run the monster half of the round in one go.

        The renderer-driven loop in main.py steps the phase frame by frame
        instead; this is the all-at-once equivalent for tests and any
        headless caller.
        """
        if not self.monster_phase_pending():
            self.end_player_phase()
        while self.step_monster_phase():
            pass

    def _player_just_died(self):
        """True only on the single step that kills the player, so the death
        is logged once and the round stops there."""
        if self.player.hp > 0 or self.game_over:
            return False
        self.game_over = True
        self.log('You died.')
        return True

    def _finish_round(self):
        self.entities = [e for e in self.entities
                         if e is self.player or getattr(e, 'alive', True)]
        self.update_fov()

    def update_fov(self):
        update_visibility(self.game_map, self.visible, self.seen,
                          self.player.x, self.player.y, self.fov_radius)

    # -- queries the renderer uses ----------------------------------------

    def monster_at(self, x, y):
        for e in self.entities:
            if isinstance(e, Monster) and e.alive and e.x == x and e.y == y:
                return e
        return None

    def melee_opponents(self):
        """Living monsters in view that are orthogonally adjacent to the
        player, i.e. close enough that one of the two can hit the other."""
        return [e for e in self.entities
                if isinstance(e, Monster) and e.alive and e.is_adjacent(self.player)
                and self.visible[e.y][e.x]]

    def chest_at(self, x, y):
        for e in self.entities:
            if isinstance(e, Chest) and e.x == x and e.y == y:
                return e
        return None

    def is_visible(self, x, y):
        return self.visible[y][x]

    def visible_entities(self):
        """Living entities in view. The `alive` filter matters now that the
        renderer draws mid-round: a monster killed during the player's half
        must not still be on screen while the monster half plays out."""
        return [e for e in self.entities
                if getattr(e, 'alive', True) and self.visible[e.y][e.x]]

    def log(self, text):
        self.messages.append(text)
