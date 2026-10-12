"""Stdlib KEY=VALUE config reader that replaces python-dotenv. Owned by WS-B.

Same semantics main.py relies on today: a real environment variable wins over
the file, and env_int() falls back to the default on a missing or unparseable
value instead of crashing. Search order (desktop_build_plan.md §5 WS-B task 3):
$PYROGUE_CONFIG -> a .env next to the exe / main.py -> .env in the CWD.

P0 stub: env_int() is real (it's main.py's current logic, moved); load() and
find_config() are WS-B's. main.py keeps using python-dotenv until load() lands
-- the switch-over in main.py goes through WS-A, its owner.
"""

import os


def find_config():
    """Path of the first config file in the search order, or None."""
    raise NotImplementedError('WS-B: game/settings.py find_config')


def load(path=None):
    """Read KEY=VALUE lines from `path` (default: find_config()) into
    os.environ, never overriding a variable that is already set. Blank lines
    and `#` comments are ignored. Missing file is not an error."""
    raise NotImplementedError('WS-B: game/settings.py load')


def env_int(name, default):
    """os.environ[name] as an int, or `default` if unset or not an integer."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default
