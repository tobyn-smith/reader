"""telling a reading list apart from everything that sits where one sits.

each guard here was written against a real shape that produced wrong output,
and each is judged on the whole document rather than the single line, because
no line can be judged alone: "The Australia Group" is an assigned resource in
one syllabus and a lecture topic in another.
"""

from __future__ import annotations

from vault.syllabus import citations as cit
from vault.syllabus.schedule import (
    ReadingEntry,
    ScheduleParse,
    SessionEntry,
    _demote_topic_outline,
    _drop_trailing_tail,
    _looks_like_prose,
)


def _reading(raw: str) -> ReadingEntry:
    return ReadingEntry(raw=raw, citation=cit.parse_citation(raw))


def _parse(sessions: list[tuple[str | None, list[str]]]) -> ScheduleParse:
    parsed = ScheduleParse("bulleted")
    for index, (topic, rows) in enumerate(sessions):
        session = SessionEntry(ordinal=index, week_number=index + 1, topic=topic)
        session.readings = [_reading(r) for r in rows]
        parsed.sessions.append(session)
    return parsed


class TestTopicOutline:
    def test_an_outline_of_topics_becomes_topics(self):
        """a module heading with its sub topics bulleted underneath."""
        parsed = _parse([
            (None, ["Scope and size of the sector", "How the sector changed"]),
            (None, ["Management and success", "Decision making", "The four functions"]),
        ])
        _demote_topic_outline(parsed)
        assert all(not s.readings for s in parsed.sessions)
        # the first row of a session with no topic becomes its topic
        assert parsed.sessions[0].topic == "Scope and size of the sector"
        assert parsed.sessions[0].session_type == "topic"
        # nothing is thrown away silently
        assert "How the sector changed" in parsed.unparsed

    def test_a_real_reading_list_is_untouched(self):
        parsed = _parse([
            (None, ["Okonkwo, A. 2019. A Real Book. Cambridge University Press."]),
            (None, ["Osei, B. 2020. Another Real Book. Yale University Press.",
                    "Some unrecognised line"]),
        ])
        _demote_topic_outline(parsed)
        assert sum(len(s.readings) for s in parsed.sessions) == 3

    def test_too_short_to_judge(self):
        """two odd lines really can be two hard readings."""
        parsed = _parse([(None, ["Something", "Something else"])])
        _demote_topic_outline(parsed)
        assert sum(len(s.readings) for s in parsed.sessions) == 2

    def test_one_stray_match_does_not_save_a_long_outline(self):
        """a single accidental citation used to disable the whole test."""
        rows = [f"Topic number {n} in the sector" for n in range(20)]
        rows.append("Okonkwo, A. 2019. A Real Book. Cambridge University Press.")
        parsed = _parse([(None, rows)])
        _demote_topic_outline(parsed)
        assert sum(len(s.readings) for s in parsed.sessions) == 0

    def test_a_list_that_mostly_resolves_survives_one_bad_row(self):
        rows = [f"Okonkwo, A. {2000 + n}. Book {n}. Cambridge University Press."
                for n in range(14)]
        rows.append("an unrecognised line")
        parsed = _parse([(None, rows)])
        _demote_topic_outline(parsed)
        assert sum(len(s.readings) for s in parsed.sessions) == 15


class TestTrailingTail:
    def test_the_last_session_stops_collecting_the_document(self):
        parsed = _parse([
            (None, ["Okonkwo, A. 2019. Book One. Cambridge University Press."]),
            (None, ["Osei, B. 2020. Book Two. Yale University Press."]),
            (None, ["must include (but non-exhaustive):", "Introduction and background",
                    "Detailed analysis of the sector", "The justification of the proposal",
                    "Relevant references, at least five of them", "A note on who did what"]),
        ])
        _drop_trailing_tail(parsed)
        assert not parsed.sessions[-1].readings
        assert len(parsed.sessions[0].readings) == 1
        assert "Introduction and background" in parsed.unparsed

    def test_a_genuine_final_reading_pack_survives(self):
        """it is big, but it resolves, so it is real."""
        pack = [f"Okonkwo, A. {2000 + n}. Book {n}. Cambridge University Press."
                for n in range(6)]
        parsed = _parse([
            (None, ["Osei, B. 2020. Book Two. Yale University Press."]),
            (None, ["Berg, T. 2021. Book Three. Yale University Press."]),
            (None, pack),
        ])
        _drop_trailing_tail(parsed)
        assert len(parsed.sessions[-1].readings) == 6


class TestProse:
    def test_a_sentence_naming_a_year_is_still_prose(self):
        assert _looks_like_prose(
            "The 2018 parliamentary elections led to three different, consecutive "
            "governments in the space of a single year across the whole region"
        )

    def test_an_instruction_to_the_class_is_prose(self):
        assert _looks_like_prose(
            "Before coming to class, select one or more countries and survey rounds "
            "and explore what the data show about trust in institutions"
        )

    def test_a_long_citation_is_not_prose(self):
        for text in (
            "Halvorsen, Ida. Patterns of Governance: Forms and Performance in Thirty "
            "Countries. New Haven; London: Yale University Press, 2012, chapters 1-3.",
            "Berg, Tomas. \"The Long Peace and What It Was Built On.\" "
            "International Security, vol. 44, no. 2, pages 12-48.",
        ):
            assert not _looks_like_prose(text), text

    def test_a_title_containing_a_verb_survives(self):
        assert not _looks_like_prose(
            "Okonkwo, A. and Osei, B. 2019. Why Institutions Are Weak: A Study of "
            "Governance in Thirty Countries. Cambridge University Press."
        )


class TestNewCitationShapes:
    def test_author_date_book_without_a_city(self):
        c = cit.parse_citation(
            "Levitsky, Steven, and Daniel Ziblatt. 2018. How Democracies Die. Crown."
        )
        assert c.matched_pattern == "author_date_book"
        assert c.year == 2018

    def test_the_year_may_wear_brackets(self):
        assert cit.parse_citation(
            "Levitsky, Steven, and Daniel Ziblatt. (2018). How Democracies Die. Crown."
        ).matched_pattern == "author_date_book"

    def test_an_editor_mark_rides_along(self):
        assert cit.parse_citation(
            "Mainwaring, Scott, and Frances Hagopian, eds. 2005. The Third Wave. "
            "Cambridge University Press."
        ).matched_pattern == "author_date_book"

    def test_a_set_text_with_its_week_subject_after_a_semicolon(self):
        c = cit.parse_citation("NRC Ch 12; Fish Meat film")
        assert c.matched_pattern == "author_short_chapter"
        assert "12" in (c.pages or "")

    def test_a_chapter_given_by_its_title(self):
        """a shorter one is claimed by chapter_reference; this covers past its cap."""
        c = cit.parse_citation(
            "Chapter 3 Earnings and Income: The building blocks of your budget planning"
        )
        assert c.matched_pattern == "chapter_with_title"
        assert "3" in (c.pages or "")

    def test_a_short_chapter_title_still_belongs_to_the_older_rule(self):
        assert cit.parse_citation(
            "Chapter 3 Earnings and Income: The blocks"
        ).matched_pattern == "chapter_reference"

    def test_prose_is_not_a_book(self):
        for text in ("We will meet on Tuesday. Bring your notes. Thanks.",
                     "The course begins in 2018. There is a lot to read."):
            assert cit.parse_citation(text).matched_pattern != "author_date_book", text
