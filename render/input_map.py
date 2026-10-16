"""pygame key -> semantic Action table.

Printable keys are matched on the *character* the key produced (so a shifted
letter is a different key from the plain one); arrows are matched on the
keycode, since they produce no character.
"""

import pygame

from render.base import Action

CHAR_ACTIONS = {
    'w': Action.MOVE_N,
    's': Action.MOVE_S,
    'a': Action.MOVE_W,
    'd': Action.MOVE_E,
    '.': Action.WAIT,
    ' ': Action.WAIT,
    'e': Action.DESCEND,
    'q': Action.ABILITY,
    'h': Action.DRINK,
    # Only acts on the game-over screen (GameState.handle_action).
    'r': Action.RESTART,
    # A chest's choice cards. The numpad's digits produce the same characters.
    '1': Action.CHOOSE_1,
    '2': Action.CHOOSE_2,
    '3': Action.CHOOSE_3,
}

# Arrows are SHOOT_*, not MOVE_* -- GameState decides what that means per class.
KEY_ACTIONS = {
    pygame.K_UP: Action.SHOOT_N,
    pygame.K_DOWN: Action.SHOOT_S,
    pygame.K_LEFT: Action.SHOOT_W,
    pygame.K_RIGHT: Action.SHOOT_E,
}

# Handled inside the renderer (fullscreen toggle), never turned into an Action --
# GameState has no business knowing about windows.
FULLSCREEN_KEYS = (pygame.K_F11,)

CONFIRM_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


def event_char(event):
    """The character a KEYDOWN produced, or '' for non-printing keys.

    `event.unicode` is the reliable source, but it can come back empty when SDL
    text input is off; fall back to rebuilding letters from keycode + shift.
    """
    if event.unicode:
        return event.unicode
    if pygame.K_a <= event.key <= pygame.K_z:
        char = chr(event.key)
        return char.upper() if event.mod & pygame.KMOD_SHIFT else char
    return ''


def lookup(event):
    """Map a KEYDOWN event to an Action, or None for an unmapped key."""
    if event.key in KEY_ACTIONS:
        return KEY_ACTIONS[event.key]
    return CHAR_ACTIONS.get(event_char(event))
