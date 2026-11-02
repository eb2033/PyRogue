"""Crash logging for the windowed build. Owned by WS-B.

Mandatory, not polish: a `--windowed` PyInstaller build discards stderr, so
without this an uncaught exception is a window that silently vanishes
(desktop_build_plan.md §5 WS-B task 4, §7 risk register).

Standard library only -- no dialog here. main.py calls write() itself from
its __main__ block (an excepthook may never run in a windowed build).
"""

import datetime
import logging
import sys
import traceback
from pathlib import Path

from game import paths


def _resolve(path):
    return Path(path) if path is not None else paths.log_path()


def format_entry(exc_type, exc_value, exc_tb):
    """One log entry: a timestamp header, version/platform, the traceback."""
    try:
        from game.version import __version__ as version
    except Exception:  # noqa: BLE001 -- the log must still get written
        version = '?'
    stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    body = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return (
        f'===== {stamp} =====\n'
        f'PyRogue {version} | Python {sys.version.split()[0]} | {sys.platform}'
        f' | frozen={paths.is_frozen()}\n'
        f'{body}\n'
    )


def write(exc_type, exc_value, exc_tb, path=None):
    """Append one timestamped traceback to the log; returns the log's Path,
    or None if nothing could be written. Never raises -- it runs while the
    program is already failing."""
    try:
        target = _resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = format_entry(exc_type, exc_value, exc_tb)
        with open(target, 'a', encoding='utf-8', errors='replace') as f:
            f.write(entry)
        return target
    except BaseException:  # noqa: BLE001 -- see docstring
        return None


WARNINGS_FILENAME = 'warnings.log'
_WARNING_LOGGERS = ('render',)  # e.g. render.tileset's "tileset unavailable"


def route_warnings(path=None):
    """Send WARNING-and-above log records from the render package to a file
    (default: warnings.log in the user data dir, next to crash.log). Without
    this they reach logging's last-resort stderr handler, which a windowed
    build doesn't have. Idempotent; never raises. Returns the log's Path, or
    None if it could not be set up."""
    try:
        target = Path(path) if path is not None else paths.user_data_dir() / WARNINGS_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        for name in _WARNING_LOGGERS:
            logger = logging.getLogger(name)
            if any(getattr(h, '_pyrogue_warnings', False) for h in logger.handlers):
                continue
            handler = logging.FileHandler(target, encoding='utf-8', delay=True)
            handler.setFormatter(
                logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')
            )
            handler._pyrogue_warnings = True  # type: ignore[attr-defined]
            logger.addHandler(handler)
            logger.setLevel(logging.WARNING)
        return target
    except Exception:  # noqa: BLE001 -- logging must never stop the game
        return None
