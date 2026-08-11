# Architecture

This file is written for the person who opens the repo in three months with no
memory of it. Read this before touching anything.

## What this is

A pipeline for coursework reading management, in two halves.

Half A takes a syllabus PDF and extracts the course, the week-by-week schedule,
every assigned reading as a structured citation, every graded deliverable, and
the policies that matter during the term. Nothing is written until the parse
has been reviewed and confirmed.

Half B takes the actual reading PDFs, extracts clean text with page numbers
preserved, links each file to the syllabus entry it satisfies, and stores
everything in a searchable local database. `vault status` reports what this
week assigns, what has been ingested, what is missing, and what is due.

The output is a static site built in two variants from the same templates: a
public one safe for GitHub Pages and a private one that never leaves the
machine.

## Layout

    src/vault/
      text/           pdf -> clean pages
        model.py        the extracted document, with no pdf library attached
        extract.py      pymupdf and pdfplumber. command line only
        runs.py         positioned text runs -> the same document. browser only
        normalize.py    the extraction artifact repairs
        layout.py       columns, running headers, footnotes
        chunk.py        page aligned segments
      syllabus/       clean pages -> structured parse. zones, schedule, citations,
                      deliverables, policies, dates, pipeline
      site/           parse + database -> static html and print pdfs
      llm/            the one module allowed to import a model sdk
      web.py          the browser entry points, json in and json out
      match.py        reading to syllabus scoring, shared by both paths
      config.py       where files live
      db.py           all sql, sqlite behind one module
      publish.py      the public/private boundary
      ingest.py       reading pdfs in
      status.py       the week view
      review.py       the confirmation step
      enrich.py       crossref and openlibrary, cached, additive only
      brief.py        model-backed briefs, gated by course ai policy
      cli.py          the vault command
    app/              the browser app. plain html, css and modules
      extract-worker.js   pdf.js
      parse-worker.js     pyodide running src/vault
      store.js            indexeddb
      render.js           the views
    db/migrations/    sqlite schema, applied in filename order
    db/postgres/      the same schema in postgres dialect, unused but current
    tests/fixtures/   synthetic pdfs reproducing hostile layouts
    scripts/          fixture generator, app bundler, the publish gate
    .githooks/        the pre-commit guard

## Decisions and why

Two extractors, one parser. Extraction is the only part that differs between
the command line and the browser. `text/model.py` holds the extracted document
and imports no pdf library, so `extract.py` (pymupdf and pdfplumber) and
`runs.py` (positioned text runs from pdf.js) are interchangeable and everything
downstream is shared. `tests/test_runs_parity.py` drives the same fixtures
through both and holds them to the same expected output, which is what stops
the two drifting apart.

Pyodide rather than a second parser in TypeScript. The citation patterns, the
week detection and the normalization table are the expensive part of this
project, and every one of them was arrived at by finding a case that broke.
Reimplementing them would mean rediscovering the same bugs. The cost is a large
download, so nothing loads until a file is picked and the service worker keeps
it afterwards.

Table structure is recovered differently in each path. pdfplumber reads ruled
lines directly. pdf.js exposes no rules at all, so `runs.py` infers columns
from where text starts and rows from vertical gaps in the leftmost column. The
two disagree on one point: cell extraction gives the header its own row, while
the geometric path folds it into the first data row, because the gap under a
heading is no larger than the gap between lines inside a cell. Rather than
tuning a threshold that would break on the next document, the schedule parser
strips header labels from the top of every cell and drops a row only when
nothing survives. That is correct for both.

Print output uses print CSS and `window.print()` in the browser, and WeasyPrint
on the command line. The browser already has a typesetter and a pdf writer, and
using them gives selectable text and correct page breaks for no bundle cost.
`pdf-lib` is not used anywhere.

Single threaded builds of pyodide. GitHub Pages cannot set response headers, so
`Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` cannot be sent,
which rules out `SharedArrayBuffer` and therefore WASM threading. A syllabus
parses in about two seconds single threaded, so the `coi-serviceworker` shim is
not worth its risk to first load. `app/_headers` is committed anyway: Cloudflare
Pages and Netlify honour it and GitHub Pages ignores it harmlessly.

SQLite over hosted Postgres. Nothing reads the database at request time, so a
server bought nothing but a connection string and a free tier to outgrow. The
schema is kept portable and `db/postgres/` holds the same DDL; the swap is
mechanical because every query already lives in `db.py`.

Static site over an app. The site is tables of readings and deadlines. It is
rebuilt when data changes, which is a few times a week, not per request. Plain
HTML with one stylesheet is faster, cannot break at 2 a.m., and is trivially
hostable anywhere.

Deterministic parsing over a model. The parsers are pattern sets built against
real syllabus structures, and every extracted row records which pattern
produced it and at what confidence. A model may only improve low-confidence
rows, never do the primary extraction. This is a cost decision and an accuracy
one: mechanical extraction is auditable, model extraction is not. The whole
pipeline runs with zero keys configured, which the test suite enforces.

Citation parsing refuses to guess. Anything no pattern claims lands in the
review queue as unparsed rather than being half-filled. A wrong citation is
worse than a flagged one, because a wrong one looks done.

Counts are the primary test currency. A parser that drops one reading in five
looks correct from the outside. Fixture tests assert exact per-week counts
before anything else.

