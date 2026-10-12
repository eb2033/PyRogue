"""Stdlib KEY=VALUE config reader that replaces python-dotenv. Owned by WS-B.

Same semantics main.py relied on with python-dotenv: a real environment
variable wins over the file, and env_int() falls back to the default on a
missing or unparseable value instead of crashing. Search order
(desktop_build_plan.md §5 WS-B task 3): $PYROGUE_CONFIG -> a .env next to the
exe (frozen) / main.py (source) -> .env in the CWD -> code defaults.

Accepted syntax, deliberately small: `KEY=VALUE` per line; blank lines and
lines starting with `#` are ignored; an optional leading `export ` is
dropped; whitespace around key and value is stripped; a value wrapped in
matching single or double quotes is unwrapped; an unquoted value loses a
trailing ` # comment`. Lines that don't parse are skipped, never fatal.
"""

import os
from pathlib import Path

from game import paths

CONFIG_ENV = 'PYROGUE_CONFIG'
CONFIG_FILENAME = '.env'


def find_config():
    """Path of the first existing config file in the search order, or None."""
    candidates = []
    explicit = os.environ.get(CONFIG_ENV)
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(paths.app_dir() / CONFIG_FILENAME)
    candidates.append(Path.cwd() / CONFIG_FILENAME)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def parse_line(line):
    """(key, value) for one config line, or None if it holds no setting."""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if line.startswith('export '):
        line = line[len('export '):].lstrip()
    key, sep, value = line.partition('=')
    key = key.strip()
    if not sep or not key or any(c.isspace() for c in key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    else:
        hash_at = value.find(' #')
        if hash_at != -1:
            value = value[:hash_at].rstrip()
    return key, value


def parse(text):
    """Dict of every setting in `text`; later duplicates win, as in dotenv."""
    result = {}
    for line in text.splitlines():
        parsed = parse_line(line)
        if parsed is not None:
            result[parsed[0]] = parsed[1]
    return result


def load(path=None):
    """Read KEY=VALUE lines from `path` (default: find_config()) into
    os.environ, never overriding a variable that is already set. Blank lines
    and `#` comments are ignored. A missing or unreadable file is not an
    error. Returns the dict of values actually applied."""
    if path is None:
        path = find_config()
        if path is None:
            return {}
    try:
        # utf-8-sig: Notepad on Windows likes to prepend a BOM.
        text = Path(path).read_text(encoding='utf-8-sig')
    except (OSError, UnicodeDecodeError):
        return {}
    applied = {}
    for key, value in parse(text).items():
        if key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def env_int(name, default):
    """os.environ[name] as an int, or `default` if unset or not an integer."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default
