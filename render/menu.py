"""Pure menu-selection state, kept separate from pygame so it's unit-testable
without a window. The renderer owns drawing and input translation; this owns
"which option is highlighted."
"""


class Menu:
    def __init__(self, options):
        if not options:
            raise ValueError('Menu needs at least one option')
        self.options = list(options)
        self.index = 0

    def move(self, delta):
        self.index = (self.index + delta) % len(self.options)

    def selected(self):
        return self.options[self.index]
