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
    return (
        set(input_map.CHAR_ACTIONS.values())
        | set(input_map.KEY_ACTIONS.values())
        | set(input_map.SHOP_CHAR_ACTIONS.values())
    )


@unittest.skipUnless(input_map, 'pygame-ce not installed')
class ParityTest(unittest.TestCase):
    def test_every_action_reachable_in_pygame(self):
        # QUIT comes from closing the window, not from a key.
        self.assertEqual(pygame_actions() | {Action.QUIT}, ALL_ACTIONS)
        self.assertNotIn(Action.QUIT, pygame_actions())

    def test_key_bindings_drink_wait_ability(self):
        self.assertEqual(input_map.CHAR_ACTIONS['h'], Action.DRINK)
        self.assertEqual(input_map.CHAR_ACTIONS[' '], Action.WAIT)
        self.assertEqual(input_map.CHAR_ACTIONS['.'], Action.WAIT)
        self.assertEqual(input_map.CHAR_ACTIONS['q'], Action.ABILITY)
        self.assertEqual(input_map.CHAR_ACTIONS['r'], Action.RESTART)
        # Space still confirms in menus.
        self.assertIn(input_map.pygame.K_SPACE, input_map.CONFIRM_KEYS)

    def test_key_4_is_only_a_shop_key(self):
        four = input_map.pygame.event.Event(
            input_map.pygame.KEYDOWN, key=input_map.pygame.K_4, unicode='4', mod=0
        )
        self.assertIsNone(input_map.lookup(four))
        self.assertIsNone(input_map.lookup(four, choosing=True))
        self.assertEqual(input_map.lookup(four, shopping=True), Action.CHOOSE_4)

    def test_space_skips_only_on_the_choice_screen(self):
        self.assertEqual(input_map.CHOICE_CHAR_ACTIONS, {' ': Action.SKIP})
        space = input_map.pygame.event.Event(
            input_map.pygame.KEYDOWN, key=input_map.pygame.K_SPACE, unicode=' ', mod=0
        )
        self.assertEqual(input_map.lookup(space), Action.WAIT)
        self.assertEqual(input_map.lookup(space, choosing=True), Action.SKIP)
        # The digits still choose on the choice screen.
        one = input_map.pygame.event.Event(
            input_map.pygame.KEYDOWN, key=input_map.pygame.K_1, unicode='1', mod=0
        )
        self.assertEqual(input_map.lookup(one, choosing=True), Action.CHOOSE_1)

    def test_window_keys_never_shadow_game_keys(self):
        # F11 is the renderer's own (fullscreen); it must not also be an Action.
        for k in input_map.FULLSCREEN_KEYS:
            self.assertNotIn(k, input_map.KEY_ACTIONS)
            self.assertNotIn(k, input_map.CONFIRM_KEYS)


if __name__ == '__main__':
    unittest.main()
