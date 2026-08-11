"""fill citation gaps from crossref and openlibrary.

both apis are free and keyless. every response is cached on disk, a failed
lookup never breaks a parse, and a field the user confirmed by hand is never
overwritten. enrichment adds, it does not correct silently: a fetched value only
lands in an empty field.

there are two jobs here and they behave differently. filling completes a
citation the patterns already read, and lands values straight into empty fields.
rescue takes a line no pattern could read at all, asks crossref what it is, and
attaches the answer as a suggestion for review. rescue never writes to the
citation, because the line got there by defeating the deterministic rules and a
search result is not evidence enough to overrule that on its own.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .lookup import rescue_from_item, worth_rescuing
from .syllabus.citations import Suggestion
from .syllabus.pipeline import ParsedSyllabus
from .text.normalize import collapse_whitespace

TIMEOUT = 8
PAUSE = 0.4
RESCUE_ROWS = 5

_FILLABLE = ("container", "publisher", "volume", "issue", "pages", "doi", "url", "year")


@dataclass
class EnrichResult:
    filled: int = 0
    suggested: int = 0
    looked_up: int = 0

    def __bool__(self) -> bool:
        return bool(self.filled or self.suggested)


def enrich_parse(parsed: ParsedSyllabus, *, cache_dir: Path, rescue: bool = True) -> EnrichResult:
    result = EnrichResult()
    try:
        import requests
    except ImportError:
        return result

    session = requests.Session()
    session.headers["User-Agent"] = "seminar-vault/0.1 (course reading manager)"

    for entry in (r for s in parsed.sessions for r in s.readings):
        citation = entry.citation

        if not citation.parsed:
            if not rescue or not worth_rescuing(citation.raw):
                continue
            result.looked_up += 1
            suggestion = _crossref_rescue(session, citation.raw, cache_dir)
            if suggestion:
                citation.suggestion = suggestion
                result.suggested += 1
            continue

        if citation.confidence >= 0.99:
            continue
        record = None
        if citation.doi:
            record = _crossref_doi(session, citation.doi, cache_dir)
        elif citation.work_type in {"journal_article", "book_chapter"} and citation.title and citation.authors:
            record = _crossref_search(session, citation, cache_dir)
        elif citation.work_type == "book" and citation.title:
            record = _openlibrary(session, citation, cache_dir)
        if not record:
            continue
        result.filled += _fill(citation, record)

    return result


def _cache_path(cache_dir: Path, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return cache_dir / "lookups" / f"{digest}.json"


def _cached_get(session, url: str, cache_dir: Path) -> dict | None:
    path = _cache_path(cache_dir, url)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    try:
        response = session.get(url, timeout=TIMEOUT)
        time.sleep(PAUSE)
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _crossref_doi(session, doi: str, cache_dir: Path) -> dict | None:
    data = _cached_get(session, f"https://api.crossref.org/works/{quote(doi)}", cache_dir)
    return (data or {}).get("message")


def _crossref_search(session, citation, cache_dir: Path) -> dict | None:
    author = citation.authors[0].surname or citation.authors[0].literal
    query = quote(f"{citation.title} {author}")
    url = f"https://api.crossref.org/works?rows=3&query.bibliographic={query}"
    data = _cached_get(session, url, cache_dir)
    for item in ((data or {}).get("message") or {}).get("items", []):
        if _plausible(citation, item):
            return item
    return None


def _plausible(citation, item: dict) -> bool:
    """require year and title agreement before trusting a search hit."""
    year = None
    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    if issued and issued[0]:
        year = issued[0][0]
    if citation.year and year and abs(citation.year - year) > 1:
        return False
    titles = item.get("title") or []
    if not titles:
        return False
    a = re.sub(r"[^a-z0-9 ]", "", (citation.title or "").lower())
    b = re.sub(r"[^a-z0-9 ]", "", titles[0].lower())
    a_words, b_words = set(a.split()), set(b.split())
    if not a_words:
        return False
    return len(a_words & b_words) / len(a_words) > 0.6


_SELECT = "title,author,container-title,issued,volume,issue,page,DOI,URL,publisher,type"


def _crossref_rescue(session, raw: str, cache_dir: Path) -> Suggestion | None:
    query = quote(collapse_whitespace(raw)[:300])
    url = (
        f"https://api.crossref.org/works?rows={RESCUE_ROWS}"
        f"&select={_SELECT}&query.bibliographic={query}"
    )
    data = _cached_get(session, url, cache_dir)
    for item in ((data or {}).get("message") or {}).get("items", []):
        suggestion = rescue_from_item(raw, item)
        if suggestion:
            return suggestion
    return None


def _openlibrary(session, citation, cache_dir: Path) -> dict | None:
    query = quote(citation.title or "")
    data = _cached_get(session, f"https://openlibrary.org/search.json?limit=3&q={query}", cache_dir)
    docs = (data or {}).get("docs") or []
    for doc in docs:
        if citation.year and doc.get("first_publish_year"):
            if abs(citation.year - doc["first_publish_year"]) > 2:
                continue
        return {
            "container-title": [],
            "publisher": (doc.get("publisher") or [None])[0],
            "DOI": None,
        }
    return None


def _fill(citation, record: dict) -> int:
    """copy fetched values into empty fields only."""
    fetched = {
        "container": (record.get("container-title") or [None])[0],
        "publisher": record.get("publisher"),
        "volume": record.get("volume"),
        "issue": record.get("issue"),
        "pages": record.get("page"),
        "doi": record.get("DOI"),
        "url": record.get("URL"),
    }
    issued = (record.get("issued") or {}).get("date-parts") or [[None]]
    if issued and issued[0]:
        fetched["year"] = issued[0][0]

    filled = 0
    for field in _FILLABLE:
        if getattr(citation, field, None):
            continue
        value = fetched.get(field)
        if value:
            setattr(citation, field, value)
            filled += 1
    if filled:
        citation.notes.append("enriched from crossref" if record.get("DOI") else "enriched from openlibrary")
    return filled
