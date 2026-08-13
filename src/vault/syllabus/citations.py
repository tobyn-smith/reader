"""citation parsing as an ordered set of patterns.

each pattern records its own name on the row it produces, so it is always
possible to ask "which rule produced this and what did it match on". anything no
pattern claims is returned unparsed for review rather than guessed at, because a
citation that is quietly wrong costs more than one that is obviously missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..text.normalize import URL_RE, collapse_whitespace, parsing_form

JOURNAL_ARTICLE = "journal_article"
BOOK = "book"
BOOK_CHAPTER = "book_chapter"
REPORT = "report"
NEWS_ARTICLE = "news_article"
WEB_PAGE = "web_page"
GOVERNMENT_DOCUMENT = "government_document"
UNKNOWN = "unknown"


@dataclass
class Author:
    surname: str = ""
    given: str = ""
    literal: str = ""

    def as_dict(self) -> dict[str, str]:
        if self.literal:
            return {"literal": self.literal}
        return {"surname": self.surname, "given": self.given}

    def display(self) -> str:
        if self.literal:
            return self.literal
        return f"{self.surname}, {self.given}".strip().rstrip(",")


@dataclass
class Suggestion:
    """a proposed reading for a line no pattern claimed.

    this is deliberately not a citation. it sits beside the unparsed row and
    waits for a person to accept it, because the line reached this point exactly
    because the deterministic rules could not read it. source and agreement are
    carried so review can show why the suggestion is being offered at all.
    """

    source: str
    display: str
    title_cover: float
    fields: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "display": self.display,
            "title_cover": round(self.title_cover, 2),
            "fields": self.fields,
        }


@dataclass
class Citation:
    raw: str
    authors: list[Author] = field(default_factory=list)
    title: str | None = None
    container: str | None = None
    publisher: str | None = None
    year: int | None = None
    year_end: int | None = None
    year_is_open: bool = False
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    url: str | None = None
    report_number: str | None = None
    work_type: str = UNKNOWN
    matched_pattern: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    suggestion: Suggestion | None = None

    @property
    def parsed(self) -> bool:
        return self.matched_pattern is not None

    def accept_suggestion(self) -> bool:
        """fold an offered suggestion into this citation.

        only ever called from a confirmation step. the pattern name records that
        a lookup produced this rather than a rule, so a later reader can tell the
        two apart, and confidence stays below 1.0 because a person accepted a
        match rather than a rule proving one.
        """
        if self.suggestion is None:
            return False
        for key, value in self.suggestion.fields.items():
            if value in (None, "", []):
                continue
            if key == "authors":
                self.authors = [Author(**a) for a in value]
            else:
                setattr(self, key, value)
        self.matched_pattern = f"{self.suggestion.source}_lookup"
        self.confidence = 0.9
        self.notes.append(f"accepted from {self.suggestion.source}")
        self.suggestion = None
        return True

    def signature(self) -> str:
        surname = self.authors[0].surname or self.authors[0].literal if self.authors else ""
        title = re.sub(r"[^a-z0-9 ]", "", (self.title or "").lower())
        words = " ".join(title.split()[:6])
        return f"{surname.lower()}|{self.year or ''}|{words}".strip()


_ETAL = re.compile(r",?\s*et\.?\s+al\.?", re.IGNORECASE)
_INSTITUTIONAL = re.compile(
    r"^(the\s+)?(department|bureau|office|ministry|committee|commission|council|"
    r"secretariat|organization|organisation|institute|centre|center|agency|"
    r"world|united|national|international)\b",
    re.IGNORECASE,
)
_HONORIFIC = re.compile(r"\b(dr|prof|professor|mr|mrs|ms)\.?\s+", re.IGNORECASE)


def parse_authors(raw: str) -> list[Author]:
    """read an author list in the styles syllabi actually use.

    the first author is usually inverted and the rest are not, which is the only
    reliable structural rule available. an institutional author is kept whole,
    because splitting it into a surname and a given name produces nonsense.
    """
    text = _trim_author_tail(collapse_whitespace(raw))
    if not text:
        return []

    truncated = bool(_ETAL.search(text))
    text = _ETAL.sub("", text).strip().rstrip(",")
    text = _HONORIFIC.sub("", text)

    if _INSTITUTIONAL.match(text) and "," not in text:
        return [Author(literal=text)]

    text = re.sub(r",?\s+and\s+", "|", text)
    text = re.sub(r"\s*;\s*", "|", text)
    segments = [s.strip() for s in text.split("|") if s.strip()]
    if not segments:
        return []

    authors: list[Author] = []
    head = segments[0]
    parts = [p.strip() for p in head.split(",") if p.strip()]
    if len(parts) >= 2:
        authors.append(Author(surname=parts[0], given=parts[1]))
        # anything past the first two comma parts is a further author written
        # given name first
        for extra in parts[2:]:
            authors.append(_given_first(extra))
    elif parts:
        authors.append(_given_first(parts[0]) if " " in parts[0] else Author(surname=parts[0]))

    for segment in segments[1:]:
        for piece in [p.strip() for p in segment.split(",") if p.strip()]:
            authors.append(_given_first(piece))

    if truncated:
        authors.append(Author(literal="et al."))
    return authors


def _trim_author_tail(text: str) -> str:
    """drop a trailing separator without eating the period on an initial."""
    text = text.strip().rstrip(",")
    if text.endswith(".") and not re.search(r"\b[A-Z]\.$", text):
        text = text[:-1]
    return text.strip()


def _given_first(name: str) -> Author:
    name = _trim_author_tail(name)
    if _INSTITUTIONAL.match(name):
        return Author(literal=name)
    bits = name.split()
    if len(bits) == 1:
        return Author(surname=bits[0])
    return Author(surname=bits[-1], given=" ".join(bits[:-1]))


_YEAR = r"(?P<year>1[89]\d{2}|20\d{2})"
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
_QUOTED = r"[\"“‘]\s*(?P<title>.+?)\s*[\"”’]"
# pages are not always digits. supplements run "S1-S31" and online-first
# articles carry an id like "sqad032" where the page range would be.
_PAGES = r"(?P<pages>[A-Za-z]?\d+\s*[-‐-―]\s*[A-Za-z]?\d+|[A-Za-z]{0,6}\d+)"
_REPORT_NUMBER = r"(?P<report>(?:[A-Z]{1,3}\d{4,6}|[A-Z]{2,4}-\d{2,6}|Report\s+\d+))"

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;\"'<>]+)", re.IGNORECASE)


@dataclass
class Pattern:
    name: str
    regex: re.Pattern[str]
    work_type: str
    confidence: float
    # which fields this form is supposed to carry. a page range assignment has
    # no author and no year by nature, so scoring it as if it were a broken
    # journal article would push a perfectly good row into review.
    expects_author: bool = True
    expects_year: bool = True
    expects_title: bool = True


# order matters. the more structure a pattern demands, the earlier it sits, so a
# specific match is never stolen by a looser one.
PATTERNS: list[Pattern] = [
    Pattern(
        "dated_report_with_number",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+(?P<date>" + _MONTH + r"\s+\d{1,2},?\s*" + _YEAR + r")\.?\s*"
            + _QUOTED + r"[.,]?\s*" + _REPORT_NUMBER + r"[.,]?\s*(?P<container>[^,]+)",
            re.IGNORECASE | re.DOTALL,
        ),
        GOVERNMENT_DOCUMENT,
        0.9,
    ),
    Pattern(
        "dated_news_with_url",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+(?P<date>" + _MONTH + r"\s+\d{1,2},?\s*" + _YEAR + r")\.?\s*"
            + _QUOTED + r"[.,]?\s*(?P<container>[^:]+?)\s*:\s*(?P<url>https?://\S+)",
            re.IGNORECASE | re.DOTALL,
        ),
        NEWS_ARTICLE,
        0.9,
    ),
    Pattern(
        "dated_agency_document",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+(?P<date>" + _MONTH + r"\s+\d{1,2},?\s*" + _YEAR + r")\.?\s*"
            + _QUOTED + r"[.,]?\s*(?P<container>[^,]+)",
            re.IGNORECASE | re.DOTALL,
        ),
        REPORT,
        0.75,
    ),
    Pattern(
        # the same agency-report shape without quotes and often without a day:
        # "Halvorsen, Brendan W. December 2022. Defense Primer: PPBE Process.
        # Congressional Research Service." grad policy courses assign these by
        # the dozen.
        "dated_unquoted_report",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+(?P<date>" + _MONTH + r"\s+(?:\d{1,2},?\s*)?" + _YEAR + r")\.\s*"
            r"(?P<title>[^\"“]{6,140}?)\.\s*(?P<container>[A-Z][^.]{3,60})[.,]?\s*$",
            re.IGNORECASE | re.DOTALL,
        ),
        REPORT,
        0.75,
    ),
    Pattern(
        # a federal regulation, cited the way the eCFR site titles itself:
        # "eCFR :: 15 CFR Part 774 -- The Sample Control List". the part
        # number is the identity; the name may sit before or after it.
        "cfr_citation",
        re.compile(
            r"^(?:(?P<title>.+?)\s+)?e?CFR\s*::\s*"
            r"(?P<report>\d{1,2}\s+CFR\s+Part\s+\d{1,4})\s*(?:--|[-–—])?\s*(?P<tail>.*)$",
            re.IGNORECASE,
        ),
        GOVERNMENT_DOCUMENT,
        0.8,
        expects_year=False,
        expects_title=False,
    ),
    Pattern(
        "author_date_chapter",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+" + _YEAR + r"\.\s*" + _QUOTED +
            r"[.,]?\s*In\s+(?P<container>.+?)[.,]\s*"
            r"(?:(?P<chapters>Chapters?\s+[\d‐-―\s-]+)[.,]\s*)?"
            r"(?:(?P<city>[A-Z][A-Za-z .]+):\s*(?P<publisher>[^.]+))?\.?\s*$",
            re.IGNORECASE | re.DOTALL,
        ),
        BOOK_CHAPTER,
        0.9,
    ),
    Pattern(
        "author_date_journal",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+" + _YEAR + r"\.\s*" + _QUOTED +
            # a comma between the journal name and its volume is as common as
            # no comma, and the page range is often absent entirely
            r"[.,]?\s*(?!In\s)(?P<container>[A-Za-z][^\d]*?)\s*,?\s*"
            r"(?P<volume>\d+)\s*(?:\((?P<issue>[^)]+)\))?"
            r"(?:\s*[:,]\s*" + _PAGES + r")?",
            re.IGNORECASE | re.DOTALL,
        ),
        JOURNAL_ARTICLE,
        0.95,
    ),
    Pattern(
        "author_date_unquoted_journal",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+" + _YEAR + r"\.\s*(?P<title>[^\"“]{6,140}?)\.\s*"
            r"(?P<container>[A-Z][^\d]*?)\s*,?\s*"
            r"(?P<volume>\d+)\s*(?:\((?P<issue>[^)]+)\))?\s*[:,]\s*" + _PAGES,
            re.DOTALL,
        ),
        JOURNAL_ARTICLE,
        0.8,
    ),
    Pattern(
        "series_entry_open_ended",
        re.compile(
            r"^(?P<authors>.+?)\.\s*" + _QUOTED + r"\.?\s*In\s+(?P<container>.+?)\.\s*"
            r"(?P<city>[A-Z][A-Za-z .]+):\s*(?P<publisher>.+?),\s*"
            r"(?P<year>\d{4})\s*[‐-―-]\s*(?P<year_end>\d{4})?\.?",
            re.DOTALL,
        ),
        WEB_PAGE,
        0.85,
    ),
    Pattern(
        "web_resource_in_site",
        re.compile(
            r"^(?P<authors>.+?),\s*" + _QUOTED + r",?\s*in\s+(?P<container>[^,]+?)"
            r"(?:,\s*(?P<extra>[^,]*?))?,?\s*(?P<url>https?://\S+)",
            re.IGNORECASE | re.DOTALL,
        ),
        WEB_PAGE,
        0.8,
        expects_year=False,
    ),
    Pattern(
        # humanities syllabi put the year at the end rather than after the
        # author: "Halvorsen, John and Simon Tomas Berg. The European Union: A Very
        # Short Introduction. Oxford: Oxford University Press, 2018, chapter 3."
        "book_year_last",
        re.compile(
            r"^(?P<authors>.+?)\s*(?:\(eds?\.?\))?[.,]\s*"
            r"(?P<title>[^.]{6,140})\.\s*"
            # a multi-place imprint: "New York, etc:", "New Haven; London:".
            # the comma and semicolon were outside the city class and failed
            # the whole pattern on two real book readings.
            r"(?P<city>[A-Z][A-Za-z .'-]{2,30}"
            r"(?:\s*[;,]\s*(?:etc\.?|[A-Z][A-Za-z .'-]{2,30})){0,2}):\s*"
            r"(?P<publisher>[^,]{2,60}),\s*"
            + _YEAR
            + r"(?:[,.]\s*(?P<edition>[^,.]{0,24}edition))?"
            r"(?:[,.]\s*(?P<chapters>chapters?\s+[\d\s,and-]+))?",
            re.IGNORECASE | re.DOTALL,
        ),
        BOOK,
        0.85,
    ),
    Pattern(
        "author_date_book",
        re.compile(
            r"^(?P<authors>.+?)\.?\s+" + _YEAR + r"\.\s*(?P<title>[^\"“]+?)\.\s*"
            r"(?P<city>[A-Z][A-Za-z .]+):\s*(?P<publisher>[^.]+?)[.,]?\s*"
            r"(?:(?P<chapters>chapters?\s+[\d‐-―\s-]+))?\.?\s*$",
            re.DOTALL,
        ),
        BOOK,
        0.75,
    ),
    Pattern(
        # the set text named by chapter number in parens, or bare surname:
        # "Okonkwo (12) in Comparative Politics." and "Berg in European
        # Politics." and "Hine in Hale & Osei". one course wrote half its
        # reading list this way. capitals are load bearing, so no IGNORECASE.
        "chapter_in_container",
        re.compile(
            r"^(?P<authors>[A-Z][\w'’-]+(?:\s*\(\d{1,3}\))?"
            r"(?:\s*(?:,|and|&)\s*[A-Z][\w'’-]+(?:\s*\(\d{1,3}\))?)*)"
            r"\s+in\s+(?P<container>[A-Z].{2,60}?)\s*\.?\s*$",
        ),
        BOOK_CHAPTER,
        0.7,
        expects_year=False,
        expects_title=False,
    ),
    Pattern(
        # a course with one set text refers to it in shorthand all term:
        # "Okonkwo and Osei, Chapter 1", and terser still "NRC Ch 3 & 4"
        # where the comma never appears and chapters come in pairs. the
        # surname or acronym is the whole citation.
        "author_short_chapter",
        re.compile(
            r"^(?P<authors>[A-Z][A-Za-z'’-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'’-]+)*)"
            r"\s*,?\s+(?P<pages>(?:chapters?|ch\.?|sections?|pp?\.|pages?)\s*"
            r"[\d][\d.,\s&-]*(?:and\s*[\d.]+)?)\s*\.?\s*$",
            re.IGNORECASE,
        ),
        BOOK_CHAPTER,
        0.7,
        expects_year=False,
        expects_title=False,
    ),
    Pattern(
        # the same shorthand with no author at all, where the set text is named
        # once in the front matter: "Chapter section 1.2", "Chapters 3.1, 3.2".
        "chapter_reference",
        re.compile(
            r"^(?:chapters?|ch\.?|sections?)\s*(?:sections?\s*)?"
            r"(?P<pages>[\d][\d.,\s-]*(?:\s*and\s*[\d.]+)?)\s*(?P<title>.{0,60})$",
            re.IGNORECASE,
        ),
        BOOK_CHAPTER,
        0.65,
        expects_author=False,
        expects_year=False,
        expects_title=False,
    ),
    Pattern(
        "numbered_sections_in_work",
        re.compile(
            r"^(?:Chapters?|Sections?)\s+(?P<sections>[\d.]+(?:\s*(?:and|,|&)\s*[\d.]+)*)\s*"
            r"(?P<title>.*?)\s*,?\s*in\s+(?P<container>.+?)\.?\s*$",
            re.IGNORECASE | re.DOTALL,
        ),
        BOOK_CHAPTER,
        0.7,
        expects_author=False,
        expects_year=False,
    ),
    Pattern(
        "page_range_in_work",
        re.compile(
            r"^(?:pages?|pp?\.)\s*" + _PAGES + r"\s+in\s+(?P<container>.+?)\.?\s*$",
            re.IGNORECASE | re.DOTALL,
        ),
        BOOK_CHAPTER,
        0.7,
        expects_author=False,
        expects_year=False,
        expects_title=False,
    ),
    Pattern(
        # the long tail: a quoted title, whatever came before it read as the
        # author, whatever follows read as where it appeared. museum timelines,
        # teaching sites and magazine pieces all land here. it sits last and
        # scores low, so anything with real structure is claimed first and
        # these still reach review, but with a title and an author rather than
        # a wall of raw text.
        "quoted_title_loose",
        re.compile(
            r"^(?:(?P<authors>[^\"“]{0,90}?)[,.]?\s*)?"
            + _QUOTED
            + r"[,.]?\s*(?:in\s+)?(?P<container>[^,.]{0,70})?",
            re.IGNORECASE | re.DOTALL,
        ),
        WEB_PAGE,
        0.55,
        expects_author=False,
        expects_year=False,
    ),
    Pattern(
        "titled_with_bare_url",
        re.compile(
            r"^(?P<title>.+?)\s*:?\s*(?P<url>https?://\S+)\s*$",
            re.IGNORECASE | re.DOTALL,
        ),
        WEB_PAGE,
        0.5,
        expects_author=False,
        expects_year=False,
    ),
    Pattern(
        # a book named as one, with the chapter after a semicolon or comma:
        # "Book: Hazard Analysis; Chapter 1". policy courses assign a set text
        # this way rather than by author, and every one of them was landing in
        # review as unrecognised.
        "named_book_chapter",
        re.compile(
            r"^(?:book|text|textbook)\s*:\s*(?P<title>[^;,:]{4,90})"
            r"\s*[;,:]\s*(?:chapters?|ch\.?)\s*(?P<pages>\d[\d\s,&-]*)\s*$",
            re.IGNORECASE,
        ),
        BOOK_CHAPTER,
        0.7,
        expects_author=False,
        expects_year=False,
    ),
    Pattern(
        # the short form a seminar reading list is written in, where the full
        # citation lives in a bibliography elsewhere: "Seawright & Gerring
        # (2008)", "Gibler, Miller, & Little (2016)", "Schenoni et al. (2023),
        # including Appendix B". it carries no title by nature, so it is scored
        # as the shorthand it is rather than as a broken article.
        #
        # the surnames must be capitalised and the year must close the names,
        # which is what keeps it off prose that happens to cite a year mid
        # sentence.
        # deliberately case sensitive: the capital on each surname is what
        # separates this from a sentence that cites a year in passing.
        "author_year_short",
        re.compile(
            r"^(?P<authors>[A-Z][A-Za-z'’-]+"
            r"(?:\s*(?:,\s*&|,\s*and|,|&|and)\s*"
            r"(?:[A-Z][A-Za-z'’-]+|et\s+al\.?))*"
            r"(?:\s*,?\s*et\s+al\.?)?)"
            r"\s*\(\s*" + _YEAR + r"\s*\)"
            r"(?:\s*[,.:;]?\s*(?P<pages>[Cc]h(?:apters?|s?\.?)\s*[\d\s,&-]+))?"
            r"\s*[,.]?\s*(?P<extra>[^.]{0,60})?\s*$"
        ),
        JOURNAL_ARTICLE,
        0.5,
        expects_title=False,
    ),
    Pattern(
        # a web page carrying its site in the title, the way a browser writes
        # it: "Countries and Areas | The Arms Data Project". the pipe
        # is doing real work here, so this stays narrow: nothing else in a
        # reading list uses one.
        "page_title_with_site",
        re.compile(
            r"^(?P<title>[^|]{4,110}?)\s*\|\s*(?P<container>[^|]{2,60})\s*$",
        ),
        WEB_PAGE,
        0.55,
        expects_author=False,
        expects_year=False,
    ),
]

# a line that is an instruction rather than a citation. these are recorded so a
# week is not silently short a reading, but they never become a work.
PLACEHOLDER_RE = re.compile(
    r"^\s*(?:[A-Z][\w ()/'-]{0,60}:\s*)?(?:tbd|tba|to be (?:announced|determined))\s*\.?\s*$",
    re.IGNORECASE,
)


def looks_like_placeholder(text: str) -> bool:
    return bool(PLACEHOLDER_RE.match(collapse_whitespace(text)))


def parse_citation(raw: str) -> Citation:
    text = collapse_whitespace(raw)
    citation = Citation(raw=raw)
    if not text:
        return citation

    probe = parsing_form(text)
    for pattern in PATTERNS:
        m = pattern.regex.match(probe)
        if not m:
            continue
        _fill(citation, m, pattern)
        break

    _attach_identifiers(citation, text)
    if citation.parsed:
        citation.confidence = _score(citation)
    return citation


def _fill(citation: Citation, m: re.Match[str], pattern: Pattern) -> None:
    groups = m.groupdict()
    citation.matched_pattern = pattern.name
    citation.work_type = pattern.work_type

    if groups.get("authors"):
        raw_authors = groups["authors"]
        # "Lindqvist (15) and Peters (14)" carries one chapter number per author.
        # the numbers are pages data, and left in place they wreck the name
        # split, so they are collected and stripped before parsing.
        if pattern.name == "chapter_in_container":
            numbers = re.findall(r"\((\d{1,3})\)", raw_authors)
            if numbers:
                citation.pages = "chapters " + ", ".join(numbers) if len(numbers) > 1 \
                    else "chapter " + numbers[0]
                raw_authors = re.sub(r"\s*\(\d{1,3}\)", "", raw_authors)
        citation.authors = parse_authors(raw_authors)
    if groups.get("title"):
        citation.title = collapse_whitespace(groups["title"]).strip(" ,.")
    if groups.get("container"):
        citation.container = collapse_whitespace(groups["container"]).strip(" ,.:")
    if groups.get("publisher"):
        citation.publisher = collapse_whitespace(groups["publisher"]).strip(" ,.")
    if groups.get("year"):
        citation.year = int(groups["year"])
    if groups.get("year_end"):
        citation.year_end = int(groups["year_end"])
    if groups.get("volume"):
        citation.volume = groups["volume"]
    if groups.get("issue"):
        citation.issue = groups["issue"]
    if groups.get("pages"):
        citation.pages = collapse_whitespace(groups["pages"]).replace(" ", "")
    if groups.get("report"):
        citation.report_number = groups["report"].strip()
    if groups.get("url"):
        citation.url = groups["url"].rstrip(".,;")
    if groups.get("sections"):
        citation.pages = f"sections {collapse_whitespace(groups['sections'])}"
    if groups.get("chapters"):
        citation.pages = collapse_whitespace(groups["chapters"])

    if pattern.name == "series_entry_open_ended" and not citation.year_end:
        citation.year_is_open = True

    # a cfr line may carry its name only after the part number
    if pattern.name == "cfr_citation" and not citation.title and groups.get("tail"):
        citation.title = collapse_whitespace(groups["tail"]).strip(" ,.")

    if groups.get("date") and citation.year is None:
        year = re.search(r"(1[89]\d{2}|20\d{2})", groups["date"])
        if year:
            citation.year = int(year.group(1))


def _attach_identifiers(citation: Citation, text: str) -> None:
    doi = DOI_RE.search(text)
    if doi:
        citation.doi = doi.group(1).rstrip(".,;")
    if not citation.url:
        url = URL_RE.search(text)
        if url:
            citation.url = url.group(0).rstrip(".,;)")
    if not citation.report_number:
        report = re.search(r"\b([A-Z]{1,3}\d{4,6})\b", text)
        if report:
            citation.report_number = report.group(1)


def _score(citation: Citation) -> float:
    """confidence is how much of a citation actually got filled in.

    the base is the pattern's own reliability. missing an author or a year on a
    pattern that should have produced one is what drops a row into review.
    """
    pattern = next((p for p in PATTERNS if p.name == citation.matched_pattern), None)
    if pattern is None:
        return 0.5
    base = pattern.confidence
    if pattern.expects_author and not citation.authors:
        base -= 0.2
    if pattern.expects_year and citation.year is None:
        base -= 0.2
    if pattern.expects_title and not citation.title:
        base -= 0.25
    if citation.title and len(citation.title) < 4:
        base -= 0.2
    return max(0.0, min(1.0, round(base, 3)))


def render(citation: Citation) -> str:
    """a plain rendering used when no style specific formatter applies."""
    bits: list[str] = []
    if citation.authors:
        bits.append("; ".join(a.display() for a in citation.authors))
    if citation.year:
        year = str(citation.year)
        if citation.year_is_open:
            year += "-"
        elif citation.year_end:
            year += f"-{citation.year_end}"
        bits.append(year)
    if citation.title:
        bits.append(f"“{citation.title}.”")
    if citation.container:
        bits.append(citation.container)
    if citation.volume:
        vol = citation.volume
        if citation.issue:
            vol += f"({citation.issue})"
        bits.append(vol)
    if citation.pages:
        bits.append(citation.pages)
    if citation.report_number:
        bits.append(citation.report_number)
    return ". ".join(b for b in bits if b).strip()
