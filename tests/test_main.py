"""main.py's process-level wiring: .env loading and crash logging -- plus
main.play's title -> class -> run -> (restart) cycle, with a stand-in renderer.

Run as real subprocesses -- `python main.py` is what a player (or the frozen
exe) actually executes, and the `if __name__ == '__main__'` block is the part
under test. Every run points PYROGUE_DATA_DIR at a temp dir, so nothing touches
the real user data directory.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None


def run_main(*args, drop=(), **env):
    """main.py as a subprocess: this environment minus PYROGUE_CONFIG and
    any name in `drop`, plus `env`."""
    skip = {'PYROGUE_CONFIG', *drop}
    full_env = {k: v for k, v in os.environ.items() if k not in skip}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(ROOT / 'main.py'), *args],
        cwd=env.get('PYROGUE_DATA_DIR'),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class MainProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)

    @unittest.skipUnless(pygame, 'pygame-ce not installed')
    def test_crash_is_logged_and_still_reported(self):
        # A display that can't open is a real-world crash for the windowed build.
        result = run_main(
            PYROGUE_DATA_DIR=str(self.data),
            SDL_VIDEODRIVER='no-such-driver',
            PYGAME_HIDE_SUPPORT_PROMPT='1',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Traceback', result.stderr, 'the default hook must still run')
        log = (self.data / 'crash.log').read_text(encoding='utf-8')
        self.assertIn('Traceback', log)
        self.assertIn('pygame', log)
        self.assertEqual(log.count('====='), 2, 'logged exactly once (one header)')

    @unittest.skipUnless(pygame, 'pygame-ce not installed')
    def test_config_file_is_loaded_before_the_window_opens(self):
        # SDL_VIDEODRIVER from PYROGUE_CONFIG must reach pygame's display
        # init: a driver that doesn't exist makes it fail -- proof the file
        # was read before the window was made.
        config = self.data / 'pyrogue.env'
        config.write_text('SDL_VIDEODRIVER=from-config-file\n', encoding='utf-8')
        result = run_main(
            drop=('SDL_VIDEODRIVER',),
            PYROGUE_DATA_DIR=str(self.data),
            PYROGUE_CONFIG=str(config),
            PYGAME_HIDE_SUPPORT_PROMPT='1',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('from-config-file', result.stderr)


class StandInRenderer:
    """A headless Renderer: menus answer from `titles` / `classes`, and
    get_action asks `script(state)` for each action. `log` records the order
    things happened in."""

    def __init__(self, titles, classes, script):
        self.titles, self.classes, self.script = list(titles), list(classes), script
        self.log = []
        self.state = None

    def show_title_screen(self):
        self.log.append('title')
        return self.titles.pop(0)

    def choose_class(self):
        self.log.append('class')
        return self.classes.pop(0)

    def draw(self, state):
        self.state = state

    def get_action(self):
        return self.script(self.state)

    def pause(self, ms):
        pass


class PlayLoopTest(unittest.TestCase):
    """main.play: R on the death screen goes back to the title screen; the
    next run is a GameState built only once its class is chosen."""

    def die_then(self, death_screen_key):
        """A script that kills the first run's player, then presses
        `death_screen_key`; any later run closes the window at once."""
        runs = []

        def script(state):
            if not runs or runs[-1] is not state:
                runs.append(state)
                if len(runs) > 1:
                    return 'quit'
                state.player.hp = 0
                state.game_over = True
            return death_screen_key if state.game_over else 'wait'

        return script, runs

    def test_restart_goes_back_to_the_title_and_starts_a_fresh_run(self):
        import main

        script, runs = self.die_then('restart')
        renderer = StandInRenderer([True, True], ['warrior', 'archer'], script)
        built = []
        real = main.GameState

        def build(*args, **kwargs):
            renderer.log.append('new run')
            built.append(real(*args, **kwargs))
            return built[-1]

        with mock.patch.object(main, 'GameState', side_effect=build):
            main.play(renderer, 40, 20, delay_ms=0)
        self.assertEqual(renderer.log, ['title', 'class', 'new run', 'title', 'class', 'new run'])
        dead, fresh = built
        self.assertTrue(dead.restart_requested)
        self.assertEqual(fresh.player.char_class, 'archer')
        self.assertEqual(fresh.player.hp, fresh.player.max_hp)
        self.assertFalse(fresh.game_over)

    def test_quit_on_the_death_screen_ends_play(self):
        import main

        script, runs = self.die_then('ability')  # 'press q to quit'
        renderer = StandInRenderer([True], ['warrior'], script)
        main.play(renderer, 40, 20, delay_ms=0)
        self.assertEqual(renderer.log, ['title', 'class'])
        self.assertEqual(len(runs), 1)

    def test_quit_on_the_title_after_a_restart_ends_play(self):
        import main

        script, _ = self.die_then('restart')
        renderer = StandInRenderer([True, False], ['warrior'], script)
        main.play(renderer, 40, 20, delay_ms=0)
        self.assertEqual(renderer.log, ['title', 'class', 'title'])


if __name__ == '__main__':
    unittest.main()
