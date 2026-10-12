"""Crash logging for the windowed build. Owned by WS-B.

Mandatory, not polish: a `--windowed` PyInstaller build discards stderr, so
without this an uncaught exception is a window that silently vanishes
(desktop_build_plan.md §5 WS-B task 4, §7 risk register).

P0 stub: final signatures only.
"""


def install(path=None):
    """Install a sys.excepthook that appends a timestamped traceback to `path`
    (default: game.paths.log_path()) before the default hook runs."""
    raise NotImplementedError('WS-B: game/crashlog.py install')


def write(exc_type, exc_value, exc_tb, path=None):
    """Append one timestamped traceback to the log; returns the log's Path.
    Must never raise -- it runs while the program is already failing."""
    raise NotImplementedError('WS-B: game/crashlog.py write')
