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
    import pygame  # noqa: F401
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None


def run_main(*args, **env):
    full_env = {k: v for k, v in os.environ.items()
                if k not in ('RENDERER', 'PYROGUE_CONFIG')}
    full_env.update(env)
    return subprocess.run([sys.executable, str(ROOT / 'main.py'), *args],
                          cwd=env.get('PYROGUE_DATA_DIR'), env=full_env,
                          capture_output=True, text=True, timeout=60)


class MainProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)

    @unittest.skipUnless(pygame, 'pygame-ce not installed')
    def test_crash_is_logged_and_still_reported(self):
        # A display that can't open is a real-world crash for the windowed build.
        result = run_main('--renderer', 'pygame', PYROGUE_DATA_DIR=str(self.data),
                          SDL_VIDEODRIVER='no-such-driver', PYGAME_HIDE_SUPPORT_PROMPT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Traceback', result.stderr, 'the default hook must still run')
        log = (self.data / 'crash.log').read_text(encoding='utf-8')
        self.assertIn('Traceback', log)
        self.assertIn('pygame', log)
        self.assertEqual(log.count('====='), 2, 'logged exactly once (one header)')

    def test_config_file_is_loaded_before_renderer_is_chosen(self):
        # RENDERER from PYROGUE_CONFIG must reach the renderer choice. An
        # unknown name is rejected by make_renderer (argparse doesn't check a
        # default against `choices`) -- proof the file was read in time.
        config = self.data / 'pyrogue.env'
        config.write_text('RENDERER=from-config-file\n', encoding='utf-8')
        result = run_main(PYROGUE_DATA_DIR=str(self.data), PYROGUE_CONFIG=str(config))
        self.assertEqual(result.returncode, 1)
        self.assertIn('unknown renderer: from-config-file', result.stderr)
        self.assertFalse((self.data / 'crash.log').exists(), 'a usage error is not a crash')


if __name__ == '__main__':
    unittest.main()
