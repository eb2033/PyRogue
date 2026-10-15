"""The camera: which part of the map the window shows, and the beats that
change it.

Exploring, the window shows a fixed-size view of the map -- `view_size`: the
base map (MAP_WIDTH x MAP_HEIGHT, which every floor's map is at least as big
as) shrunk by `VIEW_ZOOM` on each axis -- centred on the player and clamped to
the map's edges (`follow_view`). Deeper floors have bigger maps (game/dungeon.py
map_size), so the view pans to follow the player rather than shrinking the
tiles to fit; a map no bigger than the view is shown whole, centred, and never
pans. Each step's pan is a short `Pan(..., follow=True)` beat.

When a monster is in melee range the map zooms in on the fight -- the player
and that monster centred, `MARGIN` squares of map around them -- and zooms
back out when the fight ends. Ranged combat (the archer) doesn't zoom for now:
`ZOOM_CLASSES`.

The camera is *staged*: `Director.plan(state)` turns what changed since the
last frame into a list of beats, and the renderer plays them one after another
before showing the frame. Today there are three kinds:

  Flight(paths, steps)
                     arrows flying together, cell to cell, for `steps`
                     cells at FLIGHT_MS_PER_CELL a cell: paths[i] is arrow
                     i's cells over this stretch. Planned from
                     GameState.shots (game/combat.py's Shot): every arrow in
                     shot.arrows leaves the shooter's cell at the same moment
                     (a volley's arrows fly side by side; any other bow, and
                     the goblin archer, is a one-arrow Shot on the same path).
                     The shot's timeline is cut at each step where an arrow
                     reaches a monster it hit: a Flight up to there, that
                     hit's Impact, then a Flight on. So each arrow's damage
                     shows the moment that arrow arrives, and a pierce's
                     second hit waits for the arrow to fly on to it. An arrow
                     whose path ends inside a stretch (it landed, or left
                     sight) is gone from then on. Plays out like an Impact:
                     keys wait in the queue until it ends.
  Impact(hit, shake, held)
                     a blow landing -- played at the current view, so a
                     killing blow is seen before the camera pulls back.
                     `held`: the arrows still in the air at that moment, as
                     (from, at) cell pairs, drawn hanging at `at`. The
                     map shakes for the length of the beat (`Shake`: harder
                     and longer on a crit), and the beat always plays out:
                     keys pressed meanwhile wait in the queue until it ends
  Pan(start, end, follow)
                     the view moving: zooming in, out, or across to another
                     opponent; `follow` when it is only the exploring view
                     tracking the player (played shorter)

A new effect (a lunge, a screen shake, a death animation) is another beat type
here plus a player for it in the renderer; the loop in main.py never changes.
The renderer services the window during every beat and leaves key presses
queued, so input typed during an animation is never lost -- and a queued key
cuts the remaining animation short (except an Impact's shake or a Flight,
which are short and always finish), so it never holds the player up for long.

Pure geometry, no pygame: views are in map cells (floats while animating).
"""

import random
from collections import namedtuple

from game.combat import Shot

# The exploring zoom -- the one knob for it. The map area is laid out for
# base map / VIEW_ZOOM cells per axis (view_size), so tiles are VIEW_ZOOM
# times the size the whole base map would get: a 40x20 base shows 32x16 cells,
# 50x20 shows 40x16. The layout still picks the tile from ui.TILE_SIZES
# (16 px at the least), so it is never below the renderer's minimum.
VIEW_ZOOM = 1.25
MARGIN = 2  # squares of map shown around the fight
ZOOM_CLASSES = frozenset({'warrior'})
HOLD_RANGE = 3  # once zoomed, a monster this close keeps it
HOLD_TURNS = 2  # player turns the zoom outlasts the fight


class View(namedtuple('View', 'left top width height')):
    """A rectangle of the map, in cells."""

    __slots__ = ()

    @property
    def center(self):
        return self.left + self.width / 2, self.top + self.height / 2


Impact = namedtuple('Impact', 'hit shake held')
Impact.__new__.__defaults__ = (None, ())
Pan = namedtuple('Pan', 'start end follow')
Pan.__new__.__defaults__ = (False,)
Flight = namedtuple('Flight', 'paths steps')
FLIGHT_MS_PER_CELL = 40  # a 5-cell shot flies for 0.2 s

