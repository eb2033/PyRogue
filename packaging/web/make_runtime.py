"""Self-host a slimmed pygbag runtime inside the itch.io zip (standard library only).

    python packaging/web/make_runtime.py <pygbag build dir> <out.zip> [--cache DIR]

<pygbag build dir> is what `pygbag --build --template packaging/web/index.tmpl`
leaves behind (index.html, favicon.png, web.apk). This script downloads the
pinned pygbag 0.9.3 runtime from pygame-web.github.io (cached, checked against
SHA-256 pins), then writes next to index.html an rt/ folder with:

  * main.wasm.gz   the CPython wasm, gzip -9 (same bytes the CDN sends, no CDN hop)
  * main.data.gz   the stdlib bundle, repacked: it ships LZ4-compressed, which gzip
                   cannot squeeze, so it is decoded, stripped of what the game
                   never loads (a 3.3 MB FreeSerif font, test data) and gzipped
  * main.js        the emscripten loader, patched to read that bundle and to fetch
                   it with fetch() (see patch_loader)
  * pythons.js, cpythonrc.py, the pygame-ce wheel and a one-entry package index,
    unchanged; pygbag's package installer is pointed at rt/ instead of the CDN

and inlines packaging/web/prefetch.js into index.html. It also puts LICENSE,
THIRD_PARTY_NOTICES.txt and licenses/ (packaging/web/) at the zip root: the zip
redistributes third-party binaries, so the build fails without them.
    python packaging/web/make_runtime.py --verify <out.zip>
re-checks a finished zip. Every patch asserts that
its target text exists, so a runtime that differs from the pinned one fails the
build instead of shipping a broken game.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
NOTICES = 'THIRD_PARTY_NOTICES.txt'
CDN = 'https://pygame-web.github.io/cdn/'
PYGBAG = '0.9.3'
ABI = 'cp312'
WHEEL = 'pygame_ce-2.5.7-cp312-cp312-wasm32_bi_emscripten.whl'

# key -> (path under CDN, sha256 of the bytes as served, once decompressed)
UPSTREAM = {
    'pythons.js': (
        f'{PYGBAG}/pythons.js',
        '6da43e3e62c3db933421b99681e8ef99ed9b0ce1589ed8a0c69b88443278e019',
    ),
    'main.js': (
        f'{PYGBAG}/cpython312/main.js',
        '01c4e4dc7145a482ad259d8272ce73d97b58ec2a141bfb57e620347730d159c7',
    ),
    'main.wasm': (
        f'{PYGBAG}/cpython312/main.wasm',
        '3cfb882de90feeb367325f0c58731932880c8f424fb5a670b98d035ae862b280',
    ),
    'main.data': (
        f'{PYGBAG}/cpython312/main.data',
        'b068df4d59b06b113cfc3c4d6419bdf699d2c2eeb547c9119e2044c98cdc4a59',
    ),
    'cpythonrc.py': (
        f'{PYGBAG}/cpythonrc.py',
        'b8a0b8168b58ef7c38c17d4705c9cbe1751fa667a0a6d26ed26f0537134735de',
    ),
    'wheel': (
        f'{ABI}/{WHEEL}',
        '4f2caa3020592950565f3649c41e2eeacd001be93da892d60e5a4a43d893a323',
    ),
}

ASSETS = '/data/data/org.python/assets'
# files of the stdlib bundle the game never loads
DROP_FILES = (
    ASSETS
    + '/site-packages/pygame/FreeSerif.ttf',  # 3.3 MB; pygame's default font is freesansbold
)
# whole modules that a title -> class -> floors -> death session never imports
# (checked against sys.modules in Chromium); the game and pygbag's installer do not use them
DROP_SUBSTRINGS = (
    '/site-packages/pkg_resources/',
    '/site-packages/_xterm_parser/',
    '/usr/lib/python3.12/xml/',
    '/usr/lib/python3.12/multiprocessing/',
    '/usr/lib/python3.12/curses/',
    '/usr/lib/python3.12/sqlite3/',
    '/usr/lib/python3.12/pydoc.py',
    '/usr/lib/python3.12/optparse.py',
    '/usr/lib/python3.12/plistlib.py',
)

# text patches inside the bundle: (file suffix, old, new)
DATA_PATCHES = (
    (
        '/aio/pep0723.py',
        'PKG_BASE_DEFAULT = "https://pygame-web.github.io/cdn/"',
        'PKG_BASE_DEFAULT = "rt/"',
    ),
    ('/aio/pep0723.py', 'rewritecdn = "http://localhost:8000/cdn/"', 'rewritecdn = ""'),
)


def fail(msg: str) -> None:
    sys.exit(f'make_runtime: {msg}')


def fetch_upstream(cache: Path) -> dict[str, bytes]:
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, (rel, pin) in UPSTREAM.items():
        path = cache / rel.replace('/', '_')
        if not path.is_file():
            print(f'    downloading {CDN}{rel}')
            req = urllib.request.Request(CDN + rel, headers={'User-Agent': 'PyRogue-build'})
            with urllib.request.urlopen(req, timeout=120) as r:
                path.write_bytes(r.read())
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if pin and digest != pin:
            fail(f'{rel} differs from the pinned pygbag {PYGBAG} runtime (sha256 {digest})')
        out[key] = data
    return out


# --- LZ4 block decoding (emscripten -sLZ4 packs main.data in 2 KB chunks) -------------


def lz4_block(src: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i : i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if off >= ml:
            out += out[start : start + ml]
        else:
            for k in range(ml):
                out.append(out[start + k])
    return bytes(out)


def unpack_bundle(js: str, data: bytes) -> tuple[bytes, list[tuple[str, int, int, str]]]:
    i = js.index('var compressedData={data:null')
    blob = js[i : js.index('};', i)]

    def numbers(name: str) -> list[int]:
        m = re.search(name + r':\[([^\]]*)\]', blob)
        assert m, name
        return [int(float(x)) for x in m.group(1).split(',')]

    raw = bytearray()
    for off, size, ok in zip(numbers('offsets'), numbers('sizes'), numbers('successes')):
        chunk = data[off : off + size]
        raw += lz4_block(chunk) if ok else chunk
    files = [
        (f, int(a), int(b), extra)
        for f, a, b, extra in re.findall(
            r'\{filename:"([^"]+)",start:(\d+),end:(\d+)([^}]*)\}', js
        )
    ]
    if not files or max(b for _, _, b, _ in files) != len(raw):
        fail('main.data did not unpack to the size its file table says')
    return bytes(raw), files


def repack_bundle(js: str, data: bytes) -> tuple[bytes, str]:
    """Return (raw bundle without the dropped files, main.js with its new file table)."""
    raw, files = unpack_bundle(js, data)
    blob = bytearray()
    placed: dict[tuple[int, int], int] = {}
    entries = []
    patched = set()
    for name, a, b, extra in files:
        if name in DROP_FILES or any(s in name for s in DROP_SUBSTRINGS):
            continue
        body = raw[a:b]
        key: tuple[int, int] | None = (a, b)
        for suffix, old, new in DATA_PATCHES:
            if name.endswith(suffix) and old.encode() in body:
                body = body.replace(old.encode(), new.encode())
                patched.add((suffix, old))
                key = None
        if key is not None and key in placed:
            start = placed[key]
        else:
            start = len(blob)
            blob += body
            if key is not None:
                placed[key] = start
        entries.append(f'{{filename:"{name}",start:{start},end:{start + len(body)}{extra}}}')
    for suffix, old, _ in DATA_PATCHES:
        if (suffix, old) not in patched:
            fail(f'bundle patch target not found: {old!r}')
    if len(entries) == len(files):
        fail('nothing was dropped from the bundle; the drop list is stale')
    table_start = js.index('loadPackage({files:[') + len('loadPackage(')
    m = re.compile(r',remote_package_size:\d+\}').search(js, table_start)
    assert m
    new_table = '{files:[' + ','.join(entries) + f'],remote_package_size:{len(blob)}}}'
    return bytes(blob), js[:table_start] + new_table + js[m.end() :]


# --- patches to main.js ----------------------------------------------------------------

LZ4_LOAD = re.compile(
    r'var compressedData=\{data:null,.*?\};compressedData\["data"\]=byteArray;'
    r'assert\(typeof Module\["LZ4"\]==="object","LZ4 not present - was your app build with -sLZ4\?"\);'
    r'Module\["LZ4"\]\.loadPackage\(\{metadata:metadata,compressedData:compressedData\},true\);',
    re.S,
)
RAW_LOAD = (
    'metadata.files.forEach(function(file){var dir=PATH.dirname(file.filename);'
    'FS.createPath("",dir,true,true);'
    'FS.createDataFile(dir,PATH.basename(file.filename),byteArray.subarray(file.start,file.end),true,true,true)});'
)
FETCH_HEAD = 'function fetchRemotePackage(packageName,packageSize,callback,errback){'
FETCH_NEW = (
    FETCH_HEAD
    + 'fetch(packageName).then(function(r){return r.arrayBuffer()}).then(callback,errback);return;'
)


def patch_loader(js: str) -> str:
    js, n = LZ4_LOAD.subn(lambda _m: RAW_LOAD, js)
    if n != 1:
        fail('main.js: the LZ4 package loader was not found')
    if js.count(FETCH_HEAD) != 1:
        fail('main.js: fetchRemotePackage was not found')
    # the glue now runs as an inline script (no src), so the wasm is named by its page-relative path
    if js.count('var f="main.wasm"') != 1:
        fail('main.js: findWasmBinary was not found')
    return js.replace(FETCH_HEAD, FETCH_NEW).replace(
        'var f="main.wasm"', 'var f="rt/cpython312/main.wasm"'
    )


JSIMPORT = 'function jsimport(url, sync) {' + chr(10)


def patch_pythons(js: str) -> str:
    """Let jsimport() hand the interpreter glue to prefetch.js (a gzipped inline script)."""
    if js.count(JSIMPORT) != 1:
        fail('pythons.js: jsimport was not found')
    return js.replace(
        JSIMPORT, JSIMPORT + '    if (window.__rt && window.__rt.script(url)) return' + chr(10)
    )


MAX_ZIP_BYTES = 15_000_000  # the budget in web_build_plan.md section 5
MAX_ZIP_FILES = 100  # itch.io allows 1000; a dozen runtime files plus the licence texts


def notice_files() -> dict[str, Path]:
    """Zip path -> source file for the licence material at the zip root."""
    files = {'LICENSE': ROOT / 'LICENSE', NOTICES: HERE / NOTICES}
    folder = HERE / 'licenses'
    for p in sorted(folder.glob('*.txt')) if folder.is_dir() else []:
        files[f'licenses/{p.name}'] = p
    for name, src in files.items():
        if not src.is_file():
            fail(f'{src} is missing; the zip cannot ship without {name}')
    if len(files) < 3:
        fail(f'{folder} holds no licence texts')
    return files


def check_zip(path: Path) -> None:
    """Fail the build when the archive is not something itch.io will serve correctly."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        index = zf.read('index.html').decode('utf8') if 'index.html' in names else ''
    if not index:
        fail(f'index.html is not at the root of {path}; entries: {names}')
    if len(names) > MAX_ZIP_FILES:
        fail(f'{len(names)} files in {path}; the limit is {MAX_ZIP_FILES}')
    if path.stat().st_size > MAX_ZIP_BYTES:
        fail(f'{path} is {path.stat().st_size} bytes, over the {MAX_ZIP_BYTES} budget')
    if 'pygame-web.github.io' in index:
        fail('index.html still reaches for the pygbag CDN')
    # a licence file the notices name but the zip lacks (or the reverse) is a release bug
    listed = set(re.findall(r'[\w.+-]+\.txt', zf_text(path, NOTICES))) - {NOTICES}
    shipped = {
        n[len('licenses/') :] for n in names if n.startswith('licenses/') and n != 'licenses/'
    }
    if listed != shipped:
        fail(f'{NOTICES} and licenses/ disagree: {sorted(listed ^ shipped)}')
    for need in (
        'LICENSE',
        NOTICES,
        'rt/pythons.js',
        'rt/cpython312/main.wasm.gz',
        'rt/cpython312/main.data.gz',
        'web.apk',
    ):
        if need not in names:
            fail(f'{need} is missing from {path}')


