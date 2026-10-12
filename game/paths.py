"""Where the game finds its files and where it writes yours. Owned by WS-B.

Standard library only. Every asset read must go through resource_path() and
every user-file write through user_data_dir() -- in a frozen build installed
under Program Files, the CWD is neither writable nor where the assets are
(desktop_build_plan.md §1, §5 WS-B).

P0 stub: final signatures. is_frozen() and the from-source branch of
resource_path() are real; the per-OS user-data logic is WS-B's to write.
"""

import sys
from pathlib import Path

APP_NAME = 'PyRogue'
# The repo root: game/paths.py -> game/ -> root.
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def is_frozen():
    """True inside a PyInstaller (sys.frozen) or Nuitka (__compiled__) build."""
    return bool(getattr(sys, 'frozen', False)) or '__compiled__' in globals()


def resource_path(*parts):
    """Path to a bundled read-only resource, e.g. resource_path('assets', 'tiles.json').

    Resolution order once WS-B is done: sys._MEIPASS (PyInstaller), the exe's
    directory (Nuitka / other freezers), then the repo root when running from
    source. The stub only handles the source case.
    """
    return SOURCE_ROOT.joinpath(*parts)


def user_data_dir():
    """Per-user writable directory, created if missing:
    %APPDATA%\\PyRogue | ~/Library/Application Support/PyRogue |
    $XDG_DATA_HOME/pyrogue | ~/.local/share/pyrogue."""
    raise NotImplementedError('WS-B: game/paths.py user_data_dir')


def save_path():
    """user_data_dir()/savegame.json."""
    return user_data_dir() / 'savegame.json'


def log_path():
    """user_data_dir()/crash.log."""
    return user_data_dir() / 'crash.log'
