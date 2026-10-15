"""game/paths.py and the save-location wiring in game/state.py (WS-B), plus
game/version.py (WS-F). Settings and crash logging have their own files:
tests/test_settings.py, tests/test_crashlog.py.

Nothing here touches the real user data dir: every test that resolves one
points it at a TemporaryDirectory via a faked APPDATA / XDG_DATA_HOME / home
or $PYROGUE_DATA_DIR.
"""

import os
import random
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from game import crashlog, paths, settings
from game import state as state_module
from game.state import GameState
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
    def test_not_frozen_from_source(self):
        self.assertFalse(paths.is_frozen())

    def test_frozen_detected(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertTrue(paths.is_frozen())


class ResourcePathTest(_TempDirTest):
    def test_from_source_resolves_into_the_repo(self):
        self.assertTrue(paths.resource_path('main.py').is_file())
        self.assertTrue(paths.resource_path('game', 'paths.py').is_file())
        self.assertEqual(paths.resource_path(), paths.SOURCE_ROOT)

    def test_meipass_wins(self):
        bundle = self.tmp / '_internal'
        with mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, '_MEIPASS', str(bundle), create=True):
            self.assertEqual(paths.resource_path('assets', 'tiles.json'),
                             bundle / 'assets' / 'tiles.json')

    def test_meipass_wins_even_without_frozen_flag(self):
        with mock.patch.object(sys, '_MEIPASS', str(self.tmp), create=True):
            self.assertEqual(paths.resource_path('x'), self.tmp / 'x')

    def test_frozen_without_meipass_uses_exe_dir(self):
        exe = self.tmp / 'dist' / 'PyRogue' / 'PyRogue.exe'
        exe.parent.mkdir(parents=True)
        exe.touch()
        self.assertFalse(hasattr(sys, '_MEIPASS'))
        with mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, 'executable', str(exe)):
            self.assertEqual(paths.resource_path('assets', 'icon.png'),
                             exe.parent.resolve() / 'assets' / 'icon.png')
            self.assertEqual(paths.app_dir(), exe.parent.resolve())

    def test_app_dir_from_source_is_repo_root(self):
        self.assertTrue((paths.app_dir() / 'main.py').is_file())


class UserDataDirTest(_TempDirTest):
    def test_windows_honours_appdata(self):
        with mock.patch.object(sys, 'platform', 'win32'):
            os.environ['APPDATA'] = str(self.tmp)
            d = paths.user_data_dir()
        self.assertEqual(d, self.tmp / 'PyRogue')
        self.assertTrue(d.is_dir())

    def test_windows_without_appdata_falls_back_to_roaming(self):
        with mock.patch.object(sys, 'platform', 'win32'), \
                mock.patch.object(Path, 'home', return_value=self.tmp):
            d = paths.user_data_dir()
        self.assertEqual(d, self.tmp / 'AppData' / 'Roaming' / 'PyRogue')
        self.assertTrue(d.is_dir())

    def test_macos_application_support(self):
        with mock.patch.object(sys, 'platform', 'darwin'), \
                mock.patch.object(Path, 'home', return_value=self.tmp):
            d = paths.user_data_dir()
        self.assertEqual(d, self.tmp / 'Library' / 'Application Support' / 'PyRogue')
        self.assertTrue(d.is_dir())

    def test_linux_honours_xdg_data_home(self):
        xdg = self.tmp / 'xdg'
        with mock.patch.object(sys, 'platform', 'linux'):
            os.environ['XDG_DATA_HOME'] = str(xdg)
            d = paths.user_data_dir()
        self.assertEqual(d, xdg / 'pyrogue')
        self.assertTrue(d.is_dir(), 'parents must be created too')

    def test_linux_default_is_local_share(self):
        with mock.patch.object(sys, 'platform', 'linux'), \
                mock.patch.object(Path, 'home', return_value=self.tmp):
            d = paths.user_data_dir()
        self.assertEqual(d, self.tmp / '.local' / 'share' / 'pyrogue')
        self.assertTrue(d.is_dir())

    def test_relative_xdg_data_home_is_ignored(self):
        with mock.patch.object(sys, 'platform', 'linux'), \
                mock.patch.object(Path, 'home', return_value=self.tmp):
            os.environ['XDG_DATA_HOME'] = 'relative/dir'
            d = paths.user_data_dir()
        self.assertEqual(d, self.tmp / '.local' / 'share' / 'pyrogue')

    def test_explicit_override_wins_on_every_platform(self):
        override = self.tmp / 'portable'
        os.environ['PYROGUE_DATA_DIR'] = str(override)
        os.environ['APPDATA'] = str(self.tmp / 'appdata')
        os.environ['XDG_DATA_HOME'] = str(self.tmp / 'xdg')
        for platform in ('win32', 'darwin', 'linux'):
            with mock.patch.object(sys, 'platform', platform):
                self.assertEqual(paths.user_data_dir(), override)

    def test_save_and_log_live_in_the_data_dir(self):
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp)
        self.assertEqual(paths.save_path(), self.tmp / 'savegame.json')
        self.assertEqual(paths.log_path(), self.tmp / 'crash.log')

    def test_resolved_at_call_time_not_import_time(self):
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp / 'a')
        first = paths.save_path()
        os.environ['PYROGUE_DATA_DIR'] = str(self.tmp / 'b')
        self.assertNotEqual(first, paths.save_path())


