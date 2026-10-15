"""Crash logging for the windowed build. Owned by WS-B.

Mandatory, not polish: a `--windowed` PyInstaller build discards stderr, so
without this an uncaught exception is a window that silently vanishes
(desktop_build_plan.md §5 WS-B task 4, §7 risk register).

Standard library only -- no dialog here. A renderer that can show one (the
pygame build) should wrap install()'s hook or call write() itself.
"""

import datetime
import sys
import traceback
from pathlib import Path

from game import paths

# The hook install() replaced, so a second install() doesn't chain to itself.
_previous_hook = None


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


def install(path=None):
    """Install a sys.excepthook that appends a timestamped traceback to `path`
    (default: game.paths.log_path(), resolved at crash time) before the
    previously installed hook runs. Idempotent. Returns the new hook."""
    global _previous_hook
    current = sys.excepthook
    if getattr(current, '_pyrogue_crashlog', False):
        previous = _previous_hook
    else:
        previous = current
        _previous_hook = current

    def hook(exc_type, exc_value, exc_tb):
        # Ctrl+C in the terminal build is not a crash worth logging.
        if not issubclass(exc_type, KeyboardInterrupt):
            write(exc_type, exc_value, exc_tb, path)
        if previous is not None:
            previous(exc_type, exc_value, exc_tb)

    hook._pyrogue_crashlog = True
    sys.excepthook = hook
    return hook
