"""policy blocks, kept verbatim and classified.

roughly half a syllabus is university boilerplate. none of it is deleted, but it
is labelled so the interface can collapse it and leave the handful of policies
that actually get looked up mid term in view.

the ai use policy is the one that changes what the tool will do, so it is
classified into a stance rather than just stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..text.normalize import collapse_whitespace
from .zones import FRONT_MATTER, POLICIES, REQUIREMENTS, Zone, classify_heading, is_heading

AI_USE = "ai_use"
LATE_WORK = "late_work"
ATTENDANCE = "attendance"
GRADING_SCALE = "grading_scale"
ACADEMIC_HONESTY = "academic_honesty"
BOILERPLATE = "boilerplate"
OTHER = "other"

PROHIBITED = "prohibited"
RESTRICTED = "restricted"
PERMITTED = "permitted"
UNSTATED = "unstated"


@dataclass
class Policy:
    policy_type: str
    body: str
    heading: str | None = None
    page_number: int = 0
    ai_stance: str | None = None
    confidence: float = 1.0


AI_TERMS = re.compile(
    r"\b(artificial intelligence|a\.?i\.?[- ]based|generative ai|chatgpt|"
    r"large language model|llm|copilot|gemini|claude|midjourney)\b",
    re.IGNORECASE,
)

_PROHIBITED = re.compile(
    r"\b(must not be used|may not (?:be )?use|is not (?:allowed|permitted)|"
    r"are not (?:allowed|permitted)|not be used|prohibit\w*|forbidden|"
    r"do not use|banned|will result in (?:a )?(?:failing|zero)|"
    r"considered (?:academic dishonesty|plagiarism))\b",
    re.IGNORECASE,
)
_RESTRICTED = re.compile(
    r"\b(with (?:my |the instructor.s |prior |explicit )?(?:permission|approval)|"
    r"only (?:with|when|for|if)|must (?:be )?(?:cite|disclose|acknowledge)|"
    r"must cite|must disclose|unless (?:explicitly|otherwise) (?:stated|permitted|approved)|"
    r"case[- ]by[- ]case|limited to|except)\b",
    re.IGNORECASE,
)
_PERMITTED = re.compile(
    r"\b(you (?:may|can) use|are (?:allowed|permitted|encouraged) to use|"
    r"free to use|welcome to use|encourage\w* the use)\b",
    re.IGNORECASE,
)

_BOILERPLATE_HEADINGS = re.compile(
    r"\b(ferpa|mental health|wellness|well[- ]being|land (?:and labor )?acknowledge|"
    r"disability|accommodation|title ix|covid|counseling|student care|"
    r"privacy|emergency|non[- ]discrimination|equal opportunity|"
    r"basic needs|food insecurity|veteran)\b",
    re.IGNORECASE,
)

_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (LATE_WORK, re.compile(r"\blate (?:work|submission|assignment|policy)\b", re.IGNORECASE)),
    (ATTENDANCE, re.compile(r"\b(attendance|absence|excused absence|participation policy)\b", re.IGNORECASE)),
    (GRADING_SCALE, re.compile(r"\b(grading scale|grade scale|letter grade)\b", re.IGNORECASE)),
    (
        ACADEMIC_HONESTY,
        re.compile(r"\b(academic honesty|academic integrity|honor code|plagiaris|culture of honesty|dishonesty)\b", re.IGNORECASE),
    ),
]

# blocks worth surfacing even though their heading names none of the above
_KEEP_ANYWAY = re.compile(
    r"\b(grade dispute|regrade|dispute a grad|make[- ]?up|submission format|"
    r"format requirement|extra credit)\b",
    re.IGNORECASE,
)


def classify_ai_stance(text: str) -> str:
    """read a policy paragraph and decide what it permits.

    order matters. a policy that says "unless explicitly stated, ai must not be
    used" is a prohibition with a narrow exception, not a permission, so the
    prohibition test runs first.
    """
    if not AI_TERMS.search(text):
        return UNSTATED
    if _PROHIBITED.search(text):
        return PROHIBITED
    if _RESTRICTED.search(text):
        return RESTRICTED
    if _PERMITTED.search(text):
        return PERMITTED
    return RESTRICTED


def classify_policy(heading: str | None, body: str) -> str:
    probe = f"{heading or ''} {body[:400]}"
    if AI_TERMS.search(body):
        return AI_USE
    for kind, pattern in _TYPE_PATTERNS:
        if pattern.search(probe):
            return kind
    if _BOILERPLATE_HEADINGS.search(probe):
        return BOILERPLATE
    return OTHER


def extract(zones: list[Zone]) -> list[Policy]:
    """pull labelled blocks out of the policy, front matter and requirements zones.

    policies are not confined to the section named after them: a late work rule
    often sits in the grading discussion pages earlier.
    """
    found: list[Policy] = []
    for zone in zones:
        if zone.kind not in {POLICIES, FRONT_MATTER, REQUIREMENTS}:
            continue
        for heading, body, page in _blocks(zone):
            text = collapse_whitespace(body)
            if len(text) < 30:
                continue
            kind = classify_policy(heading, text)
            if kind == OTHER and not _KEEP_ANYWAY.search(f"{heading or ''} {text}"):
                continue
            policy = Policy(
                policy_type=kind,
                body=text,
                heading=heading,
                page_number=page,
                ai_stance=classify_ai_stance(text) if kind == AI_USE else None,
            )
            found.append(policy)

    _dedupe(found)
    if not any(p.policy_type == AI_USE for p in found):
        found.append(
            Policy(
                policy_type=AI_USE,
                body="",
                heading=None,
                ai_stance=UNSTATED,
                confidence=0.5,
            )
        )
    return found


def _blocks(zone: Zone):
    """walk a zone as heading plus the prose under it."""
    heading: str | None = None
    page = zone.start_page
    buffer: list[str] = []

    for line in zone.lines:
        text = line.stripped
        if not text:
            continue
        if is_heading(line.text, starts_block=line.starts_block):
            if buffer:
                yield heading, "\n".join(buffer), page
                buffer = []
            heading = text.rstrip(":")
            page = line.page
            continue
        if not buffer:
            page = line.page
        buffer.append(text)

    if buffer:
        yield heading, "\n".join(buffer), page


def _dedupe(policies: list[Policy]) -> None:
    seen: set[str] = set()
    keep: list[Policy] = []
    for policy in policies:
        key = policy.body[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        keep.append(policy)
    policies[:] = keep


def ai_stance_of(policies: list[Policy]) -> str:
    for policy in policies:
        if policy.policy_type == AI_USE and policy.ai_stance:
            return policy.ai_stance
    return UNSTATED


def briefs_allowed(stance: str) -> bool:
    """brief generation is off by default wherever a course restricts ai use."""
    return stance in {PERMITTED, UNSTATED}
