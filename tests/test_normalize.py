"""golden cases for the extraction artifact table in ARCHITECTURE.md.

the inputs here are synthetic. they reproduce the shape of each artifact seen in
real course pdfs without carrying any real course content.
"""

import pytest

from vault.text import normalize as n


def clean(text: str) -> str:
    return n.clean_page_text(text).text


class TestUndecodableGlyphs:
    def test_cid_run_is_dropped(self):
        assert clean("(cid:117) Week 2 (8/21): Opening") == " Week 2 (8/21): Opening"

    def test_marker_stripped_from_line_start(self):
        line, marker = n.strip_leading_marker("(cid:117) Week 2 (8/21): Opening")
        assert line == "Week 2 (8/21): Opening"
        assert marker == "(cid:117)"

    def test_symbol_font_bullet_extracting_as_a_letter(self):
        # a dingbat in a symbol font can come back as a single latin letter
        line, marker = n.strip_leading_marker("u Week 2 (8/21): Opening")
        assert line == "Week 2 (8/21): Opening"
        assert marker == "u"

    def test_real_word_is_not_mistaken_for_a_marker(self):
        line, marker = n.strip_leading_marker("Readings for Tuesday:")
        assert line == "Readings for Tuesday:"
        assert marker is None


class TestDiacritics:
    def test_acute_accent_leading_its_vowel(self):
        assert n.compose_diacritics("L´opez, Jos´e").text == "López, José"

    def test_diaeresis_leading_its_vowel(self):
        assert n.compose_diacritics("Schr¨oder, Hans").text == "Schröder, Hans"

    def test_accent_with_no_precomposed_form_is_left_alone(self):
        # an acute used as a stray apostrophe must not invent a character
        assert n.compose_diacritics("don´t").text == "don´t"

    def test_cedilla_trails_its_letter(self):
        assert n.compose_diacritics("Franc¸ois").text == "François"

    def test_output_is_nfc(self):
        import unicodedata

        out = n.normalize_unicode("L´opez").text
        assert out == unicodedata.normalize("NFC", out)
        assert len(out) == len("López")


class TestLigatures:
    def test_common_ligatures_expand(self):
        assert n.expand_ligatures("deﬁne the ﬂow of aﬀairs").text == "define the flow of affairs"


class TestLostSpaces:
    def test_lowercase_run_is_split(self):
        assert clean("Explainwhyeachsourcematters") == "Explain why each source matters"

    def test_author_list_run_is_split(self):
        assert clean("Nguyen,AnhT.,andPriyaRaman") == "Nguyen, Anh T., and Priya Raman"

    def test_surname_particles_are_not_split(self):
        for name in ("McDonald", "MacArthur", "DeGaulle"):
            assert clean(name) == name

    def test_short_tokens_are_left_alone(self):
        assert clean("PhD TBD eLC") == "PhD TBD eLC"

    def test_ordinary_prose_is_untouched(self):
        prose = "Students must submit a reading checklist each week before class."
        assert clean(prose) == prose

    def test_every_split_is_logged(self):
        result = n.restore_spaces("Explainwhyeachsourcematters")
        assert [e.rule for e in result.edits] == ["word_split"]
        assert result.edits[0].before == "Explainwhyeachsourcematters"

    def test_splitter_refuses_without_a_lexicon(self, monkeypatch):
        empty = n.Lexicon()
        monkeypatch.setattr(empty, "_words", set())
        monkeypatch.setattr(n, "_LEXICON", empty)
        # no dictionary means no guessing
        assert n.restore_spaces("Explainwhyeachsourcematters").text == (
            "Explainwhyeachsourcematters"
        )


class TestUrls:
    def test_url_split_across_lines_is_rejoined_without_adding_a_hyphen(self):
        raw = "https://example.edu/notes/empires-\nand-their-endings/"
        assert clean(raw) == "https://example.edu/notes/empires-and-their-endings/"

    def test_injected_space_inside_a_url_is_closed(self):
        raw = "https://example.org/2020/07/28/time-repatriate looted-art-objects/"
        assert clean(raw) == "https://example.org/2020/07/28/time-repatriate-looted-art-objects/"

    def test_prose_after_a_url_is_not_swallowed(self):
        raw = "See https://example.edu/syllabus Readings are on the course site."
        assert "syllabus Readings" in clean(raw)

    def test_word_splitter_never_touches_a_url(self):
        raw = "https://example.edu/averylongpathsegmenthere/more"
        assert clean(raw) == raw


class TestHyphenation:
    def test_word_split_across_lines_is_rejoined(self):
        assert clean("interna-\ntional") == "international"

    def test_hyphenated_surname_keeps_its_hyphen(self):
        assert clean("Hafner-\nBurton") == "Hafner-Burton"


class TestDashes:
    def test_page_range_normalises_for_parsing(self):
        assert n.parsing_form("120–148") == "120-148"

    def test_display_text_keeps_the_original_dash(self):
        assert n.clean_page_text("120–148").text == "120–148"

    def test_name_range_normalises(self):
        assert n.parsing_form("Müller–Crepon") == "Müller-Crepon"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("(cid:117) Week 3", " Week 3"),
        ("L´opez", "López"),
        ("Schr¨oder", "Schröder"),
        ("deﬁne", "define"),
        ("Explainwhyeachsourcematters", "Explain why each source matters"),
        ("Nguyen,AnhT.,andPriyaRaman", "Nguyen, Anh T., and Priya Raman"),
        ("https://example.edu/a-\nb-c", "https://example.edu/a-b-c"),
        ("interna-\ntional", "international"),
    ],
)
def test_artifact_table(raw, expected):
    assert clean(raw) == expected
