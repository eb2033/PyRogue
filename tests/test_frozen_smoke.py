"""Smoke test for the frozen (PyInstaller) build, plus packaging sanity checks.

FrozenSmokeTest is skipped unless a build exists at dist/PyRogue/ (run
./packaging/build.sh or packaging/build.ps1 first), so a plain checkout's suite
never fails just because nothing was built. When a build is present it
launches the binary the way a machine with no Python would -- PYTHONHOME /
PYTHONPATH unset, the venv off PATH, an empty working directory -- under SDL's
dummy drivers, and asserts it is still alive after a few seconds: the title
screen blocks waiting for a key, so "still running" means it got through
interpreter start-up, every import, and window creation without a traceback.
On Windows it also asserts the process owns no visible window, because a
windowed build's crash is a modal dialog that keeps the process alive.

PackagingTest always runs: it guards the rules in packaging/NOTES.md that are
cheap to check statically (never onefile, never UPX, version resource text
generated from game/version.py).

Owned by WS-G (task 4); written by WS-E alongside the spec.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / 'dist' / 'PyRogue'
EXE = BUNDLE / ('PyRogue.exe' if sys.platform == 'win32' else 'PyRogue')
# How long the binary must survive. Generous: a first launch on a Windows CI
# runner is slowed by Defender scanning every DLL in the bundle.
ALIVE_SECONDS = float(os.environ.get('PYROGUE_SMOKE_SECONDS', '5'))


def visible_windows_of(pid):
    """Titles of visible top-level windows owned by `pid` (Windows only).

    Under SDL's dummy video driver the game creates no window at all, so any
    visible window is the PyInstaller bootloader's "Unhandled exception"
    dialog -- which would otherwise keep a crashed process alive and make
    "still running" look like success.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    titles = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            titles.append(buffer.value or '<untitled>')
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return titles


def clean_env(scratch):
    """os.environ minus anything that could let the frozen app find this
    checkout's Python, with per-user dirs pointed into `scratch` so a save or
    crash.log can't land in the real profile."""
    env = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'VIRTUAL_ENV',
                 'PYTHONSAFEPATH', 'PYTHONNOUSERSITE'):
        env.pop(name, None)
    venv_markers = (str(ROOT / '.venv'), os.environ.get('VIRTUAL_ENV') or '\0')
    env['PATH'] = os.pathsep.join(
        p for p in env.get('PATH', '').split(os.pathsep)
        if p and not p.startswith(venv_markers))
    env.update({
        'RENDERER': 'pygame',          # until WS-A makes it the frozen default
        'SDL_VIDEODRIVER': 'dummy',
        'SDL_AUDIODRIVER': 'dummy',
        'APPDATA': str(scratch),       # Windows user_data_dir
        'XDG_DATA_HOME': str(scratch), # Linux user_data_dir
    })
    return env


