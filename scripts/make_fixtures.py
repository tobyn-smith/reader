"""regenerate the pdf fixtures under tests/fixtures.

every course, person and citation in these files is invented. the layouts, not
the contents, are the point: each fixture reproduces a schedule structure or an
extraction hazard that the parser has to survive.

run from the repo root:  python scripts/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SYLLABI = ROOT / "tests" / "fixtures" / "syllabi"
READINGS = ROOT / "tests" / "fixtures" / "readings"

MARGIN = 72
WIDTH, HEIGHT = 612, 792
BODY = 10.5


def _page(doc: pymupdf.Document) -> pymupdf.Page:
    return doc.new_page(width=WIDTH, height=HEIGHT)


def _flow(page: pymupdf.Page, text: str, *, size: float = BODY, y: float = MARGIN) -> float:
    rect = pymupdf.Rect(MARGIN, y, WIDTH - MARGIN, HEIGHT - MARGIN)
    page.insert_textbox(rect, text, fontsize=size, fontname="helv")
    lines = text.count("\n") + 1
    return y + lines * size * 1.32


def make_bulleted() -> None:
    """structure a: week headings with a glyph marker, bulleted wrapped citations."""
    doc = pymupdf.open()

    page = _page(doc)
    _flow(
        page,
        "POLS 6510: Seminar in Invented World Politics\n"
        "Fall 2031\n"
        "Instructor: Dana Okafor\n"
        "Email: dana.okafor@example.edu\n"
        "Time: Thurs 3:55-6:45\n"
        "Place: 14 Example Hall, Rm. 210\n"
        "\n"
        "1. Class Guidelines\n"
        "Grading Policy: Reading Memo & Participation (30%), Field Survey (15%),\n"
        "Mid-term Essay (20%), Research Design (35%).\n"
        "\n"
        "- Reading Memo & Participation (30%): Students must submit a reading memo\n"
        "each week before class (by 9:00 a.m. on Thursdays). The memo (maximum\n"
        "five pages) should address the core argument of each reading.\n"
        "- Field Survey (15%): Due by midnight on September 11 (maximum five pages).\n"
        "- Mid-term Essay (20%): Due before the Week 5 class (October 9, 3:55 p.m.,\n"
        "maximum twelve pages).\n"
        "- Research Design (35%): Due by midnight on December 4 (maximum twenty pages).\n"
        "- Every assignment should be written in Times New Roman, 12 point, with\n"
        "APSR citation style.\n",
    )

    page = _page(doc)
    _flow(
        page,
        "2. University Policies\n"
        "Academic honesty: students are bound by the campus honor code.\n"
        "In addition, unless explicitly stated, artificial intelligence-based\n"
        "technologies, such as ChatGPT, must not be used to generate responses\n"
        "for student assignments. The use of such programs for any course\n"
        "assignments, including your exams, reports, and essays, is not allowed\n"
        "in this course and could result in failing this class.\n"
        "\n"
        "Late Work Policy: I only accept late work that is submitted within 24\n"
        "hours after the deadline with a 10% grade deduction.\n",
    )

    page = _page(doc)
    _flow(
        page,
        "3. Course Outline\n"
        "Most required readings are available through the university library.\n"
        "\n"
        "⧫ Week 1 (8/14): Introduction\n"
        "- Syllabus review, no reading.\n"
        "\n"
        "⧫ Week 2 (8/21): Contending Approaches\n"
        "- Vantree, Nils A. 2018. \"One Field, Many Maps.\" Journal of Invented\n"
        "Politics 44 (Spring): 12-39.\n"
        "- Halloran, Maeve. 1979. \"Structures of Order.\" In Theory of Invented\n"
        "Politics, Chapters 5-6. Boston: Fictional Press.\n"
        "- B´uz´as, Zolt´an I. 2021. \"Naming Practices in Invented Orders.\"\n"
        "Invented Organization 75(2): 440-463.\n"
        "\n"
        "⧫ Week 3 (8/28): Analytical Tools\n"
        "- Reyes, Camila, and Piotr Nowak. 1985. \"Cooperation under Invented\n"
        "Anarchy: Strategies and Institutions.\" World Fictions 38(1): 226-54.\n"
        "- M¨uller-Crepon, Sven. 2025. \"Drawing Borders on Invented Maps.\"\n"
        "American Journal of Invented Science 69(1): 132-147.\n"
        "\n"
        "⧫ Week 4 (9/4): Assignment week: the instructor at a conference\n"
        "\n"
        "⧫ Week 5 (9/11): Interstate Bargaining\n"
        "- Okonkwo, Adaeze N. 1995. \"Rationalist Accounts of Bargaining\n"
        "Failure.\" Invented Organization 49(3): 379-414.\n"
        "- Lindqvist, Karin. 2006. \"War as an Invented Commitment Problem.\"\n"
        "Invented Organization 60(1): 169-203.\n"
        "- Osei, Kwame, James Morrow, Randi Silver, and Alastair Finch. 1999.\n"
        "\"An Institutional Account of the Invented Peace.\" American Invented\n"
        "Science Review 93(4): 791-807.\n",
    )

    doc.save(SYLLABI / "structure-a-bulleted.pdf")
    doc.close()


def make_table() -> None:
    """structure b: a ruled three column table with two meetings per week."""
    doc = pymupdf.open()

    page = _page(doc)
    _flow(
        page,
        "ARTS 2210 Survey of Invented Art: Movements and Meanings\n"
        "Fall 2031\n"
        "Instructor: Priya Raman\n"
        "E-mail: priya.raman@example.edu\n"
        "Class Time: T/TR 11:10-12:25\n"
        "Location: Invented Learning Center Room 0102\n"
        "\n"
        "COURSE REQUIREMENTS & GRADES\n"
        "Weekly Assessments                    40%\n"
        "Exams (3)                             40%\n"
        "Activities                            20%\n"
        "optional extra credit assignment +3%\n",
    )

    page = _page(doc)
    y = MARGIN
    _flow(page, "COURSE SCHEDULE AND ASSIGNMENTS", y=y)
    y += 30

    columns = [MARGIN, MARGIN + 90, MARGIN + 210, WIDTH - MARGIN]
    rows = [
        ("Date", "Topic", "Assignments and Due Dates", 26),
        (
            "Week 1\n\n8/14",
            "Introduction to\nInvented Art",
            "Readings for Thursday:\n\n"
            "Mara Voss, \"Why Study Invented Art,\" pgs. 1-4, in A Field\n"
            "Guide for Invented Art Students\n"
            "Pdf of required pages on eLC\n",
            108,
        ),
        (
            "Week 2\n\n8/19\n\n8/21",
            "Early Invented\nPeriod",
            "T: Dr. Ana Ruiz and Dr. Sam Weber, \"The Painted Door of\n"
            "the Old Capital,\" in Artsurvey,\n"
            "https://example.org/painted-door-of-the-old-capital/.\n"
            "\n"
            "TR: Pages 29-37 in The Illustrated Companion to Invented\n"
            "Art. PDF on eLC.\n"
            "• Content warning: discussion of political violence\n"
            "\n"
            "Weekly Assessment 1 due 8/24 at 11:59 pm\n",
            150,
        ),
        (
            "Week 3\n\n8/26\n\n8/28",
            "High Invented\nPeriod",
            "T: EXAM 1 IN CLASS\n"
            "\n"
            "TR: Department of Invented Art. \"Quiet Rooms.\" In Timeline\n"
            "of Invented Art. New City: The Example Museum, 2000-.\n"
            "http://www.example.org/toah/hd/quiet/quiet.htm\n"
            "\n"
            "Weekly Assessment 2 due 8/31 at 11:59 pm\n",
            126,
        ),
        (
            "12/4",
            "Final Exam",
            "UNITS 3 AND 4 EXAM THUR., DEC. 4, 12:00 - 3:00 PM",
            40,
        ),
    ]

    top = y
    for label, topic, body, height in rows:
        bottom = top + height
        for x in columns:
            page.draw_line(pymupdf.Point(x, top), pymupdf.Point(x, bottom))
        page.draw_line(pymupdf.Point(columns[0], top), pymupdf.Point(columns[-1], top))
        page.insert_textbox(
            pymupdf.Rect(columns[0] + 4, top + 4, columns[1] - 4, bottom - 2),
            label, fontsize=9.5, fontname="helv",
        )
        page.insert_textbox(
            pymupdf.Rect(columns[1] + 4, top + 4, columns[2] - 4, bottom - 2),
            topic, fontsize=9.5, fontname="helv",
        )
        page.insert_textbox(
            pymupdf.Rect(columns[2] + 4, top + 4, columns[3] - 4, bottom - 2),
            body, fontsize=9.5, fontname="helv",
        )
        top = bottom
    page.draw_line(pymupdf.Point(columns[0], top), pymupdf.Point(columns[-1], top))

    doc.save(SYLLABI / "structure-b-table.pdf")
    doc.close()


def make_labelled() -> None:
    """structure c: keyword blocks, hanging indent, an important dates list."""
    doc = pymupdf.open()

    page = _page(doc)
    _flow(
        page,
        "Invented University\n"
        "TRDE 8330\n"
        "The Politics of Invented Commerce\n"
        "Spring 2031\n"
        "Time: Monday 12:40 - 3:50\n"
        "Instructor: Rowan Ashe\n"
        "Email: rowan.ashe@example.edu\n"
        "\n"
        "Course Requirements and Grading Components\n"
        "Professionalism                     20%     Weekly\n"
        "Case Study Report                   20%     February 2nd\n"
        "Agency Reports                      25%     March 2nd\n"
        "Final Issues Report                 35%     April 13th\n"
        "\n"
        "Important Dates\n"
        "January 10th - 14th: Drop Add\n"
        "March 3rd: Midterm\n"
        "March 7th - 11th: Spring Break\n"
        "March 24th: Withdrawal Deadline\n"
        "May 3rd: Classes End\n",
    )

    page = _page(doc)
    _flow(
        page,
        "Course Overview: The syllabus is a general plan for the course.\n"
        "\n"
        "Week 1, January 12th\n"
        "Course Introduction and Overview\n"
        "\n"
        "January 19th - NO CLASS\n"
        "\n"
        "Week 2, January 26th\n"
        "\n"
        "Topic: Why Invented Controls?\n"
        "\n"
        "Readings:\n"
        "\n"
        "        Darrow, Jonah L. and Nils K. Vantree. 2019. \"Careers in\n"
        "Invented Trade Control.\" Invented Trade Review. 5:8, 93-96.\n"
        "\n"
        "        Ferreira, Ian F. and Paul K. Osei. January 28, 2020. \"The\n"
        "Invented Control System and Reform Initiative\" R99123, Invented\n"
        "Research Service, example.gov, 1-31.\n"
        "\n"
        "SIGN-UP: Case Study Presentation and Report #1\n"
        "\n"
        "Week 3, February 2nd\n"
        "\n"
        "Topic: Multilateral Invented Regimes\n"
        "\n"
        "Readings:\n"
        "\n"
        "        Sun, Mira. August 31, 2020. \"Blacklists Used for Invented\n"
        "Policy Goals\" The Daily Example:\n"
        "https://www.example.com/articles/blacklists-invented-policy-goals\n"
        "\n"
        "Review (Inspectional Reading):\n"
        "\n"
        "        Invented Trade Enforcement: Implementation Guide, World\n"
        "Example Organization (WEO), 1-37.\n"
        "\n"
        "DUE: Case Study Paper and Presentation\n"
        "\n"
        "Week 4, February 9th\n"
        "\n"
        "Topic: Regulators and Regulations\n"
        "\n"
        "Readings: TBD\n"
        "\n"
        "Presentation: Case Studies 1 - 5\n",
        size=10,
    )

    doc.save(SYLLABI / "structure-c-labelled.pdf")
    doc.close()


def make_two_column() -> None:
    body_left = (
        "The study of invented institutions has long asked why cooperation "
        "persists in the absence of central enforcement. This essay revisits "
        "that question with a simple model of repeated exchange. Actors who "
        "expect to meet again discount the future less heavily, and the shadow "
        "of that future disciplines present behaviour. The columns of this page "
        "are set separately, and an extractor that reads straight across the "
        "page will interleave them into nonsense."
    )
    body_right = (
        "Critics reply that repetition alone cannot carry the weight placed on "
        "it. Institutions, on this view, matter because they change what actors "
        "believe about one another rather than what they earn from one another. "
        "The disagreement is partly empirical and partly about what counts as "
        "an explanation. The second column continues the argument to give the "
        "column detector enough text on each side of the page to measure."
    )

    doc = pymupdf.open()
    for _ in range(2):
        page = _page(doc)
        mid = WIDTH / 2
        for start in range(0, 4):
            y = MARGIN + start * 160
            page.insert_textbox(
                pymupdf.Rect(MARGIN, y, mid - 12, y + 150), body_left,
                fontsize=9.5, fontname="helv",
            )
            page.insert_textbox(
                pymupdf.Rect(mid + 12, y, WIDTH - MARGIN, y + 150), body_right,
                fontsize=9.5, fontname="helv",
            )
    doc.save(READINGS / "two-column.pdf")
    doc.close()


def make_footnoted() -> None:
    doc = pymupdf.open()
    for number in range(2):
        page = _page(doc)
        _flow(
            page,
            "On the Uses of Invented Evidence\n"
            "\n"
            "Claims about invented politics rest on records that someone kept "
            "for reasons of their own.1 The historian of the invented must "
            "therefore read against the grain of the archive.2 What survives is "
            "not what happened but what was written down, and the two part ways "
            "whenever writing was costly or dangerous. The body text on this "
            "page runs at full size while the notes below run smaller, which is "
            "the signal the footnote splitter relies on.",
        )
        page.insert_textbox(
            pymupdf.Rect(MARGIN, HEIGHT - 150, WIDTH - MARGIN, HEIGHT - MARGIN),
            f"1. Ilsa Marchetti, The Invented Archive (New City: Example Press, 2011), {40 + number}.\n"
            f"2. Tomas Reinholt, \"Reading Records,\" Journal of Invented History 8, no. 2 (2015): {112 + number}.",
            fontsize=7.5,
            fontname="helv",
        )
    doc.save(READINGS / "footnote-heavy.pdf")
    doc.close()


def make_scanned() -> None:
    """a page whose text exists only as pixels, so ocr is the only way in."""
    source = pymupdf.open()
    page = _page(source)
    _flow(
        page,
        "A Scanned Page of Invented Prose\n\n"
        "This page began as text, was rendered to an image, and was inserted "
        "back into a fresh pdf with no text layer at all. An extractor that "
        "reports text for this page without running ocr is inventing it.",
        size=13,
    )
    pixmap = page.get_pixmap(dpi=120)
    source.close()

    doc = pymupdf.open()
    target = _page(doc)
    target.insert_image(pymupdf.Rect(0, 0, WIDTH, HEIGHT), pixmap=pixmap)
    doc.save(READINGS / "scanned.pdf")
    doc.close()


def main() -> None:
    SYLLABI.mkdir(parents=True, exist_ok=True)
    READINGS.mkdir(parents=True, exist_ok=True)
    make_bulleted()
    make_table()
    make_labelled()
    make_two_column()
    make_footnoted()
    make_scanned()
    for path in sorted(SYLLABI.glob("*.pdf")) + sorted(READINGS.glob("*.pdf")):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
