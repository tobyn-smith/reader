-- core schema. one file per migration, applied in filename order by
-- `vault db migrate`. applied names are tracked in schema_migration.

create table if not exists schema_migration (
    name        text primary key,
    applied_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- courses
-- ---------------------------------------------------------------------------

create table course (
    id                bigserial primary key,
    code              text not null,
    title             text not null,
    term              text,                       -- fall / spring / summer / winter
    year              int,
    instructor_name   text,
    instructor_email  text,
    meeting_time      text,
    location          text,
    site_url          text,
    citation_style    text,                       -- per-course override, e.g. apsr
    source_file_hash  text not null unique,       -- sha256 of the syllabus pdf
    source_filename   text,
    parsed_at         timestamptz not null default now()
);

create index course_term_year_idx on course (year desc, term);

-- policy text is kept verbatim. type drives what the ui surfaces vs collapses.
create table course_policy (
    id           bigserial primary key,
    course_id    bigint not null references course (id) on delete cascade,
    policy_type  text not null check (policy_type in (
                     'ai_use', 'late_work', 'attendance', 'grading_scale',
                     'academic_honesty', 'boilerplate', 'other')),
    -- only meaningful when policy_type = 'ai_use'
    ai_stance    text check (ai_stance in ('prohibited', 'restricted', 'permitted', 'unstated')),
    heading      text,
    body         text not null,
    page_number  int,
    confidence   real not null default 1.0,
    created_at   timestamptz not null default now()
);

create index course_policy_course_idx on course_policy (course_id, policy_type);

-- ---------------------------------------------------------------------------
-- schedule
-- ---------------------------------------------------------------------------

-- one row per meeting. a course that meets twice a week and assigns different
-- readings to each meeting gets two rows with the same week_number and
-- different sub_session_label.
create table session (
    id                bigserial primary key,
    course_id         bigint not null references course (id) on delete cascade,
    week_number       int,
    meeting_date      date,
    sub_session_label text,                       -- 't', 'tr', 'mon', null
    topic             text,
    section_heading   text,                       -- unit/module the week sits in
    session_type      text not null default 'reading' check (session_type in (
                          'reading', 'no_reading', 'exam', 'holiday',
                          'guest', 'review', 'assignment', 'presentation')),
    ordinal           int not null,               -- document order, survives odd numbering
    page_number       int,
    raw_source_text   text,
    confidence        real not null default 1.0
);

create unique index session_slot_idx
    on session (course_id, ordinal);
create index session_week_idx on session (course_id, week_number);
create index session_date_idx on session (course_id, meeting_date);

-- ---------------------------------------------------------------------------
-- bibliography
-- ---------------------------------------------------------------------------

-- a work is the bibliographic record, independent of which course assigned it
-- or whether a pdf has been ingested for it.
create table work (
    id                bigserial primary key,
    -- ordered list of {surname, given, literal}. literal is used for
    -- institutional authors that do not split, e.g. "Department of Asian Art".
    authors           jsonb not null default '[]'::jsonb,
    title             text,
    container         text,                       -- journal, book, site, series
    publisher         text,
    year              int,
    year_end          int,                        -- for open-ended ranges like "2000-"
    year_is_open      boolean not null default false,
    volume            text,
    issue             text,
    pages             text,
    doi               text,
    url               text,
    report_number     text,                       -- crs numbers etc: R41916, IF11251
    work_type         text not null default 'unknown' check (work_type in (
                          'journal_article', 'book', 'book_chapter', 'report',
                          'news_article', 'web_page', 'government_document',
                          'unknown')),
    rendered_citation text,
    raw_source_text   text not null,              -- exact string it was parsed from
    matched_pattern   text,                       -- which citation rule fired
    signature         text,                       -- normalized author+year+title key
    enriched_from     text,                       -- crossref / openlibrary / null
    confidence        real not null default 1.0,
    created_at        timestamptz not null default now()
);

create index work_signature_idx on work (signature);
create index work_year_idx on work (year);
create unique index work_doi_idx on work (lower(doi)) where doi is not null;

-- fields the user confirmed by hand. enrichment must not overwrite these.
create table work_locked_field (
    work_id     bigint not null references work (id) on delete cascade,
    field_name  text not null,
    primary key (work_id, field_name)
);

create table assigned_reading (
    id                bigserial primary key,
    session_id        bigint not null references session (id) on delete cascade,
    work_id           bigint not null references work (id) on delete cascade,
    requirement_level text not null default 'required' check (requirement_level in (
                          'required', 'recommended', 'inspectional', 'review', 'reference')),
    page_range        text,                       -- when only part of the work is assigned
    access_note       text,                       -- "pdf on elc", "library", a url
    content_warning   text,
    ordinal           int not null,
    raw_source_text   text,
    confidence        real not null default 1.0
);

create unique index assigned_reading_slot_idx on assigned_reading (session_id, ordinal);
create index assigned_reading_work_idx on assigned_reading (work_id);

-- ---------------------------------------------------------------------------
-- graded work
-- ---------------------------------------------------------------------------

create table deliverable (
    id                bigserial primary key,
    course_id         bigint not null references course (id) on delete cascade,
    title             text not null,
    kind              text not null default 'other' check (kind in (
                          'exam', 'essay', 'presentation', 'weekly_assessment',
                          'checklist', 'proposal', 'signup', 'report',
                          'case_study', 'other')),
    due_date          date,
    due_time          time,
    -- set for anything that repeats, e.g. "every thursday 9:00 am"
    recurrence        text,
    weight_percent    numeric(5, 2),
    page_limit        int,
    word_limit        int,
    format_notes      text,
    requirements_text text,                       -- verbatim
    source_zone       text,                       -- 'requirements' or 'schedule'
    page_number       int,
    confidence        real not null default 1.0
);

create index deliverable_course_idx on deliverable (course_id, due_date);

-- ---------------------------------------------------------------------------
-- documents and text
-- ---------------------------------------------------------------------------

create table document (
    id                  bigserial primary key,
    work_id             bigint references work (id) on delete set null,
    file_hash           text not null unique,     -- sha256, makes re-ingest a no-op
    source_path         text,
    filename            text,
    page_count          int,
    ocr_used            boolean not null default false,
    extraction_status   text not null default 'ok' check (extraction_status in (
                            'ok', 'partial', 'failed', 'needs_ocr')),
    extraction_warnings jsonb not null default '[]'::jsonb,
    match_confidence    real,                     -- how sure we are of work_id
    match_method        text,
    ingested_at         timestamptz not null default now()
);

create index document_work_idx on document (work_id);

-- page-aligned segments. page_number is not optional: a quote that cannot be
-- cited to a page is not usable in a footnote.
create table chunk (
    id           bigserial primary key,
    document_id  bigint not null references document (id) on delete cascade,
    page_number  int not null,
    ordinal      int not null,
    kind         text not null default 'body' check (kind in ('body', 'footnote', 'caption')),
    -- for footnotes, the marker they hang off of, when we can tell
    ref_marker   text,
    body         text not null,
    tsv          tsvector generated always as (to_tsvector('english', body)) stored,
    -- v1 leaves this null. swap the type to vector(N) and add an ivfflat index
    -- if pgvector ever gets turned on. nothing else in the schema changes.
    embedding    real[]
);

create unique index chunk_slot_idx on chunk (document_id, ordinal);
create index chunk_tsv_idx on chunk using gin (tsv);
create index chunk_page_idx on chunk (document_id, page_number);

-- ---------------------------------------------------------------------------
-- generated and hand-written notes
-- ---------------------------------------------------------------------------

create table brief (
    id            bigserial primary key,
    work_id       bigint not null references work (id) on delete cascade,
    course_id     bigint references course (id) on delete set null,
    -- 'human' or 'model:<name>'. anything starting with model: is watermarked
    -- in the ui and excluded from copy-to-clipboard.
    generated_by  text not null,
    prompt_version text,
    body          jsonb not null default '{}'::jsonb,
    markdown      text,
    created_at    timestamptz not null default now()
);

create unique index brief_work_idx on brief (work_id);

create table note (
    id          bigserial primary key,
    work_id     bigint not null references work (id) on delete cascade,
    chunk_id    bigint references chunk (id) on delete set null,
    page_number int,
    body        text not null,
    created_at  timestamptz not null default now()
);

create index note_work_idx on note (work_id);

-- ---------------------------------------------------------------------------
-- review trail
-- ---------------------------------------------------------------------------

create table parse_run (
    id            bigserial primary key,
    course_id     bigint references course (id) on delete cascade,
    source_file_hash text not null,
    source_filename  text,
    schedule_structure text,                      -- which parser handled it
    started_at    timestamptz not null default now(),
    committed_at  timestamptz
);

-- every row that scored below threshold, with what it was parsed from, what we
-- guessed, and what the user decided.
create table parse_review (
    id           bigserial primary key,
    parse_run_id bigint not null references parse_run (id) on delete cascade,
    entity_type  text not null check (entity_type in (
                     'course', 'session', 'work', 'assigned_reading',
                     'deliverable', 'policy')),
    entity_ref   text,                            -- pointer into the parse json
    field_name   text,
    source_text  text not null,
    guess        jsonb,
    confidence   real not null,
    reason       text,
    decision     text not null default 'pending' check (decision in (
                     'pending', 'accepted', 'edited', 'rejected')),
    decided_value jsonb,
    decided_at   timestamptz
);

create index parse_review_run_idx on parse_review (parse_run_id, decision);
