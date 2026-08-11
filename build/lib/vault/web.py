"""entry points for the browser build.

everything crosses the javascript boundary as a json string, which keeps the
contract explicit and lets the same calls be tested from ordinary python. no
function here touches the filesystem, the database, the network, or a pdf
library, because under pyodide none of those are available.
"""

from __future__ import annotations

import json

from . import __version__
from .match import Candidate, match_document
from .syllabus.pipeline import parse_extracted
from .text.model import ExtractedDoc
from .text.runs import document_from_runs


def version() -> str:
    return __version__


def parse_runs(payload: str, threshold: float = 0.75) -> str:
    """turn positioned text runs into a reviewable parse.

    payload is the json described in text/runs.py. the reply is the same
    structure the command line writes for review, so both paths present the
    identical set of flagged rows.
    """
    doc = document_from_runs(json.loads(payload))
    parsed = parse_extracted(doc, threshold=threshold)
    result = parsed.to_dict()
    result["page_warnings"] = _page_warnings(doc)
    return json.dumps(result)


def _page_warnings(doc: ExtractedDoc) -> list[dict]:
    return [
        {"page": page.number, "needs_ocr": True}
        for page in doc.pages
        if not page.had_text_layer
    ]


def extract_reading(payload: str) -> str:
    """pull clean page text out of a reading, keeping page numbers attached."""
    doc = document_from_runs(json.loads(payload), detect_tables=False)
    return json.dumps(
        {
            "filename": str(doc.path),
            "page_count": doc.page_count,
            "status": doc.status,
            "warnings": doc.warnings,
            "pages": [
                {
                    "number": page.number,
                    "text": page.text,
                    "footnotes": page.footnotes,
                    "had_text_layer": page.had_text_layer,
                }
                for page in doc.pages
            ],
        }
    )


def match_reading(head: str, candidates: str) -> str:
    """score one reading against the works already parsed from a syllabus."""
    rows = json.loads(candidates)
    result = match_document(
        head,
        [
            Candidate(
                id=row.get("id"),
                title=row.get("title"),
                year=row.get("year"),
                authors=row.get("authors") or [],
                doi=row.get("doi"),
            )
            for row in rows
        ],
    )
    return json.dumps({"id": result.id, "score": result.score, "method": result.method})
