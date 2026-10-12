# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PyRogue -- the committed source of truth for the build.

Owned by WS-E (desktop_build_plan.md §5). Run it through packaging/build.sh or
packaging/build.ps1, not by hand; both clean build/ and dist/ first and zip
the result. See packaging/NOTES.md for the rules this file encodes.

    pyinstaller --noconfirm --clean packaging/pyrogue.spec

Non-negotiables (plan §2.5, antivirus):
  * onedir only -- there is deliberately no onefile EXE below. Never add one.
  * upx=False everywhere -- UPX-packed binaries are an AV trigger.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

# SPECPATH is injected by PyInstaller: the directory containing this file.
PACKAGING = Path(SPECPATH).resolve()
ROOT = PACKAGING.parent

sys.path.insert(0, str(PACKAGING))
import version_info  # noqa: E402  (packaging/version_info.py)

VERSION = version_info.read_version(ROOT / 'game' / 'version.py')
APP_NAME = 'PyRogue'

# --- data files --------------------------------------------------------------
# Everything under assets/ ships as <bundle>/assets/ and must be read through
# game.paths.resource_path('assets', ...) -- never a CWD-relative path. The
# directory doesn't exist until WS-C lands it, so it's optional here.
datas = []
# pygame-ce is LGPL-2.1: ship its package metadata (name, version, licence
# identifier) next to it. The wheel carries no licence *text*; a proper
# third-party notices file is a pre-public-release item (packaging/NOTES.md).
datas += copy_metadata('pygame-ce')
assets = ROOT / 'assets'
if assets.is_dir():
    datas.append((str(assets), 'assets'))

# --- icon ----------------------------------------------------------------------
# Windows wants an .ico; only used if WS-C has vendored one. Without it the exe
# gets PyInstaller's default icon, which is fine for a dry run.
icon = None
for candidate in (assets / 'icon.ico', PACKAGING / 'icon.ico'):
    if candidate.is_file():
        icon = str(candidate)
        break

# --- Windows file properties, generated from game/version.py ------------------
# Ignored (with a warning) on non-Windows builds.
version_file = None
if sys.platform == 'win32':
    version_file = str(version_info.write(VERSION, Path(workpath) / 'version_info.txt'))

# --- modules that must not ship ------------------------------------------------
excludes = [
    'tkinter', '_tkinter',
    'numpy',
    'unittest', 'test', 'pydoc', 'doctest',
    # The exe is the pygame build. The terminal renderer stays a from-source
    # thing; if it is ever shipped frozen, it needs its own spec (plan §5 WS-E).
    'curses', '_curses', '_curses_panel',
    'render.curses_render',
    # tcod_render is a scaffold slated for deletion; never bundle tcod.
    'tcod', 'render.tcod_render',
    # pygame's bundled test suite and examples are dead weight in a release.
    'pygame.tests', 'pygame.examples', 'pygame.docs',
]

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    # main.py imports renderers lazily inside make_renderer(); PyInstaller's
    # import scan sees function-level imports, but say it explicitly so the
    # one renderer this exe exists for can never be silently dropped.
    # game.paths / game.version: what resource_path() and the title screen
    # need, listed so the bundle has them before main.py imports them.
    hiddenimports=['render.pygame_render', 'game.paths', 'game.version'],
    hookspath=[str(PACKAGING / 'hooks')] if (PACKAGING / 'hooks').is_dir() else [],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir: binaries go in COLLECT, not the exe
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # windowed: no console on Windows
    # Windows: an unhandled exception that escapes main() shows the
    # bootloader's modal traceback dialog (True would only swap the traceback
    # for a "disabled" message -- still a dialog). Keep the traceback: it is
    # what a player can screenshot. Caveat for CI: the dialog keeps a crashed
    # process alive, so the frozen smoke test must not rely on "still running"
    # alone on Windows -- see packaging/NOTES.md.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
