"""the vault command.

  vault syllabus <pdf>      parse, review, confirm, write
  vault ingest <path>       take reading pdfs into the library
  vault status              this week across every course
  vault search <query>      full text search over everything ingested
  vault brief <work-id>     generate a brief where the course policy allows it
  vault export --public     write the reviewed public json into the repo
  vault build               render the site, public or private
  vault serve               local server over the private build
  vault db migrate          apply schema migrations
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.server
import json
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

from . import config as config_mod
from . import db as db_mod


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    config = config_mod.load().ensure()
    return args.handler(args, config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault", description="syllabus and reading pipeline")
    commands = parser.add_subparsers(dest="command")

    syllabus = commands.add_parser("syllabus", help="parse a syllabus pdf and review the result")
    syllabus.add_argument("pdf", type=Path)
    syllabus.add_argument("--yes", action="store_true", help="accept the parse without the review prompt")
    syllabus.add_argument("--json", type=Path, help="write the parse to a file instead of the database")
    syllabus.add_argument("--no-enrich", action="store_true", help="skip crossref and openlibrary lookups")
    syllabus.add_argument(
        "--no-rescue",
        action="store_true",
        help="skip crossref lookups for lines no citation pattern could read",
    )
    syllabus.set_defaults(handler=cmd_syllabus)

    ingest = commands.add_parser("ingest", help="ingest reading pdfs")
    ingest.add_argument("path", type=Path, nargs="?", help="file or directory, defaults to the inbox")
    ingest.add_argument("--ocr", choices=["auto", "never", "always"], default="auto")
    ingest.set_defaults(handler=cmd_ingest)

    status = commands.add_parser("status", help="what is assigned, present, missing and due")
    status.add_argument("--course", help="limit to one course code")
    status.add_argument("--week", type=int)
    status.add_argument("--date", help="pretend today is this date, yyyy-mm-dd")
    status.set_defaults(handler=cmd_status)

    search = commands.add_parser("search", help="full text search over ingested readings")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(handler=cmd_search)

    brief = commands.add_parser("brief", help="generate a brief for a work")
    brief.add_argument("work_id", type=int)
    brief.add_argument("--force", action="store_true", help="override a prohibited or restricted course policy")
    brief.set_defaults(handler=cmd_brief)

    export = commands.add_parser("export", help="write the filtered public data file")
    export.add_argument("--public", action="store_true", required=True)
    export.set_defaults(handler=cmd_export)

    build = commands.add_parser("build", help="render the static site")
    scope = build.add_mutually_exclusive_group()
    scope.add_argument("--public", action="store_true")
    scope.add_argument("--private", action="store_true")
    build.add_argument("--pdf", action="store_true", help="also render the print pdfs")
    build.set_defaults(handler=cmd_build)

    serve = commands.add_parser("serve", help="serve the private build locally")
    serve.add_argument("--port", type=int, default=8377)
    serve.set_defaults(handler=cmd_serve)

    database = commands.add_parser("db", help="database maintenance")
    database.add_argument("action", choices=["migrate"])
    database.set_defaults(handler=cmd_db)

    return parser


def cmd_syllabus(args, config) -> int:
    from .review import review_and_confirm
    from .syllabus.pipeline import parse_syllabus

    if not args.pdf.exists():
        print(f"no such file: {args.pdf}", file=sys.stderr)
        return 1

    print(f"parsing {args.pdf.name}")
    parsed = parse_syllabus(args.pdf, threshold=config.threshold)

    if not args.no_enrich:
        from .enrich import enrich_parse

        enriched = enrich_parse(parsed, cache_dir=config.cache, rescue=not args.no_rescue)
        if enriched.filled:
            print(f"enrichment filled {enriched.filled} fields from crossref and openlibrary")
        if enriched.looked_up:
            print(
                f"crossref matched {enriched.suggested} of {enriched.looked_up} unreadable "
                "lines, offered as suggestions in review"
            )

    if args.json:
        args.json.write_text(
            json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.json}, nothing committed to the database")
        return 0

    confirmed = review_and_confirm(parsed, auto_accept=args.yes)
    if confirmed is None:
        print("nothing written")
        return 1

    conn = db_mod.open_vault(config)
    course_id = db_mod.write_parse(conn, confirmed)
    print(f"committed course {course_id}: {confirmed['course'].get('code')} "
          f"with {len(confirmed['sessions'])} sessions")
    return 0


def cmd_ingest(args, config) -> int:
    from .ingest import ingest_path
    from .status import cite_label

    target = args.path or config.inbox
    if not target.exists():
        print(f"no such path: {target}", file=sys.stderr)
        return 1

    conn = db_mod.open_vault(config)
    results = ingest_path(conn, target, ocr=args.ocr)
    if not results:
        print("no pdfs found")
        return 0

    for result in results:
        if result.skipped:
            print(f"  already ingested  {result.path.name}")
            continue
        note = ""
        if result.matched_work_id:
            row = conn.execute(
                "select w.*, w.pages as work_pages, '' as raw_source_text from work w where id = ?",
                (result.matched_work_id,),
            ).fetchone()
            note = f" -> {cite_label(row)} ({result.match_confidence})"
        elif result.match_method == "below threshold":
            note = " -> no confident match, link it by hand"
        ocr = " [ocr]" if result.ocr_used else ""
        print(f"  {result.chunks:4d} chunks  {result.path.name}{ocr}{note}")
        for warning in result.warnings or []:
            print(f"        note: {warning}")
    return 0


def cmd_status(args, config) -> int:
    from .status import render, upcoming_deliverables, week_status

    conn = db_mod.open_vault(config)
    on = dt.date.fromisoformat(args.date) if args.date else None
    statuses = week_status(conn, course_code=args.course, week=args.week, on=on)
    deliverables = upcoming_deliverables(conn, on=on)
    if args.course:
        deliverables = [
            d for d in deliverables
            if d["course_code"].replace(" ", "").lower() == args.course.replace(" ", "").lower()
        ]
    print(render(statuses, deliverables))
    return 0


def cmd_search(args, config) -> int:
    conn = db_mod.open_vault(config)
    query = " ".join(args.query)
    rows = db_mod.search_chunks(conn, query, args.limit)
    if not rows:
        print("no matches")
        return 0
    for row in rows:
        source = row["title"] or row["filename"]
        print(f"{source}, p. {row['page_number']}")
        print(f"  {row['excerpt']}")
    return 0


def cmd_brief(args, config) -> int:
    from .brief import generate_brief

    conn = db_mod.open_vault(config)
    result = generate_brief(conn, args.work_id, force=args.force)
    print(result.message)
    return 0 if result.ok else 1


def cmd_export(args, config) -> int:
    from .publish import write_public_export

    conn = db_mod.open_vault(config)
    summary = write_public_export(conn, config.public_export)
    print(summary.render())
    print(f"\nwrote {config.public_export}")
    print("review it, then commit it. it is the only data file that belongs in the repo.")
    return 0


def cmd_build(args, config) -> int:
    from .site.build import build, build_private_payload, load_public_payload
    from .site.pdf import build_pdfs

    private = args.private or not args.public
    if private:
        conn = db_mod.open_vault(config)
        payload = build_private_payload(conn)
        target = config.private_site
    else:
        if not config.public_export.exists():
            print(
                f"{config.public_export} does not exist. run `vault export --public` first.",
                file=sys.stderr,
            )
            return 1
        payload = load_public_payload(config.public_export)
        target = config.public_site

    report = build(payload, target, private=private)
    print(report.render())

    if args.pdf:
        pdf_report = build_pdfs(payload, target / "pdf")
        if pdf_report.skipped_reason:
            print(f"pdfs skipped: {pdf_report.skipped_reason}")
        else:
            print(f"pdfs written: {len(pdf_report.written)}")

    _run_pagefind(target)
    return 0


def _run_pagefind(target: Path) -> None:
    """index the built html if the pagefind binary is around.

    npx works too. if neither is present the search page says the index is
    missing and everything else still works.
    """
    binary = shutil.which("pagefind")
    command = [binary, "--site", str(target)] if binary else None
    if command is None and shutil.which("npx"):
        command = ["npx", "--yes", "pagefind", "--site", str(target)]
    if command is None:
        print("pagefind not found, search index not built")
        return
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=600)
        print("search index built")
    except (subprocess.SubprocessError, OSError) as error:
        print(f"pagefind failed: {error}")


def cmd_serve(args, config) -> int:
    target = config.private_site
    if not target.exists():
        print("no private build yet. run `vault build --private` first.", file=sys.stderr)
        return 1
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(target))
    print(f"serving {target} on http://127.0.0.1:{args.port}")
    try:
        http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_db(args, config) -> int:
    conn = db_mod.connect(config.database)
    applied = db_mod.migrate(conn)
    if applied:
        for name in applied:
            print(f"applied {name}")
    else:
        print("schema is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
