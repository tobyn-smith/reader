"""the crossref rescue for lines no citation pattern could read.

the gate is the whole point of this feature, so most of these tests are about
what it refuses. a rescue that accepts a near miss is worse than no rescue at
all: the row stops being flagged and a wrong citation gets carried into a
bibliography looking exactly like a right one.

nothing here touches the network. the gate takes a crossref item as a plain
dict, so the interesting cases are written out by hand.
"""

from __future__ import annotations

import json

import pytest

from vault.lookup import display_of, fields_of, rescue_from_item, worth_rescuing
from vault.review import _merge_suggestion
from vault.syllabus.citations import parse_citation
from vault.syllabus.pipeline import _citation_dict

RAW = (
    'Okonkwo, Chidi. "Rationalist Accounts of Bargaining Failure." '
    "International Organization 49, no. 3 (1995): 379-414."
)


def item(**overrides) -> dict:
    base = {
        "title": ["Rationalist Accounts of Bargaining Failure"],
        "author": [{"family": "Okonkwo", "given": "Chidi"}],
        "container-title": ["International Organization"],
        "issued": {"date-parts": [[1995, 6]]},
        "volume": "49",
        "issue": "3",
        "page": "379-414",
        "DOI": "10.1017/s0020818300028447",
        "URL": "https://doi.org/10.1017/s0020818300028447",
        "type": "journal-article",
    }
    base.update(overrides)
    return base


class TestWorthRescuing:
    """the local filter, so a network call is only spent on a plausible line."""

    def test_accepts_a_real_citation_line(self):
        assert worth_rescuing(RAW)

    def test_rejects_a_line_too_short_to_identify_anything(self):
        assert not worth_rescuing("Ch. 4")
        assert not worth_rescuing("pp. 12-40")

    def test_rejects_a_bare_url(self):
        assert not worth_rescuing("https://example.org/some/long/path/to/a/reading.pdf")

    @pytest.mark.parametrize(
        "line",
        [
            "TBA",
            "To be announced closer to the date",
            "See the course site for this week's reading",
            "No reading this week, come with questions",
        ],
    )
    def test_rejects_placeholders(self, line):
        assert not worth_rescuing(line)

    def test_accepts_a_line_with_a_url_in_it(self):
        """a citation that happens to carry a link is still a citation."""
        assert worth_rescuing(
            "Bakare, A. (2011). Coastal Retreat in the Delta. https://example.org/report"
        )

    @pytest.mark.parametrize(
        "line",
        [
            # a schedule row that lost its line breaks
            "November 7 Environmental impacts of war November 9 Natural disasters and risk",
            # prose from under a week heading
            "The famous political scientist once said that democracy is impossible "
            "without parties, and the week takes that claim seriously",
            # a topic label with a unit reference
            "Orientation Readings ABG Part III",
            # a chapter heading from a textbook table of contents
            "Chapter 10 Planning for the future: Retirement and Estate Planning",
        ],
    )
    def test_rejects_lines_that_are_not_references(self, line):
        """every one of these was asked about, and came back confidently wrong.

        a lookup service answers whatever it is asked. these are schedule
        fragments and prose that leaked into a reading list, and the fix is to
        not ask rather than to judge the answer harder.
        """
        assert not worth_rescuing(line)


class TestGate:
    """agreement on title, author and year, or the hit is dropped."""

    def test_accepts_a_genuine_match(self):
        suggestion = rescue_from_item(RAW, item())
        assert suggestion is not None
        assert suggestion.source == "crossref"
        assert suggestion.fields["doi"] == "10.1017/s0020818300028447"
        assert suggestion.fields["work_type"] == "journal_article"
        assert suggestion.title_cover == 1.0

    def test_rejects_a_title_that_does_not_appear_in_the_line(self):
        other = item(title=["Domestic Audiences and Coercive Diplomacy in Wartime"])
        assert rescue_from_item(RAW, other) is None

    def test_rejects_partial_title_overlap_below_the_bar(self):
        """two words of five is what a keyword search returns, not a match."""
        other = item(title=["Rationalist Explanations for Nuclear Proliferation Choices"])
        assert rescue_from_item(RAW, other) is None

    def test_rejects_when_the_first_author_is_absent_from_the_line(self):
        other = item(author=[{"family": "Lindqvist", "given": "Marta"}])
        assert rescue_from_item(RAW, other) is None

    def test_rejects_a_review_of_the_work_it_is_looking_for(self):
        """crossref indexes reviews under the reviewed book's exact title.

        seen on real syllabi: a line naming Dahl's Polyarchy matched a 1972
        review of Polyarchy in American Quarterly, whose first author is the
        reviewer. title and year both agree, so only the author position tells
        the two apart.
        """
        review = item(
            title=["Polyarchy: Participation and Opposition"],
            author=[{"family": "Ericson"}, {"family": "Dahl"}],
            container_title=["American Quarterly"],
        )
        review["container-title"] = ["American Quarterly"]
        raw = "Dahl, Robert. 1972. Polyarchy: Participation and Opposition. Yale University Press."
        review["issued"] = {"date-parts": [[1972]]}
        assert rescue_from_item(raw, review) is None

    def test_rejects_a_reference_work_entry(self):
        """a who's who entry names the person, and matches almost anything."""
        entry = item(
            title=["Santos, Juan Manuel"],
            author=[],
            issued={"date-parts": [[2016]]},
        )
        entry["container-title"] = ["International Year Book and Statesmen's Who's Who"]
        raw = "Santos, Juan Manuel. 2016. Notes on the peace negotiations in Colombia."
        assert rescue_from_item(raw, entry) is None

    def test_rejects_a_year_the_line_contradicts(self):
        other = item(issued={"date-parts": [[2014]]})
        assert rescue_from_item(RAW, other) is None

    def test_allows_a_year_one_out(self):
        """print and online years disagree by one often enough to allow it."""
        assert rescue_from_item(RAW, item(issued={"date-parts": [[1996]]})) is not None

    def test_rejects_a_title_too_short_to_mean_anything(self):
        """short titles overlap everything, so they are never evidence."""
        other = item(title=["On War"], author=[{"family": "Okonkwo"}])
        assert rescue_from_item("Okonkwo on war and the state, 1995", other) is None

    def test_rejects_an_item_with_no_title(self):
        assert rescue_from_item(RAW, item(title=[])) is None

    def test_accepts_when_crossref_lists_no_authors(self):
        """an institutional work with no author list still matches on title."""
        agency = {
            "title": ["Global Assessment of Coastal Erosion and Retreat"],
            "author": [],
            "publisher": "Coastal Research Board",
            "issued": {"date-parts": [[2019]]},
            "type": "report",
        }
        raw = "Global Assessment of Coastal Erosion and Retreat (Coastal Research Board, 2019)"
        suggestion = rescue_from_item(raw, agency)
        assert suggestion is not None
        assert suggestion.fields["work_type"] == "report"

    def test_rejects_a_line_with_no_year_to_corroborate_against(self):
        """without a year nothing pins the match to this work or this edition."""
        raw = 'Okonkwo, "Rationalist Accounts of Bargaining Failure," Intl Organization'
        assert rescue_from_item(raw, item()) is None


