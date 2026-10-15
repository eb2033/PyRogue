"""The archer's shot: flight, the bows' effects, and where the arrow lands.

GameState.shoot_arrow is the entry point; everything here works on a
GameState. Standard library only.

One shot spends one arrow from the quiver (game/quiver.py) and leaves one
ArrowPile where the aim-line arrow stopped: on the last monster it hit, or the
last free tile before the wall. The equipped weapon's effects (game/item.py,
all defaulted for any other weapon) change the shot:

- pierce (longbow): the arrow passes through up to `pierce` monsters, each hit
  in full; a wall still stops it.
- reload (heavy crossbow): after a shot, `reload` player turns before the next
  (GameState.reload_turns); a shot meanwhile is refused.
- spread (volley bow): `spread` extra arrows at `spread_factor` damage -- the
  first two in the lanes either side of the aim line (starting diagonally
  forward of the player, then straight on), a third down the aim line itself.
  Extras spend no arrow and leave no pile. They leave with the aim arrow, on
  the same turn, as part of the same Shot.
- knockback (sling): a hit monster is pushed up to `knockback` tiles straight
  away from the player, a tile at a time, stopping at a wall, a monster or
  the player. A move, not a Hit.
- mark_bonus (hunter's bow): a hit marks the monster (GameState.marked, one at
  a time); arrows at the marked monster deal (1 + mark_bonus) x damage.
- tempo (quickdraw): every `tempo`-th shot is free -- the action queues no
  monster half (GameState._free_turn).

Every shot records one game.combat.Shot in GameState.shots: one Arrow (its
path and its Hits) for each arrow it looses -- just the aim arrow for most
bows, the aim arrow plus its extras for a volley -- so the window can draw
them flying together from the player (render/camera.py's Flight beat).
"""

from typing import TYPE_CHECKING

from game.combat import Arrow, Shot
from game.quiver import ArrowPile
from game.tiles import is_walkable

if TYPE_CHECKING:
    from game.monster import Monster
    from game.state import GameState


def shoot(state: 'GameState', dx, dy):
    """Loose an arrow from the player in (dx, dy). Returns False, logging
    why and changing nothing, if the shot is refused: the quiver is empty or
    the crossbow is still reloading. A player without a quiver (a warrior, if
    called directly) shoots without spending arrows."""
    player = state.player
    weapon = player.weapon
    if player.quiver is not None and player.quiver <= 0:
        state.log('No arrows left.')
        return False
    # Only a weapon that reloads waits for it: swapping the crossbow for
    # another bow mid-reload doesn't carry the wait over.
    if state.reload_turns > 0 and weapon is not None and weapon.reload:
        turns = state.reload_turns
        state.log(f'Still reloading ({turns} more turn{"s" if turns != 1 else ""}).')
        return False
    if player.quiver is not None:
        player.quiver -= 1
    state.log('You loose an arrow.')

    serial = state.next_event_serial()  # before any arrow flies: sorts first
    pierce = weapon.pierce if weapon is not None else 1
    stop, aim = _fly(state, player.x, player.y, dx, dy, pierce, 1.0, loud=True)
    arrows = [aim]
    _drop_arrow(state, *stop)
    if weapon is not None and weapon.spread:
        for start in _volley_starts(state, dx, dy, weapon.spread):
            if start is not None:
                sx, sy = start
                _, extra = _fly(
                    state,
                    sx,
                    sy,
                    dx,
                    dy,
                    1,
                    weapon.spread_factor,
                    loud=False,
                    origin=(player.x, player.y),
                )
                arrows.append(extra)
    state.shots.append(Shot(serial, aim.path, aim.hits, tuple(arrows)))
    if weapon is not None and weapon.reload:
        state.reload_turns = weapon.reload
    if weapon is not None and weapon.tempo:
        state.tempo_shots += 1
        if state.tempo_shots >= weapon.tempo:
            state.tempo_shots = 0
            state._free_turn = True
            state.log('A quick draw: no time passes.')
    return True


def _fly(state: 'GameState', x, y, dx, dy, pierce, factor, loud, origin=None):
    """Fly from (x, y), not including it, until a wall or the `pierce`-th
    monster hit. Returns (the tile the arrow stopped on, its Arrow). `loud`
    logs a wall hit when nothing was struck (the aim line; volley extras stay
    quiet). The Arrow's path starts at `origin` (default (x, y)): the
    shooter's cell, which a volley's side arrow doesn't start on."""
    path = [origin if origin is not None else (x, y)]
    first_event = len(state.combat_events)
    hits = 0
    while True:
        nx, ny = x + dx, y + dy
        if not is_walkable(state.game_map, nx, ny):
            if loud and hits == 0:
                state.log('The arrow thuds into a wall.')
            break
        x, y = nx, ny
        path.append((x, y))
        monster = state.monster_at(x, y)
        if monster is not None:
            _hit(state, monster, factor, dx, dy)
            hits += 1
            if hits >= pierce:
                break
    return (x, y), Arrow(tuple(path), tuple(state.combat_events[first_event:]))


def _volley_starts(state: 'GameState', dx, dy, spread):
    """Where each of a volley's `spread` extra arrows starts flying from:
    the player's tile for one down the aim line, else the player's tile
    shifted one to a side (it then flies on from there, so its first tile is
    diagonally forward of the player). A side lane is None (no arrow) if its
    first tile is a wall, or both tiles it would squeeze between are."""
    px, py = state.player.x, state.player.y
    lanes = [(-dy, dx), (dy, -dx), (0, 0)]
    starts = []
    for i in range(spread):
        sx, sy = lanes[i % len(lanes)]
        if (sx, sy) == (0, 0):
            starts.append((px, py))
            continue
        game_map = state.game_map
        first = (px + sx + dx, py + sy + dy)
        if not is_walkable(game_map, *first) or not (
            is_walkable(game_map, px + sx, py + sy) or is_walkable(game_map, px + dx, py + dy)
        ):
            starts.append(None)
            continue
        starts.append((px + sx, py + sy))
    return starts


def _hit(state: 'GameState', monster: 'Monster', factor, dx, dy):
    """One arrow striking `monster`, with the hunter's mark and the sling's
    knockback."""
    weapon = state.player.weapon
    mark_bonus = weapon.mark_bonus if weapon is not None else 0.0
    if mark_bonus and state.marked is monster:
        factor *= 1 + mark_bonus
    state.attack(state.player, monster, factor)
    if not monster.alive:
        return
    if mark_bonus and state.marked is not monster:
        state.marked = monster
        state.log(f'You mark the {monster.name}.')
    if weapon is not None and weapon.knockback:
        _knock_back(state, monster, dx, dy, weapon.knockback)


def _knock_back(state: 'GameState', monster: 'Monster', dx, dy, tiles):
    """Push `monster` up to `tiles` tiles along (dx, dy), one at a time,
    stopping before a wall, a living monster or the player."""
    moved = 0
    for _ in range(tiles):
        tx, ty = monster.x + dx, monster.y + dy
        if (
            not is_walkable(state.game_map, tx, ty)
            or state.monster_at(tx, ty) is not None
            or (tx, ty) == (state.player.x, state.player.y)
        ):
            break
        monster.x, monster.y = tx, ty
        moved += 1
    if moved:
        state.log(f'The {monster.name} is knocked back.')


def _drop_arrow(state: 'GameState', x, y):
    """Leave the spent arrow at (x, y): onto the pile already there, or a
    new pile (put before the monsters, so they are drawn over it)."""
    pile = state.arrows_at(x, y)
    if pile is not None:
        pile.count += 1
        return
    state.entities.insert(1, ArrowPile(x, y))
