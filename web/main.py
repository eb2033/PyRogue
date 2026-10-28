"""Browser entry point (pygbag). The build copies this to main.py at the root
of the staged folder, next to game/, render/, web/ and assets/.

Settings are hard-coded: there is no .env and no crash.log in the browser, and
an uncaught error is written to the browser console instead.
"""

import asyncio
import sys
import traceback

import pygame  # noqa: F401  (pygbag scans imports to fetch the pygame-ce wheel)

from game.paths import resource_path
from render.tileset import Tileset
from web.loop import play
from web.renderer import WebRenderer

WIDTH = 50
HEIGHT = 20
FOV_RADIUS = 6
TURN_DELAY_MS = 110
BUNDLED_FONT = 'JetBrainsMono-Regular.ttf'


def log_to_console(text):
    """print() does not reach DevTools under pygbag; platform.window does."""
    if sys.platform == 'emscripten':
        import platform

        platform.window.console.log(text)  # type: ignore[attr-defined]
    else:
        print(text, file=sys.stderr)


async def main():
    try:
        font = resource_path('assets', 'fonts', BUNDLED_FONT)
        renderer = WebRenderer(
            WIDTH,
            HEIGHT,
            tileset=Tileset(resource_path('assets')),
            font_path=str(font) if font.is_file() else None,
            combat_zoom=True,
        )
        try:
            await play(renderer, WIDTH, HEIGHT, fov_radius=FOV_RADIUS, delay_ms=TURN_DELAY_MS)
        finally:
            renderer.close()
    except Exception:
        log_to_console(traceback.format_exc())
        raise


if __name__ == '__main__':
    asyncio.run(main())
