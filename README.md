# schedule reader

Give it your syllabi at the start of term and your reading PDFs as you go. It
pulls out the schedule, the readings and the deadlines, then tells you each week
what's assigned and what you haven't got yet.

Two ways to run it.

## In a browser

<https://tobyn-smith.github.io/reader/>

Drop a syllabus PDF in and you get the schedule, the readings as citations, the
deadlines, and a bibliography you can print. No install, no account.

Files never leave your machine. There's no server behind this and no upload
endpoint, so there's nothing to leak. What you parse lives in that browser and
nowhere else, which also means clearing your browser data wipes it. Export to
JSON if you want it somewhere safer.

It runs the same Python as the command line, compiled to WebAssembly. Both paths
get tested against the same fixtures.

## How accurate it is

Worth knowing before you lean on it. This is pattern matching, not a model, and
people write syllabi in whatever layout occurs to them that morning.

24 real syllabi, parsed and checked by hand:

| | |
| --- | --- |
| Told a syllabus from a reading | 100% |
| Course code | 100% |
| Term | 96% |
| Found a schedule | 79% |
| Readings parsed into full citations | 77% |
| Weights adding up to about 100 | 6 of 10 |

Course code and term are dependable. Reading lists are the weak spot, and the
reason is worth knowing: most of what fails was never a reading. Week topics,
prose from under a heading, a grading table's columns, and the week's own
timetable were all being swept into reading lists and then counted as things
you hadn't read yet.

That was 66% until recently. Keeping non-readings out is what moved it to 77%,
and there's more of it left. Of the rows that still fail, about a third are
genuine references in a short form the patterns can't unpick, like "Nye, Part
II, pp. 113-234" pointing at a book named weeks earlier. The rest is still
junk that shouldn't be in the list.

Anything it can't read, it shows you verbatim and marks for checking. It doesn't
drop things quietly and it doesn't invent them. That's what the review step is
for.

When no schedule turns up it's usually because the PDF hasn't got one, either
because it lives on the course site or the file is really just a grading table.
Course info and weights still come out.

Layouts it knows: bulleted lists, ruled tables, labelled blocks, date-led
headings, and numbered meetings with the date at either end. Anything stranger
falls back to the nearest parser and shows up as low confidence.

The command line also asks Crossref about lines it couldn't parse, and offers
whatever comes back for you to confirm. The gate is strict on purpose, so it
only recovers about one row in a hundred. The browser doesn't do this, since
nothing is meant to leave your machine there.

## On the command line

Better for bulk work: a folder of readings, full text search, publishing a site.

Two halves sharing one database.

**Syllabus intake.** Point it at a PDF. You get course info, the weekly
schedule, readings as citations, graded work with due dates, and the policies
you'll want to look up later, including whatever the course says about AI. It
shows you all of it before writing anything.

**Reading pipeline.** Put PDFs in a folder and run one command. Page numbers
survive the whole way through. Two-column articles come out in reading order,
footnotes stay separate, and scanned pages get flagged for OCR. Each file gets
matched to its syllabus entry, so `vault status` can print:

    POLS 6510 Week 5 (9/11) Interstate Bargaining
      [x] Okonkwo 1995, Rationalist Accounts of Bargaining Failure
      [ ] Lindqvist 2006, War as an Invented Commitment Problem   MISSING
      [x] Osei et al 1999, An Institutional Account of the Invented Peace

    due
      POLS 6510  Reading Memo & Participation  weekly on thursday 09:00

`vault search` searches everything you've ingested and gives you the citation
and page number with each hit.

It all runs locally with no keys. There's an optional model layer that writes
reading briefs and does nothing else; skip it and the rest still works. Where a
course bans AI, briefs are off for that course. Nothing here writes anything
you'd submit.

## Install

Python 3.11 or newer.

    git clone https://github.com/tobyn-smith/reader
    cd reader
    python -m venv .venv
    .venv/Scripts/activate          # linux/mac: source .venv/bin/activate
    pip install -e ".[dev]"
    git config core.hooksPath .githooks

Optional, one feature each:

- `ocrmypdf` on the PATH for scanned PDFs
- `pagefind` for search on the built site
- `weasyprint` for print PDFs locally (CI builds them regardless)

## Configure

Nothing to configure. Your database, PDFs and caches sit in `~/.seminar-vault/`,
well outside the repo, so coursework can't wander into a commit. Copy
`.env.example` to `.env` and set `VAULT_HOME` to put them elsewhere.

## Use

    vault syllabus syllabus.pdf       parse, review, save
    vault ingest readings/            add reading pdfs, safe to re-run
    vault ingest                      same, from ~/.seminar-vault/inbox
    vault status                      this week: have, missing, due
    vault status --course "POLS 6510" --week 5
    vault search "commitment problem"
    vault brief 42                    needs a model key, off where AI is banned
    vault export --public             write the filtered data/public.json
    vault build --public --pdf        what github pages serves
    vault build --private             everything, local only
    vault serve                       browse the private build

## Publishing

The public site carries schedules, citations, deadlines and bibliographies, and
that's the lot. A field has to be named on an allowlist to get out, and the
tests fail if something new shows up. Reading text, briefs, notes and instructor
contact details stay local. CI builds from `data/public.json`, which you review
before committing, and never touches your database. `ARCHITECTURE.md` covers the
rest, including reaching your private build from a phone.

## Make it yours

The demo at `tobyn-smith.github.io/reader/demo/` runs on invented courses from
`tests/fixtures/`. There's no real coursework in this repo. For your own:

1. Fork it. Settings, Pages, source: GitHub Actions.
2. `vault syllabus your-syllabus.pdf` per course, and review the parse.
3. `vault ingest your-readings/` as term goes on.
4. `vault export --public`, read what it says it kept and dropped, then commit
   `data/public.json`. Pushing publishes.

Your database and PDFs stay in `~/.seminar-vault`. The allowlist, the CI setup
and the pre-commit hook all carry over to your fork.

## Tests

    pytest -q

Runs offline with no keys. Fixtures are invented PDFs copying the layouts real
syllabi use: bulleted schedules with odd glyph markers, ruled tables with two
meetings a week, labelled topic and reading blocks, two-column articles,
footnote-heavy pages, and one scan with no text layer. They assert exact reading
counts per week, because a parser that quietly loses one reading in five
otherwise looks fine.
