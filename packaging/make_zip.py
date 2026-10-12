"""Zip a PyInstaller onedir bundle for release. Used by build.sh and build.ps1.

    python packaging/make_zip.py dist/PyRogue dist/PyRogue-linux-0.1.0.zip

The archive has a single top-level folder (PyRogue/) so unzipping never
sprays files into the user's Downloads. Python's zipfile rather than
`zip`/Compress-Archive so both platforms produce the same layout with no extra
tools. Standard library only.
"""

import os
import sys
import zipfile


def make_zip(bundle, out):
    bundle = os.path.normpath(bundle)
    base = os.path.dirname(bundle)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for folder, dirs, files in os.walk(bundle):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(folder, name)
                arc = os.path.relpath(path, base).replace(os.sep, '/')
                if os.path.islink(path):
                    # PyInstaller makes symlinks on Linux/macOS; keep them links.
                    info = zipfile.ZipInfo(arc)
                    info.external_attr = 0o120777 << 16
                    zf.writestr(info, os.readlink(path))
                else:
                    zf.write(path, arc)
    return out


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: make_zip.py <bundle-dir> <out.zip>')
    make_zip(sys.argv[1], sys.argv[2])
