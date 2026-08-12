# Schedule Reader

**Turn a syllabus PDF into the term you actually have to get through.**

[![CI](https://github.com/tobyn-smith/reader/actions/workflows/ci.yml/badge.svg)](https://github.com/tobyn-smith/reader/actions/workflows/ci.yml)
[![Pages](https://github.com/tobyn-smith/reader/actions/workflows/pages.yml/badge.svg)](https://github.com/tobyn-smith/reader/actions/workflows/pages.yml)

### → [Open it in your browser](https://tobyn-smith.github.io/reader/)

Drop a syllabus PDF and get the week-by-week schedule, every reading as a
proper citation, the deadlines, and a bibliography you can print. No install,
no account, no upload.

Built for reading-heavy courses: international affairs, political science,
history, English, the humanities generally, where the syllabus is a long list
of citations and the work is keeping up with it.

---

## What you get

| | |
| --- | --- |
| **One ledger** | Every week, every reading, one continuous table. Columns stay aligned from week 1 to week 15. |
| **Real citations** | Chicago, APA, MLA, Harvard or APSR, switchable after the fact. |
| **Deadlines that mean something** | Banded overdue / next 7 days / later, with "in 3 days" rather than a bare date. |
| **Correct anything** | Fix a citation, add a reading it missed, move a due date. Grades re-total as you go. |
| **Print it** | Black on white, named after the course, checkboxes you can tick with a pen. |
| **Nothing leaves** | Files are read in your browser. There is no server and no upload endpoint. |

## How accurate it is

Worth knowing before you lean on it. Tested on over 35 real syllabi from one
university, parsed and checked by hand:

| | |
| --- | --- |
| Told a syllabus from a reading | **100%** |
| Course code | **100%** |
| Term | **96%** |
| Found a schedule | **79%** |
| Readings parsed into full citations | **83%** |
| Weights adding up to about 100 | **6 of 10** |

Reading lists are the weak spot. Most of what fails was never a reading in the
first place: week topics, description paragraphs, columns off a grading table.
Cleaning that up took it from 66% to 83%.

Anything it can't read, it shows you verbatim and marks for checking. It won't
quietly drop a reading or invent one. No schedule found usually means the PDF
hasn't got one.

Which is why everything stays editable. Instructors move deadlines and no
parser catches that, so a tracker you can't correct goes stale by week three.
Courses parsed by an older version offer to re-read themselves.

---

## On the command line

For bulk work: a folder of readings, full text search, publishing a site.

```bash
vault syllabus syllabus.pdf     # parse, review, save
vault ingest readings/          # add reading pdfs, safe to re-run
vault status                    # this week: have, missing, due
vault search "commitment problem"
vault build --public --pdf      # what github pages serves
vault serve                     # browse the private build
```

Two halves sharing one database.

**Syllabus intake.** Course info, the weekly schedule, readings as citations,
graded work with due dates, and the policies you'll want later, including
whatever the course says about AI. It shows you all of it before writing
anything.

**Reading pipeline.** Page numbers survive the whole way through. Two-column
articles come out in reading order, footnotes stay separate, scanned pages get
flagged for OCR. Each file is matched to its syllabus entry, so `vault status`
can print:

```
POLS 6510 Week 5 (9/11) Interstate Bargaining
  [x] Okonkwo 1995, Rationalist Accounts of Bargaining Failure
  [ ] Lindqvist 2006, War as an Invented Commitment Problem   MISSING
  [x] Osei et al 1999, An Institutional Account of the Invented Peace

due
  POLS 6510  Reading Memo & Participation  weekly on thursday 09:00
```

It all runs locally with no keys. There's an optional model layer that writes
reading briefs and does nothing else; skip it and the rest still works. Where a
course bans AI, briefs are off for that course. Nothing here writes anything
you'd submit.

## Install

Python 3.11 or newer.

```bash
git clone https://github.com/tobyn-smith/reader
cd reader
python -m venv .venv
.venv/Scripts/activate          # linux/mac: source .venv/bin/activate
pip install -e ".[dev]"
git config core.hooksPath .githooks
```

Optional, one feature each: `ocrmypdf` for scanned PDFs, `pagefind` for search
on the built site, `weasyprint` for print PDFs locally (CI builds them either
way).

Nothing to configure. Your database, PDFs and caches sit in `~/.seminar-vault/`,
well outside the repo, so coursework can't wander into a commit.

## How it works

The same Python parses your syllabus whether you run the command line or the
browser, compiled to WebAssembly for the latter, so both give the same answers.
Parsing is deterministic pattern matching: every extracted row records which
rule produced it, and a line no rule claims goes to review unparsed rather than
being guessed at. A wrong citation looks finished; a flagged one doesn't.

`ARCHITECTURE.md` has the details, including what the parser gets wrong and why.

## Publishing

The public site carries schedules, citations, deadlines and bibliographies, and
that's the lot. A field has to be named on an allowlist to get out, and the
tests fail if something new shows up. Reading text, briefs, notes and instructor
contact details stay local. CI builds from `data/public.json`, which you review
before committing, and never touches your database.

## Make it yours

1. Fork it. Settings, Pages, source: GitHub Actions.
2. `vault syllabus your-syllabus.pdf` per course, and review the parse.
3. `vault ingest your-readings/` as term goes on.
4. `vault export --public`, read what it kept and dropped, commit
   `data/public.json`. Pushing publishes.

The allowlist, the CI setup and the pre-commit hook all carry over to your fork.
There's no real coursework in this repo; the demo runs on invented courses from
`tests/fixtures/`.

## Tests

```bash
pytest -q
```

Runs offline with no keys. Fixtures are invented PDFs copying the layouts real
syllabi use: bulleted schedules with odd glyph markers, ruled tables with two
meetings a week, labelled topic and reading blocks, two-column articles,
footnote-heavy pages, and one scan with no text layer. They assert exact reading
counts per week, because a parser that quietly loses one reading in five
otherwise looks fine.
