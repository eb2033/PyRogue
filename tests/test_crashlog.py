"""game/crashlog.py (WS-B): tracebacks land in crash.log."""

import os
import sys
import tempfile
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


class RouteWarningsTest(unittest.TestCase):
    def test_render_warnings_go_to_the_file(self):
        import logging

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'warnings.log'
            logger = logging.getLogger('render')
            before = list(logger.handlers)
            self.addCleanup(logger.setLevel, logger.level)
            try:
                self.assertEqual(crashlog.route_warnings(path), path)
                crashlog.route_warnings(path)  # idempotent
                logging.getLogger('render.tileset').warning('tileset unavailable (test)')
                for handler in logger.handlers:
                    handler.flush()
                text = path.read_text(encoding='utf-8')
            finally:
                for handler in list(logger.handlers):
                    if handler not in before:
                        logger.removeHandler(handler)
                        handler.close()
            self.assertEqual(text.count('tileset unavailable (test)'), 1)


if __name__ == '__main__':
    unittest.main()
