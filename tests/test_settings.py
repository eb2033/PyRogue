"""game/settings.py (WS-B): the stdlib replacement for python-dotenv."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from game import paths, settings

_REAL_APP_DIR = paths.app_dir

KEYS = (
    'PYROGUE_T_A',
    'PYROGUE_T_B',
    'PYROGUE_T_C',
    'PYROGUE_T_D',
    'PYROGUE_T_E',
    'PYROGUE_T_F',
    'PYROGUE_T_G',
    'PYROGUE_T_INT',
)


class _EnvTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in KEYS + (settings.CONFIG_ENV,):
            os.environ.pop(key, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write(self, name, text):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p


class EnvIntTest(_EnvTest):
    def test_parses_and_falls_back_to_the_default(self):
        os.environ['PYROGUE_T_INT'] = '42'
        self.assertEqual(settings.env_int('PYROGUE_T_INT', 7), 42)
        del os.environ['PYROGUE_T_INT']
        self.assertEqual(settings.env_int('PYROGUE_T_INT', 7), 7)  # missing
        os.environ['PYROGUE_T_INT'] = 'forty'
        self.assertEqual(settings.env_int('PYROGUE_T_INT', 7), 7)  # garbage

    def test_out_of_range_uses_default_and_bounds_are_inclusive(self):
        for text in ('0', '-4', '9'):
            os.environ['PYROGUE_T_INT'] = text
            self.assertEqual(settings.env_int('PYROGUE_T_INT', 7, 10, 20), 7, text)
        os.environ['PYROGUE_T_INT'] = '21'
        self.assertEqual(settings.env_int('PYROGUE_T_INT', 7, maximum=20), 7)
        for text in ('10', '20'):
            os.environ['PYROGUE_T_INT'] = text
            self.assertEqual(settings.env_int('PYROGUE_T_INT', 15, 10, 20), int(text))


class LoadTest(_EnvTest):
    def test_parses_values_comments_and_quotes(self):
        path = self.write(
            '.env',
            '\n'.join(
                [
                    '# a comment',
                    '',
                    '   ',
                    'PYROGUE_T_A=1',
                    '  PYROGUE_T_B  =  two words  ',
                    'PYROGUE_T_C="quoted # not a comment"',
                    "PYROGUE_T_D='single'",
                    'PYROGUE_T_E=40 # trailing comment',
                    'export PYROGUE_T_F=exported',
                    'PYROGUE_T_G=',
                ]
            ),
        )
        settings.load(path)
        self.assertEqual(os.environ['PYROGUE_T_A'], '1')
        self.assertEqual(os.environ['PYROGUE_T_B'], 'two words')
        self.assertEqual(os.environ['PYROGUE_T_C'], 'quoted # not a comment')
        self.assertEqual(os.environ['PYROGUE_T_D'], 'single')
        self.assertEqual(os.environ['PYROGUE_T_E'], '40')
        self.assertEqual(os.environ['PYROGUE_T_F'], 'exported')
        self.assertEqual(os.environ['PYROGUE_T_G'], '')

    def test_real_env_var_wins_over_file(self):
        os.environ['PYROGUE_T_A'] = 'from-env'
        path = self.write('.env', 'PYROGUE_T_A=from-file\nPYROGUE_T_B=from-file\n')
        applied = settings.load(path)
        self.assertEqual(os.environ['PYROGUE_T_A'], 'from-env')
        self.assertEqual(os.environ['PYROGUE_T_B'], 'from-file')
        self.assertEqual(applied, {'PYROGUE_T_B': 'from-file'})

    def test_garbage_lines_are_skipped(self):
        path = self.write(
            '.env',
            '\n'.join(
                [
                    'this line has no equals sign',
                    '=value-without-key',
                    'BAD KEY=spaces in key',
                    '"',
                    'PYROGUE_T_A=ok',
                    '\x00\x01 binary-ish junk',
                ]
            ),
        )
        settings.load(path)
        self.assertEqual(os.environ['PYROGUE_T_A'], 'ok')
        self.assertNotIn('BAD KEY', os.environ)

    def test_missing_undecodable_or_absent_config_is_not_an_error(self):
        self.assertEqual(settings.load(self.tmp / 'nope.env'), {})
        p = self.tmp / '.env'
        p.write_bytes(b'\xff\xfe\xfa\x80 not utf-8')
        self.assertEqual(settings.load(p), {})
        with mock.patch.object(settings, 'find_config', return_value=None):
            self.assertEqual(settings.load(), {})

    def test_bom_and_crlf_are_tolerated(self):
        p = self.tmp / '.env'
        p.write_bytes('﻿PYROGUE_T_A=1\r\nPYROGUE_T_B=2\r\n'.encode())
        settings.load(p)
        self.assertEqual(os.environ['PYROGUE_T_A'], '1')
        self.assertEqual(os.environ['PYROGUE_T_B'], '2')

    def test_garbage_value_then_env_int_falls_back(self):
        settings.load(self.write('.env', 'PYROGUE_T_INT=lots\n'))
        self.assertEqual(settings.env_int('PYROGUE_T_INT', 50), 50)


class FindConfigTest(_EnvTest):
    def setUp(self):
        super().setUp()
        self.app = self.tmp / 'app'
        self.app.mkdir()
        self.cwd = self.tmp / 'cwd'
        self.cwd.mkdir()
        old = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, old)
        patcher = mock.patch.object(paths, 'app_dir', return_value=self.app)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_search_order(self):
        self.assertIsNone(settings.find_config())
        # the working directory is the last resort
        cwd_env = self.write('cwd/.env', 'X=1')
        self.assertEqual(settings.find_config().resolve(), cwd_env.resolve())
        # the app dir beats it
        app_env = self.write('app/.env', 'X=2')
        self.assertEqual(settings.find_config(), app_env)
        # a PYROGUE_CONFIG that points nowhere falls through
        os.environ[settings.CONFIG_ENV] = str(self.tmp / 'missing.cfg')
        self.assertEqual(settings.find_config(), app_env)
        # a real one beats everything
        custom = self.write('custom/game.cfg', 'X=3')
        os.environ[settings.CONFIG_ENV] = str(custom)
        self.assertEqual(settings.find_config(), custom)

    def test_load_uses_search_order(self):
        self.write('cwd/.env', 'PYROGUE_T_A=cwd\n')
        self.write('app/.env', 'PYROGUE_T_A=app\n')
        settings.load()
        self.assertEqual(os.environ['PYROGUE_T_A'], 'app')

    def test_frozen_looks_next_to_the_exe(self):
        exe_dir = self.tmp / 'dist'
        exe_dir.mkdir()
        p = self.write('dist/.env', 'X=1')
        # Undo setUp's app_dir() stub so the real frozen branch runs.
        with (
            mock.patch.object(paths, 'app_dir', _REAL_APP_DIR),
            mock.patch.object(paths.sys, 'frozen', True, create=True),
            mock.patch.object(paths.sys, 'executable', str(exe_dir / 'PyRogue.exe')),
        ):
            self.assertEqual(settings.find_config(), exe_dir.resolve() / '.env')
        self.assertTrue(p.is_file())


if __name__ == '__main__':
    unittest.main()