class MigrationTest(_TempDirTest):
    def test_copies_legacy_save_when_target_missing(self):
        legacy = self.tmp / 'old' / 'savegame.json'
        legacy.parent.mkdir()
        legacy.write_text('{"legacy": true}')
        target = self.tmp / 'data' / 'savegame.json'
        self.assertTrue(paths.migrate_legacy_save(target, legacy))
        self.assertEqual(target.read_text(), '{"legacy": true}')
        self.assertTrue(legacy.exists(), 'the original is never deleted')

    def test_never_overwrites_an_existing_save(self):
        legacy = self.tmp / 'legacy.json'
        legacy.write_text('old')
        target = self.tmp / 'savegame.json'
        target.write_text('new')
        self.assertFalse(paths.migrate_legacy_save(target, legacy))
        self.assertEqual(target.read_text(), 'new')

    def test_nothing_to_migrate(self):
        target = self.tmp / 'savegame.json'
        self.assertFalse(paths.migrate_legacy_save(target, self.tmp / 'missing.json'))
        self.assertFalse(target.exists())


class SaveLocationTest(_TempDirTest):
    """GameState's 'save'/'load' actions go through paths.save_path()."""

    def setUp(self):
        super().setUp()
        self.data = self.tmp / 'data'
        os.environ['PYROGUE_DATA_DIR'] = str(self.data)
        self.work = self.tmp / 'cwd'
        self.work.mkdir()
        old_cwd = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, old_cwd)
        random.seed(7)
        self.state = GameState(40, 20)

    def test_save_goes_to_user_data_dir_not_cwd(self):
        self.state.handle_action('save')
        self.assertTrue((self.data / 'savegame.json').is_file())
        self.assertFalse((self.work / 'savegame.json').exists())
        self.assertEqual(self.state.messages[-1], 'Game saved.')

    def test_round_trip(self):
        self.state.handle_action('save')
        hp = self.state.player.hp
        self.state.player.hp = 1
        self.state.handle_action('load')
        self.assertEqual(self.state.player.hp, hp)
        self.assertEqual(self.state.messages[-1], 'Game loaded.')

    def test_legacy_cwd_save_is_migrated_on_load(self):
        self.state.player.hp = 3
        from game.save import save_game
        save_game(self.state, self.work / 'savegame.json')  # a pre-WS-B save
        self.state.player.hp = 20
        self.state.handle_action('load')
        self.assertEqual(self.state.player.hp, 3)
        self.assertTrue((self.data / 'savegame.json').is_file())

    def test_explicit_save_path_seam(self):
        explicit = self.tmp / 'elsewhere.json'
        with mock.patch.object(state_module, 'SAVE_PATH', str(explicit)):
            self.state.handle_action('save')
        self.assertTrue(explicit.is_file())
        self.assertFalse((self.data / 'savegame.json').exists())

    @unittest.skipIf(sys.platform.startswith('win'),
                     'Windows ignores POSIX directory permission bits')
    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'root ignores directory permissions')
    def test_save_load_with_read_only_cwd(self):
        os.chmod(self.work, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.work, stat.S_IRWXU)
        with self.assertRaises(OSError):
            (self.work / 'probe').write_text('x')  # really is read-only
        self.state.handle_action('save')
        self.assertEqual(self.state.messages[-1], 'Game saved.')
        self.state.player.hp = 1
        self.state.handle_action('load')
        self.assertEqual(self.state.messages[-1], 'Game loaded.')
        self.assertGreater(self.state.player.hp, 1)

    def test_unwritable_save_location_logs_instead_of_crashing(self):
        blocker = self.tmp / 'file-not-dir'
        blocker.write_text('')
        with mock.patch.object(state_module, 'SAVE_PATH', str(blocker / 'savegame.json')):
            self.state.handle_action('save')
        self.assertTrue(self.state.messages[-1].startswith('Save failed'))

    def test_corrupt_save_logs_instead_of_crashing(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / 'savegame.json').write_text('{not json')
        self.state.handle_action('load')
        self.assertTrue(self.state.messages[-1].startswith('Load failed'))


class ContractTest(unittest.TestCase):
    """Signatures other streams code against exist."""

    def test_platform_functions_exist(self):
        for fn in (paths.user_data_dir, paths.save_path, paths.log_path,
                   settings.find_config, settings.load,
                   crashlog.install, crashlog.write):
            self.assertTrue(callable(fn), fn)

    def test_version_is_semver(self):
        self.assertRegex(__version__, re.compile(r'^\d+\.\d+\.\d+$'))


if __name__ == '__main__':
    unittest.main()
