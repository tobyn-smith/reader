"""last gate before anything reaches a public url.

two checks, both default deny:

  the export file may only contain allowlisted field names, so adding a column
  to the schema cannot quietly start publishing it

  the built site may not contain the markers that only ever appear in private
  material, checked inside generated pdfs as well as html, because a pdf hides
  its text from a plain grep

this runs in ci, where the database is absent by design. it is checking the
artifact, not the source of truth.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vault.publish import check_export_file  # noqa: E402

# text that has no business on a public page. these are the shapes private
# content takes, not a list of secrets.
FORBIDDEN = [
    (re.compile(r"\bchunk_text\b", re.I), "extracted reading text"),
    (re.compile(r"\bbrief_markdown\b", re.I), "generated brief"),
    (re.compile(r"\bgenerated_by\s*[:=]\s*[\"']?model", re.I), "model generated content"),
    (re.compile(r"\binstructor_email\b", re.I), "instructor email field"),
    (re.compile(r"[\w.+-]+@[\w-]+\.(?:edu|ac\.[a-z]{2})\b"), "an academic email address"),
]

TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".json", ".txt", ".xml", ".svg", ".md"}


def scan_text(path: Path) -> list[str]:
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [why for pattern, why in FORBIDDEN if pattern.search(body)]


def scan_pdf(path: Path) -> list[str]:
    """read the text layer, because a file name proves nothing about contents."""
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        with pymupdf.open(path) as doc:
            body = "\n".join(page.get_text("text") for page in doc)
    except Exception:
        return []
    return [why for pattern, why in FORBIDDEN if pattern.search(body)]


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    problems: list[str] = []

    export = Path("data/public.json")
    if export.exists():
        for issue in check_export_file(export):
            problems.append(f"{export}: {issue}")
    else:
        print(f"note: {export} absent, only the built site is checked")

    if not site.exists():
        print(f"{site} does not exist")
        return 1

    checked = 0
    for path in sorted(site.rglob("*")):
        if not path.is_file():
            continue
        # vendored libraries are third party code, not published data
        if "vendor" in path.parts or "pagefind" in path.parts:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            found = scan_text(path)
        elif path.suffix.lower() == ".pdf":
            found = scan_pdf(path)
        else:
            continue
        checked += 1
        for why in found:
            problems.append(f"{path}: contains {why}")

    if problems:
        print(f"refusing to publish, {len(problems)} problem(s):")
        for line in problems:
            print(f"  {line}")
        return 1

    print(f"publish check passed over {checked} file(s) in {site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
