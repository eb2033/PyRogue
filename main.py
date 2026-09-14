"""PythonRogue entry point.

Picks a renderer, builds the world, runs the loop. The loop itself is
renderer-agnostic: it only ever sees semantic actions (render.base.Action), so
adding the tcod front end does not touch this file.

    .venv/bin/python main.py                  # terminal (default)
    .venv/bin/python main.py --renderer tcod  # graphical (not yet implemented)
"""

import argparse
import os

from dotenv import load_dotenv

from game.state import GameState

DEFAULT_WIDTH = 50
DEFAULT_HEIGHT = 20
DEFAULT_FOV_RADIUS = 6
# How long to hold a frame between monster turns, in milliseconds. Set
# TURN_DELAY_MS=0 to resolve each round instantly, as it worked before the
# player and monster halves were split apart.
DEFAULT_TURN_DELAY_MS = 110


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def make_renderer(name, width, height):
    if name == 'curses':
        from render.curses_render import CursesRenderer
        return CursesRenderer()
    if name == 'tcod':
        from render.tcod_render import TcodRenderer
        return TcodRenderer(width, height)
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
    load_dotenv()

    parser = argparse.ArgumentParser(description='PythonRogue')
    parser.add_argument('--renderer', default=os.getenv('RENDERER', 'curses'),
                        choices=['curses', 'tcod'])
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
    main()
