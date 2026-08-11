# schedule reader

Keep track of coursework readings. Give it your syllabi at the start of term
and your reading PDFs each week. It keeps the schedule, the citations, the
deadlines and the full text in one searchable place, and tells you each week
what you have, what is missing, and what is due.

There are two ways to use it.

## In a browser

<https://tobyn-smith.github.io/reader/>

Drag in a syllabus PDF and you get back the schedule, the readings as proper
citations, the deadlines and a bibliography, ready to print or save as a PDF.
Nothing to install, no account, no Python.

Your files are read in the browser and are never uploaded. There is no server
and no upload endpoint, so there is nothing to store or leak. Everything you
parse is kept in that browser only, and a "Clear all data" button removes it.
Export to JSON to move it to another machine.

The parser is the same Python the command line uses, compiled to WebAssembly
and run in a worker, so both paths give the same answers. The fixture suite
checks exactly that.

## How accurate it is

Read this before trusting the output. The parser is a set of patterns, not a
model, and syllabi are written in every layout a person can invent.

Measured over 24 real syllabi from one university, parsed and checked by hand:

| What | Rate |
| --- | --- |
| Recognised a syllabus from a reading | 100% |
| Course code | 100% |
| Term | 96% |
| Found the schedule | 79% |
| Readings turned into full citations | 66% |
| Weights totalling near 100% | 6 of 10 |

The structural fields are reliable. Reading lists are not, and that is the
number to keep in mind: a third of readings come through as the raw line from
your syllabus rather than as author, title and year.

What it will not do is hide that from you. A reading it cannot parse is shown
as the exact text from the PDF and marked for checking. Nothing is dropped
silently and nothing is invented. That is what the review step is for, and why
it is worth the few minutes at the start of term.

Where a schedule is missing entirely it is usually because the PDF has none:
the schedule lives on the course site, or the file carries only a deadline
grid with no topics or readings. In those cases the course, term and weights
still come through.

Layouts handled: bulleted lists, ruled tables, labelled blocks, date-led
headings, and numbered meetings with the date leading or trailing. Anything
else degrades to the closest parser and shows up as low confidence in review.

## On the command line

For batch work: a folder of readings, full text search, and publishing a site.

It has two halves that share one database:

**Syllabus intake.** Give it a syllabus PDF. It pulls out the course info, the
week-by-week schedule, each reading as a proper citation, each graded
assignment with its due date, and the policies you will need to look up later,
including the course's AI policy. It shows you the whole parse before saving
anything.

**Reading pipeline.** Drop your PDFs in a folder and run one command. Text is
extracted with page numbers kept all the way through. Two-column layouts are
read in the right order, footnotes are kept separate, and scanned pages are
flagged for OCR. Each file is matched to its syllabus entry, so `vault status`
can print a checklist:

    POLS 6510 Week 5 (9/11) Interstate Bargaining
      [x] Okonkwo 1995, Rationalist Accounts of Bargaining Failure
      [ ] Lindqvist 2006, War as an Invented Commitment Problem   MISSING
      [x] Osei et al 1999, An Institutional Account of the Invented Peace

    due
      POLS 6510  Reading Memo & Participation  weekly on thursday 09:00

`vault search` runs full text search over everything ingested and returns the
citation and page number with each hit.

Everything runs on your machine, offline, with no accounts and no keys. The
optional model layer writes reading briefs and does nothing else. Without it
the tool still does everything above. If a course bans AI use, briefs are
turned off for that course. Nothing in the tool generates submittable text.

## Install

Python 3.11 or newer.

    git clone https://github.com/tobyn-smith/reader
    cd reader
    python -m venv .venv
    .venv/Scripts/activate          # linux/mac: source .venv/bin/activate
    pip install -e ".[dev]"
    git config core.hooksPath .githooks

Optional extras. Each one adds a single feature:

- `ocrmypdf` on the PATH: read scanned PDFs
- `pagefind` (or npx): search on the built site
- `weasyprint`: print PDFs on your machine (CI makes them either way)

## Configure

Nothing to configure. Your database, PDFs, inbox and caches live in
`~/.seminar-vault/`, outside the repo, so course files cannot end up in git by
accident. To move them, copy `.env.example` to `.env` and set `VAULT_HOME`.

## Use

    vault syllabus syllabus.pdf       parse, review each flagged row, save
    vault ingest readings/            add reading pdfs; safe to re-run
    vault ingest                      same, from ~/.seminar-vault/inbox
    vault status                      this week: have, missing, due
    vault status --course "POLS 6510" --week 5
    vault search "commitment problem"
    vault brief 42                    needs a model key; off where AI is banned
    vault export --public             write the filtered data/public.json
    vault build --public --pdf        the site github pages serves
    vault build --private             everything, local only, never committed
    vault serve                       browse the private build

## Publishing

The public site on GitHub Pages shows schedules, citations, deadlines and
bibliographies. Nothing else. Every published field has to be on an allowlist,
and the test suite fails if anything new slips in. Reading text, briefs,
private notes and instructor contact details stay on your machine. CI builds
the site from one reviewed file, `data/public.json`, and never sees your
database, so it cannot leak what it cannot read. `ARCHITECTURE.md` has the
details, plus a guide for reaching your private build from a phone.

## Make it yours

The demo at `tobyn-smith.github.io/reader/demo/` is built from the invented
courses in `tests/fixtures/`. The repo holds no real coursework. To run your
own:

1. Fork the repo. In Settings, Pages, set the source to GitHub Actions.
2. Run `vault syllabus your-syllabus.pdf` for each course and review the parse.
3. Run `vault ingest your-readings/` as the term goes on.
4. Run `vault export --public`, read what it says it included and left out,
   then commit `data/public.json`. The push publishes your site.

Your database and PDFs stay in `~/.seminar-vault`, outside the repo. The
allowlist, the CI setup and the pre-commit hook all work the same in your
fork, so the only thing that can reach your public site is what the export
file contains.

## Tests

    pytest -q

The suite runs offline with no keys set. The fixtures are made-up PDFs that
copy the layouts real syllabi use: bulleted schedules with odd glyph markers,
ruled tables with two meetings a week, labelled topic and readings blocks,
two-column articles, footnote-heavy pages, and a scanned page with no text
layer. The tests check exact reading counts per week, because a parser that
quietly drops one reading in five looks correct in every other way.
