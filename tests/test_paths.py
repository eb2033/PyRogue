"""game/paths.py (WS-B), plus
game/version.py (WS-F). Settings and crash logging have their own files:
tests/test_settings.py, tests/test_crashlog.py.

Nothing here touches the real user data dir: every test that resolves one
points it at a TemporaryDirectory via a faked APPDATA / XDG_DATA_HOME / home
or $PYROGUE_DATA_DIR.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from game import crashlog, paths, settings
from game.version import __version__

# Variables that steer user_data_dir(); each test starts with none of them set.
_DATA_ENV = ('PYROGUE_DATA_DIR', 'APPDATA', 'XDG_DATA_HOME')


def _clean_env(**extra):
    """mock.patch.dict that removes every data-dir variable, then sets `extra`."""
    patcher = mock.patch.dict(os.environ)
    patcher.start()
    for name in _DATA_ENV:
        os.environ.pop(name, None)
    os.environ.update(extra)
    return patcher


class _TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = _clean_env()
        self.addCleanup(patcher.stop)


class FrozenDetectionTest(unittest.TestCase):
    def test_frozen_detection(self):
        self.assertFalse(paths.is_frozen())
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertTrue(paths.is_frozen())


class ResourcePathTest(_TempDirTest):
    def test_from_source_resolves_into_the_repo(self):
        self.assertTrue(paths.resource_path('main.py').is_file())
        self.assertTrue(paths.resource_path('game', 'paths.py').is_file())
        self.assertEqual(paths.resource_path(), paths.SOURCE_ROOT)

    def test_meipass_wins_with_or_without_the_frozen_flag(self):
        bundle = self.tmp / '_internal'
        with (
            mock.patch.object(sys, 'frozen', True, create=True),
            mock.patch.object(sys, '_MEIPASS', str(bundle), create=True),
        ):
            self.assertEqual(
                paths.resource_path('assets', 'tiles.json'), bundle / 'assets' / 'tiles.json'
            )
        with mock.patch.object(sys, '_MEIPASS', str(self.tmp), create=True):
            self.assertEqual(paths.resource_path('x'), self.tmp / 'x')

    def test_frozen_without_meipass_uses_exe_dir(self):
        exe = self.tmp / 'dist' / 'PyRogue' / 'PyRogue.exe'
        exe.parent.mkdir(parents=True)
        exe.touch()
        self.assertFalse(hasattr(sys, '_MEIPASS'))
        with (
            mock.patch.object(sys, 'frozen', True, create=True),
            mock.patch.object(sys, 'executable', str(exe)),
        ):
            self.assertEqual(
                paths.resource_path('assets', 'icon.png'),
                exe.parent.resolve() / 'assets' / 'icon.png',
            )
            self.assertEqual(paths.app_dir(), exe.parent.resolve())

    def test_app_dir_from_source_is_repo_root(self):
        self.assertTrue((paths.app_dir() / 'main.py').is_file())


class UserDataDirTest(_TempDirTest):
    def test_platform_data_dirs(self):
        xdg = self.tmp / 'xdg'
        local_share = self.tmp / '.local' / 'share' / 'pyrogue'
        cases = (
            # name, platform, env, expected
            ('windows appdata', 'win32', {'APPDATA': str(self.tmp)}, self.tmp / 'PyRogue'),
            (
                'windows without appdata -> roaming',
                'win32',
                {},
                self.tmp / 'AppData' / 'Roaming' / 'PyRogue',
            ),
            (
                'macos application support',
                'darwin',
                {},
                self.tmp / 'Library' / 'Application Support' / 'PyRogue',
            ),
            ('linux xdg data home', 'linux', {'XDG_DATA_HOME': str(xdg)}, xdg / 'pyrogue'),
            ('linux default is local share', 'linux', {}, local_share),
            (
                'relative xdg data home is ignored',
                'linux',
                {'XDG_DATA_HOME': 'relative/dir'},
                local_share,
            ),
        )
        for name, platform, env, expected in cases:
            with self.subTest(name):
                patcher = _clean_env(**env)
                try:
                    with (
                        mock.patch.object(sys, 'platform', platform),
                        mock.patch.object(Path, 'home', return_value=self.tmp),
                    ):
                        d = paths.user_data_dir()
                finally:
                    patcher.stop()
                self.assertEqual(d, expected)
                self.assertTrue(d.is_dir(), 'parents must be created too')

    def test_explicit_override_wins_on_every_platform(self):
        override = self.tmp / 'portable'
        os.environ['PYROGUE_DATA_DIR'] = str(override)
        os.environ['APPDATA'] = str(self.tmp / 'appdata')
        os.environ['XDG_DATA_HOME'] = str(self.tmp / 'xdg')
        for platform in ('win32', 'darwin', 'linux'):
            with mock.patch.object(sys, 'platform', platform):
                self.assertEqual(paths.user_data_dir(), override)

    def test_log_lives_in_the_data_dir_resolved_at_call_time(self):
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp)
        self.assertEqual(paths.log_path(), self.tmp / 'crash.log')
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp / 'a')
        first = paths.log_path()
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp / 'b')
        self.assertNotEqual(first, paths.log_path())


class ContractTest(unittest.TestCase):
    """Signatures other streams code against exist."""

    def test_platform_functions_exist_and_version_is_semver(self):
        for fn in (
            paths.user_data_dir,
            paths.log_path,
            settings.find_config,
            settings.load,
            crashlog.write,
        ):
            self.assertTrue(callable(fn), fn)
        self.assertRegex(__version__, re.compile(r'^\d+\.\d+\.\d+$'))


if __name__ == '__main__':
    unittest.main()
