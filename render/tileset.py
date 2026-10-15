"""Tile atlas loader: game char -> pygame Surface. Owned by WS-C.

Contract (desktop_build_plan.md §5 WS-C): `glyph()` returning None means "no
tile for this char -- the caller draws the character instead", and the
missing-asset path never raises. That fallback is what keeps the renderer
playable with no `assets/` at all.

The art is data, not code: `assets/tiles.json` names the spritesheets and maps
each game char to a stack of sheet cells (`layers`, drawn bottom first -- the
Kenney characters sheet is a paper-doll kit, so a goblin is a body plus
clothes plus a weapon). Adding a monster is a JSON edit. Entry options:

  "layers":   [[sheet, col, row], ...]   required
  "backdrop": true   draw a soft square in the entity's palette colour behind
                     the layers -- how an item shows its rarity
  "tint": 0.6        multiply the layers by the entity's palette colour, this
                     strong (0-1) -- for sprites that fill the whole tile, like
                     the chest, where a backdrop wouldn't show: it's what
                     makes a potion chest pink and a gear chest cyan

`assets/ASSETS.md` records where every file came from and its licence.
"""

import json
import logging
from pathlib import Path

import pygame

from render import palette

log = logging.getLogger(__name__)

TILES_FILE = 'tiles.json'
# Remembered (not currently visible) map cells: multiplied by this, the tile
# counterpart of the glyph renderer's palette.SEEN grey.
DIM = (95, 95, 115)
BACKDROP_ALPHA = 150


class Tileset:
    def __init__(self, path=None, cell=16, scale=2):
        """`path`: directory holding tiles.json and its sheets (normally
        game.paths.resource_path('assets')); `cell`: source tile size in
        pixels, overridden by tiles.json's "tile_size"; `scale`: integer
        nearest-neighbour upscale used when glyph() is given no size."""
        self.path = Path(path) if path is not None else None
        self.cell = cell
        self.scale = scale
        self.margin = 0
        self._entries = {}
        self._sheet_files = {}
        self._sheets: dict[str, pygame.Surface] | None = (
            None  # loaded lazily: convert_alpha() needs a display
        )
        self._cache = {}
        self._broken = False
        if self.path is not None:
            self._read_manifest(self.path)

    def _read_manifest(self, path):
        try:
            data = json.loads((path / TILES_FILE).read_text(encoding='utf-8'))
            self.cell = int(data.get('tile_size', self.cell))
            self.margin = int(data.get('margin', 0))
            self._sheet_files = {name: path / rel for name, rel in data['sheets'].items()}
            self._entries = {char: entry for char, entry in data['tiles'].items()}
            missing = [str(p) for p in self._sheet_files.values() if not p.is_file()]
            if missing:
                raise FileNotFoundError(', '.join(missing))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail(f'tileset unavailable ({exc}); drawing characters instead')

    def _fail(self, message):
        if not self._broken:
            log.warning(message)
        self._broken = True
        self._entries = {}

    @property
    def available(self):
        """False if the assets are missing or unreadable."""
        return bool(self._entries) and not self._broken

    @property
    def default_size(self):
        return self.cell * self.scale

    def has(self, char):
        return self.available and char in self._entries

    def glyph(self, char, color=0, size=None, dim=False):
        """The tile Surface for map char `char`, `size` pixels square (default
        cell * scale), backed by Entity.color int `color` where the entry asks
        for a backdrop, darkened when `dim` (remembered, not in view). None to
        fall back to drawing the character."""
        if not self.has(char):
            return None
        size = size or self.default_size
        key = (char, color, size, dim)
        if key not in self._cache:
            base = self._compose(char, color)
            if base is None:
                return None
            tile = pygame.transform.scale(base, (size, size))  # nearest-neighbour
            if dim:
                tile.fill(DIM, special_flags=pygame.BLEND_RGB_MULT)
            self._cache[key] = tile
        return self._cache[key]

    def _compose(self, char, color):
        """The entry's layers stacked at source resolution."""
        if not self._load_sheets():
            return None
        assert self._sheets is not None
        entry = self._entries[char]
        surface = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
        if entry.get('backdrop'):
            rgb = palette.color(color, palette.TEXT)
            pygame.draw.rect(
                surface,
                (*rgb, BACKDROP_ALPHA),
                surface.get_rect(),
                border_radius=max(1, self.cell // 4),
            )
        try:
            for sheet, col, row in entry['layers']:
                step = self.cell + self.margin
                rect = pygame.Rect(col * step, row * step, self.cell, self.cell)
                surface.blit(self._sheets[sheet].subsurface(rect), (0, 0))
        except (KeyError, ValueError, TypeError) as exc:
            log.warning('bad tiles.json entry for %r: %s', char, exc)
            del self._entries[char]
            return None
        strength = float(entry.get('tint', 0))
        if strength > 0:
            rgb = palette.color(color, palette.TEXT)
            multiplier = tuple(round(255 - (255 - c) * strength) for c in rgb)
            surface.fill(multiplier, special_flags=pygame.BLEND_RGB_MULT)
        return surface

    def _load_sheets(self):
        if self._sheets is not None:
            return True
        try:
            sheets = {name: pygame.image.load(str(p)) for name, p in self._sheet_files.items()}
            if pygame.display.get_surface() is not None:
                sheets = {name: s.convert_alpha() for name, s in sheets.items()}
        except (pygame.error, OSError) as exc:
            self._fail(f'tileset unavailable ({exc}); drawing characters instead')
            return False
        self._sheets = sheets
        return True
