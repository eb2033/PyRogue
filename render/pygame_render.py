"""Windowed renderer on pygame-ce. Allowed to import pygame; game/ never does.

This is the desktop_build_plan.md §3.1 spike: prove that the game loop in
main.py can stay exactly as it is -- draw, then a *blocking* get_action -- in an
OS window. The trick is that "blocking" means pygame.event.wait(), not a sleep:
the wait keeps the OS event queue drained, so the window repaints on expose /
resize and never gets flagged "Not Responding" while the player thinks.

Drawing is a plain glyph grid (one monospace cell per map char), the same thing
the terminal shows. Tiles, a real HUD, and in-window menus with mouse support
are later workstreams (WS-C / WS-D) and will replace the _paint_* helpers.
"""

import os
import warnings

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame

from render import input_map
from render.banner import render_banner
from render.base import Action, Renderer
from render.menu import Menu

# Mirrors curses_render.COLOR_PAIRS: Entity.color ints -> RGB.
COLORS = {
    1: (255, 215, 0),     # player (yellow)
    2: (220, 60, 60),     # red
    3: (0, 200, 200),     # chest (cyan)
    4: (70, 200, 70),     # uncommon (green)
    5: (90, 130, 255),    # rare (blue)
    6: (205, 90, 205),    # epic (magenta)
    7: (230, 230, 230),   # common (white)
}
TEXT = (200, 200, 200)
VISIBLE = (235, 235, 235)   # curses A_BOLD
SEEN = (90, 90, 90)         # curses A_DIM -- remembered, not currently in view
BACKGROUND = (0, 0, 0)

MESSAGE_LOG_LINES = 4
# The side panel starts two columns right of the map, as in curses; this many
# columns fit the widest gear line ("Wpn: <name> (+7 atk) [uncommon]").
PANEL_COLS = 44
PANEL_ROWS = 21  # log ends on row 19, plus one spare

FONT_NAMES = 'dejavusansmono,liberationmono,consolas,menlo,couriernew,monospace'
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 48
START_FONT_SIZE = 18

# Events after which the window contents may be stale: repaint the last frame.
REPAINT_EVENTS = (
    pygame.VIDEORESIZE,
    pygame.VIDEOEXPOSE,
    pygame.WINDOWEXPOSED,
    pygame.WINDOWRESIZED,
    pygame.WINDOWSIZECHANGED,
)

CLASS_DESCRIPTIONS = {
    'warrior': 'Melee. Walk into an enemy to hit it.',
    'archer': 'Ranged. WASD moves, arrow keys fire.',
}


