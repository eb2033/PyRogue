"""Every Action is either handled by GameState or deliberately renderer-only."""

import unittest

from game.actions import Action
from game.state import HANDLED_ACTIONS, GameState
from render.base import Action as BaseAction

# Actions the renderer consumes itself and GameState never needs to act on.
RENDERER_ONLY = frozenset()


def all_actions():
    return {v for k, v in vars(Action).items() if k.isupper() and isinstance(v, str)}


class ActionVocabularyTest(unittest.TestCase):
    def test_render_base_reexports_the_same_class(self):
        self.assertIs(BaseAction, Action)

    def test_handled_set_matches_the_vocabulary(self):
        self.assertEqual(all_actions() - HANDLED_ACTIONS - RENDERER_ONLY, set())
        self.assertLessEqual(HANDLED_ACTIONS, all_actions())

    def test_handle_action_accepts_every_handled_action(self):
        for action in sorted(HANDLED_ACTIONS - {Action.QUIT, Action.RESTART}):
            state = GameState(30, 15, seed=1)
            state.handle_action(action)  # must not raise
        state = GameState(30, 15, seed=1)
        state.handle_action(Action.QUIT)
        self.assertFalse(state.running)


if __name__ == '__main__':
    unittest.main()
