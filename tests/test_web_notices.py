"""packaging/web/THIRD_PARTY_NOTICES.txt covers what the browser zip redistributes.

The browser zip carries pygbag's prebuilt runtime (rt/), which statically contains
other people's code, so it ships its own notices and licence texts. These tests keep
the notices and packaging/web/licenses/ in step, and keep the build scripts and
packaging/web/make_runtime.py wired to put them in the zip. Standard library only.
"""

import importlib.util
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'packaging' / 'web'
NOTICES = WEB / 'THIRD_PARTY_NOTICES.txt'
LICENSES = WEB / 'licenses'


def load_make_runtime():
    spec = importlib.util.spec_from_file_location('make_runtime', WEB / 'make_runtime.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def listed_files(text):
    return set(re.findall(r'[\w.+-]+\.txt', text)) - {'THIRD_PARTY_NOTICES.txt'}


class NoticesTableTest(unittest.TestCase):
    def setUp(self):
        self.text = NOTICES.read_text(encoding='utf-8')
        self.files = {p.name for p in LICENSES.glob('*')}

    def test_every_licence_file_in_the_notices_exists(self):
        self.assertTrue(self.files)
        self.assertEqual(listed_files(self.text) - self.files, set(), 'named but missing')

    def test_every_licence_file_is_referenced_by_the_notices(self):
        self.assertEqual(self.files - listed_files(self.text), set(), 'shipped but unreferenced')

    def test_licence_files_are_text_and_not_empty(self):
        for name in self.files:
            self.assertTrue(name.endswith('.txt'), name)
            body = (LICENSES / name).read_text(encoding='utf-8', errors='replace')
            self.assertGreater(len(body.strip()), 100, name)

    def test_says_it_is_not_an_audit(self):
        self.assertIn('NOT an audit', self.text)
        self.assertIn('may be present', self.text)

    def test_explains_how_to_replace_the_lgpl_parts(self):
        self.assertIn('Replacing the LGPL parts', self.text)
        self.assertIn('rt/cp312/', self.text)
        self.assertIn('https://github.com/pygame-community/pygame-ce/tree/2.5.7', self.text)

    def test_names_the_runtime_the_build_pins(self):
        pinned = load_make_runtime()
        self.assertIn(f'rt/{pinned.ABI}/{pinned.WHEEL}', self.text)
        self.assertIn(f'pygbag {pinned.PYGBAG}', self.text)
        wheel_version = pinned.WHEEL.split('-')[1]
        self.assertIn(f'pygame-ce {wheel_version}', self.text)
        self.assertIn(f'tree/{wheel_version}', self.text)


class ZipWiringTest(unittest.TestCase):
    def test_notice_files_cover_licence_notices_and_every_text(self):
        files = load_make_runtime().notice_files()
        self.assertIn('LICENSE', files)
        self.assertIn('THIRD_PARTY_NOTICES.txt', files)
        for p in LICENSES.glob('*.txt'):
            self.assertIn(f'licenses/{p.name}', files)

    def test_file_count_stays_modest(self):
        # itch.io allows 1000 files per project; the runtime itself is about a dozen
        self.assertLess(len(load_make_runtime().notice_files()), 60)

    def test_verify_rejects_a_zip_without_notices(self):
        module = load_make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / 'bare.zip'
            with zipfile.ZipFile(bare, 'w') as zf:
                zf.writestr('index.html', '<html></html>')
            with self.assertRaises(SystemExit):
                module.check_zip(bare)

    def test_both_build_scripts_verify_the_finished_zip(self):
        for script in ('build_web.sh', 'build_web.ps1'):
            text = (ROOT / 'packaging' / script).read_text(encoding='utf-8')
            self.assertIn('make_runtime.py', text, script)
            self.assertIn('--verify', text, script)


if __name__ == '__main__':
    unittest.main()
