"""The renderer interface. Three methods is enough.

get_action() returns a *semantic* action string, never a keycode — that is what
keeps keys and windows out of the game loop and GameState.
"""


class Action:
    """Valid return values from Renderer.get_action()."""

    MOVE_N = 'move_n'
    MOVE_S = 'move_s'
    MOVE_W = 'move_w'
    MOVE_E = 'move_e'
    # Arrow keys. For a warrior these behave exactly like MOVE_* (walk /
    # bump-attack); for an archer they fire an arrow instead of moving.
    # GameState decides which, based on player.char_class -- the renderer
    # doesn't need to know about classes at all.
    SHOOT_N = 'shoot_n'
    SHOOT_S = 'shoot_s'
    SHOOT_W = 'shoot_w'
    SHOOT_E = 'shoot_e'
    WAIT = 'wait'
    DESCEND = 'descend'
    QUIT = 'quit'
    # Keys 1-3: take that card of an opened chest's choice (GameState.choose).
    # Outside a choice they do nothing.
    CHOOSE_1 = 'choose_1'
    CHOOSE_2 = 'choose_2'
    CHOOSE_3 = 'choose_3'
    # 'h': drink the first potion on the belt (GameState.drink_from_belt).
    DRINK = 'drink'


class Renderer:
    def draw(self, state):
        """Draw the whole frame from `state`."""
        raise NotImplementedError

    def get_action(self):
        """Block for input; return an Action value, or None to ignore it."""
        raise NotImplementedError

    def show_title_screen(self):
        """Block until the player picks Start or Quit. Returns True to start,
        False to quit without ever building a GameState."""
        raise NotImplementedError

    def choose_class(self):
        """Block until the player picks a class. Returns 'warrior' or 'archer'."""
        raise NotImplementedError

    def pause(self, ms):
        """Hold the current frame for `ms` milliseconds.

        Lets the game loop space out the monster half of a round so the
        player watches it resolve instead of seeing every blow land at once.
        """
        raise NotImplementedError

    def close(self):
        """Tear down the window."""
        raise NotImplementedError