class TestFields:
    def test_maps_crossref_types_to_work_types(self):
        assert fields_of(item(type="book-chapter"), 1995)["work_type"] == "book_chapter"
        assert fields_of(item(type="monograph"), 1995)["work_type"] == "book"
        assert fields_of(item(type="posted-content"), 1995)["work_type"] == "unknown"

    def test_keeps_institutional_authors_whole(self):
        fields = fields_of(item(author=[{"name": "World Meteorological Organization"}]), 2019)
        assert fields["authors"] == [{"literal": "World Meteorological Organization"}]

    def test_display_is_readable(self):
        display = display_of(fields_of(item(), 1995))
        assert "Okonkwo 1995" in display
        assert "Rationalist Accounts of Bargaining Failure" in display
        assert "International Organization 49.3: 379-414" in display


class TestAcceptance:
    """a suggestion only becomes a citation when someone says so."""

    def test_suggestion_does_not_make_a_citation_parsed(self):
        citation = parse_citation("Okonkwo, Rationalist Accounts, IO 49:3")
        citation.suggestion = rescue_from_item(RAW, item())
        if citation.parsed:
            pytest.skip("this line now matches a pattern, so it is not a rescue case")
        assert citation.suggestion is not None
        assert citation.matched_pattern is None
        assert citation.title is None

    def test_accepting_folds_the_fields_in(self):
        citation = parse_citation("a line no pattern reads, honestly")
        citation.suggestion = rescue_from_item(RAW, item())
        assert citation.accept_suggestion()
        assert citation.title == "Rationalist Accounts of Bargaining Failure"
        assert citation.year == 1995
        assert citation.authors[0].surname == "Okonkwo"
        assert citation.matched_pattern == "crossref_lookup"
        assert citation.confidence == 0.9
        assert citation.suggestion is None

    def test_accepting_nothing_is_a_no_op(self):
        citation = parse_citation("a line no pattern reads, honestly")
        assert citation.accept_suggestion() is False

    def test_a_suggestion_cannot_reach_the_database_or_the_export(self, vault_conn):
        """the boundary is the schema: work has no column for an unaccepted guess.

        this is the invariant that lets the rescue exist at all. a suggestion is
        an unverified claim about a reading, so it may sit in a parse waiting for
        review and nowhere else. if someone later adds a column for it, this
        fails and they have to think about the export before it ships.
        """
        from vault import db, publish

        citation = parse_citation("a line no pattern reads, honestly")
        citation.suggestion = rescue_from_item(RAW, item())
        work = _citation_dict(citation)
        assert work["suggestion"] is not None

        work_id = db._upsert_work(vault_conn, work)
        row = vault_conn.execute("select * from work where id = ?", (work_id,)).fetchone()
        stored = " ".join(str(v) for v in tuple(row))
        assert "Rationalist Accounts" not in stored
        assert "crossref" not in stored.lower()

        payload, _ = publish.build_public_payload(vault_conn)
        assert publish.check_payload(payload) == []
        assert "suggestion" not in json.dumps(payload)

    def test_merge_keeps_what_the_parse_already_read(self):
        guess = {
            "title": "The Title As Printed In The Syllabus",
            "year": None,
            "doi": None,
            "suggestion": {"source": "crossref"},
        }
        suggestion = {
            "source": "crossref",
            "fields": {"title": "A Different Title", "year": 1995, "doi": "10.1/x"},
        }
        merged = _merge_suggestion(guess, suggestion)
        assert merged["title"] == "The Title As Printed In The Syllabus"
        assert merged["year"] == 1995
        assert merged["doi"] == "10.1/x"
        assert merged["matched_pattern"] == "crossref_lookup"
        assert "suggestion" not in merged
