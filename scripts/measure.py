"""accuracy over a folder of real syllabi.

the fixture suite proves the parser does what it is told; this says whether
what it is told is right. three fixes in one week looked correct in review and
made the corpus worse, and only these numbers caught them, so nothing in the
parser changes without a before and after.

no syllabus is named here and nothing is written into the repo. point it at a
folder, and it writes its detail to the system temp directory:

    python scripts/measure.py ~/Downloads
    python scripts/measure.py ~/Downloads --json out.json --detail
    python scripts/measure.py ~/Downloads --web

the file list is whatever pdfs the folder holds, so the corpus lives on your
machine and this stays a tool rather than a record of your coursework.

--web measures through the same path the website takes: pdf.js hands over
positioned text runs and no ruled-table geometry, where the command line has
pdfplumber. the two do not score the same, and the figures printed on the site
have to be the ones a visitor actually gets, so quote --web there.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vault.classify import SYLLABUS, classify  # noqa: E402
from vault.syllabus.pipeline import parse_extracted, parse_syllabus  # noqa: E402
from vault.text.extract import extract_document  # noqa: E402


def _runs_document(path: Path):
    """what the browser hands the parser: positioned spans, no line geometry."""
    import pymupdf

    from vault.text.runs import document_from_runs

    doc = pymupdf.open(path)
    pages = []
    for index, page in enumerate(doc):
        runs = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    x0, y0, x1, y1 = span["bbox"]
                    runs.append({"text": span["text"], "x": x0, "y": y0,
                                 "w": x1 - x0, "h": y1 - y0,
                                 "size": span.get("size", 0)})
        pages.append({"number": index + 1, "width": page.rect.width,
                      "height": page.rect.height, "runs": runs,
                      "hasTextLayer": bool(runs)})
    return document_from_runs({"filename": path.name, "pages": pages})


def measure_one(path: Path, web: bool = False) -> dict:
    row: dict = {"file": path.name}
    try:
        doc = _runs_document(path) if web else extract_document(path)
        row["kind"] = classify(doc).kind
        if row["kind"] != SYLLABUS:
            return row
        parsed = (parse_extracted(doc, threshold=0.75) if web
                  else parse_syllabus(path, threshold=0.75))
    except Exception as exc:  # a crash is a result, not a reason to stop
        row["error"] = f"{type(exc).__name__}: {exc}"[:160]
        return row

    readings = [r for s in parsed.sessions for r in s.readings]
    cited = [r for r in readings if r.citation.matched_pattern]
    row.update(
        code=parsed.course.code,
        term=str(parsed.course.term) if parsed.course.term else None,
        sessions=len(parsed.sessions),
        dated=sum(1 for s in parsed.sessions if s.meeting_date),
        readings=len(readings),
        cited=len(cited),
        weights=parsed.deliverables.weight_total,
        warnings=list(parsed.warnings),
        unparsed=[r.citation.raw[:150] for r in readings if not r.citation.matched_pattern],
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=Path, help="folder of syllabus pdfs")
    ap.add_argument("--json", type=Path, help="where to write the detail")
    ap.add_argument("--detail", action="store_true", help="print unparsed lines")
    ap.add_argument("--web", action="store_true",
                    help="measure through the browser's path, as the site runs it")
    args = ap.parse_args()

    files = sorted(p for p in args.folder.glob("*.pdf"))
    if not files:
        print(f"no pdfs in {args.folder}", file=sys.stderr)
        return 1

    rows = [measure_one(p, web=args.web) for p in files]
    syllabi = [r for r in rows if r.get("kind") == SYLLABUS and "error" not in r]

    print(f"{'file':46s} {'sess':>5s} {'dated':>6s} {'cited':>9s} {'weights':>8s}")
    print("-" * 78)
    for row in rows:
        name = row["file"][:44]
        if "error" in row:
            print(f"{name:46s} ERROR {row['error'][:24]}")
        elif row.get("kind") != SYLLABUS:
            print(f"{name:46s} not a syllabus ({row.get('kind')})")
        else:
            cited = f"{row['cited']}/{row['readings']}" if row["readings"] else "-"
            print(f"{name:46s} {row['sessions']:5d} {row['dated']:6d} "
                  f"{cited:>9s} {str(row['weights'] or '-'):>8s}")

    total = sum(r["readings"] for r in syllabi)
    cited = sum(r["cited"] for r in syllabi)
    scheduled = sum(1 for r in syllabi if r["sessions"])
    near100 = [r for r in syllabi if r["weights"]]
    coded = sum(1 for r in syllabi if r.get("code"))
    termed = sum(1 for r in syllabi if r.get("term"))
    print()
    print(f"path                 {'browser (--web)' if args.web else 'command line'}")
    print(f"syllabi              {len(syllabi)} of {len(files)} files")
    print(f"course code found    {coded}/{len(syllabi)}")
    print(f"term found           {termed}/{len(syllabi)}")
    print(f"schedule found       {scheduled}/{len(syllabi)}"
          f" ({scheduled / max(len(syllabi), 1):.0%})")
    print(f"readings extracted   {total}")
    print(f"citations resolved   {cited}/{total} ({cited / max(total, 1):.0%})")
    print(f"weights near 100     "
          f"{sum(1 for r in near100 if abs(r['weights'] - 100) <= 1)}/{len(near100)}")

    if args.detail:
        for row in syllabi:
            if row["unparsed"]:
                print(f"\n--- {row['file']}")
                for line in row["unparsed"][:12]:
                    print(f"    {line}")

    # detail lands in temp unless asked otherwise. writing it beside the repo
    # is how a dump of real syllabus lines once ended up in a commit.
    out = args.json or Path(tempfile.gettempdir()) / "vault-measure.json"
    out.write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    print(f"\ndetail written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
