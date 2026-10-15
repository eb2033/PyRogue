"""The combat camera: which part of the map the window shows, and the beats
that change it.

When a monster is in melee range the map zooms in on the fight -- the player
and that monster centred, `MARGIN` squares of map around them -- and zooms
back out when the fight ends. Ranged combat (the archer) doesn't zoom for now:
`ZOOM_CLASSES`.

The camera is *staged*: `Director.plan(state)` turns what changed since the
last frame into a list of beats, and the renderer plays them one after another
before showing the frame. Today there are two kinds:

  Impact(hit)        a blow landing -- played at the current view, so a
                     killing blow is seen before the camera pulls back
  Pan(start, end)    the view moving: zooming in, out, or across to another
                     opponent

A new effect (a lunge, a screen shake, a death animation) is another beat type
here plus a player for it in the renderer; the loop in main.py never changes.
The renderer services the window during every beat and leaves key presses
queued, so input typed during an animation is never lost -- and a queued key
cuts the remaining animation short, so it never holds the player up.

Pure geometry, no pygame: views are in map cells (floats while animating).
"""

from collections import namedtuple

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


Impact = namedtuple('Impact', 'hit')
Pan = namedtuple('Pan', 'start end')


def full_view(map_width, map_height):
    return View(0, 0, map_width, map_height)


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

    Keeps the view (None = the whole map, whatever its size), the monster the
    camera is following, and the serial of the last hit it staged. Reads the
    GameState; never mutates it.

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

    def __init__(self, zoom=True):
        self.zoom = zoom
        self.view = None
        self.focus = None
        self._last_hit = 0
        self._turn = None  # state.turn at the last frame
        self._pos_seen = None  # the player's position at the last frame
        self._pos_before = None  # ... before their latest turn
        self._calm_since = None  # turn the hold's countdown started, or None

    def current(self, state):
        return self.view or full_view(state.width, state.height)

    def plan(self, state):
        """The beats to play before showing `state`: any new hits, then a pan
        if the camera has to move. Updates the director as if they had
        played (the renderer may cut an animation short, never skip one)."""
        beats = []
        for hit in state.combat_events:
            if hit.serial > self._last_hit:
                self._last_hit = hit.serial
                if state.visible[hit.y][hit.x]:
                    beats.append(Impact(hit))

        self._track_turn(state)
        start = self.current(state)
        self.focus, view = self._frame(state)
        if view is None:
            self._calm_since = None
        target = view or full_view(state.width, state.height)
        if target != start:
            beats.append(Pan(start, target))
        self.view = view
        return beats

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
