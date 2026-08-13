"""page numbers, from the citation they are written in to the meter that counts them.

a page range is the one number a student actually plans against: how much is
there to read this week, and how much of it is done. it travels a long way to
get to the screen, and it was losing accuracy at every stage. a journal
citation states its pages with no "pp." anywhere and the range was dropped; a
brief that says "8-10 pages" set no limit because the pattern only knew the
singular; a sentence about how long a monograph runs became the essay's own cap.

every case below is written synthetically.
"""

from __future__ import annotations

from vault.site.pdf import _page_note
from vault.syllabus import citations as cit
from vault.syllabus import deliverables, schedule, zones


def requirements(*texts: str) -> list[zones.Zone]:
    """a requirements zone, first line opening a block and the rest inside it."""
    lines = [
        zones.Line(1, i, text, starts_block=(i == 0))
        for i, text in enumerate(texts)
    ]
    return [zones.Zone(zones.REQUIREMENTS, None, lines)]


def only_limit(*texts: str) -> int | None:
    parsed = deliverables.extract(requirements(*texts), None, [])
    return parsed.items[0].page_limit if parsed.items else None


class TestAPageRangeSurvivesTheCitationItCameIn:
    def test_a_journal_citation_keeps_its_pages_without_a_pp_label(self):
        """"12(3): 231-245" is where a page range normally lives.

        most reading lists never write "pp." at all, so keying the range to
        that label left the pages column empty on the majority of a list while
        the citation parser had already read the range.
        """
        entry = schedule._build_reading(
            'Quilliam, M. 2019. "Invented Title." Made Up Review 12(3): 231-245.', 0
        )
        assert entry is not None
        assert entry.page_range == "231-245"

    def test_an_elided_upper_bound_is_kept_as_written(self):
        entry = schedule._build_reading(
            'Okonkwo, A. 2020. "Second Invented." Nowhere Journal 8(2): 1064-79.', 0
        )
        assert entry is not None
        assert entry.page_range == "1064-79"

    def test_an_explicit_pp_label_still_wins(self):
        entry = schedule._build_reading(
            "Osei, B. Invented Book. Nowhere Press, 2021, pp. 12-30.", 0
        )
        assert entry is not None
        assert entry.page_range == "12-30"


class TestThingsThatAreNotPageNumbers:
    def test_a_year_after_the_volume_is_not_a_page_range(self):
        """a bare four figure number where the pages go is the year again."""
        line = 'Quilliam, M. 2019. "Invented Title." Made Up Review 12, 2020.'
        assert cit.parse_citation(line).pages is None
        entry = schedule._build_reading(line, 0)
        assert entry is not None
        assert entry.page_range is None

    def test_a_chapter_locator_is_not_a_page_range(self):
        entry = schedule._build_reading("Quilliam and Bex, Chapter 1", 0)
        assert entry is not None
        assert entry.page_range is None

    def test_a_chapter_locator_keeps_its_space(self):
        """stripping every space out of the field turned this into Chapter1."""
        assert cit.parse_citation("Quilliam and Bex, Chapter 1").pages == "Chapter 1"


class TestHowLongTheAssignmentMayBe:
    def test_a_plural_range_sets_the_upper_bound(self):
        """"8-10 pages" is the ordinary way to write it.

        the pattern ended "page\\b", and that boundary cannot fall inside
        "pages", so the commonest form of all set no limit.
        """
        assert only_limit(
            "Book Review (25%): a review of one monograph. Length: 8-10 pages, double spaced."
        ) == 10

    def test_a_word_between_the_keyword_and_the_number_is_allowed(self):
        assert only_limit("Reflective Essay (15%): a maximum of 5 pages, submitted online.") == 5

    def test_a_restated_numeral_does_not_break_the_match(self):
        assert only_limit("Short Paper (10%): no more than five (5) pages.") == 5

    def test_words_between_the_number_and_the_noun_are_allowed(self):
        assert only_limit("Term Paper (30%): 12-15 typed pages, due at the end of term.") == 15

    def test_the_other_ways_of_saying_at_most(self):
        assert only_limit("Response (10%): no longer than 6 pages.") == 6
        assert only_limit("Seminar Paper (30%): not to exceed 20 pages.") == 20

    def test_a_books_length_is_not_the_assignments_limit(self):
        """the window runs past the brief, so it can reach the wrong sentence.

        a report told to pick a monograph took the monograph's own length as
        its cap and told the student to write four hundred pages.
        """
        assert only_limit(
            "Book Report (20%): choose any monograph from the invented list.",
            "Most run to a 300-400 page length.",
        ) is None


class TestThePrintedPageNote:
    def test_a_citation_that_states_its_pages_is_not_told_twice(self):
        assert _page_note("Zzyzx; Quorbin. pp.12-30", "12-30") is None
        assert _page_note("Zzyzx; Quorbin. pp. 12-30", "12-30") is None

    def test_a_citation_without_pages_still_gets_the_note(self):
        assert _page_note("Zzyzx; Quorbin. Invented Title.", "12-30") == "pp. 12-30"
