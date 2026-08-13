# Schedule Reader

**Turn a syllabus PDF into the term you actually have to get through.**

[![Release](https://img.shields.io/github/v/release/tobyn-smith/reader?style=flat-square&color=D2704A&labelColor=2B2924)](https://github.com/tobyn-smith/reader/releases)
[![Tests](https://img.shields.io/github/actions/workflow/status/tobyn-smith/reader/ci.yml?style=flat-square&label=tests&labelColor=2B2924)](https://github.com/tobyn-smith/reader/actions/workflows/ci.yml)
[![Deploy](https://img.shields.io/github/actions/workflow/status/tobyn-smith/reader/pages.yml?style=flat-square&label=deploy&labelColor=2B2924)](https://github.com/tobyn-smith/reader/actions/workflows/pages.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-EDE8DA?style=flat-square&labelColor=2B2924)](#install)
[![Citations parsed](https://img.shields.io/badge/citations_parsed-85%25-D2704A?style=flat-square&labelColor=2B2924)](#how-accurate-it-is)
[![Last commit](https://img.shields.io/github/last-commit/tobyn-smith/reader?style=flat-square&color=6E695E&labelColor=2B2924)](https://github.com/tobyn-smith/reader/commits/main)

### → [Open it in your browser](https://tobyn-smith.github.io/reader/)

Drop a syllabus PDF and get the week-by-week schedule, every reading as a
proper citation, the deadlines, and a bibliography you can print. No install,
no account, no upload.

**Want it as an app?** It installs itself, with an icon beside your other
programmes, its own window and offline launch. In Chrome or Edge, click the
install icon at the right-hand end of the address bar, or the "install it as an
app" link at the foot of the page. In Safari, File then Add to Dock. Firefox on
desktop has no install, and the site works the same in it. Nothing is
downloaded and your saved courses carry over either way.

I built this for reading-heavy courses: international affairs, political
science, history, English, the humanities generally, where the syllabus is a
long list of citations and the entire job is keeping up with it. Every term
starts with the same hour of copying dates into a calendar, so I wrote
something to do it instead.

---

## What you get

| | |
| --- | --- |
| **One ledger** | Every week, every reading, one continuous table. Columns stay aligned from week 1 to week 15. |
| **Real citations** | Chicago, APA, MLA, Harvard or APSR, switchable after the fact. |
| **Deadlines that mean something** | Banded overdue / next 7 days / later, and "in 3 days" rather than a bare date. |
| **Correct anything** | Fix a citation, add a reading it missed, move a due date. Weights re-total as you go. |
| **Print it** | Black on white, named after the course, checkboxes you can tick with a pen. |
| **Nothing leaves** | Files are read in your browser. There is no server and no upload endpoint. |

## How accurate it is

The numbers matter more than the pitch, so they come first. Measured over 32
real syllabi, through the browser's path, which is what most people use:

| | |
| --- | --- |
| Course code | **100%** |
| Term | **97%** |
| Found a schedule | **81%** |
| Readings parsed into full citations | **85%** |
| Weights adding up to about 100 | **10 of 12** |

Reproduce the lot with `python scripts/measure.py <folder> --web`, or drop
`--web` for the command line's figures, which run a few points better because
it can see the ruled lines a table is drawn with and the browser cannot.

Reading lists are the weak spot, whilst everything structural is dependable.
Most of what fails was never a reading in the first place: week topics,
description paragraphs, columns lifted off a grading table. Keeping those out
took it from 66% to 85%.

Anything it cannot read, it shows you verbatim and marks for checking. It will
not quietly drop a reading or invent one. Where no schedule turns up, the PDF
usually has not got one.

Which is why everything stays editable. Instructors move deadlines and no
parser catches that, so a tracker you cannot correct goes stale by week three.
Courses read by an older version offer to read themselves again.

---

## On the command line

The command line is for bulk work: a folder of readings, full text search,
and publishing a site.

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

It all runs locally with no keys. There is an optional model layer that writes
reading briefs and does nothing else, so skip it and the rest still works.
Where a course bans AI, briefs are off for that course, and nothing here writes
anything you would submit.

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

Parsing is deterministic pattern matching, and that choice governs everything
else. Every extracted row records which rule produced it, whilst a line no rule
claims goes to review unparsed rather than being guessed at. A wrong citation
looks finished, a flagged one does not, and that asymmetry is worth the lower
headline number.

The same Python runs whether you use the command line or the browser, compiled
to WebAssembly for the latter. They do not get identical answers: on your own
machine it can see the ruled lines a table is drawn with, and in the browser it
has to work the columns out from where the text sits, so a handful of files come
out differently.

`ARCHITECTURE.md` has the details, including what the parser gets wrong and why.

## Publishing

Nothing reaches the public site unless it is named on an allowlist, and the
tests fail if something new shows up. What that permits is schedules,
citations, deadlines and bibliographies. Reading text, briefs, notes and
instructor contact details stay local. CI builds from `data/public.json`, which
you review before committing, whilst never touching your database at all.

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

Runs offline with no keys. The fixtures are invented PDFs copying the layouts
real syllabi use: bulleted schedules with odd glyph markers, ruled tables with
two meetings a week, labelled topic and reading blocks, two-column articles,
footnote-heavy pages, and one scan with no text layer. They assert exact
reading counts per week, because a parser that quietly loses one reading in
five otherwise looks entirely healthy.
