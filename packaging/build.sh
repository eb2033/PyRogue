#!/usr/bin/env bash
# Build PyRogue for Linux (or macOS) with PyInstaller and zip it.
#
#   ./packaging/build.sh
#
# Output (all under dist/, gitignored):
#   dist/PyRogue/                         the onedir bundle; run dist/PyRogue/PyRogue
#   dist/PyRogue-<platform>-<version>.zip the bundle + LICENSE + README.txt
#
# Uses $PYTHON if set, else .venv/bin/python, else python3. The interpreter
# needs requirements.txt and requirements-dev.txt installed. Owned by WS-E;
# see packaging/NOTES.md.
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
case "$(uname -s)" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *)      PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
esac
ZIP_NAME="PyRogue-${PLATFORM}-${VERSION}.zip"

echo "==> PyRogue ${VERSION} for ${PLATFORM} (python: ${PY})"

rm -rf build dist
"$PY" -m PyInstaller --noconfirm --clean \
    --distpath dist --workpath build \
    packaging/pyrogue.spec

BUNDLE=dist/PyRogue
if [[ ! -x "$BUNDLE/PyRogue" ]]; then
    echo "error: $BUNDLE/PyRogue was not produced" >&2
    exit 1
fi

cp LICENSE packaging/README.txt "$BUNDLE/"

"$PY" packaging/make_zip.py "$BUNDLE" "dist/$ZIP_NAME"

SIZE="$(du -sh "$BUNDLE" | cut -f1)"
echo "==> $BUNDLE ($SIZE unzipped)"
echo "==> dist/$ZIP_NAME ($(du -h "dist/$ZIP_NAME" | cut -f1))"
