"""game/paths.py, game/settings.py, game/crashlog.py, game/version.py (WS-B / WS-F).

P0: covers what the stubs actually implement. WS-B extends this with the
acceptance cases in desktop_build_plan.md §5 (faked _MEIPASS / APPDATA /
XDG_DATA_HOME, read-only CWD, forced crash -> crash.log).
"""

import os
import re
import sys
import unittest
from unittest import mock

from game import crashlog, paths, settings
from game.version import __version__


class PathsTest(unittest.TestCase):
    def test_not_frozen_from_source(self):
        self.assertFalse(paths.is_frozen())

    def test_frozen_detected(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertTrue(paths.is_frozen())

    def test_resource_path_resolves_into_the_repo(self):
        self.assertTrue(paths.resource_path('main.py').is_file())
        self.assertTrue(paths.resource_path('game', 'paths.py').is_file())


class SettingsTest(unittest.TestCase):
    def test_env_int_parses(self):
        with mock.patch.dict(os.environ, {'PYROGUE_TEST_INT': '42'}):
            self.assertEqual(settings.env_int('PYROGUE_TEST_INT', 7), 42)

    def test_env_int_missing_uses_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('PYROGUE_TEST_INT', None)
            self.assertEqual(settings.env_int('PYROGUE_TEST_INT', 7), 7)

    def test_env_int_garbage_uses_default(self):
        with mock.patch.dict(os.environ, {'PYROGUE_TEST_INT': 'forty'}):
            self.assertEqual(settings.env_int('PYROGUE_TEST_INT', 7), 7)


class ContractTest(unittest.TestCase):
    """Signatures other streams code against exist (bodies are WS-B's)."""

    def test_platform_functions_exist(self):
        for fn in (paths.user_data_dir, paths.save_path, paths.log_path,
                   settings.find_config, settings.load,
                   crashlog.install, crashlog.write):
            self.assertTrue(callable(fn), fn)

    def test_version_is_semver(self):
        self.assertRegex(__version__, re.compile(r'^\d+\.\d+\.\d+$'))


if __name__ == '__main__':
    unittest.main()
