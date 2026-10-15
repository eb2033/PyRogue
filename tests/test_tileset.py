"""Headless tests for render/tileset.py and the bundled assets/ (desktop_build_plan.md
WS-C). Skip cleanly without pygame-ce."""

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

from game.item import CHEST_CHAR, CHEST_COLOR, ITEM_CHARS, POTION_CHEST_COLOR
from game.monster import MONSTER_TYPES
from game.paths import resource_path
from game.shrine import SHRINE_CHAR
from game.tiles import FLOOR, WALL

if pygame is not None:
    from render.tileset import Tileset

ASSETS = resource_path('assets')
MAX_ASSET_BYTES = 10 * 1024 * 1024


def drawable_chars():
    """Every char the game can put on the map (CLAUDE.md, Tile chars)."""
    monsters = {char for char, *_ in MONSTER_TYPES.values()}
    return (
        {WALL, FLOOR, '+', '>', '@', CHEST_CHAR, SHRINE_CHAR}
        | set(ITEM_CHARS.values())
        | monsters
        | {c.upper() for c in monsters}
    )


def mean_rgb(surface):
    return pygame.transform.average_color(surface)[:3]


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class TilesetFallbackTest(unittest.TestCase):
    """The fallback contract: no assets means 'draw the glyph', never an error."""

    def test_no_path_falls_back_to_glyphs(self):
        tileset = Tileset(path=None)
        self.assertFalse(tileset.available)
        self.assertIsNone(tileset.glyph('@', 1))

    def test_missing_directory_falls_back(self):
        with self.assertLogs('render.tileset', 'WARNING'):
            tileset = Tileset(Path(tempfile.gettempdir()) / 'no-such-pyrogue-assets')
        self.assertFalse(tileset.available)
        self.assertIsNone(tileset.glyph('#'))

    def test_corrupt_manifest_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'tiles.json').write_text('{not json', encoding='utf-8')
            with self.assertLogs('render.tileset', 'WARNING'):
                tileset = Tileset(d)
            self.assertFalse(tileset.available)

    def test_missing_sheet_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'tiles.json').write_text(
                json.dumps(
                    {
                        'sheets': {'s': 'gone.png'},
                        'tiles': {'#': {'layers': [['s', 0, 0]]}},
                    }
                ),
                encoding='utf-8',
            )
            with self.assertLogs('render.tileset', 'WARNING') as logs:
                tileset = Tileset(d)
                tileset.glyph('#')
            self.assertEqual(len(logs.output), 1)  # warned once, not per glyph
            self.assertFalse(tileset.available)
            self.assertIsNone(tileset.glyph('#'))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BundledTilesetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init()
        pygame.display.set_mode((1, 1))
        cls.tileset = Tileset(ASSETS)

    @classmethod
    def tearDownClass(cls):
        pygame.display.quit()

    def test_bundled_assets_load(self):
        self.assertTrue(self.tileset.available)

    def test_every_drawable_char_has_a_tile_of_the_requested_size(self):
        for char in sorted(drawable_chars()):
            for size in (16, 24, 48):
                tile = self.tileset.glyph(char, 0, size)
                self.assertIsNotNone(tile, f'no tile for {char!r}')
                self.assertEqual(tile.get_size(), (size, size))

    def test_unknown_char_falls_back_to_the_glyph(self):
        self.assertIsNone(self.tileset.glyph('Z'))

    def test_potion_chest_is_pinker_than_a_gear_chest(self):
        pink = mean_rgb(self.tileset.glyph(CHEST_CHAR, POTION_CHEST_COLOR, 32))
        cyan = mean_rgb(self.tileset.glyph(CHEST_CHAR, CHEST_COLOR, 32))
        self.assertGreater(pink[0] - pink[2], cyan[0] - cyan[2])
        self.assertGreater(cyan[2], pink[2] - 30)  # cyan keeps its blue

    def test_remembered_cells_are_darker(self):
        lit = mean_rgb(self.tileset.glyph(FLOOR, 0, 32))
        dim = mean_rgb(self.tileset.glyph(FLOOR, 0, 32, dim=True))
        self.assertLess(sum(dim), sum(lit))

    def test_tiles_are_cached(self):
        self.assertIs(self.tileset.glyph('@', 1, 32), self.tileset.glyph('@', 1, 32))


class AssetProvenanceTest(unittest.TestCase):
    """Plan §5 WS-C: every bundled file accounted for, under the size budget."""

    def test_assets_md_accounts_for_every_file(self):
        notes = (ASSETS / 'ASSETS.md').read_text(encoding='utf-8')
        for path in ASSETS.rglob('*'):
            if path.is_file() and path.name != 'ASSETS.md':
                rel = path.relative_to(ASSETS).as_posix()
                self.assertIn(rel, notes, f'{rel} missing from assets/ASSETS.md')

    def test_payload_under_budget(self):
        total = sum(p.stat().st_size for p in ASSETS.rglob('*') if p.is_file())
        self.assertLess(total, MAX_ASSET_BYTES)


if __name__ == '__main__':
    unittest.main()
