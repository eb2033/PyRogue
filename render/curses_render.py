"""Terminal renderer. Standard library only.

This file is the *only* place that speaks (y, x). Everything it receives from
the game is (x, y); the flip happens here, at the boundary.
"""

import curses

from render.banner import render_banner
from render.base import Action, Renderer
from render.menu import Menu

KEY_ACTIONS = {
    ord('w'): Action.MOVE_N,
    ord('s'): Action.MOVE_S,
    ord('a'): Action.MOVE_W,
    ord('d'): Action.MOVE_E,
    # Arrows are SHOOT_*, not MOVE_* -- GameState maps them back to a plain
    # move for a warrior, or fires an arrow for an archer. See render/base.py.
    curses.KEY_UP: Action.SHOOT_N,
    curses.KEY_DOWN: Action.SHOOT_S,
    curses.KEY_LEFT: Action.SHOOT_W,
    curses.KEY_RIGHT: Action.SHOOT_E,
    ord('.'): Action.WAIT,
    # 'e' rather than '>' -- '>' needs shift on most layouts and collided
    # awkwardly with the stairs tile glyph being the same character; 'e'
    # ("enter" the stairs) is a single unshifted key next to the wasd block.
    ord('e'): Action.DESCEND,
    ord('S'): Action.SAVE,
    ord('L'): Action.LOAD,
    ord('q'): Action.QUIT,
}

CONFIRM_KEYS = (curses.KEY_ENTER, ord('\n'), ord('\r'), ord(' '))

# Pair 1 is yellow-on-black (the player). See CLAUDE.md.
# Pairs 4-7 are the gear-rarity ladder (game/item.py's RARITY_COLOR maps
# straight onto these numbers) -- green/blue/magenta climbing in value,
# white for common so it doesn't read as "nothing."
COLOR_PAIRS = {
    1: (curses.COLOR_YELLOW, curses.COLOR_BLACK),
    2: (curses.COLOR_RED, curses.COLOR_BLACK),
    3: (curses.COLOR_CYAN, curses.COLOR_BLACK),
    4: (curses.COLOR_GREEN, curses.COLOR_BLACK),    # uncommon
    5: (curses.COLOR_BLUE, curses.COLOR_BLACK),     # rare
    6: (curses.COLOR_MAGENTA, curses.COLOR_BLACK),  # epic
    7: (curses.COLOR_WHITE, curses.COLOR_BLACK),    # common
}

MESSAGE_LOG_LINES = 4

CLASS_DESCRIPTIONS = {
    'warrior': 'Melee. Walk into an enemy to hit it.',
    'archer': 'Ranged. WASD moves, arrow keys fire.',
}


