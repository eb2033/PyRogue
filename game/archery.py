"""The archer's shot: flight, the bows' effects, and where the arrow lands.

GameState.shoot_arrow is the entry point; everything here works on a
GameState. Standard library only.

One shot spends one arrow from the quiver (game/quiver.py) and leaves one
ArrowPile where the aim-line arrow stopped, if it hit nothing: the last free
tile before the wall or closed door. (An arrow that strikes a monster is used
up; where it stopped is still the last monster's tile, where it stood when
struck, even if a sling then knocks it back.) A door stops an arrow like a
wall (it blocks sight, tiles.is_transparent), so nothing the player can't see
is hit through one; a monster standing in the doorway itself is hit, and the
arrow stops there -- the rule Monster.clear_shot uses for goblin archers. The
arrow flies past the shopkeeper, chests, shrines and piles. All of this is
game/level.py's ARROW row. The equipped weapon's effects (game/item.py, all
defaulted for any other weapon) change the shot:

- pierce (longbow): the arrow passes through up to `pierce` monsters, each hit
  in full; a wall or door still stops it.
- reload (heavy crossbow): after a shot, `reload` player turns before the next
  (GameState.reload_turns); a shot meanwhile is refused.
- spread (volley bow): `spread` extra arrows at `spread_factor` damage -- the
  first two in the lanes either side of the aim line (starting diagonally
  forward of the player, then straight on), a third down the aim line itself.
  Extras spend no arrow and leave no pile. They leave with the aim arrow, on
  the same turn, as part of the same Shot. Point blank -- the aim arrow's
  first monster is orthogonally adjacent -- every extra hits that monster
  too, at the same factor (_point_blank).

The shot after a successful hop (GameState.hop_crit) always crits: every hit
of its aim arrow is a forced crit, and the flag is spent by that shot, hit or
miss.
- knockback (sling): a hit monster is pushed up to `knockback` tiles straight
  away from the player, a tile at a time, stopping before a wall or a
  creature (game/level.py's KNOCKBACK). A move, not a Hit.
- mark_bonus (hunter's bow): a hit marks the monster (GameState.marked, one at
  a time); arrows at the marked monster deal (1 + mark_bonus) x damage.
- tempo (quickdraw): every `tempo`-th shot is free -- the action queues no
  monster half (GameState.grant_free_turn).

Point blank -- the aim arrow's first monster is orthogonally adjacent -- the
shot does half damage (POINT_BLANK_FACTOR), the archer's melee rate; an arrow
that strikes at least one monster is used up and leaves no pile.

Every arrow's hit on a kind in monster.RANGED_RESIST (the slimes) is scaled
by its factor (0.7), on top of everything else: 35% point blank.

Every shot records one game.combat.Shot in GameState.events
(GameState.recording_shot): one Arrow (its path and its Hits) for each arrow
it looses -- just the aim arrow for most
bows, the aim arrow plus its extras for a volley -- so the window can draw
them flying together from the player (render/camera.py's Flight beat).
"""

from typing import TYPE_CHECKING

from game import level
from game.combat import Arrow
from game.monster import RANGED_RESIST
from game.quiver import ArrowPile
from game.sound import shot_slot
from game.tiles import is_transparent, is_walkable

# An arrow fired at an orthogonally adjacent monster is melee in all but name.
POINT_BLANK_FACTOR = 0.5

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
    state.sound(shot_slot(weapon))

    with state.recording_shot() as arrows:
        _loose(state, dx, dy, weapon, arrows)
    if weapon is not None and weapon.reload:
        state.reload_turns = weapon.reload
    if weapon is not None and weapon.tempo:
        state.tempo_shots += 1
        if state.tempo_shots >= weapon.tempo:
            state.tempo_shots = 0
            state.grant_free_turn()
            state.log('A quick draw: no time passes.')
    return True


def _loose(state: 'GameState', dx, dy, weapon, arrows):
    """Fly the shot's arrows, appending each one's Arrow to `arrows`: the
    aim arrow first, then a volley's extras."""
    player = state.player
    pierce = weapon.pierce if weapon is not None else 1
    # The shot after a hop always crits: the aim arrow's hits are forced
    # crits. Spent here, whether the arrow hits anything or not.
    crit = True if state.hop_crit else None
    state.hop_crit = False
    # Point blank: the aim arrow's first monster is the adjacent one.
    point_blank = state.monster_at(player.x + dx, player.y + dy)
    # Only the hit on the adjacent monster is halved; a pierced farther one is full.
    close = POINT_BLANK_FACTOR if point_blank is not None else 1.0
    stop, aim = _fly(
        state, player.x, player.y, dx, dy, pierce, 1.0, loud=True, crit=crit, first_factor=close
    )
    arrows.append(aim)
    if not aim.hits:  # an arrow that strikes a monster is used up
        _drop_arrow(state, *stop)
    if weapon is not None and weapon.spread and point_blank is not None:
        arrows.extend(_point_blank(state, point_blank, weapon.spread, weapon.spread_factor))
    elif weapon is not None and weapon.spread:
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


