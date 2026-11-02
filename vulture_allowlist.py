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

# Test API. vulture scans production paths only (pyproject.toml), so code that
# only the tests call looks dead. These are kept on purpose; anything else
# vulture reports is real dead code and should be deleted.
#
# game/: GameState seams the tests drive directly, and tables they check.
_._monster_melee  # noqa: B018, F821  # type: ignore
_._monster_shot  # noqa: B018, F821  # type: ignore
_._summon_goblins  # noqa: B018, F821  # type: ignore
_._spawn_level_monsters  # noqa: B018, F821  # type: ignore
_.events_of  # noqa: B018, F821  # type: ignore
_.GEAR_KINDS  # noqa: B018, F821  # type: ignore
_.GEAR_DROP_KINDS  # noqa: B018, F821  # type: ignore
_.SLOTS  # noqa: B018, F821  # type: ignore
_.slime_kind_for_depth  # noqa: B018, F821  # type: ignore
# render/: geometry and counters that tests read.
_.rebuilds  # noqa: B018, F821  # type: ignore
_.HEALTH_BAR_COLORS  # noqa: B018, F821  # type: ignore
_.SLIME_COLORS  # noqa: B018, F821  # type: ignore
_.shop_rect  # noqa: B018, F821  # type: ignore
_.shop_row_rects  # noqa: B018, F821  # type: ignore
_.shop_line_rects  # noqa: B018, F821  # type: ignore
_.cell_rect  # noqa: B018, F821  # type: ignore
_.paint_panel  # noqa: B018, F821  # type: ignore
_.paint_log  # noqa: B018, F821  # type: ignore
_.boon_rows  # noqa: B018, F821  # type: ignore