The confirmation step is not skippable by accident. `vault syllabus` shows the
full parse and walks the low-confidence rows before anything is written. A
syllabus is parsed once a term; wrong data poisons everything downstream.

## The publishing boundary

This is the part with real consequences, so it is enforced three ways, each
independent of the others.

1. The export filter in `publish.py` is default deny. A field reaches
   `data/public.json` only if it is named in the `ALLOWED` map. Adding a schema
   column publishes nothing until someone adds it to the allowlist, and the
   test suite fails a payload carrying any unknown key.

2. CI never sees the database. The Pages workflow builds the public site from
   `data/public.json`, the one data file allowed in the repo, written by
   `vault export --public` and reviewed before committing. CI cannot leak what
   it cannot read.

3. The pre-commit hook (`git config core.hooksPath .githooks`) rejects any
   staged pdf, sqlite or db file outside `tests/fixtures/`, and anything over
   5 MB. The database and the reading library live under `~/.seminar-vault`,
   outside the working tree, so `git add -A` has nothing to sweep up.

What never publishes: extracted reading text (other people's copyright),
briefs (model output, opt-in per course), instructor emails and locations,
notes not explicitly marked shareable, and any course flagged sensitive.

Do not weaken this with an unlisted URL, robots.txt, or a client-side gate.
A public host without a real access layer is published to the world.

## Private access away from this machine

`vault build --private` renders everything, including full text and briefs, to
`_site_private/`, which is gitignored. `vault serve` serves it locally. That is
the default and it is enough for a desk.

To reach the private build from a phone or the library, deploy it to Cloudflare
Pages behind Cloudflare Access. By hand, from this machine, never from CI:

    npm install -g wrangler
    wrangler login
    vault build --private --pdf
    wrangler pages deploy _site_private --project-name seminar-vault-private

Then in the Cloudflare dashboard, Zero Trust, Access, Applications: add a
self-hosted application covering `seminar-vault-private.pages.dev`, policy
Allow, include emails: your email only, login method one-time PIN. The free
Zero Trust plan covers this at time of writing; verify at signup.

Alternative with no third-party auth: `tailscale serve` in front of
`vault serve` exposes the site to your own devices only. Not built here, just
noted.

## Print PDFs

WeasyPrint renders the semester plans, week sheets, bibliographies and the
deadlines document from the same payload as the site, using
`site/assets/print.css`. On Windows the native pango libraries are usually
absent; the build then says so and skips PDFs rather than failing. CI runs
Ubuntu and produces them every time. If a layout ever exceeds what WeasyPrint
can do, the fallback is headless Chromium via Playwright for that document
only; nothing needs it today.

## Known rough edges

The parsers fit the structures they were built against: bulleted, ruled table,
and labelled-block schedules. A genuinely novel layout degrades to the nearest
parser and shows up as low confidence and count warnings during review, which
is the intended failure mode, but the review step is then doing real work.

Front-matter title detection joins wrapped lines by continuation words. An
unusual header block can still truncate a title; it surfaces in review.

The document matcher scores author, title and year overlap from the first two
pages. Scanned files with no OCR yield no text and match nothing; install
ocrmypdf to close that gap.

Chunk embedding is a nullable column with no code behind it. If semantic search
ever earns its keep, add pgvector or sqlite-vec behind `db.py` and fill it; the
schema is already shaped for it.

`weasyprint` and `pagefind` are soft dependencies. Missing binaries degrade to
a message, never a failure.

OCR is not wired into the browser app. A scanned page is detected and reported
as having no text layer, and is left empty rather than guessed at. Tesseract.js
would slot into a third worker behind an explicit prompt; the detection and the
reporting are already there, the OCR pass is not.

The browser app has been exercised by hand through a real browser: parse,
review, confirm, all five views, reading match, reload persistence, and a check
that every network request stays same origin. It has not been run against a
mobile browser or a 200 page scan, and there is no headless browser test in CI
yet. `tests/test_runs_parity.py` covers the parsing half of that gap by driving
the same fixtures through the browser code path in Python.

## Running everything locally

    python -m venv .venv && .venv/Scripts/activate     # or bin/activate
    pip install -e ".[dev]"
    git config core.hooksPath .githooks

    vault syllabus path/to/syllabus.pdf     # parse, review, confirm
    vault ingest path/to/readings/          # or drop files in ~/.seminar-vault/inbox
    vault status                            # the week view
    vault search "some phrase"              # full text, cli
    vault export --public                   # writes data/public.json for review
    vault build --public --pdf              # what ci does
    vault build --private && vault serve    # the full private site locally

    pytest -q                               # the suite runs offline, no keys
    python scripts/make_fixtures.py         # regenerate the synthetic pdfs

The browser app:

    python scripts/build_app.py --vendor    # bundle the parser, fetch pdf.js and pyodide
    python -m http.server 8123 -d app       # then open http://127.0.0.1:8123

`--vendor` downloads pdf.js and the pyodide core into `app/vendor/`, which is
gitignored and rebuilt in CI. Nothing is loaded from a CDN at runtime: a tool
that promises files never leave the browser must not be calling anywhere while
it works.

    python scripts/check_publish.py _site   # the gate ci runs before deploying