# The hit shake: `ms` is how long the impact beat (and its shake) lasts,
# `amplitude` the peak offset as a fraction of an unzoomed map cell, `seed`
# makes the jitter repeatable (the hit's serial).
Shake = namedtuple('Shake', 'ms amplitude seed')
SHAKE_MS = 180
CRIT_SHAKE_MS = 280
SHAKE_AMPLITUDE = 0.12
CRIT_SHAKE_AMPLITUDE = 0.25
MIN_SHAKE_PX = 2  # so a shake is still felt on small cells
SHAKE_STEP_MS = 30  # the jitter picks a new offset this often
# The struck sprite's own shake, as a multiple of the map shake's amplitude,
# applied to the sprite's cell at the current view: 0.09 of a cell for a
# normal hit, 0.19 for a crit (4 / 8 px on a 40 px tile, 12 / 24 zoomed to 128).
SPRITE_SHAKE_RATIO = 0.75


def shake_for(hit):
    """The shake a blow gets: a crit's is bigger and lasts longer."""
    if getattr(hit, 'crit', False):
        return Shake(CRIT_SHAKE_MS, CRIT_SHAKE_AMPLITUDE, hit.serial)
    return Shake(SHAKE_MS, SHAKE_AMPLITUDE, hit.serial)


def shake_peak(shake, cell):
    """Peak offset in pixels for map cells `cell` px tall."""
    return max(MIN_SHAKE_PX, round(cell * shake.amplitude))


def shake_offset(shake, t, cell):
    """(dx, dy) in pixels at t (0 -> 1 over the beat), for map cells `cell`
    px tall. Each axis is a random jitter within the peak, held for
    SHAKE_STEP_MS, under a (1 - t)^2 decay -- so it starts at full strength
    and settles to exactly (0, 0) at t = 1. Deterministic for a given shake."""
    return _jitter(shake, t, shake_peak(shake, cell), skip=0)


def sprite_shake_offset(shake, t, cell):
    """(dx, dy) in pixels at t for the struck sprite itself, in a cell
    `cell` px tall at the current view (so it scales with the zoom). Same
    timing, decay and per-hit random sequence as shake_offset -- the next two
    draws of it, so the sprite doesn't just move in step with the map -- and
    a peak of SPRITE_SHAKE_RATIO of its own cell: bigger for a crit, whose
    shake.amplitude is. (0, 0) at t = 1, so the sprite ends back in its cell."""
    return _jitter(shake, t, sprite_shake_peak(shake, cell), skip=2)


def sprite_shake_peak(shake, cell):
    """The struck sprite's peak offset in pixels, in a cell `cell` px tall."""
    return max(MIN_SHAKE_PX, round(cell * shake.amplitude * SPRITE_SHAKE_RATIO))


def _jitter(shake, t, peak, skip):
    if not 0 <= t < 1:
        return 0, 0
    rng = random.Random(shake.seed * 7919 + int(t * shake.ms / SHAKE_STEP_MS))
    for _ in range(skip):
        rng.random()
    peak *= (1 - t) ** 2
    return round(rng.uniform(-1, 1) * peak), round(rng.uniform(-1, 1) * peak)


def flight_ms(flight, per_cell=FLIGHT_MS_PER_CELL):
    """How long `flight` plays: `per_cell` for every cell its arrows cross."""
    return flight.steps * per_cell


def flight_step(path, steps, t):
    """Where an arrow on `path` is at t (0 -> 1 over a flight of `steps`
    cells): (a, b, f) -- it is `f` of the way from cell a to the next cell b
    on `path`. Cells are crossed at an even pace, the same for every arrow in
    the flight, so at t = 1 a full-length path is on its last cell (f = 1).
    None once a path shorter than `steps` has reached its end: that arrow
    has landed (or flown out of sight)."""
    cells = len(path) - 1
    if cells < 1:
        return None
    s = min(1.0, max(0.0, t)) * steps
    if s >= cells and cells < steps:
        return None
    i = min(int(s), cells - 1)
    return path[i], path[i + 1], s - i


def full_view(map_width, map_height):
    return View(0, 0, map_width, map_height)


def view_size(base_width, base_height, zoom=VIEW_ZOOM):
    """(cols, rows) of map the window shows while exploring: the base map's
    size over `zoom`, rounded, at least one cell."""
    return max(1, round(base_width / zoom)), max(1, round(base_height / zoom))


