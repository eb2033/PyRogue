"""Put the third-party notices into a built bundle.

    python packaging/collect_licenses.py dist/PyRogue

Copies packaging/THIRD_PARTY_NOTICES.txt to the bundle's root and every
packaging/licenses/*.txt into <bundle>/licenses/, plus the licence of the
Python that ran the build (it's the runtime the bundle carries), as
licenses/Python-LICENSE.txt. Run by build.sh and build.ps1 after PyInstaller.
"""

import glob
import os
import shutil
import sys
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent


def python_license():
    """This interpreter's LICENSE.txt: next to python.exe on Windows,
    lib/pythonX.Y/ on Linux and macOS."""
    base = sys.base_prefix
    candidates = [os.path.join(base, 'LICENSE.txt')]
    candidates += glob.glob(os.path.join(base, 'lib', 'python3*', 'LICENSE.txt'))
    for path in candidates:
        if os.path.isfile(path):
            return Path(path)
    return None


def main(bundle):
    bundle = Path(bundle)
    if not bundle.is_dir():
        raise SystemExit(f'no bundle at {bundle}')
    shutil.copy2(PACKAGING / 'THIRD_PARTY_NOTICES.txt', bundle)
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    for path in sorted((PACKAGING / 'licenses').glob('*.txt')):
        shutil.copy2(path, licenses)
    python = python_license()
    if python is None:
        raise SystemExit("can't find this Python's LICENSE.txt to ship with the build")
    shutil.copy2(python, licenses / 'Python-LICENSE.txt')
    print(f'==> notices + {len(list(licenses.iterdir()))} licence files in {licenses}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'dist/PyRogue')
