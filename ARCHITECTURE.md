# Architecture

Working notes for this repo. Read before changing the parsers.

## What this is

Two halves, one database.

Half A: syllabus PDF in, structured parse out. Course info, weekly schedule,
readings as citations, graded work with dates, policies. Nothing is saved
until the parse is reviewed.

Half B: reading PDFs in. Text extracted with page numbers kept, each file
matched to its syllabus entry. `vault status` prints what is assigned, what is
ingested, what is missing, what is due.

Output is a static site in two builds from the same templates. Public build
goes to GitHub Pages. Private build stays on the machine.

There is also a browser app (`app/`) that runs the same parser client side.
Files dropped there never leave the browser.

## Layout

    src/vault/
      text/           pdf -> clean pages
        model.py        extracted document, no pdf library imports
        extract.py      pymupdf + pdfplumber, cli only
        runs.py         positioned text runs -> same document, browser path
        normalize.py    extraction artifact repairs
        layout.py       columns, running headers, footnotes
        chunk.py        page aligned segments
      syllabus/       clean pages -> parse. zones, schedule, citations,
                      deliverables, policies, dates, pipeline
      site/           parse + db -> static html and print pdfs
      llm/            the only module allowed to import a model sdk
      web.py          browser entry points, json in / json out
      match.py        reading-to-syllabus scoring, shared
      config.py       file locations
      db.py           all sql
      publish.py      public/private filter
      ingest.py       reading pdfs in
      status.py       week view
      review.py       confirmation step
      enrich.py       crossref / openlibrary, cached, additive only
      brief.py        model briefs, gated by course ai policy
      cli.py          the vault command
    app/              browser app. plain html/css/js modules
      extract-worker.js   pdf.js
      parse-worker.js     pyodide running src/vault
      store.js            indexeddb
      render.js           views
    db/migrations/    sqlite schema
    db/postgres/      same schema, postgres dialect, unused
    tests/fixtures/   synthetic pdfs. no real course material anywhere in the repo
    scripts/          fixture generator, app bundler, publish gate
    .githooks/        pre-commit guard

## Decisions

Two extractors, one parser. extract.py (cli) and runs.py (browser) both
produce the ExtractedDoc in model.py. Everything downstream is shared.
test_runs_parity.py runs the same fixtures through both and compares.

Pyodide instead of a typescript rewrite. The citation patterns and week
detection took a long time to get right. A second implementation would drift.
Cost is a big download, so nothing loads until a file is picked, and the
service worker caches it after.

Tables differ by path. pdfplumber sees ruled lines. pdf.js does not, so
runs.py infers columns from where text starts and rows from anchor-column
gaps, with week markers as hard row starts. Cell headers get stripped
per cell in schedule.py since the two paths disagree about whether the header
is its own row.

Column mapping comes from the header row when one exists (week / date / topic /
unit / readings / due). Learned per grid, not per document, because pdfplumber
reports different phantom columns page to page. No header row means the old
positional reading.

Print output: print css + window.print() in the browser, WeasyPrint in the
cli. No js pdf library.

Pyodide is the single threaded build. GitHub Pages cannot set COOP/COEP
headers, so no SharedArrayBuffer, so no wasm threads. Parse time is a couple
of seconds, fine. `app/_headers` is committed for hosts that do honour it.

SQLite, not hosted postgres. Nothing reads the db at request time. Schema kept
portable, db/postgres/ has the same DDL.

Deterministic parsing, model second. Every extracted row records the pattern
that produced it and a confidence. A model may only improve low-confidence
rows. Zero keys configured must keep the whole pipeline working; a test
enforces it.

Citations never guess. Unmatched lines go to review as unparsed. A wrong
citation looks finished, a flagged one does not.

Counts are the main test currency. Fixture tests assert exact per-week reading
counts. A parser that drops one reading in five passes every other kind of
check.

## The theme

Institutional record: a catalogue, a ledger, an index. Dark by default, warm
near-black. Hierarchy comes from weight, scale and rule thickness, never from
colour or ornament.

