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
date-led headings ("January 17th: Module 1"). Anything else degrades to the
closest parser and shows up as low confidence plus count warnings in review.

Some syllabi have no weekly schedule in the pdf at all, or only a deadline
grid with no topics or readings. Those parse to an empty schedule with course
info and weights still extracted. That is the correct output, not a bug.

One-line-per-row grids have no ruled lines the runs path can see. Plain
run-start clustering mistakes hanging-indent citation lists for tables, so it
is only allowed behind a gate: a header line naming a time column and a
content column. Grids without any header row stay invisible to the browser
path; closing that fully would need line/rect data from the pdf.js operator
list.

Weight reconciliation merges a summary-table row with its prose paragraph on
equal weight plus title overlap. Works on the cases seen so far, not general.
Totals off 100 are reported, never corrected.

Reading lists inside table cells are the weakest output. Wrapped urls can
leave fragments; obvious ones are dropped. A topic cell can still leak into
readings on tables wider than the mapped columns.

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
