-- sqlite is the source of truth. one file, no connection string, no cold start.
-- db/postgres/ holds the same shape in postgres dialect; the repository layer is
-- the only thing that would need to change to swap.

create table if not exists schema_migration (
    name       text primary key,
    applied_at text not null default (datetime('now'))
);

create table course (
    id               integer primary key autoincrement,
    code             text not null,
    title            text not null,
    term             text,
    year             integer,
    instructor_name  text,
    -- withheld from the public build. see publish.py.
    instructor_email text,
    meeting_time     text,
    -- withheld from the public build.
    location         text,
    site_url         text,
    citation_style   text,
    -- opt in per course before any model output reaches the published site
    publish_briefs   integer not null default 0,
    -- set by hand when a course's policies make it unwise to publish anything
    sensitive        integer not null default 0,
    source_file_hash text not null unique,
    source_filename  text,
    parsed_at        text not null default (datetime('now'))
);

create index course_term_year_idx on course (year desc, term);

create table course_policy (
    id          integer primary key autoincrement,
    course_id   integer not null references course (id) on delete cascade,
    policy_type text not null check (policy_type in (
                    'ai_use', 'late_work', 'attendance', 'grading_scale',
                    'academic_honesty', 'boilerplate', 'other')),
    ai_stance   text check (ai_stance in ('prohibited', 'restricted', 'permitted', 'unstated')),
    heading     text,
    body        text not null,
    page_number integer,
    confidence  real not null default 1.0,
    created_at  text not null default (datetime('now'))
);

create index course_policy_course_idx on course_policy (course_id, policy_type);

-- one row per meeting. a course meeting twice a week with different readings
-- each time gets two rows sharing week_number, split by sub_session_label.
create table session (
    id                integer primary key autoincrement,
    course_id         integer not null references course (id) on delete cascade,
    week_number       integer,
    meeting_date      text,
    sub_session_label text,
    topic             text,
    section_heading   text,
    session_type      text not null default 'reading' check (session_type in (
                          'reading', 'no_reading', 'exam', 'holiday',
                          'guest', 'review', 'assignment', 'presentation')),
    -- document order. weeks skip and repeat in real syllabi, so ordinal rather
    -- than week_number is what keeps the schedule stable.
    ordinal           integer not null,
    page_number       integer,
    raw_source_text   text,
    confidence        real not null default 1.0
);

create unique index session_slot_idx on session (course_id, ordinal);
create index session_week_idx on session (course_id, week_number);
create index session_date_idx on session (course_id, meeting_date);

create table work (
    id                integer primary key autoincrement,
    -- json array of {surname, given, literal}. literal carries institutional
    -- authors that do not split into given and family names.
    authors           text not null default '[]',
    title             text,
    container         text,
    publisher         text,
    year              integer,
    year_end          integer,
    -- for open ended series dates written as "2000-"
    year_is_open      integer not null default 0,
    volume            text,
    issue             text,
    pages             text,
    doi               text,
    url               text,
    -- agency document numbers are real identifiers and worth keeping
    report_number     text,
    work_type         text not null default 'unknown' check (work_type in (
                          'journal_article', 'book', 'book_chapter', 'report',
                          'news_article', 'web_page', 'government_document',
                          'unknown')),
    rendered_citation text,
    raw_source_text   text not null,
    matched_pattern   text,
    signature         text,
    enriched_from     text,
    confidence        real not null default 1.0,
    created_at        text not null default (datetime('now'))
);

create index work_signature_idx on work (signature);
create index work_year_idx on work (year);
create unique index work_doi_idx on work (lower(doi)) where doi is not null;

-- fields confirmed by hand. enrichment must never overwrite these.
create table work_locked_field (
    work_id    integer not null references work (id) on delete cascade,
    field_name text not null,
    primary key (work_id, field_name)
);

create table assigned_reading (
    id                integer primary key autoincrement,
    session_id        integer not null references session (id) on delete cascade,
    work_id           integer not null references work (id) on delete cascade,
    -- a syllabus that labels four items "Readings" and a fifth "Review
    -- (Inspectional Reading)" is saying to read them differently. keep it.
    requirement_level text not null default 'required' check (requirement_level in (
                          'required', 'recommended', 'inspectional', 'review', 'reference')),
    page_range        text,
    access_note       text,
    content_warning   text,
    ordinal           integer not null,
    raw_source_text   text,
    confidence        real not null default 1.0
);

create unique index assigned_reading_slot_idx on assigned_reading (session_id, ordinal);
create index assigned_reading_work_idx on assigned_reading (work_id);