Rule weights are the structure and are fixed. 6px above the masthead, 3px under
the course bar, the record header and above the colophon, 2px above every week
separator, 1px hair between reading rows. Nothing else draws a line, and
nothing is boxed, rounded, shadowed or animated.

`--flag` marks three conditions and no others: a file not held, an overdue
item, a restricted AI policy. A row that is held goes `--faint` and stays
upright, with no strike and no tick. Two things were caught breaking that rule
while it was built: a week with no reading was flagging its empty status, and
the withdraw and purge buttons were coloured. Both now carry no accent, the
buttons being set apart by a 2px border instead.

Three families, self-hosted. Archivo Narrow 700 for display, Source Serif 4 for
body, IBM Plex Mono for anything numeric, with `tabular-nums` set globally.
`vendor_fonts()` in scripts/build_app.py fetches the latin subset at build time
and writes vendor/fonts.css pointing at local files, so a visitor makes no
request off origin. 209 kB over six faces. The sheet is linked before app.css
and every family has a system fallback, so an unvendored checkout still works.

The week view is one continuous table, not a stack of blocks. Weeks are
separator rows inside it, which is the only way every column stays aligned from
week 1 to week 15. Two things are checked at 1440px: eight or more weeks
visible without scrolling, and each column resolving to exactly one left
offset across the whole term. Measured at the time of writing: ten weeks, zero
misaligned columns. If either fails, rows have grown too tall or the table has
been broken back into blocks.

## Editing after the parse

The browser app keeps an edit mode on the week and deadlines views. A reading
can be corrected, added or removed; a due date, title and weight likewise, with
the weight total recomputed on the spot. Every change writes straight to
IndexedDB, no save button.

This exists because the parse is a starting point rather than an answer. Two
things guarantee it: the parser reaches roughly 80% on reading lists, and an
instructor moving a deadline in week six is invisible to any parser at all. A
tracker that cannot be corrected is abandoned once it is wrong, which costs
more than the parsing gains.

A hand-typed reading carries `matched_pattern: "typed_by_hand"` and its text in
`work.rendered_override`. Both citation renderers honour that override, so a
correction made in one view shows in all of them, and a later reader can still
tell parser output from something a person typed.

## Publishing boundary

Three separate guards:

1. publish.py is default deny. A field reaches data/public.json only if named
   in ALLOWED. New schema columns publish nothing until allowlisted. Tests
   fail a payload with unknown keys.

2. CI never sees the database. The Pages workflow builds from data/public.json
   only, which is written by `vault export --public` and reviewed before
   commit.

3. The pre-commit hook (.githooks) rejects staged pdf/sqlite/db files outside
   tests/fixtures/ and anything over 5 MB. Data lives in ~/.seminar-vault,
   outside the tree.

Never published: extracted reading text, briefs, instructor emails and
locations, notes not marked shareable, courses flagged sensitive.

Do not swap any of this for an unlisted URL, robots.txt, or a client-side
gate. Public host, no access layer: published.

## Private access from other devices

Default: `vault build --private` (gitignored output), `vault serve` locally.

Remote, by hand, never from CI:

    npm install -g wrangler
    wrangler login
    vault build --private --pdf
    wrangler pages deploy _site_private --project-name seminar-vault-private

Then Cloudflare Zero Trust > Access > Applications: self-hosted app on the
pages.dev domain, allow one email, one-time PIN. Free tier covered this when
written, check at signup.

Or `tailscale serve` in front of `vault serve`. Not built, just works.

## Print PDFs

WeasyPrint renders semester plans, week sheets, bibliographies, deadlines from
the same payload as the site. Windows usually lacks the pango libraries; the
build says so and skips instead of failing. CI (ubuntu) always produces them.

## Known gaps

Schedule layouts handled: bulleted lists, ruled tables, labelled blocks,
date-led headings ("January 17th: Module 1"), numbered meetings with the date
either leading ("1. August 14: Topic") or trailing ("1. Topic (01/13)").

