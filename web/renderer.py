"""The browser's renderer: PygameRenderer with every wait made async.

A page only repaints (and only reads keys) when Python yields to the browser,
which under pygbag means `await asyncio.sleep(0)`. So each wait here is a loop
that drains events without blocking, does one slice of work and yields. Nothing
in this file may call pygame.event.wait() (with an empty queue it hangs the tab
for good) or pygame.time.wait() (it freezes the tab for its duration).

Never reach pygame.Window, display.toggle_fullscreen or set_fullscreen either:
hasattr says they exist, but calling one kills the wasm app. The canvas is a
fixed size and the browser (itch.io) owns fullscreen, so F11 does nothing.

Owner: browser build WS-A. Semantics are those documented on the PygameRenderer
methods each override mirrors.
"""

import asyncio

import pygame

from game.monster import Monster
from render import choice, input_map, palette, screens
from render.banner import render_banner
from render.base import Action
from render.menu import Menu
from render.pygame_render import REPEAT_BLOCKED_ACTIONS, PygameRenderer

# 16:9, which the pygbag page template assumes; CSS scales the canvas to fit.
CANVAS_SIZE = (1280, 720)

GOODBYE_TITLE = 'Thanks for playing!'
GOODBYE_HINT = 'Reload the page to play again.'


def paint_goodbye(canvas):
    """The quit screen: the thanks and how to start over, centred."""
    row = canvas.layout.rows // 2
    canvas.put_str_centered(row - 1, GOODBYE_TITLE, palette.PLAYER)
    canvas.put_str_centered(row + 1, GOODBYE_HINT)


class WebRenderer(PygameRenderer):
    def __init__(self, width, height, tileset=None, font_path=None, combat_zoom=True, **timings):
        super().__init__(
            width, height, tileset=tileset, font_path=font_path, combat_zoom=combat_zoom, **timings
        )

    def _open_display(self):
        # No DPI call and no window icon: neither exists in the browser.
        pygame.display.init()
        pygame.display.set_caption('PyRogue')
        # get_ticks() reads 0 until the timer subsystem is up. The desktop gets
        # it from its first time.wait(); there is no wait here, so make a Clock.
        pygame.time.Clock()

    @staticmethod
    def _set_mode(size, flags):
        # Fixed canvas, whatever size and flags (RESIZABLE) the layout asks for.
        return pygame.display.set_mode(CANVAS_SIZE)

    def toggle_fullscreen(self):
        """F11 does nothing: the browser has its own fullscreen button."""

    def close(self):
        """Leave the last frame on the page; pygame.quit() has nothing to free."""

    # -- events ---------------------------------------------------------------

    async def _wait_input(self, mouse=False):  # type: ignore[override]
        """Wait for a key press (or, with `mouse`, a mouse motion / left
        click), servicing the window meanwhile. Returns the event, or None if
        the window was closed. Events come off the queue one at a time with
        poll(), so what is not consumed stays queued, in order."""
        while not self._quit_requested:
            event = pygame.event.poll()
            if event.type == pygame.NOEVENT:
                await asyncio.sleep(0)
                continue
            if event.type == pygame.KEYDOWN:
                if event.key in input_map.FULLSCREEN_KEYS:
                    self.toggle_fullscreen()
                    continue
                self._last_was_repeat = bool(getattr(event, 'repeat', False)) or (
                    event.key in self._held
                )
                self._held.add(event.key)
                return event
            if event.type == pygame.KEYUP:
                self._held.discard(event.key)
                continue
            if event.type == pygame.WINDOWFOCUSLOST:
                self._held.clear()
            if mouse and (
                event.type == pygame.MOUSEMOTION
                or (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
            ):
                return event
            self._handle_window_event(event)
        return None

    async def _wait_key(self):  # type: ignore[override]
        return await self._wait_input()

    # -- menus ----------------------------------------------------------------

    async def _run_menu(self, banner_lines, options, descriptions=None):  # type: ignore[override]
        menu = Menu(options)
        repaint = True
        while True:
            if repaint:
                self._show(
                    lambda: screens.paint_menu(self.canvas, menu, banner_lines, descriptions)
                )
            repaint = True
            event = await self._wait_input(mouse=True)
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

    async def show_title_screen(self):  # type: ignore[override]
        self._forget_run()
        return await self._run_menu(render_banner('PyRogue'), screens.TITLE_OPTIONS) == 'Start'

    async def choose_class(self):  # type: ignore[override]
        picked = await self._run_menu(
            ['Choose your class'], screens.CLASS_OPTIONS, screens.CLASS_DESCRIPTIONS
        )
        return (picked or 'Warrior').lower()

    async def show_goodbye(self):
        """The last frame of a quit: a browser tab can't close itself, so say
        so instead of leaving the title or the death screen looking frozen."""
        self._show(lambda: paint_goodbye(self.canvas))

    # -- game frame -----------------------------------------------------------

    async def draw(self, state):  # type: ignore[override]
        tilts, beats = self._stage(state)
        try:
            await self._play_beats(state, beats)
        finally:
            self._parry_text = None
        self._view = self.director.current(state)
        if tilts:
            self._tilts = tilts
            try:
                await self._play(*self._walk_spec(state))
            finally:
                self._tilts = {}
        self._show_game(state)

    async def _play_beats(self, state, beats):  # type: ignore[override]
        for spec in self._beat_specs(state, beats):
            await self._play(*spec)

    async def _play(self, ms, paint, interruptible=True):  # type: ignore[override]
        """One beat: `paint(t)` for t running 0 -> 1 over `ms`, one frame per
        yield to the browser. Key presses stay queued; an interruptible beat
        ends early on one, a window close ends any beat."""
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
                await asyncio.sleep(0)
        finally:
            self._animating = False

    # -- input ----------------------------------------------------------------

    async def get_action(self):  # type: ignore[override]
        # Yield once per action, even with keys already queued: the frame just
        # drawn reaches the screen, and a backlog of typed-ahead keys (whose
        # walk and pan beats end at once) can't hold the tab for a frame each.
        await asyncio.sleep(0)
        while True:
            state = self._state
            choosing = state is not None and state.is_choosing
            event = await (self._wait_input(mouse=True) if choosing else self._wait_key())
            if event is None:
                return Action.QUIT
            if event.type == pygame.KEYDOWN:
                action = input_map.lookup(event, choosing=choosing)
                if (
                    self._last_was_repeat
                    and action in REPEAT_BLOCKED_ACTIONS
                    and state is not None
                    and any(isinstance(e, Monster) for e in state.visible_entities())
                ):
                    continue  # held movement stops while an enemy is in view
                if action == Action.RESTART and not (state is not None and state.game_over):
                    return None  # 'r' only means something on the death screen
                return action
            if event.type == pygame.MOUSEBUTTONDOWN:
                hit = screens.choice_card_at(self.layout, state, event.pos)
                if hit is not None and hit < len(choice.CHOOSE_ACTIONS):
                    return choice.CHOOSE_ACTIONS[hit]
                if screens.choice_skip_at(self.layout, state, event.pos):
                    return choice.SKIP_ACTION

    async def pause(self, ms):  # type: ignore[override]
        """Hold the frame for `ms`, yielding to the browser. Only window events
        are pulled off the queue, so typing ahead works."""
        if ms <= 0:
            return
        deadline = pygame.time.get_ticks() + ms
        while deadline - pygame.time.get_ticks() > 0:
            self._service_window()
            await asyncio.sleep(0)
