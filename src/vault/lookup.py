"""deciding whether a looked-up record really is the line in the syllabus.

this module does no fetching. it takes a record someone else retrieved and
answers one question: is this the same work the syllabus was pointing at. that
split matters because the browser build must not open a connection from python,
so the app layer does the request and this does the judging, and both paths get
identical answers from identical code.

the bar is deliberately high. a line reaches a lookup precisely because every
deterministic pattern failed on it, so a search result is a hypothesis, not
evidence. a rescue that accepts a near miss is worse than no rescue: the row
stops being flagged for review and a wrong citation travels onward looking
exactly like a right one.
"""

from __future__ import annotations

import re

from .syllabus.citations import (
    BOOK,
    BOOK_CHAPTER,
    JOURNAL_ARTICLE,
    REPORT,
    UNKNOWN,
    Suggestion,
)

# a rescued title has to be substantially present in the syllabus line, and be
# long enough that the overlap means something. three words of a six word title
# is a coincidence, so the bar is a proportion with a floor under the length.
#
# the bar sits at 0.9 because it was measured. at 0.7 roughly three quarters of
# what came back was wrong: schedule fragments matched papers that happened to
# share vocabulary, and book titles matched published reviews of the book rather
# than the book. moving to near total title agreement, the first author rather
# than any of the first three, and a year in the line to corroborate against,
# left every remaining match correct. the recall cost is real and accepted,
# because a wrong citation that stops being flagged is the one failure this
# whole tool exists to avoid.
MIN_TITLE_WORDS = 3
MIN_TITLE_COVER = 0.9

_STOPWORDS = {
    "the", "a", "an", "of", "and", "in", "on", "for", "to", "from", "with",
    "at", "by", "as", "or", "its", "their", "this", "that", "how", "why",
}

_TYPE_MAP = {
    "journal-article": JOURNAL_ARTICLE,
    "book-chapter": BOOK_CHAPTER,
    "book-part": BOOK_CHAPTER,
    "book": BOOK,
    "monograph": BOOK,
    "edited-book": BOOK,
    "reference-book": BOOK,
    "report": REPORT,
    "report-component": REPORT,
}

_BARE_URL = re.compile(r"^\S*https?://\S+$", re.IGNORECASE)
_NON_READING = re.compile(
    r"^\s*(tba|tbd|none|no reading|readings? tba|handout|in class|"
    r"see (the )?(elc|course site|website|syllabus)|"
    r"to be (announced|assigned|determined))\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_QUOTED_TITLE = re.compile(r"[\"“][^\"”]{12,}[\"”]")
_AUTHORISH = re.compile(r"[A-Z][a-z]+,\s*[A-Z]|[A-Z]\.\s*[A-Z]?\.?\s*[A-Z][a-z]+|&|et al")

# a container that is a reference work or a review venue rather than the work
# itself. crossref indexes reviews under the reviewed book's exact title, so
# without this a book match lands on somebody's review of it.
_REFERENCE_CONTAINER = re.compile(
    r"\b(who's who|year ?book|guide|a to z|encyclopa?edia|dictionary|"
    r"companion|handbook of|abstracts|index)\b",
    re.IGNORECASE,
)


def worth_rescuing(raw: str) -> bool:
    """does this line even look like a bibliographic reference.

    this is the filter that matters most, and not for the reason it was written.
    it was meant to save requests. measured on real syllabi it turned out that
    only a sixth of the lines that reach here look like citations at all: the
    rest are schedule fragments, topic labels and prose that leaked into a
    reading list. a lookup service answers every question it is asked, so
    sending those produces confident nonsense. a year and some sign of an author
    or a quoted title is the cheapest way to tell a reference from a sentence.
    """
    text = (raw or "").strip()
    if len(text) < 25:
        return False
    if _BARE_URL.match(text) or _NON_READING.match(text):
        return False
    if len(words(text)) < 4:
        return False
    quoted = bool(_QUOTED_TITLE.search(text))
    if not _YEAR.search(text) and not quoted:
        return False
    return quoted or bool(_AUTHORISH.search(text))


def rescue_from_item(raw: str, item: dict) -> Suggestion | None:
    """decide whether a crossref record really is the line printed in the syllabus.

    crossref returns a relevance score, but it ranks within one query and means
    nothing between queries, so a threshold on it would be a threshold on
    nothing. the gate is agreement instead, on four things at once, because each
    one alone lets something through that was seen going wrong on real syllabi.
    """
    titles = [t for t in (item.get("title") or []) if t]
    if not titles:
        return None
    title_words = words(titles[0])
    if len(title_words) < MIN_TITLE_WORDS:
        return None

    # near total title agreement. a partial overlap is what a keyword search
    # returns for any line sharing vocabulary with a real paper.
    cover = len(title_words & words(raw)) / len(title_words)
    if cover < MIN_TITLE_COVER:
        return None

    # the first author, not any of them. a review lists the reviewer first and
    # the reviewed author later, so allowing a later position matched reviews.
    lowered = (raw or "").lower()
    surnames = [a.get("family", "") for a in (item.get("author") or []) if a.get("family")]
    if surnames and surnames[0].lower() not in lowered:
        return None

    # a year in the line to corroborate against. with no year there is nothing
    # holding the match to this particular work, or this particular edition.
    year = year_of(item)
    stated = [int(y) for y in _YEAR.findall(raw)]
    if not stated:
        return None
    if year and all(abs(year - value) > 1 for value in stated):
        return None

    container = (item.get("container-title") or [None])[0] or ""
    if _REFERENCE_CONTAINER.search(container):
        return None

    fields = fields_of(item, year)
    return Suggestion(
        source="crossref",
        display=display_of(fields),
        title_cover=cover,
        fields=fields,
    )


def words(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return {w for w in cleaned.split() if len(w) > 2 and w not in _STOPWORDS}


def year_of(item: dict) -> int | None:
    parts = (item.get("issued") or {}).get("date-parts") or [[None]]
    if parts and parts[0] and isinstance(parts[0][0], int):
        return parts[0][0]
    return None


def fields_of(item: dict, year: int | None) -> dict:
    authors = []
    for author in item.get("author") or []:
        if author.get("family"):
            authors.append({"surname": author["family"], "given": author.get("given", "")})
        elif author.get("name"):
            authors.append({"literal": author["name"]})
    return {
        "authors": authors,
        "title": (item.get("title") or [None])[0],
        "container": (item.get("container-title") or [None])[0],
        "publisher": item.get("publisher"),
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("page"),
        "doi": item.get("DOI"),
        "url": item.get("URL"),
        "year": year,
        "work_type": _TYPE_MAP.get(item.get("type") or "", UNKNOWN),
    }


def display_of(fields: dict) -> str:
    """a one line rendering, only ever shown next to the source text in review."""
    names = ", ".join(
        a.get("surname") or a.get("literal", "") for a in fields.get("authors") or []
    )
    head = [bit for bit in (names, str(fields["year"]) if fields.get("year") else "") if bit]
    line = " ".join(head)
    if fields.get("title"):
        line = f"{line}. {fields['title']}" if line else fields["title"]
    tail = fields.get("container") or fields.get("publisher")
    if tail:
        line += f". {tail}"
    if fields.get("volume"):
        line += f" {fields['volume']}"
        if fields.get("issue"):
            line += f".{fields['issue']}"
    if fields.get("pages"):
        line += f": {fields['pages']}"
    return line
