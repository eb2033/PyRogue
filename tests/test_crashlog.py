"""game/crashlog.py (WS-B): uncaught exceptions land in crash.log."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from game import crashlog, paths


def _exc_info(message='boom'):
    def inner():
        raise ValueError(message)
    try:
        inner()
    except ValueError:
        return sys.exc_info()


class CrashlogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.log = self.tmp / 'crash.log'
        # Restore whatever hook was there, whatever a test does to it.
        self.addCleanup(setattr, sys, 'excepthook', sys.excepthook)
        self.addCleanup(setattr, crashlog, '_previous_hook', crashlog._previous_hook)

    def test_write_appends_full_traceback(self):
        self.assertEqual(crashlog.write(*_exc_info('first'), path=self.log), self.log)
        crashlog.write(*_exc_info('second'), path=self.log)
        text = self.log.read_text(encoding='utf-8')
        self.assertIn('Traceback (most recent call last)', text)
        self.assertIn('in inner', text)
        self.assertIn('ValueError: first', text)
        self.assertIn('ValueError: second', text)
        self.assertEqual(text.count('====='), 4, 'one header per entry')

    def test_write_defaults_to_log_path(self):
        with mock.patch.dict(os.environ, {'PYROGUE_DATA_DIR': str(self.tmp / 'data')}):
            written = crashlog.write(*_exc_info())
        self.assertEqual(written, self.tmp / 'data' / 'crash.log')
        self.assertIn('ValueError: boom', written.read_text(encoding='utf-8'))

    def test_write_never_raises(self):
        blocker = self.tmp / 'a-file'
        blocker.write_text('')
        self.assertIsNone(crashlog.write(*_exc_info(), path=blocker / 'crash.log'))
        with mock.patch.object(paths, 'log_path', side_effect=OSError('no disk')):
            self.assertIsNone(crashlog.write(*_exc_info()))
        crashlog.write(None, None, None, path=self.log)  # nonsense input: still no raise

    def test_install_logs_then_chains_to_previous_hook(self):
        seen = []
        sys.excepthook = lambda *exc: seen.append(exc[0])
        crashlog.install(self.log)
        sys.excepthook(*_exc_info())
        self.assertEqual(seen, [ValueError])
        self.assertIn('ValueError: boom', self.log.read_text(encoding='utf-8'))

    def test_install_twice_does_not_double_log(self):
        seen = []
        sys.excepthook = lambda *exc: seen.append(exc[0])
        crashlog.install(self.log)
        crashlog.install(self.log)
        sys.excepthook(*_exc_info())
        self.assertEqual(seen, [ValueError])
        self.assertEqual(self.log.read_text(encoding='utf-8').count('ValueError: boom'), 1)

    def test_keyboard_interrupt_is_not_logged(self):
        sys.excepthook = lambda *exc: None
        crashlog.install(self.log)
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())
        self.assertFalse(self.log.exists())

    def test_real_uncaught_exception_in_a_process(self):
        """End to end: a process that dies of an uncaught exception leaves a
        crash.log with the full traceback, and stderr still gets it too."""
        script = textwrap.dedent('''
            from game import crashlog
            crashlog.install()
            def explode():
                raise RuntimeError('forced crash for the test')
            explode()
        ''')
        env = dict(os.environ, PYROGUE_DATA_DIR=str(self.tmp / 'data'))
        proc = subprocess.run([sys.executable, '-c', script], cwd=str(paths.SOURCE_ROOT),
                              env=env, capture_output=True, text=True, timeout=60,
                              check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('RuntimeError: forced crash for the test', proc.stderr)
        text = (self.tmp / 'data' / 'crash.log').read_text(encoding='utf-8')
        self.assertIn('Traceback (most recent call last)', text)
        self.assertIn('in explode', text)
        self.assertIn('RuntimeError: forced crash for the test', text)


if __name__ == '__main__':
    unittest.main()
