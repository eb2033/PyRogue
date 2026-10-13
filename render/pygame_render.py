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
  camera.Director        the combat zoom: what part of the map to show, and
                         the beats (impacts, pans) staged before each frame
"""

import os
import warnings

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame

from game.paths import resource_path
from render import camera, input_map, palette, screens, ui
from render.banner import render_banner
from render.base import Action, Renderer
from render.menu import Menu
from render.tileset import Tileset

ICON_FILE = 'icon.png'

# Combat staging (render/camera.py). How long each beat plays; a key the
# player has already pressed cuts the rest of a beat short.
ZOOM_MS = 220
IMPACT_MS = 160
FRAME_MS = 16
IMPACT_FLASH_ALPHA = 170

# Events after which the window contents may be stale: repaint the last frame.
REPAINT_EVENTS = (
    pygame.VIDEORESIZE,
    pygame.VIDEOEXPOSE,
    pygame.WINDOWEXPOSED,
    pygame.WINDOWRESIZED,
    pygame.WINDOWSIZECHANGED,
)


class PygameRenderer(Renderer):
    def __init__(self, width, height, tileset=None, font_path=None,
                 combat_zoom=True, zoom_ms=ZOOM_MS, impact_ms=IMPACT_MS):
        """`tileset`: a tileset.Tileset (None -> an unavailable one, i.e. glyphs).
        An available one puts the layout in tile mode: square map cells.
        `font_path`: a TTF/OTF file for the grid text, handed to ui.Layout
        (None -> a system monospace font); a bundled font goes through here.
        `combat_zoom`: zoom the map in on melee fights (render/camera.py);
        `zoom_ms` / `impact_ms`: how long a pan / an impact flash plays (0 =
        no animation, the frame just changes)."""
        pygame.display.init()
        pygame.display.set_caption('PyRogue')
        _set_window_icon()
        # Hold-to-repeat, like a terminal's autorepeat.
        pygame.key.set_repeat(300, 60)

        self.tileset = tileset or Tileset()
        self.layout = ui.Layout(width, height, font_path=font_path,
                                tiles=self.tileset.available)
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

        self.director = camera.Director(zoom=combat_zoom)
        self.zoom_ms = zoom_ms
        self.impact_ms = impact_ms
        # The view being painted (None = the whole map, the unzoomed layout),
        # its projection for the frame being painted, and whether a beat is
        # mid-play (in-between sizes are drawn uncached -- see _tile).
        self._view = None
        self._proj = None
        self._animating = False
        self._zoomed_glyphs = {}

    @staticmethod
    def _set_mode(size, flags):
        with warnings.catch_warnings():
            # Tiling window managers resize the window on creation; that's
            # fine -- fit() sizes the grid to whatever we got.
            warnings.filterwarnings('ignore', 'Requested window was forcibly resized')
            return pygame.display.set_mode(size, flags)

    def _relayout(self):
        """Pick up the current window surface and size, then repaint."""
        self.canvas.surface = pygame.display.get_surface()
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
            if mouse and (event.type == pygame.MOUSEMOTION or
                          (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)):
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
                self._show(lambda: screens.paint_menu(self.canvas, menu, banner_lines,
                                                      descriptions))
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
        choice = self._run_menu(['Choose your class'], screens.CLASS_OPTIONS,
                                screens.CLASS_DESCRIPTIONS)
        return (choice or 'Warrior').lower()

    # -- game frame -----------------------------------------------------------

    def draw(self, state):
        """Play whatever the combat camera stages (impacts, then a pan), then
        show the frame. With nothing to stage this is just the paint."""
        for beat in self.director.plan(state):
            if isinstance(beat, camera.Impact):
                self._play(self.impact_ms,
                           lambda t, hit=beat.hit: self._paint_game(state, impact=(hit, t)))
            elif isinstance(beat, camera.Pan):
                self._play(self.zoom_ms, lambda t, pan=beat: self._paint_pan(state, pan, t))
        self._view = self.director.view
        self._show(lambda: self._paint_game(state))

    # -- staged beats ---------------------------------------------------------

    def _play(self, ms, paint):
        """Play one beat: `paint(t)` for t running 0 -> 1 over `ms`.

        Like pause(), the window stays serviced and key presses stay queued
        -- and a queued key (typed ahead, or held down) ends the beat early,
        so animation never makes the player wait for their next move. The
        beat's final frame isn't painted here: the next beat, or draw()'s own
        frame, is that frame.
        """
        if ms <= 0:
            return
        self._animating = True
        try:
            start = pygame.time.get_ticks()
            while not self._quit_requested and not self._key_waiting():
                t = (pygame.time.get_ticks() - start) / ms
                if t >= 1:
                    break
                self._show(lambda: paint(t))
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

    def _paint_game(self, state, impact=None):
        """The map at the current view, clipped to the map's area, then the
        panel. `impact`: (Hit, t) to draw a blow landing, t running 0 -> 1."""
        surface = self.canvas.surface
        map_rect = self.layout.map_rect()
        if self._view is None:
            self._proj = None
            cols, rows = range(state.width), range(state.height)
        else:
            self._proj = camera.project(self._view, map_rect, self.layout.map_cell_size())
            cell_w, cell_h, ox, oy = self._proj
            cols = range(max(0, (map_rect.left - ox) // cell_w),
                         min(state.width, (map_rect.right - ox) // cell_w + 1))
            rows = range(max(0, (map_rect.top - oy) // cell_h),
                         min(state.height, (map_rect.bottom - oy) // cell_h + 1))
            surface.set_clip(map_rect)
        try:
            for y in rows:
                row = state.game_map[y]
                for x in cols:
                    if state.visible[y][x]:
                        self._paint_cell(x, y, row[x], palette.VISIBLE)
                    elif state.seen[y][x]:
                        self._paint_cell(x, y, row[x], palette.SEEN, dim=True)

            for entity in state.visible_entities():
                self._paint_entity(entity)
            if impact is not None:
                self._paint_impact(*impact)
        finally:
            surface.set_clip(None)
            self._proj = None

        ui.paint_panel(self.canvas, state)
        if state.game_over:
            screens.paint_game_over(self.canvas)

    def _paint_entity(self, entity):
        rgb = palette.color(entity.color, palette.VISIBLE)
        if self._proj is not None and not self.layout.tile:
            # Zoomed glyphs are big enough that the floor dot under them shows.
            self.canvas.surface.fill(palette.BACKGROUND,
                                     self._map_cell_rect(entity.x, entity.y))
        if getattr(entity, 'is_boss', False):
            self._paint_boss(entity.x, entity.y, entity.char, palette.brighten(rgb),
                             entity.color)
        else:
            self._paint_cell(entity.x, entity.y, entity.char, rgb, entity.color)

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
        number = self._glyph(f'-{hit.damage}', palette.brighten(palette.DANGER), bold=True)
        rise = round(rect.height * 0.5 * t)
        spot = number.get_rect(midbottom=(rect.centerx, rect.top + rect.height // 3 - rise))
        # pygame's synthetic bold is thin at these sizes, so stamp the number
        # a second time, one stroke over, to thicken it.
        stroke = max(1, number.get_height() // 14)
        self.canvas.surface.blit(number, spot)
        self.canvas.surface.blit(number, spot.move(stroke, 0))

    # -- map cells ------------------------------------------------------------

    def _map_cell_rect(self, x, y):
        """Pixel rect of map cell (x, y) at the current view."""
        if self._proj is None:
            return pygame.Rect(self.layout.map_cell_to_pixel(x, y), self.layout.map_cell_size())
        cell_w, cell_h, ox, oy = self._proj
        return pygame.Rect(ox + x * cell_w, oy + y * cell_h, cell_w, cell_h)

    def _paint_cell(self, x, y, char, rgb, color_index=0, dim=False):
        if self._paint_tile(x, y, char, color_index, dim):
            return
        if self.layout.tile or self._proj is not None:
            # No tile for this char (or a zoomed glyph map): its glyph, centred.
            self._blit_centred(self._glyph(char, rgb), x, y)
        else:
            self.canvas.put(x, y, char, rgb)

    def _paint_tile(self, x, y, char, color_index, dim=False):
        """Blit the tileset's tile for `char` if there is one; True if drawn."""
        if not self.layout.tile:
            return False
        rect = self._map_cell_rect(x, y)
        tile = self._tile(char, color_index, rect.width, dim)
        if tile is None:
            return False
        self.canvas.surface.blit(tile, rect.topleft)
        return True

    def _tile(self, char, color_index, size, dim):
        """The tile at `size` px. Mid-animation every frame is a different
        size, so those are scaled from the source-size tile each frame rather
        than filling the tileset's cache with sizes never seen again."""
        if not self._animating or size == self.layout.tile:
            return self.tileset.glyph(char, color_index, size, dim)
        source = self.tileset.glyph(char, color_index, self.tileset.cell, dim)
        return None if source is None else pygame.transform.scale(source, (size, size))

    def _glyph(self, text, rgb, bold=False, underline=False):
        """`text` rendered for a map cell at the current view: the layout's
        font when unzoomed, a proportionally bigger one when zoomed in."""
        if self._proj is None:
            return self.canvas.text_surface(text, rgb, bold=bold, underline=underline)
        zoom = self._proj[1] / self.layout.map_cell_size()[1]
        size = max(ui.MIN_FONT_SIZE, round(self.layout.font_size * zoom))
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
        centre = self._map_cell_rect(x, y).center
        self.canvas.surface.blit(surface, surface.get_rect(center=centre))

    def _paint_boss(self, x, y, char, rgb, color_index):
        """curses draws a boss A_BOLD | A_UNDERLINE in its pair's colour; here
        that is a brightened colour, a bold face, and an underline. In tile
        mode the boss's own tile (tiles.json gives bosses extra armour) is the
        distinction."""
        if self._paint_tile(x, y, char, color_index):
            return
        if self.layout.tile or self._proj is not None:
            self._blit_centred(self._glyph(char, rgb, bold=True, underline=True), x, y)
        else:
            self.canvas.put(x, y, char, rgb, underline=True, bold=True)

    # -- input ----------------------------------------------------------------

    def get_action(self):
        event = self._wait_key()
        if event is None:
            return Action.QUIT
        return input_map.lookup(event)

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
