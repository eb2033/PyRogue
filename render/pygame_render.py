"""Windowed renderer on pygame-ce: the window, the event loop, and the map.
Owned by WS-A (desktop_build_plan.md §5). Allowed to import pygame; game/ never does.

The §3.1 design, proven by the spike: main.py's loop stays exactly as it is --
draw, then a *blocking* get_action -- because "blocking" here means
pygame.event.wait(), not a sleep. The wait keeps the OS event queue drained, so
the window repaints on expose / resize and never gets flagged "Not Responding"
while the player thinks.

Division of labour with the other render modules:
  ui.Layout / ui.Canvas  geometry and grid text drawing (WS-D)
  ui.paint_panel         the side panel (WS-D)
  screens                title / class-select / game-over frames (WS-D)
  tileset.Tileset        tiles for map chars, None -> draw the glyph (WS-C)
  palette                Entity.color int -> RGB (this stream)
  input_map              key -> Action (this stream)
  camera.Director        the camera: what part of the map to show (the
                         exploring view that follows the player, or the
                         combat zoom), and the beats (arrow flights,
                         melee swings, impacts, pans) staged before each
                         frame
"""

import copy
import math
import os
import random
import warnings
from typing import cast

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame

from game.monster import Monster
from game.paths import resource_path
from game.quiver import RESTOCK_TURNS
from game.state import PARRY_COOLDOWN
from render import camera, choice, input_map, palette, screens, ui
from render.banner import render_banner
from render.base import Action, Renderer
from render.menu import Menu
from render.tileset import Tileset

ARCHER_TILE = '&'  # tiles.json key for the archer player (a bow-carrying figure)

ICON_FILE = 'icon.png'

# Combat staging (render/camera.py). How long each beat plays; a key the
# player has already pressed cuts the rest of a pan or step short, but never
# an impact's shake (it waits in the queue until the shake has finished).
# IMPACT_MS is a normal hit's beat; a crit's runs longer in proportion
# (camera.CRIT_SHAKE_MS / camera.SHAKE_MS).
ZOOM_MS = 220
FOLLOW_MS = 90  # the exploring view's pan after a step (a Pan with follow)
IMPACT_MS = camera.SHAKE_MS
FLIGHT_MS = camera.FLIGHT_MS_PER_CELL  # per cell an arrow crosses
SWING_MS = camera.SWING_MS  # a standard melee swing; other shapes in proportion
GUARD_MS = camera.GUARD_MS  # the parry's shield outline
PARRY_FADE_MS = camera.PARRY_FADE_MS  # the "Parry!" text fading after the riposte
FRAME_MS = 16

# Walking gait: an entity that just took a step leans this many degrees, the
# lean alternating left/right with each step, for STEP_MS.
TILT_DEGREES = 15
STEP_MS = 110
IMPACT_FLASH_ALPHA = 170

# Boss arena: how dark the 3x3 centre stone is, and how many blood sprites
# assets/blood/ holds (blood_01.png ...).
ARENA_STONE_ALPHA = 110
BLOOD_SPRITES = 5

# Enemy health bars: a dark track with a fill in proportion to hp / max_hp,
# green above a half, amber down to a quarter, red below. Sizes are fractions
# of the map cell being drawn, so they follow the tile size and the zoom.
HEALTH_GREEN = (70, 200, 70)
HEALTH_AMBER = (235, 165, 30)
HEALTH_RED = (215, 40, 40)
HEALTH_TRACK = (25, 20, 20)
HEALTH_BAR_COLORS = frozenset({HEALTH_GREEN, HEALTH_AMBER, HEALTH_RED, HEALTH_TRACK})
HEALTH_BAR_WIDTH = 0.7  # of the cell's width; a boss's spans the whole cell
HEALTH_BAR_HEIGHT = 0.08  # of the cell's height, at least 2 px

# The archer's restock bar: a light grey bar along the bottom edge of the
# player's own cell (never meeting a monster's health bar, which sits on top),
# a touch wider than the cell and kept inside the map, filled in proportion to
# restock_progress / RESTOCK_TURNS.
RESTOCK_FILL = (205, 205, 205)
RESTOCK_TRACK = (45, 45, 45)
RESTOCK_BAR_WIDTH = 1.05  # of the cell's width: overhangs its sides a little
RESTOCK_BAR_HEIGHT = 0.15  # of the cell's height, at least 3 px; the track
# (a 1 px dark rim round the bar) keeps it readable over the sprite's feet

# Melee swings (camera.Swing), drawn rather than tiled -- the bundled sheets
# have no slash or swing effect: a light arc, tapering and fading towards its
# tail, over a dark edge so it reads on a light floor too.
SWING_RGB = (240, 244, 255)
SWING_EDGE_RGB = (20, 24, 40)
SWING_EDGE_ALPHA = 0.45  # of the arc's own alpha
SWING_MIN_PX = 2  # the arc is never thinner than this

# The parry (camera.Guard / camera.ParryText), drawn in code: a light
# shield outline (no fill) over the warrior's cell, over a dark edge like the
# swing's, fading out over the last SHIELD_FADE of its beat; and "Parry!" in a
# clear blue with a dark outline, centred just above the warrior's cell.
SHIELD_RGB = (225, 235, 255)
SHIELD_EDGE_RGB = SWING_EDGE_RGB
SHIELD_EDGE_ALPHA = 0.55
SHIELD_FADE = 0.4  # of the Guard beat
SHIELD_STROKE = 0.06  # of the cell's smaller side, at least SWING_MIN_PX
PARRY_TEXT = 'Parry!'
PARRY_RGB = (80, 160, 255)
PARRY_OUTLINE_RGB = (8, 16, 40)


def shield_outline(samples=6):
    """A heater shield's outline in fractions of a cell (0..1 each way),
    clockwise from the top-left corner: a top edge dipping a little at its
    middle, straight sides, then two curves meeting at a point below."""
    top, shoulder, tip = 0.2, 0.5, 0.84
    left, right = 0.26, 0.74

    def curve(a, ctrl, b):
        return [
            (
                (1 - f) ** 2 * a[0] + 2 * (1 - f) * f * ctrl[0] + f * f * b[0],
                (1 - f) ** 2 * a[1] + 2 * (1 - f) * f * ctrl[1] + f * f * b[1],
            )
            for f in (i / samples for i in range(1, samples + 1))
        ]

    points = [(left, top), (0.5, top + 0.05), (right, top), (right, shoulder)]
    points += curve((right, shoulder), (right, 0.74), (0.5, tip))
    points += curve((0.5, tip), (left, 0.74), (left, shoulder))[:-1]
    return points + [(left, shoulder)]


# Arrows, drawn rather than tiled (the bundled sheets have no arrow): the one
# in flight and the ones lying in a pile. A bright shaft, a steel head and red
# fletching, all outlined in near-black so they read on any floor.
ARROW_SHAFT = (255, 222, 110)
ARROW_HEAD = (235, 240, 250)
ARROW_FLETCH = (235, 70, 60)
ARROW_OUTLINE = (20, 14, 8)
ARROW_LENGTH = 0.9  # of the cell's smaller side
PILE_BACKDROP_ALPHA = 70  # the pile's light tint, in its Entity.color
PILE_MAX_ARROWS = 3  # arrows drawn for a pile of this many or more
PILE_ANGLE = 45  # degrees: the pile's arrows lie diagonally, side by side
PILE_ARROW_LENGTH = 0.8  # of the cell's smaller side
PILE_SPACING = 0.2  # of the cell, between neighbouring arrows in a pile

