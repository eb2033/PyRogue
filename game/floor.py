"""Building and populating a floor, and going down to the next one.

build_map generates this floor's map and rooms (game/dungeon.py) and fresh
FOV/fog grids; populate_level places everything on it -- the shopkeeper and
shop on a shop floor, the monsters, the chests, a boss floor's stairs, the
shrine -- through one occupancy set (game/level.py), so nothing is placed
on anything placed before it. next_level throws the old floor away and
builds the next; try_descend is the stairs key.

Free functions over a GameState, like game/archery.py; they use only its
public attributes and methods, and every roll goes through state.rng in a
fixed order (a seeded game replays exactly; game/gold.py's balance
simulation builds floors the same way).
"""

from typing import TYPE_CHECKING

from game import sound
from game.dungeon import generate_level, map_size, place_boss_stairs, place_stairs
from game.item import spawn_chests
from game.level import terrain_tiles
from game.monster import is_boss_level
from game.shop import Shopkeeper, is_shop_level, pick_shop_room, roll_shop
from game.shrine import place_shrine
from game.spawn import pick_boss_room, spawn_level
from game.tiles import STAIRS_DOWN

if TYPE_CHECKING:
    from game.state import GameState

# Taking the stairs down restores this fraction of the player's max HP.
DESCENT_HEAL_FRACTION = 0.2


def build_map(state: 'GameState'):
    """This floor's map, rooms, stairs and empty FOV/fog grids, at this
    floor's size (dungeon.map_size: it grows with depth)."""
    state.width, state.height = map_size(state.base_width, state.base_height, state.depth)
    state.game_map, state.rooms = generate_level(
        state.base_width, state.base_height, state.depth, state.rng
    )
    if not is_boss_level(state.depth):  # boss floors: populate_level
        place_stairs(state.game_map, state.rooms)
    state.visible = [[False] * state.width for _ in range(state.height)]
    state.seen = [[False] * state.width for _ in range(state.height)]


def spawn_level_monsters(state: 'GameState', exclude=(), boss_room=None, occupied=None):
    """This floor's enemies (game/spawn.py has the rules), none in a room of
    `exclude` or on a tile of `occupied` (to which theirs are added). Also
    sets state.boss_arena (`boss_room`, or one picked here on a boss
    floor)."""
    monsters, state.boss_arena = spawn_level(
        state.rooms,
        state.depth,
        state.rng,
        exclude=exclude,
        boss_room=boss_room,
        occupied=occupied,
    )
    return monsters


def populate_level(state: 'GameState'):
    """The player, then this floor's shopkeeper, monsters, chests and
    (maybe) shrine, as the new entity list. On a shop floor the shop room
    (picked after the boss room, never it) gets none of the others. One
    occupancy set (game/level.py) runs through every spawner in this order
    -- the player and the shopkeeper, the monsters, the chests (and the
    stairs), the boss floor's stairs, the shrine -- so nothing is placed on
    anything placed before it. On a boss floor the stairs are placed here,
    in the boss room, after the boss and every other entity (build_map
    leaves them out there). Sets state.boss_arena and the shop."""
    player = state.player
    boss_room = pick_boss_room(state.rooms, state.depth, state.rng)
    shop_room = None
    if is_shop_level(state.depth):
        shop_room = pick_shop_room(state.rooms, boss_room, state.rng)
    exclude = (shop_room,) if shop_room is not None else ()
    state.shop_open = False
    if shop_room is None:
        state.shop = state.shopkeeper = None
    else:
        state.shopkeeper = Shopkeeper(*shop_room.center())
        state.shop = roll_shop(state.depth, player.char_class, state.rng)
    occupied = {(player.x, player.y)}
    occupied |= terrain_tiles(state.game_map, state.rooms)
    if state.shopkeeper is not None:
        occupied.add((state.shopkeeper.x, state.shopkeeper.y))
    monsters = spawn_level_monsters(state, exclude, boss_room, occupied)
    # Adds the stairs tile (rooms[-1].center()) and the chests' tiles.
    chests = spawn_chests(
        state.rooms, state.rng, depth=state.depth, exclude=exclude, occupied=occupied
    )
    if state.boss_arena is not None:
        boss = next((m for m in monsters if m.is_boss), None)
        boss_pos = (boss.x, boss.y) if boss is not None else state.boss_arena.center()
        occupied.add(
            place_boss_stairs(state.game_map, state.boss_arena, boss_pos, occupied, state.rng)
        )
    shrine = place_shrine(
        state.rooms, state.depth, occupied, state.boss_arena, rng=state.rng, exclude=exclude
    )
    # List order is not paint order: the renderer sorts by level.draw_layer,
    # so creatures are always drawn on top.
    fixtures = [e for e in (state.shopkeeper, shrine) if e is not None]
    return [player] + fixtures + monsters + chests


def try_descend(state: 'GameState'):
    """The stairs key: go down a floor if the player is standing on the
    stairs (next_level). Returns False, logging why, if not -- or if the
    run is over."""
    if state.game_over or not state.player.alive:
        return False
    if state.game_map[state.player.y][state.player.x] != STAIRS_DOWN:
        state.log('There are no stairs here.')
        return False
    next_level(state)
    state.sound(sound.DESCEND)
    return True


def next_level(state: 'GameState'):
    """Throw this floor away and build the next one: a new map and
    entities, the player at its first room, any queued monster turns and
    strikes and the hunter's mark dropped, and the descent's rest
    (DESCENT_HEAL_FRACTION of max HP)."""
    state.depth += 1
    build_map(state)

    px, py = state.rooms[0].center()
    state.player.x, state.player.y = px, py

    state.cancel_monster_phase()
    state.cancel_strikes()
    state.marked = None
    state.pending_choice = None
    state.entities = populate_level(state)
    if is_boss_level(state.depth):
        state.log(f'You descend to level {state.depth}. Something powerful lurks here...')
    else:
        state.log(f'You descend to level {state.depth}.')
    healed = descent_heal(state.player)
    state.log(f'You descend the stairs and rest for a while, restoring {healed} HP.')
    state.update_fov()


def descent_heal(player):
    """Heal DESCENT_HEAL_FRACTION of `player`'s max HP, capped at max;
    returns the HP actually restored."""
    before = player.hp
    player.hp = min(player.max_hp, before + int(player.max_hp * DESCENT_HEAL_FRACTION))
    return player.hp - before