class PygameRenderer(Renderer):
    def __init__(self, width, height):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption('PyRogue')
        # Hold-to-repeat, like a terminal's autorepeat.
        pygame.key.set_repeat(300, 60)

        self.map_width = width
        self.map_height = height
        self.cols = width + 2 + PANEL_COLS
        self.rows = max(height, PANEL_ROWS)

        self._font_path = pygame.font.match_font(FONT_NAMES)  # None -> pygame default
        self._fonts = {}
        self.font = self._font(START_FONT_SIZE)
        cell_w, cell_h = self._cell_size(self.font)
        with warnings.catch_warnings():
            # Tiling window managers resize the window on creation; that's
            # fine -- _relayout() below fits the grid to whatever we got.
            warnings.filterwarnings('ignore', 'Requested window was forcibly resized')
            self.screen = pygame.display.set_mode(
                (cell_w * self.cols, cell_h * self.rows), pygame.RESIZABLE)

        # Whatever produced the frame currently on screen, so an expose or
        # resize can repaint it without the game loop's involvement.
        self._repaint = lambda: None
        # A window-close seen somewhere we can't return Action.QUIT from
        # (a menu, a pause) is remembered and delivered by get_action.
        self._quit_requested = False
        self._relayout()

    # -- layout ---------------------------------------------------------------

    def _font(self, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(self._font_path, size)
        return self._fonts[size]

    @staticmethod
    def _cell_size(font):
        return font.size('M')[0], font.get_linesize()

    def _relayout(self):
        """Pick the largest font whose cell grid fits the window, and centre
        (letterbox) the grid. Re-rendering text at a new size keeps it crisp,
        where scaling a fixed canvas would blur or block it."""
        win_w, win_h = self.screen.get_size()
        for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -1):
            cell_w, cell_h = self._cell_size(self._font(size))
            if cell_w * self.cols <= win_w and cell_h * self.rows <= win_h:
                break
        self.font = self._font(size)
        self.cell_w, self.cell_h = self._cell_size(self.font)
        self.origin_x = max(0, (win_w - self.cell_w * self.cols) // 2)
        self.origin_y = max(0, (win_h - self.cell_h * self.rows) // 2)
        self._glyphs = {}

    # -- drawing helpers ------------------------------------------------------

    def _glyph(self, char, color, underline=False):
        key = (char, color, underline)
        if key not in self._glyphs:
            self.font.set_underline(underline)
            self._glyphs[key] = self.font.render(char, True, color)
            self.font.set_underline(False)
        return self._glyphs[key]

    def _put(self, x, y, char, color):
        self.screen.blit(self._glyph(char, color),
                         (self.origin_x + x * self.cell_w, self.origin_y + y * self.cell_h))

    def _put_str(self, x, y, text, color=TEXT, background=None, underline=False):
        """Draw text starting at cell (x, y), clipped to the grid's width."""
        if not (0 <= y < self.rows and 0 <= x < self.cols):
            return
        text = text[:self.cols - x]
        if not text:
            return
        self.font.set_underline(underline)
        surface = self.font.render(text, True, color, background)
        self.font.set_underline(False)
        self.screen.blit(surface, (self.origin_x + x * self.cell_w,
                                   self.origin_y + y * self.cell_h))

    def _put_str_centered(self, y, text, color=TEXT, background=None):
        self._put_str(max(0, (self.cols - len(text)) // 2), y, text, color, background)

    def _show(self, paint):
        """Paint a frame and remember how, so it can be repainted on expose."""
        def repaint():
            self.screen.fill(BACKGROUND)
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
            self._repaint()

    def _wait_key(self):
        """Block until a key is pressed, servicing the window meanwhile.

        Returns the KEYDOWN event, or None if the window was closed. This is
        the heart of the spike: event.wait() sleeps in the OS like getch()
        does, but wakes for expose/resize/close too, so the window stays live.
        """
        while not self._quit_requested:
            event = pygame.event.wait()
            if event.type == pygame.KEYDOWN:
                return event
            self._handle_window_event(event)
        return None

    # -- menus ----------------------------------------------------------------

    def _run_menu(self, banner_lines, options, descriptions=None):
        """Up/down/enter menu, same keys as the terminal one. Returns the
        chosen option, or None on 'q' or window close."""
        menu = Menu(options)
        while True:
            self._show(lambda: self._paint_menu(menu, banner_lines, options, descriptions))
            event = self._wait_key()
            if event is None:
                return None
            char = input_map.event_char(event)
            if char == 'w' or event.key == pygame.K_UP:
                menu.move(-1)
            elif char == 's' or event.key == pygame.K_DOWN:
                menu.move(1)
            elif event.key in input_map.CONFIRM_KEYS:
                return menu.selected()
            elif char == 'q':
                return None

    def _paint_menu(self, menu, banner_lines, options, descriptions):
        top = max(1, self.rows // 2 - len(banner_lines) - len(options) - 2)
        for i, line in enumerate(banner_lines):
            self._put_str_centered(top + i, line, COLORS[1])

        options_top = top + len(banner_lines) + 2
        for i, option in enumerate(options):
            if i == menu.index:
                self._put_str_centered(options_top + i * 2, f'> {option} <', BACKGROUND, TEXT)
                description = (descriptions or {}).get(option.lower())
                if description:
                    self._put_str_centered(options_top + len(options) * 2 + 1, description)
            else:
                self._put_str_centered(options_top + i * 2, f'  {option}  ')

        self._put_str_centered(self.rows - 2,
                               'up/down or w/s to choose, enter to select, q to quit')

    def show_title_screen(self):
        return self._run_menu(render_banner('PyRogue'), ['Start', 'Quit']) == 'Start'

    def choose_class(self):
        choice = self._run_menu(['Choose your class'], ['Warrior', 'Archer'],
                                CLASS_DESCRIPTIONS)
        return (choice or 'Warrior').lower()

    # -- game frame -----------------------------------------------------------

    def draw(self, state):
        self._show(lambda: self._paint_game(state))

    def _paint_game(self, state):
        for y, row in enumerate(state.game_map):
            for x, tile in enumerate(row):
                if state.visible[y][x]:
                    self._put(x, y, tile, VISIBLE)
                elif state.seen[y][x]:
                    self._put(x, y, tile, SEEN)

        for entity in state.visible_entities():
            color = COLORS.get(entity.color, VISIBLE)
            is_boss = getattr(entity, 'is_boss', False)
            self.screen.blit(self._glyph(entity.char, color, underline=is_boss),
                             (self.origin_x + entity.x * self.cell_w,
                              self.origin_y + entity.y * self.cell_h))

        self._paint_panel(state)
        if state.game_over:
            text = 'YOU DIED -- press q to quit'
            x = max(0, (state.width - len(text)) // 2)
            self._put_str(x, state.height // 2, text, COLORS[2], BACKGROUND)

    def _paint_panel(self, state):
        """Same items, same rows as curses_render._draw_panel."""
        player = state.player
        x = state.width + 2
        self._put_str(x, 0, 'PythonRogue')
        self._put_str(x, 1, f'{player.char_class.capitalize()} - Depth: {state.depth}')
        hp_color = COLORS[2] if player.hp <= player.max_hp // 3 else TEXT
        self._put_str(x, 2, f'HP: {player.hp}/{player.max_hp}', hp_color)
        self._put_str(x, 3, f'ATK {player.power}   DEF {player.defense}')
        self._put_str(x, 4, f'Items: {len(player.inventory)}')

        gear_start = 6
        self._put_str(x, gear_start, '-- gear --')
        self._paint_gear_line(x, gear_start + 1, 'Wpn', player.weapon, 'atk')
        self._paint_gear_line(x, gear_start + 2, 'Arm', player.armor, 'def')

        controls_start = gear_start + 4
        if player.char_class == 'archer':
            self._put_str(x, controls_start, 'wasd move, arrows shoot')
        else:
            self._put_str(x, controls_start, 'wasd/arrows move')
        self._put_str(x, controls_start + 1, '.  wait   e  descend')
        self._put_str(x, controls_start + 2, 'S  save   L  load')
        self._put_str(x, controls_start + 3, 'q  quit')

        log_start = controls_start + 5
        self._put_str(x, log_start, '-- log --')
        for i, msg in enumerate(state.messages[-MESSAGE_LOG_LINES:]):
            self._put_str(x, log_start + 1 + i, msg)

    def _paint_gear_line(self, x, y, label, item, stat_label):
        if item is None:
            self._put_str(x, y, f'{label}: (none)')
            return
        text = f'{label}: {item.name} (+{item.bonus} {stat_label}) [{item.rarity}]'
        self._put_str(x, y, text, COLORS.get(item.color, TEXT))

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
