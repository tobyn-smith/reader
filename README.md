# seminar vault

A reading vault for graduate coursework. Hand it your syllabi at the start of
term and your reading PDFs each week; it keeps the schedule, the citations, the
deadlines and the full text in one searchable place, and tells you every week
what you have, what is missing, and what is due.

Two halves, one database:

**Syllabus intake.** Give it a syllabus PDF. It extracts the course metadata,
the week-by-week schedule, every assigned reading as a structured citation,
every graded deliverable with its due date, and the policies worth looking up
mid-term, including each course's AI policy. It shows you the whole parse for
confirmation before writing anything, because a syllabus is parsed once and
wrong data poisons the term.

**Reading pipeline.** Drop the actual PDFs in a folder and run one command.
Text is extracted with page numbers preserved through the entire pipeline,
two-column layouts read in order, footnotes kept separately, scanned pages
routed to OCR and flagged. Each file is matched to the syllabus entry it
satisfies, so `vault status` can print the checklist:

    POLS 6510 Week 5 (9/11) Interstate Bargaining
      [x] Okonkwo 1995, Rationalist Accounts of Bargaining Failure
      [ ] Lindqvist 2006, War as an Invented Commitment Problem   MISSING
      [x] Osei et al 1999, An Institutional Account of the Invented Peace

    due
      POLS 6510  Reading Memo & Participation  weekly on thursday 09:00

In April, when you half-remember a passage from a week-six reading,
`vault search` returns it with the citation and the page number, ready to paste
into a footnote.

Everything runs locally, offline, with no accounts and no keys. The optional
model layer generates reading briefs and nothing else; without it the tool is
complete. Where a course prohibits AI use, brief generation is disabled for
that course by default, and the tool never generates submittable prose for
anyone.

## Install

Python 3.11 or newer.

    git clone https://github.com/tobyn-smith/reader
    cd reader
    python -m venv .venv
    .venv/Scripts/activate          # linux/mac: source .venv/bin/activate
    pip install -e ".[dev]"
    git config core.hooksPath .githooks

Optional, each unlocking one feature and nothing else:

- `ocrmypdf` on the PATH: text from scanned PDFs
- `pagefind` (or npx): search on the built site
- `weasyprint`: print PDFs locally (CI produces them regardless)

## Configure

Nothing is required. The database, reading library, inbox and caches live under
`~/.seminar-vault/`, outside the repository, so course PDFs can never end up in
git history. To move them, copy `.env.example` to `.env` and set `VAULT_HOME`.

## Use

    vault syllabus syllabus.pdf       parse, review row by row, confirm, commit
    vault ingest readings/            ingest pdfs; re-running is a no-op
    vault ingest                      same, from ~/.seminar-vault/inbox
    vault status                      this week: have, missing, due
    vault status --course "POLS 6510" --week 5
    vault search "commitment problem"
    vault brief 42                    model-backed, off where a course bans AI
    vault export --public             write the filtered data/public.json
    vault build --public --pdf        the site github pages serves
    vault build --private             everything, gitignored, local only
    vault serve                       browse the private build

## Publishing

The public site on GitHub Pages carries schedules, citations, deadlines and
bibliographies, nothing else. The filter is default-deny and tested: extracted
reading text, briefs, private notes and instructor contact details never leave
the machine, and CI builds the site from the reviewed `data/public.json`
without ever seeing the database. `ARCHITECTURE.md` covers the boundary in
detail, plus a runbook for reaching the private build from other devices.

## Make it yours

The deployed demo at `tobyn-smith.github.io/reader` is built entirely from the
invented courses in `tests/fixtures/`, so the repository carries no real
coursework. To run it with your own courses:

1. Fork the repo, then in Settings, Pages, set the source to GitHub Actions.
2. Locally: `vault syllabus your-syllabus.pdf` for each course, review the
   parse, confirm.
3. `vault ingest your-readings/` as the term goes on.
4. `vault export --public`, read the printed summary of what is included and
   withheld, then commit `data/public.json`. The push builds and publishes
   your site.

Your database and PDFs stay under `~/.seminar-vault`, outside the repo. The
export allowlist, the CI isolation and the pre-commit hook all hold for your
fork exactly as they do here, so the only thing that can reach your public
site is what the reviewed export file contains.

## Tests

    pytest -q

The suite runs offline with no keys in the environment. Fixtures are synthetic
PDFs that reproduce the layouts real syllabi use: glyph-bulleted schedules,
ruled tables with two meetings per week, labelled blocks with inspectional
readings, two-column articles, footnote-heavy pages, and a scanned page with no
text layer. Counting tests assert exact per-week reading counts, because a
parser that silently drops one reading in five is indistinguishable from a
correct one any other way.
