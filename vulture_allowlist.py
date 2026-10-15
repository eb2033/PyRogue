"""Names vulture reports as unused that are used -- just not by our code.

Run `vulture` from the repo root (paths and confidence are in
pyproject.toml). When it flags a false positive, add it here with the reason;
when it flags real dead code, delete the code instead.
"""

# Read by zipfile when it writes the archive: marks a symlink entry
# (packaging/make_zip.py).
_.external_attr  # noqa: B018, F821  # type: ignore

# collections.namedtuple's generated class sets __defaults__ for Hit's optional
# `crit` field (game/combat.py); nothing in our code names it.
_.__defaults__  # noqa: B018, F821  # type: ignore
