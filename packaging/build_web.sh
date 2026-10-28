#!/usr/bin/env bash
# Build PyRogue for the browser (itch.io HTML5) with pygbag and zip it.
#
#   ./packaging/build_web.sh
#
# Output (all under dist/, gitignored):
#   dist/PyRogue-web-<version>.zip   index.html at the zip root; upload it to itch.io
#
# Stages build/web/ (main.py from web/main.py, plus game/, render/, web/ and the
# assets the game loads at run time), runs `pygbag --build` with our own page
# template (packaging/web/index.tmpl), then packaging/web/make_runtime.py adds a
# slimmed copy of the pygbag runtime to the zip (rt/) so the player downloads
# 8 MB from one host instead of 11 MB from pygame-web.github.io, adds LICENSE,
# THIRD_PARTY_NOTICES.txt and licenses/ (from packaging/web/) at the zip root, and
# checks the zip (the script fails if any of those is missing). Needs network
# access once: pygbag fetches its favicon and make_runtime.py
# downloads the pinned runtime (cached in build/web-runtime-cache/).
#
# Uses $PYTHON if set, else .venv/bin/python, else python3. The interpreter needs
# requirements-dev.txt installed (pygbag). Owned by WS-C; see packaging/NOTES.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON:-}" ]]; then
    PY="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
    PY=.venv/bin/python
else
    PY=python3
fi

VERSION="$("$PY" packaging/version_info.py --print-version)"
ZIP_NAME="PyRogue-web-${VERSION}.zip"
STAGE=build/web

echo "==> PyRogue ${VERSION} for the browser (python: ${PY})"

if [[ ! -f web/main.py ]]; then
    echo "error: web/main.py is missing; the browser entry point has not landed" >&2
    exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE" dist

cp web/main.py "$STAGE/main.py"
# Packages that main.py imports. web/main.py itself is already copied to the top.
for pkg in game render web; do
    mkdir -p "$STAGE/$pkg"
    cp -r "$pkg/." "$STAGE/$pkg/"
done
rm -f "$STAGE/web/main.py"

# Only what the game loads at run time (see render/tileset.py, render/ui.py,
# render/pygame_render.py). icon.png/icon.ico are the desktop window icon and
# assets/ASSETS.md is the provenance table; neither is read in the browser.
mkdir -p "$STAGE/assets"
cp assets/tiles.json "$STAGE/assets/"
cp -r assets/kenney assets/blood assets/fonts "$STAGE/assets/"

# Keep the staged tree clean of bytecode caches.
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete

"$PY" -m pygbag --build --ume_block 0 --template packaging/web/index.tmpl --title PyRogue "$STAGE"

BUILT="$STAGE/build/web"
"$PY" packaging/web/make_runtime.py "$BUILT" "dist/$ZIP_NAME" --cache build/web-runtime-cache
# The zip redistributes third-party binaries (rt/): fail unless it carries their notices.
"$PY" packaging/web/make_runtime.py --verify "dist/$ZIP_NAME"
echo "==> dist/$ZIP_NAME ($(du -h "dist/$ZIP_NAME" | cut -f1))"
