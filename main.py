"""PythonRogue entry point.

Picks a renderer, builds the world, runs the loop. The loop itself is
renderer-agnostic: it only ever sees semantic actions (render.base.Action), so
adding a graphical front end does not touch this file.

    .venv/bin/python main.py                    # terminal (default from source)
    .venv/bin/python main.py --renderer pygame  # window (needs pygame-ce)

A frozen build (PyInstaller exe) defaults to the window instead: it is built
without a console, so there is no terminal for curses to draw in.

Settings come from the environment, then a .env file (game/settings.py), then
the code defaults below. An uncaught exception is appended to crash.log in the
per-user data directory (game/paths.py) -- the windowed exe has no stderr.

The terminal path imports nothing outside the standard library.
"""

import argparse
import os
import sys

from game import crashlog, settings
from game.paths import is_frozen
from game.settings import env_int
from game.state import GameState

DEFAULT_WIDTH = 50
DEFAULT_HEIGHT = 20
DEFAULT_FOV_RADIUS = 6
# How long to hold a frame between monster turns, in milliseconds. Set
# TURN_DELAY_MS=0 to resolve each round instantly, as it worked before the
# player and monster halves were split apart.
DEFAULT_TURN_DELAY_MS = 110


RENDERERS = ['curses', 'pygame']


def default_renderer():
    """$RENDERER if set, else 'pygame' in a frozen build and 'curses' from source."""
    return os.getenv('RENDERER') or ('pygame' if is_frozen() else 'curses')


def make_renderer(name, width, height):
    if name == 'curses':
        from render.curses_render import CursesRenderer
        return CursesRenderer()
    if name == 'pygame':
        from game.paths import resource_path
        from render.pygame_render import PygameRenderer
        from render.tileset import Tileset
        # TILES=0 keeps the window drawing characters, like the terminal.
        tileset = Tileset(resource_path('assets')) if env_int('TILES', 1) else None
        return PygameRenderer(width, height, tileset=tileset)
    raise SystemExit(f'unknown renderer: {name}')


def resolve_monster_phase(renderer, state, delay_ms):
    """Drive the monster half of the round one visible step at a time.

    Each pass draws the world *before* the next monster acts, then holds
    that frame if the step turns out to be something the player can see. So
    the first frame shown is the result of the player's own action, with the
    monsters yet to answer, and each subsequent frame is one monster's reply
    -- rather than the whole exchange appearing at once.

    Steps nothing can see (a monster shuffling around in the dark) resolve
    without a pause, so crossing an empty dungeon is as responsive as ever.
    """
    while state.monster_phase_pending():
        renderer.draw(state)
        if state.step_monster_phase():
            renderer.pause(delay_ms)


def run(renderer, state, delay_ms=DEFAULT_TURN_DELAY_MS):
    while state.running:
        renderer.draw(state)
        state.handle_action(renderer.get_action())
        resolve_monster_phase(renderer, state, delay_ms)


def main():
    # Before anything reads the environment -- default_renderer() included.
    settings.load()

    parser = argparse.ArgumentParser(description='PythonRogue')
    parser.add_argument('--renderer', default=default_renderer(), choices=RENDERERS)
    args = parser.parse_args()

    width = env_int('MAP_WIDTH', DEFAULT_WIDTH)
    height = env_int('MAP_HEIGHT', DEFAULT_HEIGHT)

    renderer = make_renderer(args.renderer, width, height)
    try:
        if not renderer.show_title_screen():
            return  # player chose Quit
        char_class = renderer.choose_class()
        state = GameState(width, height,
                          fov_radius=env_int('FOV_RADIUS', DEFAULT_FOV_RADIUS),
                          char_class=char_class)
        run(renderer, state, env_int('TURN_DELAY_MS', DEFAULT_TURN_DELAY_MS))
    finally:
        renderer.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Written here rather than via crashlog.install()'s excepthook: a
        # --windowed PyInstaller build reports the exception in its own dialog
        # and may never run sys.excepthook. renderer.close() has already run
        # (main's finally), so a terminal is restored before the traceback.
        crashlog.write(*sys.exc_info())
        raise