def follow_view(player, map_width, map_height, size):
    """A `size` (cols, rows) view with `player` at its centre (to the cell),
    clamped so it never runs past the map's edges. On an axis where the map
    is no bigger than the view, the map is centred instead -- shown whole,
    the same wherever the player stands."""

    def axis(pos, extent, span):
        if extent <= span:
            return (extent - span) / 2
        return min(max(0, pos - span // 2), extent - span)

    cols, rows = size
    return View(axis(player.x, map_width, cols), axis(player.y, map_height, rows), cols, rows)


def combat_view(a, b, margin=MARGIN):
    """The two entities' bounding box plus `margin` cells on every side, so
    both sit at its centre. Not clamped to the map: near the border the view
    runs past the edge (drawn as darkness) rather than pushing the fight
    off-centre."""
    left, top = min(a.x, b.x) - margin, min(a.y, b.y) - margin
    return View(left, top, abs(a.x - b.x) + 1 + 2 * margin, abs(a.y - b.y) + 1 + 2 * margin)


def centred_on(entity, view):
    """A view the size of `view` with `entity`'s cell at its centre."""
    return View(
        entity.x + 0.5 - view.width / 2, entity.y + 0.5 - view.height / 2, view.width, view.height
    )


def lerp_view(a, b, t):
    return View(*(p + (q - p) * t for p, q in zip(a, b)))


def ease(t):
    """Smoothstep: starts and lands gently."""
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def project(view, rect, cell):
    """Fit `view` into the pixel rect `rect` (x, y, w, h), keeping the map's
    cell shape `cell` (w, h) -- square tiles or text cells.

    Returns (cell_w, cell_h, origin_x, origin_y): map cell (x, y) has its
    top-left at (origin_x + x * cell_w, origin_y + y * cell_h). Cell sizes are
    whole pixels so the grid has no seams; the view's centre lands on the
    rect's centre, and whichever axis has room to spare shows extra map.
    """
    rx, ry, rw, rh = rect
    base_w, base_h = cell
    zoom = min(rw / (view.width * base_w), rh / (view.height * base_h))
    cell_w, cell_h = max(1, int(base_w * zoom + 1e-9)), max(1, int(base_h * zoom + 1e-9))
    cx, cy = view.center
    return cell_w, cell_h, round(rx + rw / 2 - cx * cell_w), round(ry + rh / 2 - cy * cell_h)


class Director:
    """Decides what the camera should show and stages the beats to get there.

    Keeps the combat view (None = not zoomed on a fight: the exploring view,
    `explore_view`), the monster the camera is following, and the serial of
    the last hit it staged. Reads the GameState; never mutates it.

    `view_size`: (cols, rows) of the exploring view (see `view_size`); None
    shows the whole map, whatever its size, and never follows the player.

    Two rules keep the zoom from jolting (both count *player turns* --
    `state.turn` -- never frames, so the monster phase and redrawn frames
    change nothing):

    - Direction gate: it never zooms IN on an opponent the player just
      stepped away from (their last move increased the distance to the
      nearest opponent). Running away stays zoomed out.
    - Hold: once zoomed, it stays zoomed while any monster in view is within
      `HOLD_RANGE` (Chebyshev) of the player, and for `HOLD_TURNS` more turns
      after none is -- so a second monster closing in after the first dies
      doesn't cause a zoom-out for one turn. With no monster in view at all
      (the last one died or left sight) the fight is over and it zooms out at
      once.
    """

    def __init__(self, zoom=True, view_size=None):
        self.zoom = zoom
        self.view_size = view_size
        self.view = None
        self._map = None  # the level (its game_map) at the last frame
        self._shown = None  # the view planned for the last frame
        self.focus = None
        self._last_hit = 0
        self._turn = None  # state.turn at the last frame
        self._pos_seen = None  # the player's position at the last frame
        self._pos_before = None  # ... before their latest turn
        self._calm_since = None  # turn the hold's countdown started, or None

    def current(self, state):
        """The view to paint: the fight's, else the exploring one."""
        return self.view or self.explore_view(state)

    def explore_view(self, state):
        """The view while no fight is framed: following the player, or the
        whole map if there is no view_size."""
        if self.view_size is None:
            return full_view(state.width, state.height)
        return follow_view(state.player, state.width, state.height, self.view_size)

    def plan(self, state):
        """The beats to play before showing `state`: any new arrows' flights
        and hits, in the order they happened, then a pan if the camera has to
        move. Updates the director as if they had
        played (the renderer may cut an animation short, never skip one)."""
        beats = []
        new = [e for e in state.combat_events if e.serial > self._last_hit]
        new += [s for s in getattr(state, 'shots', ()) if s.serial > self._last_hit]
        staged = set()  # serials of hits a shot has already staged
        for event in sorted(new, key=lambda e: e.serial):
            self._last_hit = max(self._last_hit, event.serial)
            if isinstance(event, Shot):
                beats += self._shot_beats(state, event)
                staged.update(hit.serial for arrow in event.arrows for hit in arrow.hits)
            elif event.serial not in staged and state.visible[event.y][event.x]:
                beats.append(Impact(event, shake_for(event)))

        self._track_turn(state)
        # A new floor: the old view belongs to another map, so no pan from it.
        same_level = self._map is None or self._map is state.game_map
        self._map = state.game_map
        # Where the last frame's view was -- not current(), which follows the
        # player to where they stand now.
        start = self._shown if self._shown is not None else self.current(state)
        was_zoomed = self.view is not None
        self.focus, view = self._frame(state)
        if view is None:
            self._calm_since = None
        target = view or self.explore_view(state)
        if target != start and same_level:
            beats.append(Pan(start, target, follow=not was_zoomed and view is None))
        self.view = view
        self._shown = target
        return beats

    @staticmethod
    def _shot_beats(state, shot):
        """A shot's beats. Every arrow in shot.arrows leaves the shooter at
        once and crosses a cell a step; the timeline is cut at each step where
        an arrow reaches a monster it hit: a Flight of all the arrows still in
        the air up to there, the hit's Impact (if in view) with the others
        held in the air, and so on to where the last one lands."""
        paths = [Director._in_sight(state, arrow.path) for arrow in shot.arrows]
        arrivals = []  # (step, hit): when each arrow reaches each monster
        for arrow in shot.arrows:
            at = 0
            for hit in arrow.hits:
                cell = (hit.x, hit.y)
                if cell not in arrow.path[at:]:
                    continue  # not on its path: nothing to fly to
                at = arrow.path.index(cell, at)
                arrivals.append((at, hit))
        arrivals.sort(key=lambda arrival: arrival[0])  # stable: aim arrow first
        last = max(len(path) - 1 for path in paths)
        beats, at = [], 0
        for step, hit in arrivals:
            beats += Director._flight(paths, at, min(step, last))
            at = max(at, step)
            if state.visible[hit.y][hit.x]:
                held = tuple((p[step - 1], p[step]) for p in paths if len(p) - 1 > step)
                beats.append(Impact(hit, shake_for(hit), held))
        return beats + Director._flight(paths, at, last)

    @staticmethod
    def _in_sight(state, path):
        """`path` cut short where the arrow leaves the player's sight (the
        shooter's cell is always kept)."""
        seen = list(path[:1])
        for x, y in path[1:]:
            if not state.visible[y][x]:
                break
            seen.append((x, y))
        return tuple(seen)

    @staticmethod
    def _flight(paths, start, end):
        """A Flight of every arrow in the air from step `start` to `end`;
        none if that is no time, or no arrow is seen moving."""
        if end <= start:
            return []
        stretch = tuple(p[start : end + 1] for p in paths if len(p) - 1 > start)
        return [Flight(stretch, end - start)] if stretch else []

    def _track_turn(self, state):
        """Remember where the player stood before their latest turn. The
        player never moves during the monster phase, so the position at the
        last frame of the previous turn is where this turn's move began."""
        pos = (state.player.x, state.player.y)
        if self._turn is None:
            self._pos_before = pos
        elif state.turn != self._turn:
            self._pos_before = self._pos_seen
        self._turn = state.turn
        self._pos_seen = pos

    def _frame(self, state):
        """(focus, view) for this frame; view None = the whole map."""
        if not self.zoom or state.game_over or state.player.char_class not in ZOOM_CLASSES:
            return None, None
        zoomed = self.view is not None
        player = state.player
        opponents = state.zoom_opponents()
        if opponents:
            if not zoomed and self._moving_away(player, opponents):
                return None, None
            self._calm_since = None
            focus = self._pick_focus(state, opponents)
            return focus, combat_view(player, focus)
        if not zoomed:
            return None, None

        nearby = state.monsters_within(HOLD_RANGE)
        if nearby:
            self._calm_since = None
            focus = (
                self.focus
                if self.focus in nearby
                else min(nearby, key=lambda m: m.distance_to(player))
            )
            return focus, combat_view(player, focus)
        if not state.visible_monsters():
            return None, None  # nobody left to wait for
        if self._calm_since is None:
            self._calm_since = state.turn
        if state.turn - self._calm_since >= HOLD_TURNS:
            return None, None
        focus = self.focus if self.focus is not None and self.focus.alive else None
        return focus, centred_on(player, self.view)

    def _moving_away(self, player, opponents):
        before = self._pos_before
        if before is None or before == (player.x, player.y):
            return False
        nearest = min(opponents, key=lambda m: m.distance_to(player))
        was = max(abs(nearest.x - before[0]), abs(nearest.y - before[1]))
        return nearest.distance_to(player) > was

    def _pick_focus(self, state, opponents):
        if self.focus in opponents:
            return self.focus  # stay on the fight already framed
        for hit in reversed(state.combat_events):
            other = hit.defender if hit.attacker is state.player else hit.attacker
            if other in opponents:
                return other  # whoever just traded blows with the player
        return opponents[0]
