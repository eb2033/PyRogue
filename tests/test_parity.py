"""The window's key table must reach every Action (desktop_build_plan.md §5 WS-G).

Catches "the key table forgot the drink key" during a refactor, which no amount
of manual play reliably catches. Skips when pygame-ce isn't installed.
"""

import os
import unittest

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

from render.base import Action

try:
    from render import input_map
except ImportError:  # pragma: no cover - no pygame
    input_map = None

ALL_ACTIONS = {value for name, value in vars(Action).items() if name.isupper()}


def pygame_actions():
    return set(input_map.CHAR_ACTIONS.values()) | set(input_map.KEY_ACTIONS.values())


@unittest.skipUnless(input_map, 'pygame-ce not installed')
class ParityTest(unittest.TestCase):
    def test_every_action_reachable_in_pygame(self):
        # QUIT comes from closing the window, not from a key.
        self.assertEqual(pygame_actions() | {Action.QUIT}, ALL_ACTIONS)
        self.assertNotIn(Action.QUIT, pygame_actions())

    def test_h_drinks(self):
        self.assertEqual(input_map.CHAR_ACTIONS['h'], Action.DRINK)

    def test_space_waits_dot_waits_q_is_the_ability(self):
        self.assertEqual(input_map.CHAR_ACTIONS[' '], Action.WAIT)
        self.assertEqual(input_map.CHAR_ACTIONS['.'], Action.WAIT)
        self.assertEqual(input_map.CHAR_ACTIONS['q'], Action.ABILITY)
        # Space still confirms in menus.
        self.assertIn(input_map.pygame.K_SPACE, input_map.CONFIRM_KEYS)

    def test_window_keys_never_shadow_game_keys(self):
        # F11 is the renderer's own (fullscreen); it must not also be an Action.
        for k in input_map.FULLSCREEN_KEYS:
            self.assertNotIn(k, input_map.KEY_ACTIONS)
            self.assertNotIn(k, input_map.CONFIRM_KEYS)


if __name__ == '__main__':
    unittest.main()