@unittest.skipUnless(EXE.is_file(), f'no frozen build at {BUNDLE} (run packaging/build.sh)')
class FrozenSmokeTest(unittest.TestCase):
    def test_launches_and_reaches_the_title_screen(self):
        with tempfile.TemporaryDirectory() as scratch:
            proc = subprocess.Popen(
                [str(EXE)], cwd=scratch, env=clean_env(scratch),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + ALIVE_SECONDS
                while time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(0.1)
                exit_code = proc.poll()
                dialogs = []
                if exit_code is None and sys.platform == 'win32':
                    dialogs = visible_windows_of(proc.pid)
            finally:
                if proc.poll() is None:
                    proc.kill()
                output, _ = proc.communicate(timeout=10)
            self.assertIsNone(
                exit_code,
                f'frozen build exited early with {exit_code}:\n'
                + output.decode(errors='replace'))
            self.assertEqual(dialogs, [],
                             'frozen build is alive but showing a dialog (a crash)')
            crash_logs = list(Path(scratch).rglob('crash.log'))
            self.assertEqual(crash_logs, [], 'frozen build wrote a crash.log')


class PackagingTest(unittest.TestCase):
    SPEC = ROOT / 'packaging' / 'pyrogue.spec'

    def test_spec_is_onedir_and_never_upx(self):
        spec = self.SPEC.read_text(encoding='utf-8')
        code = '\n'.join(line.split('#')[0] for line in spec.splitlines())
        self.assertIn('COLLECT(', code, 'spec must build --onedir (a COLLECT step)')
        self.assertIn('exclude_binaries=True', code)
        self.assertNotIn('upx=True', code.replace(' ', ''))
        self.assertIn('upx=False', code.replace(' ', ''))
        self.assertIn('console=False', code.replace(' ', ''))

    def test_version_resource_matches_game_version(self):
        sys.path.insert(0, str(ROOT / 'packaging'))
        try:
            import version_info
        finally:
            sys.path.remove(str(ROOT / 'packaging'))
        from game.version import __version__

        self.assertEqual(version_info.read_version(ROOT / 'game' / 'version.py'), __version__)
        text = version_info.render(__version__)
        self.assertIn(f"StringStruct('ProductVersion', {__version__!r})", text)
        self.assertEqual(version_info.version_tuple('1.2.3'), (1, 2, 3, 0))
        self.assertEqual(version_info.version_tuple('0.1.0rc1'), (0, 1, 0, 0))
        with self.assertRaises(ValueError):
            version_info.version_tuple('v1.0')



# Which notices entry covers a bundled native library: a substring of the
# library's lowercased file name -> the component named in the notices.
# Checked longest key first, so 'sdl2_image' wins over 'sdl2'.
LIBRARY_COMPONENTS = {
    'sdl2_image': 'SDL2_image', 'sdl2_mixer': 'SDL2_mixer', 'sdl2_ttf': 'SDL2_ttf',
    'sdl2': 'SDL2', 'freetype': 'FreeType', 'harfbuzz': 'HarfBuzz', 'png': 'libpng',
    'jpeg': 'libjpeg-turbo', 'tiff': 'libtiff', 'webp': 'libwebp', 'sharpyuv': 'libwebp',
    'opusfile': 'opusfile', 'opus': 'Opus', 'ogg': 'libogg', 'vorbis': 'libvorbis',
    'flac': 'FLAC', 'mpg123': 'mpg123', 'fluidsynth': 'FluidSynth', 'sndfile': 'libsndfile',
    'wavpack': 'WavPack', 'xmp': 'libxmp', 'portmidi': 'PortMidi', 'brotli': 'Brotli',
    'asound': 'alsa-lib', 'zlib': 'zlib',
}


class NoticesTest(unittest.TestCase):
    """packaging/THIRD_PARTY_NOTICES.txt covers what the build ships."""

    NOTICES = ROOT / 'packaging' / 'THIRD_PARTY_NOTICES.txt'
    LICENSES = ROOT / 'packaging' / 'licenses'

    def test_every_licence_file_is_listed_and_every_listed_file_exists(self):
        notices = self.NOTICES.read_text(encoding='utf-8')
        files = {p.name for p in self.LICENSES.glob('*.txt')}
        self.assertTrue(files)
        for name in files:
            self.assertIn(name, notices)
        import re
        listed = set(re.findall(r'\b([\w.-]+\.txt)\b', notices))
        listed -= {'THIRD_PARTY_NOTICES.txt', 'License.txt', 'OFL.txt', 'Python-LICENSE.txt'}
        self.assertEqual(listed - files, set(), 'named in the notices but missing')

    def test_every_library_pygame_bundles_here_is_in_the_notices(self):
        try:
            import pygame
        except ImportError:
            self.skipTest('pygame-ce not installed')
        package = Path(pygame.__file__).parent
        libs = [p.name for p in package.glob('*.dll')]
        libs += [p.name for p in package.parent.glob('pygame_ce.libs/*')]
        libs += [p.name for p in package.glob('.dylibs/*')]
        if not libs:
            self.skipTest('this pygame-ce build bundles no native libraries')
        notices = self.NOTICES.read_text(encoding='utf-8')
        for lib in libs:
            key = next((k for k in sorted(LIBRARY_COMPONENTS, key=len, reverse=True)
                        if k in lib.lower()), None)
            self.assertIsNotNone(key, f'{lib}: unknown library, add it to the notices')
            self.assertIn(LIBRARY_COMPONENTS[key], notices, lib)

    def test_build_scripts_ship_the_notices(self):
        for script in ('build.sh', 'build.ps1'):
            text = (ROOT / 'packaging' / script).read_text(encoding='utf-8')
            self.assertIn('collect_licenses.py', text, script)

    @unittest.skipUnless(BUNDLE.is_dir(), 'no build at dist/PyRogue/')
    def test_a_built_bundle_carries_the_notices(self):
        self.assertTrue((BUNDLE / 'THIRD_PARTY_NOTICES.txt').is_file())
        for name in ('pygame-ce.txt', 'SDL2.txt', 'Python-LICENSE.txt'):
            self.assertTrue((BUNDLE / 'licenses' / name).is_file(), name)

if __name__ == '__main__':
    unittest.main()