create table deliverable (
    id                integer primary key autoincrement,
    course_id         integer not null references course (id) on delete cascade,
    title             text not null,
    kind              text not null default 'other' check (kind in (
                          'exam', 'essay', 'presentation', 'weekly_assessment',
                          'checklist', 'proposal', 'signup', 'report',
                          'case_study', 'other')),
    due_date          text,
    due_time          text,
    recurrence        text,
    weight_percent    real,
    page_limit        integer,
    word_limit        integer,
    format_notes      text,
    requirements_text text,
    source_zone       text,
    page_number       integer,
    confidence        real not null default 1.0
);

create index deliverable_course_idx on deliverable (course_id, due_date);

create table document (
    id                  integer primary key autoincrement,
    work_id             integer references work (id) on delete set null,
    -- sha256 of the file, which is what makes re-ingesting a directory a no-op
    file_hash           text not null unique,
    source_path         text,
    filename            text,
    page_count          integer,
    ocr_used            integer not null default 0,
    extraction_status   text not null default 'ok' check (extraction_status in (
                            'ok', 'partial', 'failed', 'needs_ocr')),
    extraction_warnings text not null default '[]',
    match_confidence    real,
    match_method        text,
    ingested_at         text not null default (datetime('now'))
);

create index document_work_idx on document (work_id);

-- page_number is not optional. a quote that cannot be cited to a page is not
-- usable in a footnote, which is the whole point of keeping the text.
create table chunk (
    id          integer primary key autoincrement,
    document_id integer not null references document (id) on delete cascade,
    page_number integer not null,
    ordinal     integer not null,
    kind        text not null default 'body' check (kind in ('body', 'footnote', 'caption')),
    ref_marker  text,
    body        text not null,
    -- v1 leaves this null. it exists so adding vectors later is a data change
    -- rather than a schema change.
    embedding   blob
);

create unique index chunk_slot_idx on chunk (document_id, ordinal);
create index chunk_page_idx on chunk (document_id, page_number);

-- fts5 covers the cli search. the published site uses pagefind over built html
-- and never sees this table, because chunk text is other people's copyright.
create virtual table chunk_fts using fts5 (
    body,
    content = 'chunk',
    content_rowid = 'id',
    tokenize = 'porter unicode61'
);

create trigger chunk_fts_insert after insert on chunk begin
    insert into chunk_fts (rowid, body) values (new.id, new.body);
end;

create trigger chunk_fts_delete after delete on chunk begin
    insert into chunk_fts (chunk_fts, rowid, body) values ('delete', old.id, old.body);
end;

create trigger chunk_fts_update after update on chunk begin
    insert into chunk_fts (chunk_fts, rowid, body) values ('delete', old.id, old.body);
    insert into chunk_fts (rowid, body) values (new.id, new.body);
end;

create table brief (
    id             integer primary key autoincrement,
    work_id        integer not null references work (id) on delete cascade,
    course_id      integer references course (id) on delete set null,
    -- 'human', or 'model:<name>'. anything starting with model: is watermarked
    -- in the ui, excluded from copy to clipboard, and withheld from the public
    -- build unless the course opts in.
    generated_by   text not null,
    prompt_version text,
    body           text not null default '{}',
    markdown       text,
    created_at     text not null default (datetime('now'))
);

create unique index brief_work_idx on brief (work_id);

create table note (
    id          integer primary key autoincrement,
    work_id     integer not null references work (id) on delete cascade,
    chunk_id    integer references chunk (id) on delete set null,
    page_number integer,
    body        text not null,
    -- default deny. a note reaches the public build only when this is set.
    shareable   integer not null default 0,
    created_at  text not null default (datetime('now'))
);

create index note_work_idx on note (work_id);

create table parse_run (
    id                 integer primary key autoincrement,
    course_id          integer references course (id) on delete cascade,
    source_file_hash   text not null,
    source_filename    text,
    schedule_structure text,
    started_at         text not null default (datetime('now')),
    committed_at       text
);

-- every row that scored below threshold, what it was parsed from, what we
-- guessed, and what the user decided about it.
create table parse_review (
    id            integer primary key autoincrement,
    parse_run_id  integer not null references parse_run (id) on delete cascade,
    entity_type   text not null check (entity_type in (
                      'course', 'session', 'work', 'assigned_reading',
                      'deliverable', 'policy')),
    entity_ref    text,
    field_name    text,
    source_text   text not null,
    guess         text,
    confidence    real not null,
    reason        text,
    decision      text not null default 'pending' check (decision in (
                      'pending', 'accepted', 'edited', 'rejected')),
    decided_value text,
    decided_at    text
);

create index parse_review_run_idx on parse_review (parse_run_id, decision);