Detection picks a parser, then all three run and the fullest reading list
wins, detection breaking ties. This is not a fallback for failure, it is the
normal path: a syllabus that prints a summary grid and the real week by week
listing gives the grid more rows and the listing all the readings, and no
amount of layout sniffing gets that right up front.

Some syllabi have no weekly schedule in the pdf at all, or only a deadline
grid with no topics or readings. Those parse to an empty schedule with course
info and weights still extracted. That is the correct output, not a bug.

Date separators seen in the wild and handled: space, none at all when kerning
drops it, a period after an abbreviation, and a comma ("February, 5"). Meeting
numbers may lose the space after them too ("1.August 14"), so that space is
optional wherever a number prefixes a heading.

A syllabus that never prints its subject prefix, labelling the number instead
("Course Number: 4316" with the department on another line), gets the bare
number as its code. Deriving a prefix from the department name would be a
guess.

One-line-per-row grids have no ruled lines the runs path can see. Plain
run-start clustering mistakes hanging-indent citation lists for tables, so it
is only allowed behind a gate: a header line naming a time column and a
content column. Grids without any header row stay invisible to the browser
path; closing that fully would need line/rect data from the pdf.js operator
list.

Weight reconciliation merges a summary-table row with its prose paragraph on
equal weight plus at least two shared distinctive words. Type words (exam,
quiz, essay, memo) do not count as shared, because a midterm and a final are
both exams, often for the same weight, and merging them silently drops a whole
assignment from the total. Totals off 100 are reported, never corrected.

Reading lists exclude anything that is not a reading: learning objectives,
goals, discussion questions, glossary blocks, the prose description under a
week heading, and table columns the header names as due work. Both the
labelled and the bulleted parser honour those labels; a syllabus that uses
labels at all only starts collecting readings once a label says so.

Reading lists inside table cells are the weakest output. Wrapped urls can
leave fragments; obvious ones are dropped. A topic cell can still leak into
readings on tables wider than the mapped columns.

That leak was the main accuracy problem, and it was misdiagnosed for a while as
a citation parsing problem. Over 24 real syllabi it once produced 588 reading
rows, 387 of them parsing into full citations. Bucketing the 201 that did not
showed four fifths were never citations: 87 prose or topic labels, 50 too short
to be anything, 26 schedule fragments, 3 chapter pointers, and only 35 actually
reference shaped.

Five fixes in test_reading_list_hygiene.py took that to 487 rows and 390
citations, 66% to 80%, and none of them touched a citation pattern:

- a header naming every column and none of them readings yields no readings.
  the fallback that sweeps unnamed columns now excludes the due columns, so a
  grading table stops contributing thirteen weeks of "Participation".
- a date led line inside a week is that week's own timetable. it fails
  is_session_head for sitting mid block, and was being collected as a reading.
- a row that is only a url belongs to the row above, whether or not it kept its
  scheme. joining them also completes the citation that lost its link.
- a short title case line with no year, pages, quotes or link is a divider
  inside the list, not a reading. it becomes the week's topic if there is none.
- a long run of words carrying no year, quoted title, page marker or link, and
  not opening with a surname, is the week's description paragraph. the page
  test has to accept "Pages 29-37" spelled out; matching only "pp." threw away
  a real reading and that is what the test pins.

