"""take reading pdfs in, keep the page numbers, match them to the syllabus."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .syllabus.citations import Author, parse_authors
from .text.chunk import chunk_document
from .text.extract import ExtractedDoc, extract_document, file_hash


@dataclass
class IngestResult:
    path: Path
    file_hash: str
    document_id: int | None
    skipped: bool = False
    chunks: int = 0
    ocr_used: bool = False
    status: str = "ok"
    matched_work_id: int | None = None
    match_confidence: float = 0.0
    match_method: str = ""
    warnings: list[str] | None = None


def ingest_path(conn: sqlite3.Connection, target: Path, *, ocr: str = "auto") -> list[IngestResult]:
    files = sorted(target.rglob("*.pdf")) if target.is_dir() else [target]
    return [ingest_file(conn, path, ocr=ocr) for path in files]


def ingest_file(conn: sqlite3.Connection, path: Path, *, ocr: str = "auto") -> IngestResult:
    digest = file_hash(path)
    existing = conn.execute(
        "select id from document where file_hash = ?", (digest,)
    ).fetchone()
    if existing:
        return IngestResult(path, digest, existing["id"], skipped=True)

    doc = extract_document(path, ocr=ocr, detect_tables=False)
    match_id, confidence, method = match_to_reading(conn, doc)

    document_id = conn.execute(
        "insert into document (work_id, file_hash, source_path, filename, page_count,"
        " ocr_used, extraction_status, extraction_warnings, match_confidence, match_method)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            digest,
            str(path),
            path.name,
            doc.page_count,
            1 if doc.ocr_used else 0,
            doc.status,
            json.dumps(doc.warnings),
            confidence,
            method,
        ),
    ).lastrowid

    count = 0
    for chunk in chunk_document(doc):
        conn.execute(
            "insert into chunk (document_id, page_number, ordinal, kind, ref_marker, body)"
            " values (?, ?, ?, ?, ?, ?)",
            (document_id, chunk.page_number, chunk.ordinal, chunk.kind, chunk.ref_marker, chunk.body),
        )
        count += 1

    conn.commit()
    return IngestResult(
        path=path,
        file_hash=digest,
        document_id=document_id,
        chunks=count,
        ocr_used=doc.ocr_used,
        status=doc.status,
        matched_work_id=match_id,
        match_confidence=confidence,
        match_method=method,
        warnings=doc.warnings,
    )


_STOP = {"the", "a", "an", "of", "and", "in", "on", "for", "to", "is", "as"}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def match_to_reading(
    conn: sqlite3.Connection, doc: ExtractedDoc
) -> tuple[int | None, float, str]:
    """guess which assigned reading a pdf satisfies.

    scored on surname, year and title overlap taken from the first two pages,
    which is where a title block sits. the score is stored so a weak match can be
    corrected rather than silently trusted.
    """
    head = "\n".join(page.text for page in doc.pages[:2])
    if not head.strip():
        return None, 0.0, "no text"

    head_tokens = _tokens(head)
    years = set(re.findall(r"\b(1[89]\d{2}|20\d{2})\b", head))

    best_id: int | None = None
    best_score = 0.0
    for row in conn.execute(
        "select id, title, year, authors, doi from work"
    ):
        score = 0.0
        if row["doi"] and row["doi"].lower() in head.lower():
            best_id, best_score = row["id"], 1.0
            break

        title_tokens = _tokens(row["title"])
        if title_tokens:
            overlap = len(title_tokens & head_tokens) / len(title_tokens)
            score += 0.6 * overlap

        surnames = {
            (a.get("surname") or a.get("literal") or "").lower()
            for a in json.loads(row["authors"] or "[]")
        }
        surnames.discard("")
        if surnames and any(s in head_tokens for s in surnames):
            score += 0.25

        if row["year"] and str(row["year"]) in years:
            score += 0.15

        if score > best_score:
            best_id, best_score = row["id"], score

    if best_score < 0.45:
        return None, round(best_score, 3), "below threshold"
    return best_id, round(min(best_score, 1.0), 3), "author, title and year overlap"


def set_document_work(conn: sqlite3.Connection, document_id: int, work_id: int | None) -> None:
    conn.execute(
        "update document set work_id = ?, match_confidence = 1.0, match_method = 'confirmed by hand'"
        " where id = ?",
        (work_id, document_id),
    )
    conn.commit()
