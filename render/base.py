"""The renderer interface. Everything the game loop needs from a front end.

get_action() returns a *semantic* action string, never a keycode — that is what
keeps keys and windows out of the game loop and GameState.
"""

from game.actions import Action

__all__ = ['Action', 'Renderer']


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
        """Block until the player picks a class. Returns 'warrior' or
        'archer', or None if the player backed out ('q') or closed the
        window -- main.play then returns to the title screen."""
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
