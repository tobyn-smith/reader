"""assemble the browser app.

the parser that runs in the tab is the same python the command line uses, so it
is zipped straight out of src/ rather than being reimplemented. wordninja goes
in with it: without its word list the space restoring rule refuses to fire, and
the browser would quietly parse differently from the command line.

vendored javascript is fetched here rather than loaded from a cdn at runtime. a
tool that promises files never leave the browser must not be calling out to
anyone while it works.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import re
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
VENDOR = APP / "vendor"

PYODIDE_VERSION = "0.26.4"
PDFJS_VERSION = "4.6.82"

# the core distribution rather than the full one. the app loads no scientific
# packages, so the extra few hundred megabytes would be downloaded and thrown
# away on every build.
PYODIDE_URL = (
    f"https://github.com/pyodide/pyodide/releases/download/{PYODIDE_VERSION}/"
    f"pyodide-core-{PYODIDE_VERSION}.tar.bz2"
)
PDFJS_URL = (
    f"https://github.com/mozilla/pdf.js/releases/download/v{PDFJS_VERSION}/"
    f"pdfjs-{PDFJS_VERSION}-dist.zip"
)

# only what the worker actually loads. the full pyodide distribution is far
# larger than the app needs.
PYODIDE_KEEP = {
    "pyodide.js",
    "pyodide.asm.js",
    "pyodide.asm.wasm",
    "pyodide-lock.json",
    "python_stdlib.zip",
}


def browser_modules() -> list[Path]:
    """the python the browser can actually reach, walked from vault.web.

    the bundle used to be every .py under src/vault, which shipped the command
    line, the database layer, the site builder and the optional model adapter
    to every visitor: about a third of the payload, for code no browser path
    can call. worse, the version stamp was hashed over the same unfiltered
    list, so editing the cli marked every stored course in every browser as
    parsed by an older version and offered to re-read them all, for a change
    that could not have altered a parse.

    the walk is done here rather than written out by hand so a new module
    imported by the parser is picked up without anyone remembering to add it.
    """
    import ast

    source = ROOT / "src"
    files = {}
    for path in source.rglob("*.py"):
        name = path.relative_to(source).with_suffix("").as_posix().replace("/", ".")
        files[name[:-9] if name.endswith(".__init__") else name] = path

    def imports_of(module: str) -> set[str]:
        tree = ast.parse(files[module].read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = module.split(".")
                    parts = parts[: len(parts) - node.level] if node.level <= len(parts) else []
                    target = ".".join(parts + ([node.module] if node.module else []))
                else:
                    target = node.module or ""
                if target.startswith("vault"):
                    found.add(target)
                    found.update(f"{target}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names if a.name.startswith("vault"))
        return found

    seen: set[str] = set()
    queue = ["vault.web", "vault"]
    while queue:
        module = queue.pop()
        if module in seen or module not in files:
            continue
        seen.add(module)
        queue.extend(dep for dep in imports_of(module) if dep in files and dep not in seen)

    return sorted(files[m] for m in seen)


def build_bundle() -> Path:
    """zip the parser and its one pure python dependency."""
    VENDOR.mkdir(parents=True, exist_ok=True)
    target = VENDOR / "vault.zip"
    shipped = browser_modules()

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in shipped:
            archive.write(path, path.relative_to(ROOT / "src"))

        import wordninja

        module = Path(wordninja.__file__)
        archive.write(module, "wordninja.py")
        data = module.parent / "wordninja"
        for path in sorted(data.rglob("*")):
            if path.is_file():
                archive.write(path, Path("wordninja") / path.relative_to(data))

    size = target.stat().st_size / 1024
    print(f"vault.zip  {size:.0f} kB")

    # the parser's fingerprint, readable without booting pyodide. the app
    # stamps each saved parse with it, and a stored course whose stamp differs
    # from the running bundle is offered a re-read. hashed over the source
    # files, not the zip: an archive embeds timestamps, so hashing it marked
    # every course stale on every deploy even with nothing changed.
    import hashlib

    # windows checkouts carry crlf and ci carries lf, so line endings are
    # normalised or the two platforms stamp the same source differently
    # hashed over what is shipped, not over the whole package, so a change to
    # the command line no longer tells every user their courses are stale
    hasher = hashlib.sha256()
    for path in shipped:
        hasher.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
    digest = hasher.hexdigest()[:12]
    (APP / "version.js").write_text(
        "// written by scripts/build_app.py, the hash of the parser bundle\n"
        f"export const PARSER_VERSION = '{digest}'\n",
        encoding="utf-8",
    )
    print(f"parser version {digest}")
    return target


def fetch(url: str, attempts: int = 4) -> bytes:
    """download, retrying a dropped connection.

    every asset here comes from someone else's cdn, and a release build died
    twice in one afternoon on a connection closed mid-handshake. one flaky
    socket should cost a few seconds, not the whole deploy.
    """
    print(f"fetching {url}")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except Exception as exc:
            if attempt == attempts:
                raise
            wait = 2 ** attempt
            print(f"  {type(exc).__name__}, retrying in {wait}s "
                  f"({attempt} of {attempts - 1})")
            time.sleep(wait)
    raise AssertionError("unreachable")


# the three families the theme is built on, latin subset only. fetched at
# build time and served from our own origin, so a visitor loading a syllabus
# makes no request to anyone else. the css is generated rather than taken from
# the font host, because that css points back at the host.
FONT_QUERY = (
    "https://fonts.googleapis.com/css2"
    "?family=Archivo+Narrow:wght@700"
    "&family=IBM+Plex+Mono:wght@400;500"
    "&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400"
)
# a desktop chrome string, or the host serves an older format than woff2
FONT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def vendor_fonts() -> None:
    # the sheet sits beside the fonts directory, not inside it, so the
    # "fonts/name.woff2" it writes resolves from where the sheet is loaded
    out = VENDOR / "fonts"
    sheet_path = VENDOR / "fonts.css"
    if sheet_path.exists():
        print("fonts already vendored")
        return
    out.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(FONT_QUERY, headers={"User-Agent": FONT_UA})
    print(f"fetching {FONT_QUERY}")
    with urllib.request.urlopen(request) as response:
        sheet = response.read().decode("utf-8")

    # each @font-face block is preceded by a subset comment. only latin is kept,
    # which is the difference between about 60 kB and about 900 kB.
    blocks = re.split(r"/\*\s*([a-z0-9-]+)\s*\*/", sheet)
    rules: list[str] = []
    for index in range(1, len(blocks) - 1, 2):
        if blocks[index] != "latin":
            continue
        block = blocks[index + 1]
        url_match = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not url_match:
            continue
        url = url_match.group(1)
        name = url.rsplit("/", 1)[-1]
        (out / name).write_bytes(fetch(url))
        rules.append(block.replace(url, f"fonts/{name}").strip())

    sheet_path.write_text("\n".join(rules) + "\n", encoding="utf-8")
    total = sum(p.stat().st_size for p in out.glob("*.woff2")) / 1024
    print(f"fonts vendored  {len(rules)} faces, {total:.0f} kB")


def vendor_pdfjs() -> None:
    if (VENDOR / "pdf.mjs").exists():
        print("pdf.js already vendored")
        return
    blob = fetch(PDFJS_URL)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name, target in [
            ("build/pdf.mjs", "pdf.mjs"),
            ("build/pdf.worker.mjs", "pdf.worker.mjs"),
        ]:
            (VENDOR / target).write_bytes(archive.read(name))
    print("pdf.js vendored")


def vendor_pyodide() -> None:
    if (VENDOR / "pyodide" / "pyodide.js").exists():
        print("pyodide already vendored")
        return
    import tarfile

    blob = fetch(PYODIDE_URL)
    out = VENDOR / "pyodide"
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:bz2") as archive:
        for member in archive.getmembers():
            name = Path(member.name).name
            if name in PYODIDE_KEEP:
                source = archive.extractfile(member)
                if source is not None:
                    (out / name).write_bytes(source.read())
    print("pyodide vendored")


def assemble(site: Path) -> None:
    """copy the app into the directory that gets published."""
    site.mkdir(parents=True, exist_ok=True)
    for path in APP.rglob("*"):
        if path.is_dir():
            continue
        target = site / path.relative_to(APP)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    print(f"app assembled into {site}")


def main() -> int:
    parser = argparse.ArgumentParser(description="assemble the browser app")
    parser.add_argument("--vendor", action="store_true", help="download pdf.js and pyodide")
    parser.add_argument("--site", type=Path, help="also copy the finished app here")
    args = parser.parse_args()

    build_bundle()
    if args.vendor:
        vendor_fonts()
        vendor_pdfjs()
        vendor_pyodide()
    if args.site:
        assemble(args.site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
