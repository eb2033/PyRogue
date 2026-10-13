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
"""

import os
import warnings

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame

from game.paths import resource_path
from render import input_map, palette, screens, ui
from render.banner import render_banner
from render.base import Action, Renderer
from render.menu import Menu
from render.tileset import Tileset

ICON_FILE = 'icon.png'

# Events after which the window contents may be stale: repaint the last frame.
REPAINT_EVENTS = (
    pygame.VIDEORESIZE,
    pygame.VIDEOEXPOSE,
    pygame.WINDOWEXPOSED,
    pygame.WINDOWRESIZED,
    pygame.WINDOWSIZECHANGED,
)


class PygameRenderer(Renderer):
    def __init__(self, width, height, tileset=None, font_path=None):
        """`tileset`: a tileset.Tileset (None -> an unavailable one, i.e. glyphs).
        An available one puts the layout in tile mode: square map cells.
        `font_path`: a TTF/OTF file for the grid text, handed to ui.Layout
        (None -> a system monospace font); a bundled font goes through here."""
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
        self._show(lambda: self._paint_game(state))

    def _paint_game(self, state):
        for y, row in enumerate(state.game_map):
            for x, tile in enumerate(row):
                if state.visible[y][x]:
                    self._paint_cell(x, y, tile, palette.VISIBLE)
                elif state.seen[y][x]:
                    self._paint_cell(x, y, tile, palette.SEEN, dim=True)

        for entity in state.visible_entities():
            rgb = palette.color(entity.color, palette.VISIBLE)
            if getattr(entity, 'is_boss', False):
                self._paint_boss(entity.x, entity.y, entity.char, palette.brighten(rgb),
                                 entity.color)
            else:
                self._paint_cell(entity.x, entity.y, entity.char, rgb, entity.color)

        ui.paint_panel(self.canvas, state)
        if state.game_over:
            screens.paint_game_over(self.canvas, state)

    def _paint_cell(self, x, y, char, rgb, color_index=0, dim=False):
        if self._paint_tile(x, y, char, color_index, dim):
            return
        if self.layout.tile:
            # Tile mode, but no tile for this char: its glyph, centred.
            glyph = self.canvas.text_surface(char, rgb)
            rect = pygame.Rect(self.layout.map_cell_to_pixel(x, y), self.layout.map_cell_size())
            self.canvas.surface.blit(glyph, glyph.get_rect(center=rect.center))
        else:
            self.canvas.put(x, y, char, rgb)

    def _paint_tile(self, x, y, char, color_index, dim=False):
        """Blit the tileset's tile for `char` if there is one; True if drawn."""
        if not self.layout.tile:
            return False
        tile = self.tileset.glyph(char, color_index, self.layout.tile, dim)
        if tile is None:
            return False
        self.canvas.surface.blit(tile, self.layout.map_cell_to_pixel(x, y))
        return True

    def _paint_boss(self, x, y, char, rgb, color_index):
        """curses draws a boss A_BOLD | A_UNDERLINE in its pair's colour; here
        that is a brightened colour, a bold face, and an underline. In tile
        mode the boss's own tile (tiles.json gives bosses extra armour) is the
        distinction."""
        if self._paint_tile(x, y, char, color_index):
            return
        if self.layout.tile:
            glyph = self.canvas.text_surface(char, rgb, bold=True, underline=True)
            rect = pygame.Rect(self.layout.map_cell_to_pixel(x, y), self.layout.map_cell_size())
            self.canvas.surface.blit(glyph, glyph.get_rect(center=rect.center))
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
        window_events = (pygame.QUIT,) + REPAINT_EVENTS
        while (remaining := deadline - pygame.time.get_ticks()) > 0:
            for event in pygame.event.get(eventtype=window_events):
                self._handle_window_event(event)
            pygame.time.wait(min(remaining, 10))

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
