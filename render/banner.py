"""ASCII-art banner text, built from a tiny 5x5 block font.

Generated from data rather than hand-drawn line by line -- hand-aligning a
multi-line banner character-by-character is exactly the kind of thing that
silently goes crooked, so the font lives here once and render_banner() does
the layout math.
"""

_FONT = {
    'P': ['#### ', '#   #', '#### ', '#    ', '#    '],
    'Y': ['#   #', ' # # ', '  #  ', '  #  ', '  #  '],
    'R': ['#### ', '#   #', '#### ', '#  # ', '#   #'],
    'O': [' ### ', '#   #', '#   #', '#   #', ' ### '],
    'G': [' ### ', '#    ', '#  ##', '#   #', ' ### '],
    'U': ['#   #', '#   #', '#   #', '#   #', ' ### '],
    'E': ['#####', '#    ', '###  ', '#    ', '#####'],
}

FONT_HEIGHT = 5


def render_banner(word, gap=' '):
    """Return a list of FONT_HEIGHT strings spelling `word` (letters must be
    in _FONT, case-insensitive). Raises KeyError for an unsupported letter."""
    letters = [_FONT[ch.upper()] for ch in word]
    return [gap.join(letter[row] for letter in letters) for row in range(FONT_HEIGHT)]
