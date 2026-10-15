"""main.py's process-level wiring: .env loading and crash logging.

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


if __name__ == '__main__':
    unittest.main()
