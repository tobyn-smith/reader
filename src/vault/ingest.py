"""take reading pdfs in, keep the page numbers, match them to the syllabus."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .match import Candidate, match_document
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


def match_to_reading(
    conn: sqlite3.Connection, doc: ExtractedDoc
) -> tuple[int | None, float, str]:
    head = "
".join(page.text for page in doc.pages[:2])
    candidates = [
        Candidate(
            id=row["id"],
            title=row["title"],
            year=row["year"],
            authors=json.loads(row["authors"] or "[]"),
            doi=row["doi"],
        )
        for row in conn.execute("select id, title, year, authors, doi from work")
    ]
    result = match_document(head, candidates, filename=doc.path.name)
    return result.id, result.score, result.method


def set_document_work(conn: sqlite3.Connection, document_id: int, work_id: int | None) -> None:
    conn.execute(
        "update document set work_id = ?, match_confidence = 1.0, match_method = 'confirmed by hand'"
        " where id = ?",
        (work_id, document_id),
    )
    conn.commit()