class CursesRenderer(Renderer):
    def __init__(self):
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        curses.curs_set(0)

        curses.start_color()
        for pair, (fg, bg) in COLOR_PAIRS.items():
            curses.init_pair(pair, fg, bg)

    # -- drawing helpers -----------------------------------------------------

    def _put(self, y, x, ch, attr=0):
        """addch that tolerates the bottom-right cell and off-screen writes."""
        max_y, max_x = self.stdscr.getmaxyx()
        if not (0 <= y < max_y and 0 <= x < max_x):
            return
        try:
            self.stdscr.addch(y, x, ch, attr)
        except curses.error:
            pass  # bottom-right cell always raises

    def _put_str(self, y, x, text, attr=0):
        max_y, max_x = self.stdscr.getmaxyx()
        if not (0 <= y < max_y and 0 <= x < max_x):
            return
        try:
            self.stdscr.addstr(y, x, text[:max_x - x - 1], attr)
        except curses.error:
            pass

    def _put_str_centered(self, y, text, attr=0):
        max_y, max_x = self.stdscr.getmaxyx()
        x = max(0, (max_x - len(text)) // 2)
        self._put_str(y, x, text, attr)

    # -- menus ----------------------------------------------------------------

    def _run_menu(self, banner_lines, options, descriptions=None):
        """Generic up/down/enter menu. Returns the chosen option string, or
        None if the player quit out of it with 'q'."""
        menu = Menu(options)
        while True:
            self.stdscr.erase()
            max_y, max_x = self.stdscr.getmaxyx()

            top = max(1, max_y // 2 - len(banner_lines) - len(options) - 2)
            for i, line in enumerate(banner_lines):
                self._put_str_centered(top + i, line, curses.A_BOLD | curses.color_pair(1))

            options_top = top + len(banner_lines) + 2
            for i, option in enumerate(options):
                attr = curses.A_REVERSE if i == menu.index else 0
                label = f'> {option} <' if i == menu.index else f'  {option}  '
                self._put_str_centered(options_top + i * 2, label, attr)
                if descriptions and i == menu.index and descriptions.get(option.lower()):
                    self._put_str_centered(options_top + len(options) * 2 + 1,
                                           descriptions[option.lower()])

            self._put_str_centered(max_y - 2, 'up/down or w/s to choose, enter to select, q to quit')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (ord('w'), curses.KEY_UP):
                menu.move(-1)
            elif key in (ord('s'), curses.KEY_DOWN):
                menu.move(1)
            elif key in CONFIRM_KEYS:
                return menu.selected()
            elif key == ord('q'):
                return None

    def show_title_screen(self):
        banner = render_banner('PyRogue')
        choice = self._run_menu(banner, ['Start', 'Quit'])
        return choice == 'Start'

    def choose_class(self):
        banner = ['Choose your class']
        choice = self._run_menu(banner, ['Warrior', 'Archer'], CLASS_DESCRIPTIONS)
        return (choice or 'Warrior').lower()

    # -- drawing --------------------------------------------------------------

    def draw(self, state):
        self.stdscr.erase()
        self._draw_map(state)
        self._draw_entities(state)
        self._draw_panel(state)
        if state.game_over:
            self._draw_game_over(state)
        self.stdscr.refresh()

    def _draw_map(self, state):
        for y, row in enumerate(state.game_map):
            for x, tile in enumerate(row):
                if state.visible[y][x]:
                    self._put(y, x, tile, curses.A_BOLD)
                elif state.seen[y][x]:
                    self._put(y, x, tile, curses.A_DIM)

    def _draw_entities(self, state):
        for entity in state.visible_entities():
            attr = curses.color_pair(entity.color)
            if getattr(entity, 'is_boss', False):
                attr |= curses.A_BOLD | curses.A_UNDERLINE
            # (x, y) in, (y, x) out.
            self._put(entity.y, entity.x, entity.char, attr)

    def _draw_panel(self, state):
        """Side panel — stretch goal #2: HP, depth, inventory, message log,
        plus a dedicated gear section for the equipped weapon/armor."""
        x = state.width + 2
        self._put_str(0, x, 'PythonRogue')
        self._put_str(1, x, f'{state.player.char_class.capitalize()} - Depth: {state.depth}')
        hp_attr = curses.color_pair(2) if state.player.hp <= state.player.max_hp // 3 else 0
        self._put_str(2, x, f'HP: {state.player.hp}/{state.player.max_hp}', hp_attr)
        self._put_str(3, x, f'ATK {state.player.power}   DEF {state.player.defense}')
        self._put_str(4, x, f'Items: {len(state.player.inventory)}')

        gear_start = 6
        self._put_str(gear_start, x, '-- gear --')
        self._draw_gear_line(gear_start + 1, x, 'Wpn', state.player.weapon, 'atk')
        self._draw_gear_line(gear_start + 2, x, 'Arm', state.player.armor, 'def')

        controls_start = gear_start + 4
        if state.player.char_class == 'archer':
            self._put_str(controls_start, x, 'wasd move, arrows shoot')
        else:
            self._put_str(controls_start, x, 'wasd/arrows move')
        self._put_str(controls_start + 1, x, '.  wait   e  descend')
        self._put_str(controls_start + 2, x, 'S  save   L  load')
        self._put_str(controls_start + 3, x, 'q  quit')

        log_start = controls_start + 5
        self._put_str(log_start, x, '-- log --')
        recent = state.messages[-MESSAGE_LOG_LINES:]
        for i, msg in enumerate(recent):
            self._put_str(log_start + 1 + i, x, msg)

    def _draw_gear_line(self, y, x, label, item, stat_label):
        if item is None:
            self._put_str(y, x, f'{label}: (none)')
            return
        text = f'{label}: {item.name} (+{item.bonus} {stat_label}) [{item.rarity}]'
        self._put_str(y, x, text, curses.color_pair(item.color))

    def _draw_game_over(self, state):
        max_y, max_x = self.stdscr.getmaxyx()
        text = 'YOU DIED -- press q to quit'
        y = max_y // 2
        x = max(0, (state.width - len(text)) // 2)
        self._put_str(y, x, text, curses.color_pair(2) | curses.A_BOLD)

    # -- input -------------------------------------------------------------

    def get_action(self):
        return KEY_ACTIONS.get(self.stdscr.getch())

    def pause(self, ms):
        if ms > 0:
            curses.napms(ms)

    # -- teardown ----------------------------------------------------------

    def close(self):
        curses.curs_set(1)
        self.stdscr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
