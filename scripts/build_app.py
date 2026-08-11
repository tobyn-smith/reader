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


def build_bundle() -> Path:
    """zip the parser and its one pure python dependency."""
    VENDOR.mkdir(parents=True, exist_ok=True)
    target = VENDOR / "vault.zip"

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "src" / "vault").rglob("*.py")):
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
    return target


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url) as response:
        return response.read()


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
        vendor_pdfjs()
        vendor_pyodide()
    if args.site:
        assemble(args.site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