def zf_text(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read(name).decode('utf8') if name in zf.namelist() else ''


def gzip9(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, 31)  # wbits 31: gzip container, header mtime 0
    return c.compress(data) + c.flush()


def main(argv: list[str]) -> None:
    if argv[:1] == ['--verify'] and len(argv) == 2:
        check_zip(Path(argv[1]))
        print(f'==> {argv[1]} has index.html, LICENSE, {NOTICES} and licenses/')
        return
    args = [a for a in argv if not a.startswith('--')]
    cache = Path('build/web-runtime-cache')
    if '--cache' in argv:
        raw_cache = argv[argv.index('--cache') + 1]
        cache = Path(raw_cache)
        args.remove(raw_cache)
    if len(args) != 2:
        fail('usage: make_runtime.py <pygbag build dir> <out.zip> [--cache DIR]')
    build, out_zip = Path(args[0]), Path(args[1])
    for need in ('index.html', 'favicon.png', 'web.apk'):
        if not (build / need).is_file():
            fail(f'{build / need} is missing; run pygbag --build first')

    print('==> self-hosting the pygbag runtime')
    up = fetch_upstream(cache)
    js = up['main.js'].decode('utf8')
    bundle, js = repack_bundle(js, up['main.data'])
    js = patch_loader(js)

    rt = {
        'rt/pythons.js': patch_pythons(up['pythons.js'].decode('utf8')).encode('utf8'),
        'rt/cpythonrc.py.gz': gzip9(up['cpythonrc.py']),
        'rt/cpython312/main.js.gz': gzip9(js.encode('utf8')),
        'rt/cpython312/main.wasm.gz': gzip9(up['main.wasm']),
        'rt/cpython312/main.data.gz': gzip9(bundle),
        f'rt/{ABI}/{WHEEL}': up['wheel'],
        f'rt/index-{PYGBAG}-{ABI}.json': json.dumps(
            {'-CDN-': 'rt/', 'pygame': f'{ABI}/pygame_ce-2.5.7-<abi>-<abi>-<api>.whl'}
        ).encode(),
    }

    prefetch = (HERE / 'prefetch.js').read_text(encoding='utf8')
    prefetch = prefetch.replace('PYGAME_WHEEL', WHEEL).replace('PYGBAG', PYGBAG)
    html = (build / 'index.html').read_text(encoding='utf8')
    if '/*PREFETCH*/' not in html:
        fail('index.html was not built from packaging/web/index.tmpl')
    html = html.replace('/*PREFETCH*/', prefetch)

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    out_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(out_zip, 'w') as zf:
        zf.writestr('index.html', html, zipfile.ZIP_DEFLATED)
        zf.write(build / 'favicon.png', 'favicon.png', zipfile.ZIP_STORED)
        zf.write(build / 'web.apk', 'web.apk', zipfile.ZIP_STORED)
        for name, src in notice_files().items():
            zf.write(src, name, zipfile.ZIP_DEFLATED)
        for name, data in rt.items():
            stored = name.endswith(('.gz', '.whl'))
            zf.writestr(name, data, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    for name, data in rt.items():  # the same tree unpacked, for serving a local test
        p = build / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (build / 'index.html').write_text(html, encoding='utf8')
    for name, src in notice_files().items():
        (build / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, build / name)
    check_zip(out_zip)
    print(
        f'==> {out_zip} ({out_zip.stat().st_size / 1e6:.2f} MB); bundle {len(bundle) / 1e6:.2f} MB raw'
    )


if __name__ == '__main__':
    main(sys.argv[1:])
