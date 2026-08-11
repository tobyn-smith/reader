"""decide which assigned reading a pdf satisfies.

kept free of any database or pdf dependency so the command line and the browser
score matches the same way. a wrong match is quietly corrosive, so the score and
the reason are always returned alongside the answer and never hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# below this a match is reported but not applied, and the file is listed for
# manual assignment instead
THRESHOLD = 0.45

_STOP = {"the", "a", "an", "of", "and", "in", "on", "for", "to", "is", "as"}


@dataclass
class Candidate:
    id: object
    title: str | None = None
    year: int | None = None
    authors: list[dict] | None = None
    doi: str | None = None


@dataclass
class Match:
    id: object | None
    score: float
    method: str

    @property
    def accepted(self) -> bool:
        return self.id is not None


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def match_document(head: str, candidates: list[Candidate]) -> Match:
    """score a document's opening pages against every known work.

    the opening pages are where a title block sits. a doi found anywhere in them
    is decisive; otherwise title overlap carries most of the weight, with the
    author surname and the year as corroboration.
    """
    if not head.strip():
        return Match(None, 0.0, "no text")

    head_lower = head.lower()
    head_tokens = tokens(head)
    years = set(re.findall(r"\b(1[89]\d{2}|20\d{2})\b", head))

    best: object | None = None
    best_score = 0.0

    for candidate in candidates:
        if candidate.doi and candidate.doi.lower() in head_lower:
            return Match(candidate.id, 1.0, "doi found in the document")

        score = 0.0
        title_tokens = tokens(candidate.title or "")
        if title_tokens:
            score += 0.6 * len(title_tokens & head_tokens) / len(title_tokens)

        surnames = {
            (a.get("surname") or a.get("literal") or "").lower()
            for a in (candidate.authors or [])
        }
        surnames.discard("")
        if surnames and any(s in head_tokens for s in surnames):
            score += 0.25

        if candidate.year and str(candidate.year) in years:
            score += 0.15

        if score > best_score:
            best, best_score = candidate.id, score

    if best_score < THRESHOLD:
        return Match(None, round(best_score, 3), "below threshold")
    return Match(best, round(min(best_score, 1.0), 3), "author, title and year overlap")
