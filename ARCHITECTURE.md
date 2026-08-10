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
      text/           pdf -> clean pages. extraction, layout, normalization, chunking
      syllabus/       clean pages -> structured parse. zones, schedule, citations,
                      deliverables, policies, dates, pipeline
      site/           parse + database -> static html and print pdfs
      llm/            the one module allowed to import a model sdk
      config.py       where files live
      db.py           all sql, sqlite behind one module
      publish.py      the public/private boundary
      ingest.py       reading pdfs in
      status.py       the week view
      review.py       the confirmation step
      enrich.py       crossref and openlibrary, cached, additive only
      brief.py        model-backed briefs, gated by course ai policy
      cli.py          the vault command
    db/migrations/    sqlite schema, applied in filename order
    db/postgres/      the same schema in postgres dialect, unused but current
    tests/fixtures/   synthetic pdfs reproducing hostile layouts
    scripts/          fixture generator
    .githooks/        the pre-commit guard

## Decisions and why

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
