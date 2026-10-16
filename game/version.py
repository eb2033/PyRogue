"""The one place the version string lives. Owned by WS-F.

Read by the PyInstaller spec (WS-E) and the title screen; release.yml fails a
tag build whose `v*` tag doesn't match it (desktop_build_plan.md §5 WS-F).
"""

__version__ = '0.2.1'
