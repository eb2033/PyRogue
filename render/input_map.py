"""pygame key -> semantic Action table. Mirrors curses_render.KEY_ACTIONS.

Printable keys are matched on the *character* the key produced (so `S` save and
`s` move-south stay distinct, exactly as curses sees them); arrows are matched
on the keycode, since they produce no character.
"""

import pygame

from render.base import Action

CHAR_ACTIONS = {
    'w': Action.MOVE_N,
    's': Action.MOVE_S,
    'a': Action.MOVE_W,
    'd': Action.MOVE_E,
    '.': Action.WAIT,
    'e': Action.DESCEND,
    'S': Action.SAVE,
    'L': Action.LOAD,
    'q': Action.QUIT,
}

# Arrows are SHOOT_*, not MOVE_* -- GameState decides what that means per class.
KEY_ACTIONS = {
    pygame.K_UP: Action.SHOOT_N,
    pygame.K_DOWN: Action.SHOOT_S,
    pygame.K_LEFT: Action.SHOOT_W,
    pygame.K_RIGHT: Action.SHOOT_E,
}

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