# Events after which the window contents may be stale: repaint the last frame.
REPAINT_EVENTS = (
    pygame.VIDEORESIZE,
    pygame.VIDEOEXPOSE,
    pygame.WINDOWEXPOSED,
    pygame.WINDOWRESIZED,
    pygame.WINDOWSIZECHANGED,
)


# Critical-hit damage numbers: bright yellow with a black outline.
CRIT_RGB = (255, 235, 40)
CRIT_OUTLINE_RGB = (0, 0, 0)


# (x, y) -> (sprite index, angle, scale) for a boss room's blood decals.
DecalLayout = dict[tuple[int, int], tuple[int, int, float]]


class PygameRenderer(Renderer):
    def __init__(
        self,
        width,
        height,
        tileset=None,
        font_path=None,
        combat_zoom=True,
        zoom_ms=ZOOM_MS,
        follow_ms=FOLLOW_MS,
        impact_ms=IMPACT_MS,
        flight_ms=FLIGHT_MS,
        swing_ms=SWING_MS,
        guard_ms=GUARD_MS,
        parry_fade_ms=PARRY_FADE_MS,
    ):
        """`width` x `height`: the base map size (MAP_WIDTH/MAP_HEIGHT). The
        map area is laid out for camera.view_size of it -- a fixed number of
        cells, whatever the current floor's size -- and the camera pans that
        view over bigger maps (render/camera.py).
        `tileset`: a tileset.Tileset (None -> an unavailable one, i.e. glyphs).
        An available one puts the layout in tile mode: square map cells.
        `font_path`: a TTF/OTF file for the grid text, handed to ui.Layout
        (None -> a system monospace font); a bundled font goes through here.
        `combat_zoom`: zoom the map in on melee fights (render/camera.py);
        `zoom_ms` / `impact_ms`: how long a zoom's pan / a normal hit's flash and
        shake play -- a crit's in proportion longer; `follow_ms`: how long
        the exploring view takes to catch up with a step; `flight_ms`: how long
        an arrow takes to cross one cell (0 = no animation, the frame just
        changes); `swing_ms`: how long a standard melee swing plays -- the
        other swing shapes in proportion (0 = no swings); `guard_ms` /
        `parry_fade_ms`: how long a parry's shield shows / its "Parry!" takes
        to fade once the riposte has landed (0 = skipped)."""
        pygame.display.init()
        pygame.display.set_caption('PyRogue')
        _set_window_icon()
        # Hold-to-repeat, like a terminal's autorepeat.
        pygame.key.set_repeat(300, 60)

        self.tileset = tileset or Tileset()
        # The map area is the exploring view's size, not the level's: a new,
        # bigger floor never relayouts the window.
        self.view_size = camera.view_size(width, height)
        self.layout = ui.Layout(*self.view_size, font_path=font_path, tiles=self.tileset.available)
        self.fullscreen = False
        # Size to go back to when leaving fullscreen.
        self._windowed_size = self.layout.preferred_window_size()
        screen = self._set_mode(self._windowed_size, pygame.RESIZABLE)
        self.canvas = ui.Canvas(screen, self.layout)
        self.layout.fit(screen.get_size())

        # Whatever produced the frame currently on screen, so an expose or
        # resize can repaint it without the game loop's involvement.
        self._repaint = lambda: None
        # A window-close seen somewhere we can't return Action.QUIT from
        # (a menu, a pause) is remembered and delivered by get_action.
        self._quit_requested = False

        self.director = camera.Director(zoom=combat_zoom, view_size=self.view_size)
        self.zoom_ms = zoom_ms
        self.follow_ms = follow_ms
        self.impact_ms = impact_ms
        self.flight_ms = flight_ms
        self.swing_ms = swing_ms
        self.guard_ms = guard_ms
        self.parry_fade_ms = parry_fade_ms
        # (Parry, alpha) while a parry's "Parry!" is up: from its Guard beat
        # through its ParryText beat, over every beat between.
        self._parry_text = None
        # The view being painted (None = the map at the layout's own grid,
        # only before the first draw),
        # its projection for the frame being painted, and whether a beat is
        # mid-play (in-between sizes are drawn uncached -- see _tile).
        self._view = None
        self._proj = None
        self._animating = False
        self._zoomed_glyphs = {}
        # The state last drawn: get_action needs to know whether a chest's
        # choice is on screen, the one time a mouse click means something.
        self._state = None
        # Walking gait: id(entity) -> (last position, steps taken) for every
        # entity seen last frame, the lean (degrees) each entity has in the
        # frame being painted, and rotated tiles keyed by (char, colour, size,
        # dim, angle).
        self._gait = {}
        self._tilts = {}
        self._tilted_tiles = {}
        # Hit shake on the struck sprite: (entity, (dx, dy)) for the frame
        # being painted, and the offset of the sprite being painted right now.
        self._jolt = None
        self._sprite_offset = (0, 0)
        # Boss-arena blood: the sprites (loaded on first use), the decal
        # layout per arena, and scaled/rotated sprites.
        self._blood = None
        self._decal_layouts: dict[
            tuple[int, int, int, int], dict[tuple[int, int], tuple[int, int, float]]
        ] = {}
        self._decal_sprites = {}
        # Drawn arrows: (length, angle) -> Surface; cells an entity other
        # than an arrow pile stands on, in the frame being painted.
        self._arrow_sprites = {}
        self._occupied = set()

    @staticmethod
    def _set_mode(size, flags):
        with warnings.catch_warnings():
            # Tiling window managers resize the window on creation; that's
            # fine -- fit() sizes the grid to whatever we got.
            warnings.filterwarnings('ignore', 'Requested window was forcibly resized')
            return pygame.display.set_mode(size, flags)

    def _relayout(self):
        """Pick up the current window surface and size, then repaint."""
        self.canvas.surface = cast(pygame.Surface, pygame.display.get_surface())
        self.layout.fit(self.canvas.surface.get_size())
        self._repaint()

    def toggle_fullscreen(self):
        """F11. Borderless desktop fullscreen and back to the previous window
        size; the grid is re-fitted and the current frame repainted either way.

        A renderer-internal key, not an Action: GameState never sees it, so it
        works the same in a menu, mid-game, or on the game-over screen.
        """
        if not self.fullscreen:
            self._windowed_size = self.canvas.surface.get_size()
        try:
            window = self._display_window()
            if window is not None:
                if self.fullscreen:
                    window.set_windowed()
                else:
                    window.set_fullscreen(desktop=True)
            elif self.fullscreen:
                self._set_mode(self._windowed_size, pygame.RESIZABLE)
            else:
                # (0, 0) + FULLSCREEN = the desktop's resolution, which SDL
                # does as borderless desktop fullscreen. Recreates the window.
                self._set_mode((0, 0), pygame.FULLSCREEN)
        except pygame.error:
            return  # no fullscreen on this display/driver; stay as we are
        self.fullscreen = not self.fullscreen
        self._relayout()

    @staticmethod
    def _display_window():
        """The pygame.Window behind pygame.display, or None if unavailable.

        Why not the obvious calls: display.toggle_fullscreen() hangs on X11
        under i3, and set_mode() with new flags destroys and recreates the
        OS window (new X id, position lost). Window.set_fullscreen() changes
        the existing window in place. from_display_module() is deprecated in
        pygame-ce 2.4+ in favour of a Window-first API -- fine while
        requirements.txt pins pygame-ce; if it ever goes away we fall back to
        set_mode().
        """
        from_display = getattr(getattr(pygame, 'Window', None), 'from_display_module', None)
        if from_display is None:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            return from_display()

    def _show(self, paint):
        """Paint a frame and remember how, so it can be repainted on expose."""

        def repaint():
            self.canvas.clear()
            paint()
            pygame.display.flip()

        self._repaint = repaint
        repaint()

    # -- events ---------------------------------------------------------------

    def _handle_window_event(self, event):
        if event.type == pygame.QUIT:
            self._quit_requested = True
        elif event.type in REPAINT_EVENTS:
            self._relayout()

    def _wait_input(self, mouse=False):
        """Block until a key press (or, with `mouse`, a mouse motion / left
        click), servicing the window meanwhile.

        Returns the event, or None if the window was closed. event.wait()
        sleeps in the OS like getch() does, but wakes for expose / resize /
        close too, so the window stays live. Window keys (F11) are handled
        here and never returned, so every caller -- get_action and the menus
        alike -- gets them for free. Mouse events are skipped unless asked for:
        only the menus want them; gameplay stays keyboard-only.
        """
        while not self._quit_requested:
            event = pygame.event.wait()
            if event.type == pygame.KEYDOWN:
                if event.key in input_map.FULLSCREEN_KEYS:
                    self.toggle_fullscreen()
                    continue
                return event
            if mouse and (
                event.type == pygame.MOUSEMOTION
                or (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
            ):
                return event
            self._handle_window_event(event)
        return None

    def _wait_key(self):
        """Block until a key is pressed; mouse events are ignored."""
        return self._wait_input()

    # -- menus ----------------------------------------------------------------

    def _run_menu(self, banner_lines, options, descriptions=None):
        """Up/down/enter menu, same keys as the terminal one. Returns the
        chosen option, or None on 'q' or window close."""
        menu = Menu(options)
        repaint = True
        while True:
            if repaint:
                self._show(
                    lambda: screens.paint_menu(self.canvas, menu, banner_lines, descriptions)
                )
            repaint = True
            event = self._wait_input(mouse=True)
            if event is None:
                return None
            if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
                hit = screens.option_at(self.layout, menu, banner_lines, event.pos)
                if hit is None:
                    repaint = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    menu.index = hit
                    return menu.selected()
                else:
                    repaint = hit != menu.index  # only repaint when it moved
                    menu.index = hit
                continue
            char = input_map.event_char(event)
            if char == 'w' or event.key == pygame.K_UP:
                menu.move(-1)
            elif char == 's' or event.key == pygame.K_DOWN:
                menu.move(1)
            elif event.key in input_map.CONFIRM_KEYS:
                return menu.selected()
            elif char == 'q':
                return None

    def show_title_screen(self):
        return self._run_menu(render_banner('PyRogue'), screens.TITLE_OPTIONS) == 'Start'

    def choose_class(self):
        choice = self._run_menu(
            ['Choose your class'], screens.CLASS_OPTIONS, screens.CLASS_DESCRIPTIONS
        )
        return (choice or 'Warrior').lower()

    # -- game frame -----------------------------------------------------------

    def draw(self, state):
        """Play whatever the combat camera stages (arrow flights and impacts,
        then a pan), then show the frame. With nothing to stage this is just
        the paint. While a flight or impact plays, the monsters that later
        beats' hits are still to land on are drawn as they were before those
        hits (`pending`)."""
        self._state = state
        tilts = self.track_steps(state.visible_entities())
        beats = self.director.plan(state)
        try:
            self._play_beats(state, beats)
        finally:
            self._parry_text = None
        self._view = self.director.current(state)
        if tilts:
            self._tilts = tilts
            try:
                self._play(STEP_MS, lambda t: self._paint_game(state))
            finally:
                self._tilts = {}
        self._show(lambda: self._paint_game(state))

    def _play_beats(self, state, beats):
        """Play the Director's `beats` in order (see draw)."""
        for i, beat in enumerate(beats):
            pending = [b.hit for b in beats[i + 1 :] if isinstance(b, camera.Impact)]
            if isinstance(beat, camera.Flight):
                self._play(
                    camera.flight_ms(beat, self.flight_ms),
                    lambda t, flight=beat, pending=pending: self._paint_game(
                        state, flight=(flight, t), pending=pending
                    ),
                    interruptible=False,
                )
            elif isinstance(beat, camera.Swing):
                # The swing first; its blow's Impact (next) is still pending.
                self._play(
                    self.swing_ms_for(beat),
                    lambda t, swing=beat, pending=pending: self._paint_game(
                        state, swing=(swing, t), pending=pending
                    ),
                    interruptible=False,
                )
            elif isinstance(beat, camera.Impact):
                shake = beat.shake or camera.shake_for(beat.hit)
                # Arrows still flying hang where they are while it lands.
                held = (camera.Flight(beat.held, 1), 1.0) if beat.held else None
                self._play(
                    self.impact_ms_for(shake),
                    lambda t, hit=beat.hit, shake=shake, held=held, pending=pending: (
                        self._paint_game(
                            state,
                            impact=(hit, t),
                            shake=self.shake_offset(shake, t),
                            sprite_shake=shake,
                            flight=held,
                            pending=pending,
                        )
                    ),
                    interruptible=False,
                )
            elif isinstance(beat, camera.Guard):
                # "Parry!" goes up with the shield and stays until ParryText.
                self._parry_text = (beat.parry, 1.0)
                self._play(
                    self.guard_ms,
                    lambda t, parry=beat.parry, pending=pending: self._paint_game(
                        state, guard=(parry, t), pending=pending
                    ),
                    interruptible=False,
                )
            elif isinstance(beat, camera.ParryText):
                self._play(
                    self.parry_fade_ms,
                    lambda t, parry=beat.parry: self._paint_game(state, parry_text=(parry, 1 - t)),
                    interruptible=False,
                )
                self._parry_text = None
            elif isinstance(beat, camera.Pan):
                ms = self.follow_ms if beat.follow else self.zoom_ms
                self._play(ms, lambda t, pan=beat: self._paint_pan(state, pan, t))

    def track_steps(self, entities):
        """Compare `entities` with the last frame: {id(entity): degrees} for
        each one that moved exactly one orthogonal cell. The lean alternates
        sign with that entity's step count. Entities no longer visible are
        forgotten; one that jumped further (stairs, a teleport) just resets."""
        gait, tilts = {}, {}
        for entity in entities:
            key, pos = id(entity), (entity.x, entity.y)
            last, steps = self._gait.get(key, (pos, 0))
            if abs(pos[0] - last[0]) + abs(pos[1] - last[1]) == 1:
                steps += 1
                tilts[key] = TILT_DEGREES if steps % 2 else -TILT_DEGREES
            gait[key] = (pos, steps)
        self._gait = gait
        return tilts

    # -- staged beats ---------------------------------------------------------

    def impact_ms_for(self, shake):
        """How long an impact beat with `shake` plays: `impact_ms` for a
        normal hit, scaled up for a crit's longer shake."""
        return round(self.impact_ms * shake.ms / camera.SHAKE_MS)

    def swing_ms_for(self, swing):
        """How long `swing` plays: its shape's ms, scaled by swing_ms over
        the standard swing's."""
        return round(self.swing_ms * swing.shape.ms / camera.SWING_MS)

    def shake_offset(self, shake, t):
        """The map's (dx, dy) in pixels at t. Sized off the unzoomed cell, so
        a shake feels the same zoomed in or out."""
        return camera.shake_offset(shake, t, self.layout.map_cell_size()[1])

    def sprite_shake_offset(self, shake, t, hit):
        """The struck sprite's own (dx, dy) in pixels at t, inside its cell:
        sized off that cell at the view being painted, so it grows with the
        zoom. (0, 0) once the beat is over."""
        return camera.sprite_shake_offset(shake, t, self._map_cell_rect(hit.x, hit.y).height)

    def _jolt_of(self, entity):
        """`entity`'s sprite offset in the frame being painted: (0, 0) unless
        it is the one being struck."""
        if self._jolt is not None and self._jolt[0] is entity:
            return self._jolt[1]
        return (0, 0)

    def _clip_to_map(self):
        """Narrow the clip to the map's area (and any clip already set);
        returns the clip to restore."""
        surface = self.canvas.surface
        old = surface.get_clip()
        surface.set_clip(self.layout.map_rect().clip(old))
        return old

    def _play(self, ms, paint, interruptible=True):
        """Play one beat: `paint(t)` for t running 0 -> 1 over `ms`.

        Like pause(), the window stays serviced and key presses stay queued.
        If `interruptible`, a queued key (typed ahead, or held down) ends the
        beat early, so animation never makes the player wait for their next
        move; otherwise (an impact's shake) the beat always runs to the end
        and the keys are read afterwards, in order, by get_action. A window
        close still ends any beat at once. The beat's final frame isn't
        painted here: the next beat, or draw()'s own frame, is that frame.
        """
        if ms <= 0:
            return
        self._animating = True
        try:
            start = pygame.time.get_ticks()
            while not self._quit_requested and not (interruptible and self._key_waiting()):
                t = (pygame.time.get_ticks() - start) / ms
                if t >= 1:
                    break
                self._show(lambda t=t: paint(t))
                self._service_window()
                pygame.time.wait(FRAME_MS)
        finally:
            self._animating = False

    @staticmethod
    def _key_waiting():
        return pygame.event.peek(pygame.KEYDOWN)

    def _paint_pan(self, state, pan, t):
        self._view = camera.lerp_view(pan.start, pan.end, camera.ease(t))
        self._paint_game(state)

    # -- game frame -----------------------------------------------------------

    def _paint_game(
        self,
        state,
        impact=None,
        shake=(0, 0),
        sprite_shake=None,
        flight=None,
        pending=(),
        swing=None,
        guard=None,
        parry_text=None,
    ):
        """The map at the current view, clipped to the map's area, then the
        panel. `impact`: (Hit, t) to draw a blow landing, t running 0 -> 1.
        `shake`: (dx, dy) pixels to shift the whole painted map by.
        `sprite_shake`: the impact's Shake, to jolt the struck sprite (and its
        health bar) inside its cell as well. `flight`: (Flight, t) to draw its
        arrows in the air, over the map and the monsters, under an impact.
        `pending`: Hits not yet shown -- their monsters are drawn as they were
        before them (see _before_hits). `swing`: (Swing, t) to draw a melee
        swing's arc over the map and the sprites. `guard`: (Parry, t) to draw
        the parry's shield over the warrior. `parry_text`: (Parry, alpha) to
        draw "Parry!" above the warrior; None -> the one up for this run of
        beats (self._parry_text), if any."""
        surface = self.canvas.surface
        map_rect = self.layout.map_rect()
        if self._view is None:
            self._proj = None
            cols, rows = range(state.width), range(state.height)
        else:
            self._proj = camera.project(self._view, map_rect, self.layout.map_cell_size())
            cell_w, cell_h, ox, oy = self._proj
            cols = range(
                max(0, (map_rect.left - ox) // cell_w),
                min(state.width, (map_rect.right - ox) // cell_w + 1),
            )
            rows = range(
                max(0, (map_rect.top - oy) // cell_h),
                min(state.height, (map_rect.bottom - oy) // cell_h + 1),
            )
            surface.set_clip(map_rect)
        try:
            arena = getattr(state, 'boss_arena', None)
            decals = self._arena_decals(arena) if arena is not None else {}
            for y in rows:
                row = state.game_map[y]
                for x in cols:
                    if state.visible[y][x]:
                        self._paint_cell(x, y, row[x], palette.VISIBLE)
                        dim = False
                    elif state.seen[y][x]:
                        self._paint_cell(x, y, row[x], palette.SEEN, dim=True)
                        dim = True
                    else:
                        continue
                    if arena is not None and row[x] == '.':
                        self._paint_arena_floor(arena, decals, x, y, dim)

            if impact is not None and sprite_shake is not None:
                hit, t = impact
                self._jolt = (hit.defender, self.sprite_shake_offset(sprite_shake, t, hit))
            entities = state.visible_entities()
            if pending:
                entities = self._before_hits(state, entities, pending)
            if self._jolt is not None and any(e is self._jolt[0] for e in entities):
                # The struck sprite last, so it shakes on top of a neighbour.
                entities = [e for e in entities if e is not self._jolt[0]] + [self._jolt[0]]
            # Cells something stands on: a pile under it isn't drawn in glyph
            # mode, where the two characters would overlap.
            self._occupied = {(e.x, e.y) for e in entities if getattr(e, 'kind', None) != 'arrows'}
            for entity in entities:
                self._paint_entity(entity)
            for entity in entities:
                if isinstance(entity, Monster) and entity is not state.player:
                    self._paint_health_bar(entity, state.player, map_rect)
            if getattr(state.player, 'quiver', None) is not None:
                self._paint_restock_bar(state, map_rect)
            elif hasattr(state, 'parry_progress'):
                self._paint_parry_bar(state, map_rect)
            if swing is not None:
                self._paint_swing(*swing)
            if flight is not None:
                self._paint_flight(*flight)
            if impact is not None:
                self._paint_impact(*impact)
            if guard is not None:
                self._paint_guard(*guard)
            if shake != (0, 0):
                self._shift_map(map_rect, shake)
            # After the shake: the text holds still while the map jolts.
            text = parry_text or self._parry_text
            if text is not None:
                self._paint_parry_text(*text)
        finally:
            surface.set_clip(None)
            self._proj = None
            self._jolt = None

        ui.paint_panel(self.canvas, state)
        if state.is_choosing:
            screens.paint_choice(self.canvas, state)
        if state.game_over:
            screens.paint_game_over(self.canvas)

    def _shift_map(self, map_rect, offset):
        """Move what has been painted of the map by `offset` (the hit shake),
        leaving background where it moved away from. Unzoomed, a margin
        round the map moves too, for a damage number rising off the top row."""
        surface = self.canvas.surface
        area = map_rect
        if self._proj is None:
            cell_w, cell_h = self.layout.map_cell_size()
            area = map_rect.inflate(2 * cell_w, 2 * cell_h)
        area = area.clip(surface.get_rect())
        if not area.width or not area.height:
            return
        snapshot = surface.subsurface(area).copy()
        clip = surface.get_clip()
        surface.set_clip(area)
        surface.fill(palette.BACKGROUND, area)
        surface.blit(snapshot, area.move(offset))
        surface.set_clip(clip)

    def health_bar_rect(self, monster, player, map_rect):
        """Pixel rect of `monster`'s health bar: centred just above its cell,
        or along the cell's own top edge when there is no room above (the
        top of the map or of the zoomed view) or the player stands there."""
        rect = self._map_cell_rect(monster.x, monster.y)
        boss = getattr(monster, 'is_boss', False)
        width = rect.width if boss else max(4, round(rect.width * HEALTH_BAR_WIDTH))
        height = max(2, round(rect.height * HEALTH_BAR_HEIGHT)) + (1 if boss else 0)
        gap = max(1, rect.height // 20)
        top = rect.top - gap - height
        if top < map_rect.top or (player.x, player.y) == (monster.x, monster.y - 1):
            top = rect.top + gap
        bar = pygame.Rect(rect.centerx - width // 2, top, width, height)
        return bar.move(self._jolt_of(monster))  # stays on a sprite that shakes

    def _before_hits(self, state, entities, pending):
        """`entities` as they stood before the `pending` hits landed: each
        monster they strike is drawn at the cell of its first such hit (a
        sling's knockback hasn't happened yet), with the hp it had then, and
        back on screen if one of them killed it. Copies -- the state is never
        touched. The player is left alone (no health bar on the map)."""
        ghosts = {}
        for hit in pending:
            monster = hit.defender
            if monster is state.player or not isinstance(monster, Monster):
                continue
            ghost = ghosts.get(id(monster))
            if ghost is None:
                ghost = copy.copy(monster)
                ghost.x, ghost.y, ghost.alive = hit.x, hit.y, True
                ghosts[id(monster)] = ghost
            ghost.hp += hit.damage
        if not ghosts:
            return entities
        drawn = [ghosts.get(id(e), e) for e in entities]
        present = {id(e) for e in entities}
        drawn += [g for key, g in ghosts.items() if key not in present and state.visible[g.y][g.x]]
        if self._jolt is not None and id(self._jolt[0]) in ghosts:
            self._jolt = (ghosts[id(self._jolt[0])], self._jolt[1])
        return drawn

    def restock_bar_rect(self, player):
        """Pixel rect of the archer's restock bar: centred on the player's
        cell, just above its bottom edge, a little wider than the cell, and
        moving with a shaking sprite. Pushed back inside the map (its 1 px rim
        too) where the cell's overhang would cross the map's edge, zoomed or
        not."""
        rect = self._map_cell_rect(player.x, player.y)
        width = max(4, round(rect.width * RESTOCK_BAR_WIDTH))
        height = max(3, round(rect.height * RESTOCK_BAR_HEIGHT))
        gap = max(1, rect.height // 20)
        bar = pygame.Rect(rect.centerx - width // 2, rect.bottom - gap - height, width, height)
        bar = bar.move(self._jolt_of(player))
        return bar.clamp(self.layout.map_rect().inflate(-2, -2))

    @staticmethod
    def restock_fill(width, progress):
        """Filled pixels of a restock bar `width` wide: progress / RESTOCK_TURNS."""
        return round(width * min(1.0, max(0.0, progress / RESTOCK_TURNS)))

    @staticmethod
    def parry_fill(width, progress):
        """Filled pixels of the warrior's parry bar `width` wide: progress /
        PARRY_COOLDOWN (GameState.parry_progress, full when ready or armed)."""
        return round(width * min(1.0, max(0.0, progress / PARRY_COOLDOWN)))

    def _paint_restock_bar(self, state, map_rect):
        """The track, then the light grey fill: how near the next free arrow is."""
        fill = self.restock_fill(
            self.restock_bar_rect(state.player).width, getattr(state, 'restock_progress', 0)
        )
        self._paint_player_bar(state, map_rect, fill)

    def _paint_parry_bar(self, state, map_rect):
        """The warrior's parry recharge, drawn exactly like the restock bar."""
        progress = state.parry_progress()
        fill = self.parry_fill(self.restock_bar_rect(state.player).width, progress)
        self._paint_player_bar(state, map_rect, fill)

    def _paint_player_bar(self, state, map_rect, fill):
        """The bar under the player (restock_bar_rect): its dark track, then
        `fill` pixels of light grey from the left."""
        bar = self.restock_bar_rect(state.player)
        surface = self.canvas.surface
        clip = surface.get_clip()
        surface.set_clip(map_rect.clip(clip))
        try:
            surface.fill(RESTOCK_TRACK, bar.inflate(2, 2))
            if fill:
                surface.fill(RESTOCK_FILL, (bar.left, bar.top, fill, bar.height))
        finally:
            surface.set_clip(clip)

    # -- melee swings ---------------------------------------------------------

    def swing_pixels(self, swing, t):
        """camera.swing_points in pixels at the view being painted: a list of
        (x, y, alpha), from the trail's tail to the leading edge."""
        cell = self._map_cell_rect(*swing.origin)
        ox, oy = swing.origin
        return [
            (cell.left + (x - ox) * cell.width, cell.top + (y - oy) * cell.height, a)
            for x, y, a in camera.swing_points(swing, t)
        ]

    def _paint_swing(self, swing, t):
        """The swing's arc at t: segment by segment from its tail, each as
        opaque and as thick as its alpha (so it tapers into the trail), over
        a dark edge, clipped to the map."""
        points = self.swing_pixels(swing, t)
        if len(points) < 2:
            return
        cell = self._map_cell_rect(*swing.origin)
        thick = max(SWING_MIN_PX, round(min(cell.size) * swing.shape.thickness))
        pad = thick + 2
        left = math.floor(min(p[0] for p in points)) - pad
        top = math.floor(min(p[1] for p in points)) - pad
        width = math.ceil(max(p[0] for p in points)) + pad - left
        height = math.ceil(max(p[1] for p in points)) + pad - top
        art = pygame.Surface((width, height), pygame.SRCALPHA)
        segments = list(zip(points, points[1:]))
        for rgb, extra, scale in ((SWING_EDGE_RGB, 2, SWING_EDGE_ALPHA), (SWING_RGB, 0, 1.0)):
            for (x0, y0, a0), (x1, y1, a1) in segments:
                alpha = (a0 + a1) / 2
                if alpha <= 0:
                    continue
                w = max(1, round(thick * (0.5 + 0.5 * alpha))) + extra
                colour = (*rgb, round(255 * alpha * scale))
                a, b = (x0 - left, y0 - top), (x1 - left, y1 - top)
                pygame.draw.line(art, colour, a, b, w)
                pygame.draw.circle(art, colour, b, w / 2)
        clip = self._clip_to_map()
        try:
            self.canvas.surface.blit(art, (left, top))
        finally:
            self.canvas.surface.set_clip(clip)

    # -- arrows ---------------------------------------------------------------

    def arrow_sprite(self, length, angle):
        """An arrow `length` px long pointing `angle` degrees anticlockwise
        from east (screen up is +90), outlined, on a transparent square."""
        key = (length, angle)
        sprite = self._arrow_sprites.get(key)
        if sprite is not None:
            return sprite
        n = max(8, length)
        art = pygame.Surface((n, n), pygame.SRCALPHA)
        mid = n / 2
        thick = max(2, n // 10)
        tail, neck, tip = n * 0.08, n * 0.66, n * 0.94
        barb = max(2.0, n * 0.15)
        pygame.draw.line(art, ARROW_SHAFT, (tail, mid), (neck, mid), thick)
        pygame.draw.polygon(art, ARROW_HEAD, [(tip, mid), (neck, mid - barb), (neck, mid + barb)])
        feather = n * 0.2
        for side in (-1, 1):
            pygame.draw.polygon(
                art,
                ARROW_FLETCH,
                [
                    (tail, mid + side * barb * 0.9),
                    (tail + feather * 0.6, mid + side * barb * 0.9),
                    (tail + feather, mid),
                    (tail, mid),
                ],
            )
        outline = pygame.mask.from_surface(art).to_surface(
            setcolor=(*ARROW_OUTLINE, 255), unsetcolor=(0, 0, 0, 0)
        )
        sprite = pygame.Surface((n + 2, n + 2), pygame.SRCALPHA)
        for dx in (0, 1, 2):
            for dy in (0, 1, 2):
                if dx != 1 or dy != 1:
                    sprite.blit(outline, (dx, dy))
        sprite.blit(art, (1, 1))
        if angle:
            sprite = pygame.transform.rotate(sprite, angle)
        if len(self._arrow_sprites) > 64:
            self._arrow_sprites.clear()
        self._arrow_sprites[key] = sprite
        return sprite

    def flight_points(self, flight, t):
        """(pixel centre, angle in degrees) of each of `flight`'s arrows
        still in the air at t, in the order of flight.paths."""
        points = []
        for path in flight.paths:
            step = camera.flight_step(path, flight.steps, t)
            if step is None:
                continue
            a, b, f = step
            ra, rb = self._map_cell_rect(*a), self._map_cell_rect(*b)
            centre = (
                round(ra.centerx + (rb.centerx - ra.centerx) * f),
                round(ra.centery + (rb.centery - ra.centery) * f),
            )
            angle = round(math.degrees(math.atan2(-(b[1] - a[1]), b[0] - a[0])))
            points.append((centre, angle))
        return points

    def _paint_flight(self, flight, t):
        """The arrows in the air, each pointing the way it flies -- the same
        drawn arrow for the archer's shots and the goblin archer's."""
        rect = self._map_cell_rect(*flight.paths[0][-1])
        length = round(min(rect.size) * ARROW_LENGTH)
        clip = self._clip_to_map()
        try:
            for centre, angle in self.flight_points(flight, t):
                sprite = self.arrow_sprite(length, angle)
                self.canvas.surface.blit(sprite, sprite.get_rect(center=centre))
        finally:
            self.canvas.surface.set_clip(clip)

    def _paint_arrow_pile(self, pile):
        """Arrows on the floor: a light tint in the pile's colour over its
        cell, then up to PILE_MAX_ARROWS drawn arrows side by side across it
        -- or, in a text cell too narrow for a drawn arrow, the bold glyph."""
        if not self.layout.tile and (pile.x, pile.y) in self._occupied:
            return
        rect = self._map_cell_rect(pile.x, pile.y)
        rgb = palette.color(pile.color, palette.VISIBLE)
        tint = pygame.Surface(rect.size, pygame.SRCALPHA)
        inset = max(1, min(rect.size) // 10)
        pygame.draw.rect(
            tint,
            (*rgb, PILE_BACKDROP_ALPHA),
            tint.get_rect().inflate(-2 * inset, -2 * inset),
            border_radius=max(1, min(rect.size) // 4),
        )
        surface = self.canvas.surface
        if not self.layout.tile:
            surface.fill(palette.BACKGROUND, rect)  # no floor dot under the tint
        surface.blit(tint, rect)
        if not self.layout.tile and min(rect.size) < 2 * ui.MIN_FONT_SIZE:
            glyph = self._glyph(pile.char, palette.brighten(rgb), bold=True)
            self._blit_centred(glyph, pile.x, pile.y)
            return
        side = min(rect.size)
        sprite = self.arrow_sprite(round(side * PILE_ARROW_LENGTH), PILE_ANGLE)
        count = max(1, min(PILE_MAX_ARROWS, getattr(pile, 'count', 1)))
        step = side * PILE_SPACING / math.sqrt(2)  # across the diagonal
        clip = surface.get_clip()
        surface.set_clip(rect.clip(clip))
        try:
            for i in range(count):
                k = i - (count - 1) / 2
                at = (round(rect.centerx + k * step), round(rect.centery + k * step))
                surface.blit(sprite, sprite.get_rect(center=at))
        finally:
            surface.set_clip(clip)

    @staticmethod
    def health_bar_color(fraction):
        if fraction > 0.5:
            return HEALTH_GREEN
        if fraction >= 0.25:
            return HEALTH_AMBER
        return HEALTH_RED

    def _paint_health_bar(self, monster, player, map_rect):
        """The bar's track, then the fill in proportion to hp / max_hp. No
        numbers: the length and colour are the whole message."""
        max_hp = getattr(monster, 'max_hp', 0) or 0
        if max_hp <= 0:
            return
        fraction = min(1.0, max(0.0, monster.hp / max_hp))
        bar = self.health_bar_rect(monster, player, map_rect)
        surface = self.canvas.surface
        clip = self._clip_to_map()
        try:
            surface.fill(HEALTH_TRACK, bar)
            fill = round(bar.width * fraction)
            if monster.hp > 0:
                fill = max(1, fill)
            if fill:
                surface.fill(
                    self.health_bar_color(fraction), (bar.left, bar.top, fill, bar.height)
                )
        finally:
            surface.set_clip(clip)

    # -- boss arena -----------------------------------------------------------

    def _arena_decals(self, arena) -> DecalLayout:
        """{(x, y): (sprite index, angle, scale)} for a boss room: fixed by
        the room's corner, so it is the same every frame. Floor is checked at
        paint time (the layout doesn't know the map)."""
        key = (arena.x1, arena.y1, arena.x2, arena.y2)
        layout = self._decal_layouts.get(key)
        if layout is None:
            rng = random.Random(arena.x1 * 1009 + arena.y1)
            cx, cy = arena.center()
            layout = {}
            for y in range(arena.y1, arena.y2 + 1):
                for x in range(arena.x1, arena.x2 + 1):
                    near = max(abs(x - cx), abs(y - cy)) <= 2
                    if rng.random() < (0.5 if near else 0.28):
                        layout[(x, y)] = (
                            rng.randrange(BLOOD_SPRITES),
                            rng.randrange(0, 360, 15),
                            rng.uniform(0.8, 1.3),
                        )
            self._decal_layouts[key] = layout
        return layout

    def _blood_sprites(self):
        if self._blood is None:
            self._blood = []
            for i in range(1, BLOOD_SPRITES + 1):
                path = resource_path('assets/blood') / f'blood_{i:02d}.png'
                try:
                    self._blood.append(pygame.image.load(str(path)).convert_alpha())
                except (pygame.error, OSError):
                    pass
        return self._blood

    def _decal(self, index, angle, scale, size, dim):
        sprites = self._blood_sprites()
        if not sprites:
            return None
        key = (index, angle, scale, size, dim)
        sprite = self._decal_sprites.get(key)
        if sprite is None:
            base = sprites[index % len(sprites)]
            w = max(2, round(size * scale))
            h = max(2, round(w * base.get_height() / base.get_width()))
            sprite = pygame.transform.rotate(pygame.transform.smoothscale(base, (w, h)), angle)
            if dim:
                sprite.fill((130, 130, 130, 255), special_flags=pygame.BLEND_RGBA_MULT)
            if len(self._decal_sprites) > 400:
                self._decal_sprites.clear()
            self._decal_sprites[key] = sprite
        return sprite

    def _paint_arena_floor(self, arena, decals: DecalLayout, x, y, dim):
        """On a floor cell already painted: the darker stone of the arena's
        3x3 centre, then any blood decal. Entities are drawn after this."""
        rect = self._map_cell_rect(x, y)
        cx, cy = arena.center()
        if abs(x - cx) <= 1 and abs(y - cy) <= 1:
            shade = pygame.Surface(rect.size, pygame.SRCALPHA)
            shade.fill((0, 0, 0, ARENA_STONE_ALPHA))
            self.canvas.surface.blit(shade, rect)
        spec = decals.get((x, y))
        if spec is not None:
            sprite = self._decal(*spec, rect.width, dim)
            if sprite is not None:
                self.canvas.surface.blit(sprite, sprite.get_rect(center=rect.center))

    def _paint_entity(self, entity):
        """The entity's tile or glyph in its cell -- leaning if it just
        stepped, and offset inside the cell (clipped to the map) if it is the
        one being struck. Its floor was painted first and stays put."""
        if getattr(entity, 'kind', None) == 'arrows':
            self._paint_arrow_pile(entity)
            return
        angle = self._tilts.get(id(entity), 0)
        offset = self._jolt_of(entity)
        rgb = palette.color(entity.color, palette.VISIBLE)
        if (self._proj is not None or offset != (0, 0)) and not self.layout.tile:
            # Zoomed glyphs are big enough that the floor dot under them shows;
            # a shaking glyph would show it too, beside itself.
            self.canvas.surface.fill(palette.BACKGROUND, self._map_cell_rect(entity.x, entity.y))
        clip = self._clip_to_map() if offset != (0, 0) else None
        self._sprite_offset = offset
        try:
            if getattr(entity, 'is_boss', False):
                self._paint_boss(
                    entity.x, entity.y, entity.char, palette.brighten(rgb), entity.color, angle
                )
            else:
                char = entity.char
                if getattr(entity, 'char_class', '') == 'archer' and self.tileset.has(ARCHER_TILE):
                    char = ARCHER_TILE  # the archer's own sprite; glyph mode keeps '@'
                self._paint_cell(entity.x, entity.y, char, rgb, entity.color, angle=angle)
        finally:
            self._sprite_offset = (0, 0)
            if clip is not None:
                self.canvas.surface.set_clip(clip)

    def _paint_impact(self, hit, t):
        """A blow landing on `hit.defender`: its cell flashes red and fades,
        and the damage rises off it. A blow that kills is drawn on the victim,
        who has already left visible_entities()."""
        if hit.killed:
            self._paint_entity(hit.defender)
        rect = self._map_cell_rect(hit.x, hit.y)
        flash = pygame.Surface(rect.size, pygame.SRCALPHA)
        flash.fill((*palette.DANGER, round(IMPACT_FLASH_ALPHA * (1 - t))))
        self.canvas.surface.blit(flash, rect)
        rise = round(rect.height * 0.5 * t)
        midbottom = (rect.centerx, rect.top + rect.height // 3 - rise)
        text = f'-{hit.damage}'
        if getattr(hit, 'crit', False):
            # Double size, bright yellow, black outline.
            number = self._glyph(text, CRIT_RGB, bold=True, scale=2)
            outline = self._glyph(text, CRIT_OUTLINE_RGB, bold=True, scale=2)
            at = number.get_rect(midbottom=midbottom)
            stroke = max(1, number.get_height() // 16)
            for dx in (-stroke, 0, stroke):
                for dy in (-stroke, 0, stroke):
                    if dx or dy:
                        self.canvas.surface.blit(outline, at.move(dx, dy))
            self.canvas.surface.blit(number, at)
            return
        number = self._glyph(text, palette.brighten(palette.DANGER), bold=True)
        spot = number.get_rect(midbottom=midbottom)
        # pygame's synthetic bold is thin at these sizes, so stamp the number
        # a second time, one stroke over, to thicken it.
        stroke = max(1, number.get_height() // 14)
        self.canvas.surface.blit(number, spot)
        self.canvas.surface.blit(number, spot.move(stroke, 0))

    # -- the parry ------------------------------------------------------------

    def shield_pixels(self, parry):
        """shield_outline in pixels over the warrior's cell (parry.x, parry.y)
        at the view being painted."""
        rect = self._map_cell_rect(parry.x, parry.y)
        return [
            (rect.left + fx * rect.width, rect.top + fy * rect.height)
            for fx, fy in shield_outline()
        ]

    @staticmethod
    def shield_alpha(t):
        """The shield's opacity at t (0 -> 1 over the Guard beat): full,
        then fading to nothing over the last SHIELD_FADE."""
        if not 0 <= t < 1:
            return 0.0
        return 1.0 if t < 1 - SHIELD_FADE else (1 - t) / SHIELD_FADE

    def _paint_guard(self, parry, t):
        """The shield outline over the warrior's cell at t: a dark edge, then
        the light stroke, closed and unfilled, at shield_alpha(t)."""
        alpha = self.shield_alpha(t)
        if alpha <= 0:
            return
        rect = self._map_cell_rect(parry.x, parry.y)
        thick = max(SWING_MIN_PX, round(min(rect.size) * SHIELD_STROKE))
        points = [(x - rect.left, y - rect.top) for x, y in self.shield_pixels(parry)]
        art = pygame.Surface(rect.size, pygame.SRCALPHA)
        for rgb, width, opacity in (
            (SHIELD_EDGE_RGB, thick + 2, SHIELD_EDGE_ALPHA),
            (SHIELD_RGB, thick, 1.0),
        ):
            layer = pygame.Surface(rect.size, pygame.SRCALPHA)
            colour = (*rgb, round(255 * opacity))
            pygame.draw.lines(layer, colour, True, points, width)
            for point in points:  # round the joints
                pygame.draw.circle(layer, colour, point, width / 2)
            art.blit(layer, (0, 0))
        art.set_alpha(round(255 * alpha))
        clip = self._clip_to_map()
        try:
            self.canvas.surface.blit(art, rect)
        finally:
            self.canvas.surface.set_clip(clip)

    def parry_text_rect(self, parry, size):
        """Where "Parry!" (`size` px) goes: centred just above the warrior's
        cell, pushed down inside the map where the cell is on its top row."""
        rect = self._map_cell_rect(parry.x, parry.y)
        gap = max(1, rect.height // 12)
        spot = pygame.Rect((0, 0), size)
        spot.midbottom = (rect.centerx, rect.top - gap)
        top = self.layout.map_rect().top
        if spot.top < top:
            spot.top = top
        return spot

    def _paint_parry_text(self, parry, alpha):
        """ "Parry!" in PARRY_RGB, bold, with a dark outline, at `alpha`."""
        if alpha <= 0:
            return
        word = self._glyph(PARRY_TEXT, PARRY_RGB, bold=True)
        outline = self._glyph(PARRY_TEXT, PARRY_OUTLINE_RGB, bold=True)
        stroke = max(1, word.get_height() // 14)
        size = (word.get_width() + 2 * stroke + 1, word.get_height() + 2 * stroke)
        art = pygame.Surface(size, pygame.SRCALPHA)
        for dx in (-stroke, 0, stroke):
            for dy in (-stroke, 0, stroke):
                if dx or dy:
                    art.blit(outline, (stroke + dx, stroke + dy))
                    art.blit(outline, (stroke + dx + 1, stroke + dy))
        art.blit(word, (stroke, stroke))
        art.blit(word, (stroke + 1, stroke))  # thicken pygame's thin bold
        art.set_alpha(round(255 * min(1.0, alpha)))
        self.canvas.surface.blit(art, self.parry_text_rect(parry, size))

    # -- map cells ------------------------------------------------------------

    def _map_cell_rect(self, x, y):
        """Pixel rect of map cell (x, y) at the current view -- the frame
        being painted, or else the one last shown."""
        proj = self._proj
        if proj is None and self._view is not None:
            proj = camera.project(self._view, self.layout.map_rect(), self.layout.map_cell_size())
        if proj is None:
            return pygame.Rect(self.layout.map_cell_to_pixel(x, y), self.layout.map_cell_size())
        cell_w, cell_h, ox, oy = proj
        return pygame.Rect(ox + x * cell_w, oy + y * cell_h, cell_w, cell_h)

    def _paint_cell(self, x, y, char, rgb, color_index=0, dim=False, angle=0):
        if self._paint_tile(x, y, char, color_index, dim, angle):
            return
        if self.layout.tile or self._proj is not None or angle or self._sprite_offset != (0, 0):
            # No tile for this char (or a zoomed, leaning or shaking glyph): centred.
            self._blit_centred(self._rotated(self._glyph(char, rgb), angle), x, y)
        else:
            self.canvas.put(x, y, char, rgb)

    def _paint_tile(self, x, y, char, color_index, dim=False, angle=0):
        """Blit the tileset's tile for `char` if there is one; True if drawn.
        `angle`: lean it that many degrees (the walking gait), about its centre."""
        if not self.layout.tile:
            return False
        rect = self._map_cell_rect(x, y)
        tile = self._tile(char, color_index, rect.width, dim)
        if tile is None:
            return False
        if angle:
            key = (char, color_index, rect.width, dim, angle)
            leaning = self._tilted_tiles.get(key)
            if leaning is None:
                leaning = pygame.transform.rotate(tile, angle)
                if not self._animating or rect.width == self.layout.tile:
                    self._tilted_tiles[key] = leaning
            tile = leaning
            rect = tile.get_rect(center=rect.center)
        self.canvas.surface.blit(tile, rect.move(self._sprite_offset).topleft)
        return True

    @staticmethod
    def _rotated(surface, angle):
        return pygame.transform.rotate(surface, angle) if angle else surface

    def _tile(self, char, color_index, size, dim):
        """The tile at `size` px. Mid-animation every frame is a different
        size, so those are scaled from the source-size tile each frame rather
        than filling the tileset's cache with sizes never seen again."""
        if not self._animating or size == self.layout.tile:
            return self.tileset.glyph(char, color_index, size, dim)
        source = self.tileset.glyph(char, color_index, self.tileset.cell, dim)
        return None if source is None else pygame.transform.scale(source, (size, size))

    def _glyph(self, text, rgb, bold=False, underline=False, scale=1):
        """`text` rendered for a map cell at the current view: the layout's
        font when unzoomed, a proportionally bigger one when zoomed in."""
        if self._proj is None:
            if scale == 1:
                return self.canvas.text_surface(text, rgb, bold=bold, underline=underline)
            size = max(ui.MIN_FONT_SIZE, round(self.layout.font_size * scale))
        else:
            zoom = self._proj[1] / self.layout.map_cell_size()[1]
            size = max(ui.MIN_FONT_SIZE, round(self.layout.font_size * zoom * scale))
        key = (text, rgb, size, bold, underline)
        glyph = self._zoomed_glyphs.get(key)
        if glyph is None:
            font = self.layout._font(size)
            font.set_bold(bold)
            font.set_underline(underline)
            try:
                glyph = font.render(text, True, rgb)
            finally:
                font.set_bold(False)
                font.set_underline(False)
            if not self._animating:
                self._zoomed_glyphs[key] = glyph
        return glyph

    def _blit_centred(self, surface, x, y):
        centre = self._map_cell_rect(x, y).move(self._sprite_offset).center
        self.canvas.surface.blit(surface, surface.get_rect(center=centre))

    def _paint_boss(self, x, y, char, rgb, color_index, angle=0):
        """A boss in glyph mode: a brightened colour, a bold face, and an
        underline. In tile
        mode the boss's own tile (tiles.json gives bosses extra armour) is the
        distinction."""
        if self._paint_tile(x, y, char, color_index, angle=angle):
            return
        if self.layout.tile or self._proj is not None or angle or self._sprite_offset != (0, 0):
            self._blit_centred(
                self._rotated(self._glyph(char, rgb, bold=True, underline=True), angle), x, y
            )
        else:
            self.canvas.put(x, y, char, rgb, underline=True, bold=True)

    # -- input ----------------------------------------------------------------

    def get_action(self):
        """The next key's Action. Gameplay is keyboard-only; the exception is
        a chest's choice on screen, where a left click on a card is that
        card's CHOOSE_* (a click anywhere else, or a motion, is ignored)."""
        while True:
            state = self._state
            choosing = state is not None and state.is_choosing
            event = self._wait_input(mouse=choosing) if choosing else self._wait_key()
            if event is None:
                return Action.QUIT
            if event.type == pygame.KEYDOWN:
                return input_map.lookup(event)
            if event.type == pygame.MOUSEBUTTONDOWN:
                hit = screens.choice_card_at(self.layout, state, event.pos)
                if hit is not None and hit < len(choice.CHOOSE_ACTIONS):
                    return choice.CHOOSE_ACTIONS[hit]

    def pause(self, ms):
        """Hold the frame for `ms` while keeping the window serviced.

        Only window events are pulled off the queue; key presses are left
        queued, so typing ahead during the monster phase works the way it does
        in the terminal (where getch() simply reads them later).
        """
        if ms <= 0:
            return
        deadline = pygame.time.get_ticks() + ms
        while (remaining := deadline - pygame.time.get_ticks()) > 0:
            self._service_window()
            pygame.time.wait(min(remaining, 10))

    def _service_window(self):
        """Handle pending window events only; key presses stay queued."""
        for event in pygame.event.get(eventtype=(pygame.QUIT,) + REPAINT_EVENTS):
            self._handle_window_event(event)

    # -- teardown -------------------------------------------------------------

    def close(self):
        pygame.quit()


def _set_window_icon():
    """The SDL window/taskbar icon, if assets/icon.png is bundled. Must run
    before the first set_mode on some platforms."""
    path = resource_path('assets', ICON_FILE)
    if not path.is_file():
        return
    try:
        pygame.display.set_icon(pygame.image.load(str(path)))
    except pygame.error:
        pass
