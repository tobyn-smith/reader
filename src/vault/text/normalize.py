"""string-level repair of pdf text extraction artifacts.

every function here takes a string and returns a string plus a log of what it
changed. the log matters: when a citation later turns out to be wrong, the
first question is always "did the cleanup do that, or was the pdf like that".

nothing here is destructive by default. the aggressive rules (statistical word
splitting) are opt-in per token and refuse to fire unless they are confident.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# change log


@dataclass
class Edit:
    """one change, so it can be shown next to the text it produced."""

    rule: str
    before: str
    after: str

    def __str__(self) -> str:  # pragma: no cover - debugging convenience
        return f"{self.rule}: {self.before!r} -> {self.after!r}"


@dataclass
class Cleaned:
    text: str
    edits: list[Edit] = field(default_factory=list)

    def extend(self, other: "Cleaned") -> "Cleaned":
        self.text = other.text
        self.edits.extend(other.edits)
        return self


# undecodable glyphs

# fonts with a broken or missing ToUnicode map extract as literal "(cid:NNN)".
CID_RE = re.compile(r"\(cid:\d+\)")


def strip_cid_glyphs(text: str) -> Cleaned:
    """drop (cid:NNN) runs left behind by fonts we cannot decode.

    these are almost always decorative: bullets, dingbats, section markers. a
    space replaces the glyph only when there is not already whitespace beside
    it, so stripping a bullet does not leave a double space behind.
    """
    edits: list[Edit] = []
    out: list[str] = []
    pos = 0
    for m in CID_RE.finditer(text):
        out.append(text[pos:m.start()])
        before = text[m.start() - 1] if m.start() else ""
        after = text[m.end()] if m.end() < len(text) else ""
        gap = "" if (before == "" or before.isspace() or after == "" or after.isspace()) else " "
        edits.append(Edit("cid_glyph", m.group(0), gap))
        out.append(gap)
        pos = m.end()
    out.append(text[pos:])
    return Cleaned("".join(out), edits)


# diacritics

# tex-produced pdfs emit the accent as a standalone spacing character sitting
# *before* the letter it belongs to, so "Zoltán" extracts as "Zolt" + U+00B4 + "an".
# map each spacing accent to its combining equivalent.
_SPACING_TO_COMBINING = {
    "´": "́",  # acute
    "ˊ": "́",
    "`": "̀",  # grave
    "ˋ": "̀",
    "¨": "̈",  # diaeresis
    "ˆ": "̂",  # circumflex
    "^": "̂",
    "˜": "̃",  # tilde
    "~": "̃",
    "ˇ": "̌",  # caron
    "˘": "̆",  # breve
    "˙": "̇",  # dot above
    "˝": "̋",  # double acute
    "°": "̊",  # ring above
    "˚": "̊",
    "¯": "̄",  # macron
    "ˉ": "̄",
}

# accents that trail their letter instead of leading it
_TRAILING_ACCENTS = {
    "¸": "̧",  # cedilla
    "˛": "̨",  # ogonek
}

_LEAD_ACCENT_RE = re.compile(
    "([" + "".join(re.escape(c) for c in _SPACING_TO_COMBINING) + "])([A-Za-z])"
)
_TRAIL_ACCENT_RE = re.compile(
    "([A-Za-z])([" + "".join(re.escape(c) for c in _TRAILING_ACCENTS) + "])"
)


def _compose(letter: str, combining: str) -> str | None:
    """return the precomposed character, or None if there is not one.

    the "did it collapse to a single codepoint" check is what keeps this rule
    safe. an acute accent used as a stray apostrophe in "don´t" would try to
    build "t" + combining-acute, which has no precomposed form, so we leave it
    alone rather than inventing a character.
    """
    composed = unicodedata.normalize("NFC", letter + combining)
    return composed if len(composed) == 1 else None


def compose_diacritics(text: str) -> Cleaned:
    """rebuild accented letters that extracted as accent + bare letter."""
    edits: list[Edit] = []

    def lead(m: re.Match[str]) -> str:
        accent, letter = m.group(1), m.group(2)
        composed = _compose(letter, _SPACING_TO_COMBINING[accent])
        if composed is None:
            return m.group(0)
        edits.append(Edit("diacritic", m.group(0), composed))
        return composed

    def trail(m: re.Match[str]) -> str:
        letter, accent = m.group(1), m.group(2)
        composed = _compose(letter, _TRAILING_ACCENTS[accent])
        if composed is None:
            return m.group(0)
        edits.append(Edit("diacritic", m.group(0), composed))
        return composed

    out = _LEAD_ACCENT_RE.sub(lead, text)
    out = _TRAIL_ACCENT_RE.sub(trail, out)
    return Cleaned(out, edits)


# ligatures and unicode form

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Œ": "OE",
    "œ": "oe",
    "Æ": "AE",
    "æ": "ae",
}

# characters that carry no meaning for us but break naive matching
_INVISIBLE = dict.fromkeys(
    [
        "​",  # zero width space
        "‌",
        "‍",
        "﻿",
        "­",  # soft hyphen
    ],
    "",
)

_SPACE_LIKE = dict.fromkeys(
    [" ", " ", " ", " ", " ", " ", " "], " "
)


def expand_ligatures(text: str) -> Cleaned:
    edits: list[Edit] = []
    out = []
    for ch in text:
        if ch in _LIGATURES:
            edits.append(Edit("ligature", ch, _LIGATURES[ch]))
            out.append(_LIGATURES[ch])
        else:
            out.append(ch)
    return Cleaned("".join(out), edits)


def normalize_unicode(text: str) -> Cleaned:
    """nfc, ligatures expanded, invisible and exotic spaces flattened.

    run this before anything tries to match on the text. accent composition
    happens first so nfc has something to work with.
    """
    result = Cleaned(text)
    result.extend(strip_cid_glyphs(result.text))
    result.extend(compose_diacritics(result.text))
    result.extend(expand_ligatures(result.text))

    swapped = result.text.translate(str.maketrans({**_INVISIBLE, **_SPACE_LIKE}))
    if swapped != result.text:
        result.edits.append(Edit("invisible_chars", "", ""))
        result.text = swapped

    result.text = unicodedata.normalize("NFC", result.text)
    return result


# dashes

_DASHES = "‐‑‒–—−"
# a dash between two numbers is a range and should parse as a plain hyphen.
_NUMERIC_RANGE_RE = re.compile(r"(\d)\s*[" + _DASHES + r"]\s*(\d)")
# same for a dash between two capitalised name parts
_WORD_RANGE_RE = re.compile(r"([A-Za-z])[" + _DASHES + r"]([A-Za-z])")


def normalize_dashes_for_parsing(text: str) -> Cleaned:
    """turn typographic dashes into hyphens so ranges compare equal.

    display text keeps the original dash. only the parsing copy gets this, which
    is why it is a separate function rather than part of normalize_unicode.
    """
    edits: list[Edit] = []

    def sub(m: re.Match[str]) -> str:
        replacement = f"{m.group(1)}-{m.group(2)}"
        edits.append(Edit("dash_range", m.group(0), replacement))
        return replacement

    out = _NUMERIC_RANGE_RE.sub(sub, text)
    out = _WORD_RANGE_RE.sub(sub, out)
    return Cleaned(out, edits)


# urls

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\]}]+", re.IGNORECASE)

# a url that ran off the end of a line. the trailing hyphen is part of the url,
# so it is kept and no space is inserted.
_URL_LINEBREAK_RE = re.compile(
    r"((?:https?://|www\.)[^\s<>\"']*?)[ \t]*\n[ \t]*([^\s<>\"']+)", re.IGNORECASE
)


def rejoin_wrapped_urls(text: str) -> Cleaned:
    """glue urls back together after a line break.

    only fires when the fragment on the next line looks like a url tail: no
    spaces, and not the start of a new sentence or citation.
    """
    edits: list[Edit] = []

    def sub(m: re.Match[str]) -> str:
        head, tail = m.group(1), m.group(2)
        if not _looks_like_url_tail(head, tail):
            return m.group(0)
        joined = head + tail
        edits.append(Edit("url_wrap", m.group(0), joined))
        return joined

    out = text
    # a single url can wrap over more than two lines, so keep going until stable
    for _ in range(6):
        new = _URL_LINEBREAK_RE.sub(sub, out)
        if new == out:
            break
        out = new
    return Cleaned(out, edits)


def _looks_like_url_tail(head: str, tail: str) -> bool:
    # a capitalised word starting a new sentence is not a url tail
    if re.match(r"^[A-Z][a-z]{2,}\b", tail) and not head.endswith(("-", "/", "=", "&", "_", "?")):
        return False
    # bullets and citation markers end the url
    if tail[:1] in {"•", "●", "-", "*"} and len(tail) > 1 and tail[1] == " ":
        return False
    return True


def close_url_spaces(text: str) -> Cleaned:
    """remove spaces that kerning injected into the middle of a url.

    the giveaway is a space inside a run that is otherwise a url and whose next
    fragment continues the same path: no protocol, no capital start, and the
    piece before the space ends mid-path.
    """
    edits: list[Edit] = []

    out = text

    def fix_one(m: re.Match[str]) -> str:
        # the space stands in for a hyphen that the text layer lost at a wrap
        # point. both sides are slug shaped, so a hyphen is what belongs here.
        # logged, because a repaired url that is wrong is worse than an obvious
        # broken one.
        whole, left, right = m.group(0), m.group(1), m.group(2)
        joined = f"{left}-{right}"
        edits.append(Edit("url_space", whole, joined))
        return joined

    # ".../some-slug more-slug" -> ".../some-slug-more-slug"
    pattern = re.compile(
        r"((?:https?://|www\.)[^\s<>\"']*[a-z0-9])[ \t]+([a-z0-9][^\s<>\"']*)", re.IGNORECASE
    )
    for _ in range(6):
        new = pattern.sub(lambda m: fix_one(m) if _url_space_is_bogus(m) else m.group(0), out)
        if new == out:
            break
        out = new
    return Cleaned(out, edits)


def _url_space_is_bogus(m: re.Match[str]) -> bool:
    """decide whether a space inside a url is an artifact or a real boundary."""
    left, right = m.group(1), m.group(2)
    # the tail has to look like more path, not prose
    if not re.match(r"^[a-z0-9][a-z0-9._~%/-]*$", right, re.IGNORECASE):
        return False
    # prose after a url is usually a real word; path fragments in these files
    # carry a hyphen or a slash
    if not re.search(r"[-/._]", right):
        return False
    # a left side that already ended the url (trailing punctuation) is done
    if left.endswith((".", ",", ";")):
        return False
    return True


# hyphenation across line breaks


class Lexicon:
    """word list used to decide whether a repair is safe.

    backed by wordninja's frequency table when it is installed. if it is not,
    every lookup returns False, which makes the risky rules refuse to fire.
    that is the behaviour we want: no dictionary means no guessing.
    """

    def __init__(self) -> None:
        self._words: set[str] = set()
        try:
            import wordninja

            model = wordninja.DEFAULT_LANGUAGE_MODEL
            self._words = set(getattr(model, "_wordcost", {}))
            self._split = wordninja.split
        except Exception:  # pragma: no cover - only when wordninja is absent
            self._split = None

    @property
    def available(self) -> bool:
        return bool(self._words)

    def knows(self, word: str) -> bool:
        return word.strip(".,;:()[]’'\"").lower() in self._words

    def split(self, token: str) -> list[str]:
        if self._split is None:
            return [token]
        return self._split(token)


_LEXICON: Lexicon | None = None


def lexicon() -> Lexicon:
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = Lexicon()
    return _LEXICON


_HYPHEN_BREAK_RE = re.compile(r"(\w+)-[ \t]*\n[ \t]*(\w+)")


def dehyphenate_linebreaks(text: str) -> Cleaned:
    """rejoin words split by a hyphen at end of line.

    the hard part is not splitting genuine compounds. three guards:
      * a capitalised continuation keeps its hyphen (surnames, place names)
      * a continuation that makes a known word without the hyphen loses it
      * anything else keeps the hyphen, because a wrong join is harder to spot
        than a stray hyphen
    urls are handled before this runs, so they never reach here.
    """
    edits: list[Edit] = []
    lex = lexicon()

    def sub(m: re.Match[str]) -> str:
        head, tail = m.group(1), m.group(2)
        if tail[:1].isupper():
            joined = f"{head}-{tail}"
            edits.append(Edit("hyphen_compound_kept", m.group(0), joined))
            return joined
        merged = head + tail
        if lex.knows(merged):
            edits.append(Edit("hyphen_rejoin", m.group(0), merged))
            return merged
        if lex.available and lex.knows(f"{head}-{tail}"):
            joined = f"{head}-{tail}"
            edits.append(Edit("hyphen_compound_kept", m.group(0), joined))
            return joined
        # unknown either way. line-break hyphenation is far more common in
        # justified academic pdfs than a compound breaking exactly at its hyphen.
        edits.append(Edit("hyphen_rejoin_unverified", m.group(0), merged))
        return merged

    out = _HYPHEN_BREAK_RE.sub(sub, text)
    return Cleaned(out, edits)


# missing inter-word spaces

# a comma or period that lost its trailing space. the character before the
# comma may itself be a period, as in a run-together "R.,and".
_COMMA_RUN_RE = re.compile(r"([a-zà-ɏ.]),(?=[A-Za-z])")
# a period between a real word and a capitalised word. requires three lowercase
# letters in front so initials ("R.Smith") and "e.g.Foo" are left alone.
_PERIOD_RUN_RE = re.compile(r"([a-zà-ɏ]{3,})\.(?=[A-Z][a-zà-ɏ])")
_CAMEL_RE = re.compile(r"(?<=[a-zà-ɏ])(?=[A-Z])")

# below this length an all-lowercase run is more likely a real word than a
# kerning failure, so the statistical splitter leaves it alone
MIN_SPLIT_LENGTH = 12

# surname particles that legitimately carry an internal capital. splitting these
# would turn one name into two.
_NAME_PREFIXES = {
    "mc", "mac", "de", "di", "da", "del", "della", "van", "von", "der",
    "le", "la", "du", "des", "st", "o",
}


def space_after_punctuation(text: str) -> Cleaned:
    """insert the space after a comma or period that kerning dropped.

    never fires inside a url. decimals and thousands separators are untouched
    because both rules require letters on the relevant side.
    """
    edits: list[Edit] = []
    spans = [m.span() for m in URL_RE.finditer(text)]

    def inside_url(pos: int) -> bool:
        return any(start <= pos < end for start, end in spans)

    def comma(m: re.Match[str]) -> str:
        if inside_url(m.start()):
            return m.group(0)
        out = m.group(1) + ", "
        edits.append(Edit("comma_space", m.group(0), out))
        return out

    def period(m: re.Match[str]) -> str:
        if inside_url(m.start()):
            return m.group(0)
        out = m.group(1) + ". "
        edits.append(Edit("period_space", m.group(0), out))
        return out

    result = _COMMA_RUN_RE.sub(comma, text)
    result = _PERIOD_RUN_RE.sub(period, result)
    return Cleaned(result, edits)


def split_camel_token(token: str) -> list[str] | None:
    """break a token at lower-to-upper boundaries, or None if unsafe.

    the case transition is a real signal rather than a guess, so this does not
    need dictionary backing the way the statistical splitter does. it refuses
    on surname particles ("McDonald") and on a trailing lone capital after a
    short stem ("PhD"), which are the two ways the signal lies.
    """
    pieces = [p for p in _CAMEL_RE.split(token) if p]
    if len(pieces) < 2:
        return None
    for i, piece in enumerate(pieces[:-1]):
        if piece.lower() in _NAME_PREFIXES:
            return None
        # "PhD" style: short stem followed by a lone capital
        if len(piece) < 3 and len(pieces[i + 1]) == 1:
            return None
    if len(pieces[0]) < 2:
        return None
    return pieces


def restore_spaces(text: str, min_length: int = MIN_SPLIT_LENGTH) -> Cleaned:
    """recover inter-word spaces lost to kerning.

    two mechanisms, deliberately kept apart:

    camelCase boundaries are trusted. a lower-to-upper transition inside a
    single token does not happen in correctly spaced text, so splitting there
    recovers author lists without inventing anything.

    statistical splitting is not trusted. it only runs on all-lowercase runs of
    at least min_length that the lexicon does not recognise, and the result is
    thrown away unless every piece is itself a known word. without that gate it
    shreds surnames.

    every split is logged either way.
    """
    lex = lexicon()
    edits: list[Edit] = []
    url_spans = [m.span() for m in URL_RE.finditer(text)]

    def inside_url(pos: int) -> bool:
        return any(start <= pos < end for start, end in url_spans)

    def handle(m: re.Match[str]) -> str:
        token = m.group(0)
        if inside_url(m.start()) or len(token) < 4 or lex.knows(token):
            return token

        pieces = split_camel_token(token) or [token]
        expanded: list[str] = []
        for piece in pieces:
            expanded.extend(_statistical_split(piece, lex, min_length))

        if len(expanded) < 2:
            return token
        joined = " ".join(expanded)
        edits.append(Edit("word_split", token, joined))
        return joined

    out = re.sub(r"[A-Za-zÀ-ɏ]+", handle, text)
    return Cleaned(out, edits)


def _statistical_split(piece: str, lex: Lexicon, min_length: int) -> list[str]:
    """wordninja, but only where it is safe and only if it convinces us."""
    if len(piece) < min_length or lex.knows(piece):
        return [piece]
    # only all-lowercase runs. a capital anywhere means camel splitting already
    # had its say and this is a proper noun.
    if not piece[1:].islower():
        return [piece]
    candidate = lex.split(piece)
    if len(candidate) < 2 or not _split_is_confident(candidate, lex):
        return [piece]
    return candidate


# the only one and two letter pieces allowed inside an accepted split. the
# frequency list knows plenty of junk two letter "words" ("al", "ed", "un"),
# and any of them slipping through turns a rare real word into two fragments.
_SHORT_WORDS = {
    "a", "i", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in",
    "is", "it", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we",
}


def _split_is_confident(pieces: list[str], lex: Lexicon) -> bool:
    """accept a statistical split only when every piece is a real word."""
    if not lex.available:
        return False
    for piece in pieces:
        lowered = piece.lower()
        if len(piece) <= 2:
            if lowered not in _SHORT_WORDS:
                return False
        elif not lex.knows(piece):
            return False
    return True


# leading markers

# a symbol-font bullet often extracts as one stray letter. the pattern only
# strips it when what follows is clearly a heading or list item, so real words
# are never eaten.
_MARKER_RE = re.compile(
    r"^[ \t]*(?:\(cid:\d+\)|[•▪●◦‣⁃⧫◆◇∗*?–—−-]|(?<![A-Za-z])[a-zA-Z](?=\s))\s+"
)


def strip_leading_marker(line: str) -> tuple[str, str | None]:
    """remove a list marker from the front of a line.

    returns (line without marker, the marker) so callers can tell a bulleted
    line from a continuation line. that distinction is what lets a citation
    that wraps over four lines be reassembled correctly.
    """
    m = _MARKER_RE.match(line)
    if not m:
        return line, None
    marker = m.group(0).strip()
    return line[m.end():], marker or None


# top level


def clean_page_text(text: str, *, aggressive_spacing: bool = True) -> Cleaned:
    """the standard pipeline for a single page of extracted text.

    order matters. urls are repaired before hyphenation so a wrapped url is not
    mistaken for a hyphenated word, and unicode is normalised first so every
    later rule sees composed characters.
    """
    result = Cleaned(text)
    result.extend(normalize_unicode(result.text))
    result.extend(rejoin_wrapped_urls(result.text))
    result.extend(close_url_spaces(result.text))
    result.extend(dehyphenate_linebreaks(result.text))
    result.extend(space_after_punctuation(result.text))
    if aggressive_spacing:
        result.extend(restore_spaces(result.text))
    return result


def parsing_form(text: str) -> str:
    """the copy used for matching. display text keeps its original dashes."""
    return normalize_dashes_for_parsing(text).text


def collapse_whitespace(text: str) -> str:
    """flatten any run of whitespace, newlines included.

    a citation that wrapped over four lines has to become one string before it
    can be matched, so this deliberately crosses line boundaries.
    """
    return re.sub(r"\s+", " ", text).strip()
