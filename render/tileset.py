"""Tile atlas loader: game char -> pygame Surface. Owned by WS-C.

Contract (desktop_build_plan.md §5 WS-C): `glyph()` returning None means "no
tile for this char -- the caller draws the character instead", and the
missing-asset path never raises. That fallback is what keeps the renderer
playable while art is still being chosen.

P0 stub: always unavailable, so the renderer draws glyphs. WS-C fills in
loading assets/tiles.json + the atlas behind these exact signatures.
"""


class Tileset:
    def __init__(self, path=None, cell=16, scale=2):
        """`path`: directory holding tiles.json and its atlas (normally
        game.paths.resource_path('assets')); `cell`: source tile size in
        pixels; `scale`: integer nearest-neighbour upscale."""
        self.path = path
        self.cell = cell
        self.scale = scale

    @property
    def available(self):
        """False if the assets are missing or unreadable."""
        return False

    def glyph(self, char, color=0):
        """The tile Surface for map char `char` tinted by Entity.color int
        `color`, or None to fall back to drawing the character."""
        return None
