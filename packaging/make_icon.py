"""Regenerate assets/icon.png and assets/icon.ico from the player's tile.

Run from the repo root after changing the "@" entry in assets/tiles.json:
    .venv/bin/python packaging/make_icon.py
The .ico holds PNG-compressed 16/32/48/256 px images (valid since Windows
Vista); pygame can't write .ico itself, so the container is packed by hand.
"""

import io
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from render.tileset import Tileset  # noqa: E402

SIZES = (16, 32, 48, 256)


def png_bytes(surface):
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, 'icon.png')
    return buffer.getvalue()


def main():
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    tileset = Tileset(ROOT / 'assets')
    if not tileset.has('@'):
        raise SystemExit('assets/tiles.json has no "@" tile')
    images = [png_bytes(tileset.glyph('@', size=size)) for size in SIZES]

    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b''
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size  # 0 means 256 in an ICONDIRENTRY
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (ROOT / 'assets' / 'icon.ico').write_bytes(header + entries + b''.join(images))
    (ROOT / 'assets' / 'icon.png').write_bytes(png_bytes(tileset.glyph('@', size=64)))
    print('wrote assets/icon.ico and assets/icon.png')


if __name__ == '__main__':
    main()
