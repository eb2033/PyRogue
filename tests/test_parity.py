"""Both renderers must reach the same set of Actions (desktop_build_plan.md §5 WS-G).

Catches "the pygame build forgot the save key" during a refactor, which no
amount of manual play reliably catches. Skips whichever side can't be imported
(no pygame, or Windows without windows-curses).
"""

import os
import unittest

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

from render.base import Action

try:
    from render import input_map
except ImportError:  # pragma: no cover - no pygame
    input_map = None

try:
    from render.curses_render import KEY_ACTIONS as CURSES_ACTIONS
except ImportError:  # pragma: no cover - Windows without windows-curses
    CURSES_ACTIONS = None

ALL_ACTIONS = {value for name, value in vars(Action).items() if name.isupper()}


def pygame_actions():
    return set(input_map.CHAR_ACTIONS.values()) | set(input_map.KEY_ACTIONS.values())


class ParityTest(unittest.TestCase):
    @unittest.skipUnless(input_map and CURSES_ACTIONS, 'needs both pygame and curses')
    def test_same_actions_reachable_in_both_renderers(self):
        self.assertEqual(pygame_actions(), set(CURSES_ACTIONS.values()))

    @unittest.skipUnless(CURSES_ACTIONS, 'curses not available')
    def test_every_action_reachable_in_curses(self):
        self.assertEqual(set(CURSES_ACTIONS.values()), ALL_ACTIONS)

    @unittest.skipUnless(input_map, 'pygame-ce not installed')
    def test_every_action_reachable_in_pygame(self):
        self.assertEqual(pygame_actions(), ALL_ACTIONS)

    @unittest.skipUnless(input_map and CURSES_ACTIONS, 'needs both pygame and curses')
    def test_h_drinks_in_both_renderers(self):
        self.assertEqual(CURSES_ACTIONS[ord('h')], Action.DRINK)
        self.assertEqual(input_map.CHAR_ACTIONS['h'], Action.DRINK)

    @unittest.skipUnless(input_map, 'pygame-ce not installed')
    def test_window_keys_never_shadow_game_keys(self):
        # F11 is the renderer's own (fullscreen); it must not also be an Action.
        for k in input_map.FULLSCREEN_KEYS:
            self.assertNotIn(k, input_map.KEY_ACTIONS)
            self.assertNotIn(k, input_map.CONFIRM_KEYS)


if __name__ == '__main__':
    unittest.main()
