"""brief generation, gated by the course's ai policy.

the gate runs before the adapter is even asked whether it is available, so a
prohibited course gives the same answer with or without a key configured. an
explicit override is possible, and everything it produces is watermarked as
model generated and excluded from the public build and from copy paths.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from . import db
from .llm import get_adapter, load_prompt
from .syllabus.policies import briefs_allowed

PROMPT_VERSION = "brief-1"
MAX_SOURCE_CHARS = 60_000


@dataclass
class BriefResult:
    ok: bool
    message: str
    brief_id: int | None = None


def generate_brief(conn: sqlite3.Connection, work_id: int, *, force: bool = False) -> BriefResult:
    work = conn.execute("select * from work where id = ?", (work_id,)).fetchone()
    if work is None:
        return BriefResult(False, f"no work with id {work_id}")

    course = conn.execute(
        "select c.*, (select ai_stance from course_policy p where p.course_id = c.id"
        "  and p.policy_type = 'ai_use' limit 1) as ai_stance"
        " from course c"
        " join session s on s.course_id = c.id"
        " join assigned_reading ar on ar.session_id = s.id"
        " where ar.work_id = ? limit 1",
        (work_id,),
    ).fetchone()

    stance = course["ai_stance"] if course else "unstated"
    if not briefs_allowed(stance) and not force:
        return BriefResult(
            False,
            f"course policy marks ai use as {stance}, so brief generation is disabled.\n"
            "use --force to override. an overridden brief is watermarked as model\n"
            "generated and never leaves the private build.",
        )

    chunks = list(
        conn.execute(
            "select c.page_number, c.body from chunk c"
            " join document d on d.id = c.document_id"
            " where d.work_id = ? and c.kind = 'body' order by c.ordinal",
            (work_id,),
        )
    )
    if not chunks:
        return BriefResult(False, "no ingested text for this work, so there is nothing to brief")

    adapter = get_adapter()
    if not adapter.available:
        return BriefResult(
            False,
            "not generated: no model is configured. everything else works without one;"
            " set VAULT_LLM_PROVIDER and a key to enable briefs.",
        )

    source = []
    used = 0
    for chunk in chunks:
        piece = f"[p. {chunk['page_number']}] {chunk['body']}"
        if used + len(piece) > MAX_SOURCE_CHARS:
            break
        source.append(piece)
        used += len(piece)

    prompt = load_prompt("brief").split("---", 1)[-1].format(
        citation=work["rendered_citation"] or work["raw_source_text"],
        course_code=course["code"] if course else "unknown",
        pages=len(chunks),
        text="\n\n".join(source),
    )

    completion = adapter.complete(prompt, max_tokens=2500)
    if not completion.generated:
        return BriefResult(False, f"not generated: {completion.reason}")

    conn.execute("delete from brief where work_id = ?", (work_id,))
    brief_id = conn.execute(
        "insert into brief (work_id, course_id, generated_by, prompt_version, body, markdown)"
        " values (?, ?, ?, ?, ?, ?)",
        (
            work_id,
            course["id"] if course else None,
            f"model:{completion.model}",
            PROMPT_VERSION,
            json.dumps({}),
            completion.text,
        ),
    ).lastrowid
    conn.commit()

    watermark = " (forced past a restrictive course policy)" if force and not briefs_allowed(stance) else ""
    return BriefResult(True, f"brief written for work {work_id}{watermark}", brief_id)
