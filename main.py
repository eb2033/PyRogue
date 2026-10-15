"""PythonRogue entry point.

Builds the window, builds the world, runs the loop. The loop itself only ever
sees semantic actions (render.base.Action), never keycodes.

    .venv/bin/python main.py    # the game, in a window (needs pygame-ce)

Settings come from the environment, then a .env file (game/settings.py), then
the code defaults below. An uncaught exception is appended to crash.log in the
per-user data directory (game/paths.py) -- the windowed exe has no stderr.
"""

import sys

from game import crashlog, settings
from game.settings import env_int
from game.state import GameState

DEFAULT_WIDTH = 50
DEFAULT_HEIGHT = 20
DEFAULT_FOV_RADIUS = 6
# How long to hold a frame between monster turns, in milliseconds. Set
# TURN_DELAY_MS=0 to resolve each round instantly, as it worked before the
# player and monster halves were split apart.
DEFAULT_TURN_DELAY_MS = 110


BUNDLED_FONT = 'JetBrainsMono-Regular.ttf'


def make_renderer(width, height):
    from game.paths import resource_path
    from render.pygame_render import PygameRenderer
    from render.tileset import Tileset

    # TILES=0 keeps the window drawing characters instead of tiles.
    tileset = Tileset(resource_path('assets')) if env_int('TILES', 1) else None
    # The bundled font, so Windows and Linux draw the same glyphs; a missing
    # file falls back to a system monospace font.
    font = resource_path('assets', 'fonts', BUNDLED_FONT)
    # COMBAT_ZOOM=0 keeps the whole map in view during melee fights.
    return PygameRenderer(
        width,
        height,
        tileset=tileset,
        font_path=str(font) if font.is_file() else None,
        combat_zoom=bool(env_int('COMBAT_ZOOM', 1)),
    )


def resolve_player_strikes(renderer, state, delay_ms):
    """Drive the rest of the player's half: a rapier's queued second strike.

    The first strike landed in handle_action. Each pass draws it -- the
    renderer plays its hit beat (flash, damage number, shake) before the
    frame shows -- holds that frame, and only then rolls the next strike, so
    no strike's damage exists before the one before it has been seen. The
    last strike ends the player's half (GameState.step_strike queues the
    monsters), and resolve_monster_phase's first draw shows it.
    """
    while state.strike_pending():
        renderer.draw(state)
        renderer.pause(delay_ms)
        state.step_strike()


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
        resolve_player_strikes(renderer, state, delay_ms)
        resolve_monster_phase(renderer, state, delay_ms)


def main():
    # Before anything reads the environment.
    settings.load()

    # The base map size: each floor's map grows from it with depth
    # (game/dungeon.py map_size), and the window's view is sized from it
    # (render/camera.py view_size).
    width = env_int('MAP_WIDTH', DEFAULT_WIDTH)
    height = env_int('MAP_HEIGHT', DEFAULT_HEIGHT)

    renderer = make_renderer(width, height)
    try:
        if not renderer.show_title_screen():
            return  # player chose Quit
        char_class = renderer.choose_class()
        state = GameState(
            width,
            height,
            fov_radius=env_int('FOV_RADIUS', DEFAULT_FOV_RADIUS),
            char_class=char_class,
        )
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
        # (main's finally), so the window is gone before the traceback.
        crashlog.write(*sys.exc_info())
        raise
