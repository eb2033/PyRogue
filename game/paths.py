"""Where the game finds its files and where it writes yours. Owned by WS-B.

Standard library only. Every asset read must go through resource_path() and
every user-file write through user_data_dir() -- in a frozen build installed
under Program Files, the CWD is neither writable nor where the assets are
(desktop_build_plan.md §1, §5 WS-B).

Everything here is resolved at call time (sys.platform, sys.frozen, the
environment), never at import time, so tests can fake any of it.
"""

import os
import sys
from pathlib import Path

APP_NAME = 'PyRogue'
# Lowercase directory name used on XDG platforms (Linux/BSD convention).
XDG_APP_NAME = 'pyrogue'
# Escape hatch: an explicit data directory (portable installs, tests, CI).
DATA_DIR_ENV = 'PYROGUE_DATA_DIR'
LOG_FILENAME = 'crash.log'
# The repo root: game/paths.py -> game/ -> root.
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def is_frozen():
    """True inside a PyInstaller (sys.frozen) or Nuitka (__compiled__) build."""
    return bool(getattr(sys, 'frozen', False)) or '__compiled__' in globals()


def app_dir():
    """Directory holding the launcher: the exe's folder when frozen, else the
    repo root (where main.py lives). This is where a user would drop a .env."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return SOURCE_ROOT


def resource_path(*parts):
    """Path to a bundled read-only resource, e.g. resource_path('assets', 'tiles.json').

    Resolution order: sys._MEIPASS (PyInstaller's unpack/_internal dir), the
    exe's directory (Nuitka / other freezers), then the repo root when running
    from source. The path is returned whether or not it exists.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return Path(meipass).joinpath(*parts)
    return app_dir().joinpath(*parts)


def _base_data_dir():
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform.startswith('win'):
        appdata = os.environ.get('APPDATA')
        root = Path(appdata) if appdata else Path.home() / 'AppData' / 'Roaming'
        return root / APP_NAME
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP_NAME
    # XDG: a relative XDG_DATA_HOME is invalid per the spec and must be ignored.
    xdg = os.environ.get('XDG_DATA_HOME')
    if xdg and os.path.isabs(xdg):
        return Path(xdg) / XDG_APP_NAME
    return Path.home() / '.local' / 'share' / XDG_APP_NAME


def user_data_dir():
    """Per-user writable directory, created if missing:
    %APPDATA%\\PyRogue | ~/Library/Application Support/PyRogue |
    $XDG_DATA_HOME/pyrogue | ~/.local/share/pyrogue.

    $PYROGUE_DATA_DIR, if set, overrides all of these."""
    path = _base_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path():
    """user_data_dir()/crash.log."""
    return user_data_dir() / LOG_FILENAME