def _point_blank(state: 'GameState', target: 'Monster', spread, factor):
    """A volley at an adjacent `target`: every extra arrow (both side arrows,
    and a rare/epic volley's third) flies straight into it, each a hit at the
    volley's `factor` -- so it takes the whole volley -- instead of flying its
    own lane; the lane's walls don't matter at this range. Returns the
    extras' Arrows, each path (player, target). If the target is already
    dead (the aim arrow, or an earlier extra, killed it), the remaining
    arrows land on its tile without hitting it again: no overkill hits."""
    player = state.player
    path = ((player.x, player.y), (target.x, target.y))
    dx, dy = target.x - player.x, target.y - player.y
    arrows = []
    for _ in range(spread):
        hit = _hit(state, target, factor * POINT_BLANK_FACTOR, dx, dy) if target.alive else None
        arrows.append(Arrow(path, () if hit is None else (hit,)))
    return arrows


def _fly(
    state: 'GameState',
    x,
    y,
    dx,
    dy,
    pierce,
    factor,
    loud,
    origin=None,
    crit=None,
    first_factor=1.0,
):
    """Fly from (x, y), not including it, until a wall, a closed door or
    the `pierce`-th monster hit. A door is entered only to hit a monster
    standing in it, and the arrow stops there whatever pierce is left. Returns (the tile
    the arrow stopped on, its Arrow). `loud` logs a wall hit when nothing was struck (the
    aim line; volley extras stay quiet). The Arrow's path starts at `origin` (default
    (x, y)): the shooter's cell, which a volley's side arrow doesn't start on. `crit`
    is passed to each hit's attack() (True: the post-hop guaranteed crit).
    `first_factor` further scales the first monster hit only (point blank)."""
    path = [origin if origin is not None else (x, y)]
    hits = []
    while True:
        nx, ny = x + dx, y + dy
        if level.blocking_at(state, nx, ny, level.ARROW):
            if loud and not hits:
                what = 'wall' if not is_walkable(state.game_map, nx, ny) else 'door'
                state.log(f'The arrow thuds into a {what}.')
            break
        x, y = nx, ny
        path.append((x, y))
        monster = state.monster_at(x, y)
        if monster is not None:
            hits.append(
                _hit(state, monster, factor * (first_factor if not hits else 1.0), dx, dy, crit)
            )
            if len(hits) >= pierce:
                break
        if not is_transparent(state.game_map, x, y):
            break  # the monster in the doorway: nothing beyond it is reached
    return (x, y), Arrow(tuple(path), tuple(hits))


def _volley_starts(state: 'GameState', dx, dy, spread):
    """Where each of a volley's `spread` extra arrows starts flying from:
    the player's tile for one down the aim line, else the player's tile
    shifted one to a side (it then flies on from there, so its first tile is
    diagonally forward of the player). A side lane is None (no arrow) if its
    first tile stops an arrow (a wall, or a door with no monster in it), or
    both tiles it would squeeze between block sight (wall or door)."""
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
        if level.blocking_at(state, *first, level.ARROW) or not (
            is_transparent(game_map, px + sx, py + sy)
            or is_transparent(game_map, px + dx, py + dy)
        ):
            starts.append(None)
            continue
        starts.append((px + sx, py + sy))
    return starts


def _hit(state: 'GameState', monster: 'Monster', factor, dx, dy, crit=None):
    """One arrow striking `monster`, with the hunter's mark and the sling's
    knockback. `crit` goes to attack() (None: roll as usual). Returns the
    Hit."""
    weapon = state.player.weapon
    mark_bonus = weapon.mark_bonus if weapon is not None else 0.0
    if mark_bonus and state.marked is monster:
        factor *= 1 + mark_bonus
    factor *= RANGED_RESIST.get(monster.kind, 1.0)  # slimes shrug off arrows
    hit = state.attack(state.player, monster, factor, crit=crit)
    if not monster.alive:
        return hit
    if mark_bonus and state.marked is not monster:
        state.marked = monster
        state.log(f'You mark the {monster.name}.')
    if weapon is not None and weapon.knockback:
        _knock_back(state, monster, dx, dy, weapon.knockback)
    return hit


def _knock_back(state: 'GameState', monster: 'Monster', dx, dy, tiles):
    """Push `monster` up to `tiles` tiles along (dx, dy), one at a time,
    stopping before anything level.KNOCKBACK lists: a wall or a creature (a
    monster, the player, the shopkeeper). It crosses doorways, chests,
    shrines and piles."""
    moved = 0
    for _ in range(tiles):
        tx, ty = monster.x + dx, monster.y + dy
        if level.blocking_at(state, tx, ty, level.KNOCKBACK, ignore=monster):
            break
        monster.x, monster.y = tx, ty
        moved += 1
    if moved:
        state.log(f'The {monster.name} is knocked back.')


def _drop_arrow(state: 'GameState', x, y):
    """Leave the spent arrow at (x, y): onto the pile already there, or a
    new pile (drawn under any creature there: level.draw_layer)."""
    pile = state.arrows_at(x, y)
    if pile is not None:
        pile.count += 1
        return
    state.entities.append(ArrowPile(x, y))
