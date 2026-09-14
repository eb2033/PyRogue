"""Graphical renderer — scaffold only, not yet implemented.

This is going_graphical.md §F.2 step 4. Unlike the curses renderer, this file is
allowed dependencies (`tcod`, which pulls in `numpy`); the game/ package stays
standard library only, so the terminal build still runs on a bare Python.

To fill this in:
    .venv/bin/pip install tcod
    download a 16x16 tilesheet into assets/  (Kenney's Roguelike/RPG pack, CC0)

Then implement draw()/get_action()/close() against tcod.context, and — per §F.2
step 5 — swap game.fov.update_visibility for tcod.map.compute_fov, which gives
recursive shadowcasting (stretch goal #6) and makes walls block sight.
"""

from render.base import Action, Renderer

try:
    import tcod
except ImportError:  # pragma: no cover - expected until the dep is installed
    tcod = None

# tcod event symbols -> semantic actions. Filled in with the renderer.
KEY_ACTIONS = {}


class TcodRenderer(Renderer):
    def __init__(self, width, height, tileset_path=None):
        if tcod is None:
            raise RuntimeError(
                'The tcod renderer needs the tcod package: '
                '.venv/bin/pip install tcod'
            )
        self.width = width
        self.height = height
        self.tileset_path = tileset_path
        raise NotImplementedError('tcod renderer: see going_graphical.md §F.2 step 4')

    def draw(self, state):
        raise NotImplementedError

    def get_action(self):
        raise NotImplementedError

    def pause(self, ms):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