What remains splits about a third genuine short form references ("Nye, Part II,
pp. 113-234", naming a book assigned weeks earlier) and two thirds still junk.
Measure before writing another citation pattern; that is not where it is going.

Lookup rescue (lookup.py, called from enrich.py) sends a line no pattern could
read to crossref and offers the result in review. The gate wants near total
title agreement, the first author present in the line, a year to corroborate
against, and a container that is not a reference work. Every one of those
came from watching a looser gate fail: at 0.7 title cover roughly three
quarters of what came back was wrong, matching schedule fragments to papers
sharing vocabulary, and matching books to published reviews of the book, which
carry the book's exact title with the reviewer listed first.

The rescue is worth about one point of accuracy, which is small, and it is
kept because the five it recovers are correct and it costs nothing when it
finds nothing. It is command line only. The browser build promises that
nothing leaves the machine, and one point is not worth qualifying that promise
even behind a toggle. web.py must stay free of network calls.

Title detection can truncate an unusual front-matter block. Surfaces in
review.

The matcher needs text. Scanned files with no OCR match nothing. Install
ocrmypdf for the cli. The browser app detects a missing text layer and says
so; tesseract.js is not wired in yet.

Chunk embedding is a nullable column with no code behind it. Add sqlite-vec or
pgvector behind db.py if semantic search ever earns its place.

weasyprint and pagefind are soft dependencies, missing ones degrade to a
message.

No headless browser test in CI. Parity tests cover the parsing half by
running the browser code path in python. The app itself was exercised by hand:
parse, review, confirm, views, matching, reload persistence, and a check that
no request leaves the origin while a file is processed.

## How far apart the two paths actually are

Measured over 31 real syllabi, comparing session and reading counts from
extract.py against runs.py fed the same files:

    13   agree exactly
     7   both pick a line parser, and still disagree
     6   both pick the table parser, and still disagree
     3   one picks labelled, the other bulleted
     2   one picks table, the other bulleted

So the split is roughly even between "the parsers agree on the layout and read
it differently" and "they do not even agree what the layout is". Anyone
planning to close this should not expect one fix.

One case is closed and worth reading as the pattern for the rest. A syllabus
printed its deadline calendar above its schedule, as a column of date-led
lines. find_schedule_start would accept a single date-led line as the start of
the schedule zone, so on the runs path that block captured the zone and each
entry in it became a session: 34 sessions against 27, with four phantom
duplicate-date warnings. The two extractors split lines slightly differently,
which is why only one of them tripped it. The fix was precedence, not
geometry: an explicit schedule heading now outranks a bare dated line, while
week markers still outrank both. Both paths now return 27 sessions and no
warnings, confirmed against real pdf.js in a browser rather than against a
payload built from pymupdf.

The remaining table disagreements are a different animal. On one file the
runs path infers 2 to 4 columns where the ruled grid has 6, and picks up a
numbered policies list on the page above instead of the header row. pdfplumber
reads the ruled lines; runs.py has only where text starts, so it under-
segments. Closing that needs line and rect geometry out of the pdf.js operator
list, which is a change to extract-worker.js rather than to any parser.

Know what the parity tests cannot see. They feed runs.py a payload built from
pymupdf spans, which is the right shape but not the same data pdf.js produces.
A whole class of bug lives in that difference: pdf.js reports a column gap as
a whitespace run many times wider than a space, where pymupdf has already
expanded it, so a grading table that read correctly in every test came out
with one weight instead of four in a real browser. Anything touching runs.py
needs checking in a browser, not only under pytest, and the cases found that
way get pinned directly in test_runs_parity.py rather than through a fixture.

## Running locally

    python -m venv .venv && .venv/Scripts/activate     # or bin/activate
    pip install -e ".[dev]"
    git config core.hooksPath .githooks

    vault syllabus path/to/syllabus.pdf     # parse, review, confirm
    vault ingest path/to/readings/          # or ~/.seminar-vault/inbox
    vault status
    vault search "some phrase"
    vault export --public                   # writes data/public.json
    vault build --public --pdf              # what ci does
    vault build --private && vault serve

    pytest -q                               # offline, no keys
    python scripts/make_fixtures.py         # regenerate synthetic pdfs

Browser app:

    python scripts/build_app.py --vendor    # bundle parser, fetch pdf.js + pyodide
    python -m http.server 8123 -d app

vendor/ is gitignored and rebuilt in CI. Nothing loads from a CDN at runtime.

    python scripts/check_publish.py _site   # the gate ci runs before deploy
