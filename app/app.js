// main thread. holds state, drives the two workers, draws the views. all the
// heavy work happens in the workers so the page stays responsive.

import * as store from './store.js'
import * as view from './render.js'
import * as cite from './cite.js'
import * as grades from './grades.js'
import { PARSER_VERSION } from './version.js'

const $ = (id) => document.getElementById(id)

const state = {
  courses: [],
  documents: [],
  active: null,
  pending: null,
  // syllabi wait here so a batch is reviewed one at a time
  queue: [],
  files: [],
  progress: new Map(),
  // review opens on the rows that need a decision, not on everything
  reviewShowAll: false,
  currentView: 'week',
  // no parser reads every syllabus, and dates move mid term, so anything on
  // screen can be corrected by hand. off by default to keep the read view clean.
  editing: false,
  // which records the ledger is showing. off means all of them.
  filter: { unread: false, required: false, soon: false },
  // the row the keyboard is on, held as a reading id so it survives a redraw
  cursor: null,
}

let extractWorker = null
let parseWorker = null
let nextId = 1
const waiting = new Map()

// pyodide is a large download, so neither worker is created until the visitor
// picks a file. the page itself must be usable before any of that starts.
function workers() {
  if (!extractWorker) {
    extractWorker = new Worker('./extract-worker.js', { type: 'module' })
    extractWorker.onmessage = onExtractMessage
  }
  if (!parseWorker) {
    parseWorker = new Worker('./parse-worker.js')
    parseWorker.onmessage = onParseMessage
  }
  return { extractWorker, parseWorker }
}

function status(element, text) {
  $(element).textContent = text
}

function onExtractMessage(event) {
  const { type, id, payload, page, total, message } = event.data
  const job = waiting.get(id)
  if (!job) return

  if (type === 'progress') {
    note(job, `reading page ${page} of ${total}`)
    return
  }
  if (type === 'error') {
    note(job, `could not be read: ${message}`, true)
    waiting.delete(id)
    return
  }
  if (type === 'cancelled') {
    note(job, 'cancelled')
    waiting.delete(id)
    return
  }
  if (type !== 'extracted') return

  if (payload.needOcr.length) {
    note(job, `${payload.needOcr.length} page(s) have no text layer, left empty`, true)
  } else {
    note(job, 'sorting')
  }

  const { parseWorker: pw } = workers()
  pw.postMessage({ type: 'ingest', id, payload })
}

function onParseMessage(event) {
  const { type, id, result, stage, message } = event.data

  if (type === 'boot') {
    status('intake-status', `Loading parser: ${stage}`)
    return
  }
  const job = waiting.get(id)
  if (!job) return

  if (type === 'error') {
    note(job, `could not be parsed: ${message}`, true)
    waiting.delete(id)
    return
  }

  // one call decides what the file is and returns the right thing for it
  if (type === 'ingested') {
    waiting.delete(id)
    if (result.kind === 'syllabus') {
      job.kind = 'syllabus'
      note(job, 'syllabus, ready to review')
      state.queue.push({ name: job.name, parse: result, bytes: job.bytes })
      if (!state.pending) nextReview()
    } else {
      job.kind = 'reading'
      note(job, 'reading, matching')
      matchReading(job, result)
    }
    return
  }

  if (type === 'matched') {
    waiting.delete(id)
    finishReading(job, result)
  }
}

// one line per file, so a dropped batch shows what happened to each
function note(job, text, warn = false) {
  job.note = text
  job.warn = warn
  drawQueue()
}

function drawQueue() {
  const rows = state.files
    .map(
      (job) => `<tr class="${job.warn ? 'missing' : ''}">
        <td>${view.esc(job.name)}</td>
        <td>${view.esc(job.kind || '')}</td>
        <td class="secondary">${view.esc(job.note || '')}</td>
      </tr>`
    )
    .join('')
  $('queue').innerHTML = rows ? `<table><tbody>${rows}</tbody></table>` : ''
}

function nextReview() {
  if (!state.queue.length) {
    state.pending = null
    $('review').hidden = true
    return
  }
  state.pending = state.queue.shift()
  showReview()
}

async function matchReading(job, extracted) {
  const head = extracted.pages.slice(0, 2).map((p) => p.text).join('\n')
  const candidates = candidateWorks()

  if (!candidates.length) {
    finishReading(job, { id: null, score: 0, method: 'no syllabus added yet' })
    return
  }

  const id = nextId++
  waiting.set(id, Object.assign(job, { extracted }))
  const { parseWorker: pw } = workers()
  pw.postMessage({ type: 'match', id, head, candidates, filename: job.name })
}

async function finishReading(job, match) {
  const [courseId, workKey] = (match.id || '::').split('::')
  const extracted = job.extracted
  await store.putDocument({
    // the extractor hands back the file's sha256; using it means re-dropping
    // the same pdf replaces the record instead of making a second one under
    // the same name
    id: (extracted && extracted.sha256) || job.name,
    filename: job.name,
    courseId: courseId || null,
    workKey: workKey || null,
    matchScore: match.score,
    matchMethod: match.method,
    pageCount: (extracted && extracted.page_count) || 0,
    // the file itself, so a reading matched to a row can be opened from the
    // ledger. it was thrown away after matching, which meant the app knew a
    // reading was on file and could not show it to you. it never leaves this
    // browser, and the json backup drops it the way it drops the syllabus.
    pdf: job.bytes || null,
    // kept so a reading dropped before its syllabus can be matched later
    // without asking for the file again. it never leaves this browser.
    head: extracted ? extracted.pages.slice(0, 2).map((p) => p.text).join('\n') : '',
  })
  state.documents = await store.listDocuments()
  note(job, match.id ? `matched, score ${match.score}` : `not matched: ${match.method}`, !match.id)
  drawUnmatched()
  draw()
}

// dropping readings before their syllabus is the normal order for a pile of
// files, so every unmatched document gets another chance once a syllabus lands
async function rematchUnmatched() {
  const orphans = state.documents.filter((d) => !d.workKey && d.head)
  if (!orphans.length) return

  const candidates = candidateWorks()
  if (!candidates.length) return

  const { parseWorker: pw } = workers()
  for (const record of orphans) {
    const id = nextId++
    waiting.set(id, { name: record.filename, kind: 'reading', record })
    pw.postMessage({
      type: 'match',
      id,
      head: record.head,
      candidates,
      filename: record.filename,
    })
  }
}

function candidateWorks() {
  const works = []
  for (const course of state.courses) {
    for (const session of course.parse.sessions) {
      for (const reading of session.readings) {
        works.push({
          id: view.readingKey(course, session, reading),
          title: reading.work.title,
          year: reading.work.year,
          authors: reading.work.authors,
          doi: reading.work.doi,
        })
      }
    }
  }
  return works
}

function submit(files) {
  const { extractWorker: ew } = workers()
  $('welcome').hidden = true
  $('tools').hidden = false
  $('tools').open = true
  status('intake-status', `${files.length} file(s) queued`)

  for (const file of files) {
    const id = nextId++
    const job = { name: file.name, kind: '', note: 'queued' }
    state.files.push(job)
    waiting.set(id, job)
    file.arrayBuffer().then((buffer) => {
      job.bytes = buffer.slice(0)
      ew.postMessage({ type: 'extract', id, name: file.name, buffer }, [buffer])
    })
  }
  drawQueue()
}

function showReview() {
  $('review').hidden = false
  $('review-name').textContent = state.pending.name
  $('review-table').innerHTML = view.reviewTable(state.pending.parse, state.reviewShowAll)
  $('review').scrollIntoView({ block: 'start' })
}

// corrections typed on the review screen live only in the dom until they are
// harvested. redrawing that table, which the "show every reading" toggle does,
// used to throw them away without a word, so the harvest happens before any
// redraw as well as on save.
function harvestReviewEdits() {
  const parse = state.pending && state.pending.parse
  if (!parse) return
  for (const input of $('review-table').querySelectorAll('input[data-session]')) {
    const session = parse.sessions[Number(input.dataset.session)]
    const reading = session && session.readings[Number(input.dataset.reading)]
    if (!reading) continue
    const edited = input.value.trim()
    if (edited && edited !== view.citation(reading.work)) {
      reading.work.rendered_override = edited
      reading.work.title = reading.work.title || edited
      reading.confidence = 1
    }
  }
}

async function confirmParse() {
  harvestReviewEdits()
  const parse = state.pending.parse

  const code = parse.course.code || state.pending.name.replace(/\.pdf$/i, '')
  const id = parse.file_hash || code
  // a re-read of the same file lands on the same id and replaces in place;
  // if this parse somehow lacks bytes, the copy already stored is kept
  const prior = state.courses.find((c) => c.id === id)

  // a re-read replaces the parse, but the marks a student typed live inside
  // it. losing a term of grades to a re-upload is the kind of thing that gets
  // a tool deleted, so marks follow their assignment across by title.
  if (prior) {
    const marked = new Map(
      prior.parse.deliverables.items
        .filter((item) => item.mark_percent || item.mark_percent === 0)
        .map((item) => [item.title.trim().toLowerCase(), item.mark_percent])
    )
    for (const item of parse.deliverables.items) {
      const kept = marked.get(item.title.trim().toLowerCase())
      if (kept !== undefined) item.mark_percent = kept
    }
  }

  const course = {
    id,
    code,
    title: parse.course.title || '',
    name: state.pending.name,
    parse,
    pdf: state.pending.bytes || (prior && prior.pdf) || null,
    // what the visitor set about the course rather than about this parse. the
    // grading scale belongs here too: it is read off the syllabus by eye and
    // typed in, so losing it to a re-read means typing every cutoff again.
    credits: prior ? prior.credits : null,
    grade_letter: prior ? prior.grade_letter : null,
    grade_target: prior ? prior.grade_target : null,
    grade_scale: prior ? prior.grade_scale : null,
    parserVersion: PARSER_VERSION,
  }
  await store.putCourse(course)
  state.courses = await store.listCourses()
  state.active = course.id
  $('views').hidden = false
  $('tools').open = false
  $('data-tools').hidden = false
  nextReview()
  await rematchUnmatched()
  draw()
}

async function setProgress(id, patch) {
  const entry = Object.assign({ id, read: false, note: '' }, state.progress.get(id), patch)
  state.progress.set(id, entry)
  await store.putProgress(entry)
}

function drawNav() {
  const nav = $('nav')
  if (!state.courses.length) {
    nav.hidden = true
    return
  }
  nav.hidden = false
  const codeCounts = new Map()
  for (const c of state.courses) codeCounts.set(c.code, (codeCounts.get(c.code) || 0) + 1)
  // a course from an earlier term is still reachable, it just says so, since
  // the term views now leave it out and a silent absence reads as a bug
  const newest = view.latestTerm(state.courses)
  nav.innerHTML = state.courses
    .map((c) => {
      const key = view.termKey(c)
      const past = Boolean(newest && key && key !== newest)
      const tag = past || codeCounts.get(c.code) > 1 ? ` ${view.courseTag(c)}` : ''
      return `<a href="#" data-course="${view.esc(c.id)}"${past ? ' class="past-term"' : ''}
        title="${view.esc(courseLabel(c))}${past ? ' (earlier term)' : ''}"${
        c.id === state.active ? ' aria-current="page"' : ''
      }>${view.esc(c.code)}${view.esc(tag)}</a>`
    })
    .join('')
}

function drawUnmatched() {
  const orphans = state.documents.filter((d) => !d.workKey)
  $('unmatched').innerHTML = orphans.length
    ? `<h3>Not matched</h3><table><tbody>${orphans
        .map((d) => `<tr class="missing"><td>${view.esc(d.filename)}</td>
          <td class="secondary">${view.esc(d.matchMethod)}</td></tr>`)
        .join('')}</tbody></table>`
    : ''
}

// a title that just repeats the course code adds nothing to the option
function courseLabel(course) {
  const squash = (t) => (t || '').replace(/[^a-z0-9]/gi, '').toLowerCase()
  const title = (course.title || '').trim()
  if (!title || squash(title) === squash(course.code) || squash(title).length < 4) {
    return course.code
  }
  const full = `${course.code} ${title}`
  return full.length > 62 ? `${full.slice(0, 59)}...` : full
}

function drawStyleSelect() {
  const styles = $('style-select')
  if (!styles.options.length) {
    styles.innerHTML = cite
      .styles()
      .map((s) => `<option value="${s}">${view.esc(cite.STYLE_NAMES[s])}</option>`)
      .join('')
  }
  styles.value = view.style
}

function activeCourse() {
  return state.courses.find((c) => c.id === state.active) || state.courses[0]
}

function dueTarget(token) {
  const [id, index] = token.split('|')
  return { course: state.courses.find((c) => c.id === id), index: Number(index) }
}

// a reading typed by hand has no citation to parse, so the typed line is the
// citation. it is marked as hand-entered so it is never treated as parser
// output later.
function blankReading(session) {
  return {
    ordinal: session.readings.length,
    requirement_level: 'required',
    page_range: null, access_note: null, content_warning: null,
    raw_source_text: '', confidence: 1,
    work: { authors: [], title: null, work_type: 'unknown',
            rendered_override: '', matched_pattern: 'typed_by_hand',
            signature: '', confidence: 1 },
  }
}

function retotal(course) {
  const items = course.parse.deliverables.items
  const weights = items.map((i) => i.weight_percent).filter((w) => w || w === 0)
  course.parse.deliverables.weight_total =
    weights.length ? Math.round(weights.reduce((a, b) => a + b, 0) * 100) / 100 : 0
}

async function saveCourse(course) {
  await store.putCourse(course)
  draw()
}

// every editable field routes through here, so adding one is a matter of
// naming it rather than wiring another listener
async function handleEdit(el) {
  if (el.dataset.editReading !== undefined) {
    const [si, ri] = el.dataset.editReading.split('.').map(Number)
    const course = activeCourse()
    const work = course.parse.sessions[si].readings[ri].work
    work.rendered_override = el.value.trim()
    await saveCourse(course)
    return
  }
  if (el.dataset.dueTitle !== undefined) {
    const { course, index } = dueTarget(el.dataset.dueTitle)
    course.parse.deliverables.items[index].title = el.value.trim()
    await saveCourse(course)
    return
  }
  if (el.dataset.dueDate !== undefined) {
    const { course, index } = dueTarget(el.dataset.dueDate)
    course.parse.deliverables.items[index].due_date = el.value || null
    await saveCourse(course)
    return
  }
  if (el.dataset.dueWeight !== undefined) {
    const { course, index } = dueTarget(el.dataset.dueWeight)
    const raw = el.value.trim()
    course.parse.deliverables.items[index].weight_percent = raw === '' ? null : Number(raw)
    retotal(course)
    await saveCourse(course)
    return
  }
  // these all redraw, which is only safe because the listener is on change
  // rather than input: the value is committed on the way out of the box, so
  // rebuilding the view is not taking focus off anything being typed into.
  if (el.dataset.mark !== undefined) {
    const { course, index } = dueTarget(el.dataset.mark)
    const raw = el.value.trim()
    course.parse.deliverables.items[index].mark_percent = raw === '' ? null : Number(raw)
    await saveCourse(course)
    return
  }
  if (el.dataset.credits !== undefined) {
    const course = state.courses.find((c) => c.id === el.dataset.credits)
    const raw = el.value.trim()
    course.credits = raw === '' ? null : Number(raw)
    await saveCourse(course)
    return
  }
  if (el.dataset.letter !== undefined) {
    const course = state.courses.find((c) => c.id === el.dataset.letter)
    // clearing the box hands the course back to whatever the marks say
    course.grade_letter = el.value || null
    await saveCourse(course)
    return
  }
  if (el.dataset.target !== undefined) {
    const course = state.courses.find((c) => c.id === el.dataset.target)
    course.grade_target = Number(el.value)
    await saveCourse(course)
    return
  }
  if (el.dataset.scale !== undefined) {
    const course = state.courses.find((c) => c.id === el.dataset.scale)
    if (el.value === 'custom') {
      // custom starts from whatever was in force, so switching to it changes
      // nothing until a floor is actually edited
      course.grade_scale = {
        kind: 'custom',
        cutoffs: grades.resolveScale(course.grade_scale).filter(([l]) => l !== 'F'),
      }
    } else {
      course.grade_scale = el.value
    }
    reletterCourse(course)
    await saveCourse(course)
    return
  }
  if (el.dataset.cut !== undefined) {
    const [id, letter] = el.dataset.cut.split('|')
    const course = state.courses.find((c) => c.id === id)
    const raw = el.value.trim()
    const rows = (course.grade_scale.cutoffs || []).filter(([l]) => l !== letter)
    if (raw !== '') rows.push([letter, Number(raw)])
    course.grade_scale.cutoffs = rows
    reletterCourse(course)
    await saveCourse(course)
  }
}

// a stored letter or target only means something on the scale it was chosen
// from. after a scale change, anything the new scale does not offer is
// dropped back to the default rather than displayed as a lie.
function reletterCourse(course) {
  const cutoffs = grades.resolveScale(course.grade_scale)
  if (course.grade_letter && !cutoffs.some(([l]) => l === course.grade_letter)) {
    course.grade_letter = null
  }
  if (course.grade_target != null
      && !cutoffs.some(([, floor]) => floor === Number(course.grade_target))) {
    course.grade_target = null
  }
}

// the async clipboard is refused in plenty of ordinary situations: an
// insecure origin, a permission the visitor never granted, an older browser.
// the old textarea trick still works in all of them, so it is the fallback
// rather than an apology.
async function toClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const box = document.createElement('textarea')
      box.value = text
      box.setAttribute('readonly', '')
      box.style.position = 'fixed'
      box.style.opacity = '0'
      document.body.appendChild(box)
      box.select()
      const ok = document.execCommand('copy')
      box.remove()
      return ok
    } catch {
      return false
    }
  }
}

function focusLast(selector) {
  const all = document.querySelectorAll(selector)
  if (all.length) all[all.length - 1].focus()
}

// a redraw replaces the inputs, and with them whatever the keyboard had
// reached. tabbing down a column of marks otherwise dies on the first save.
// the element is remembered by its data attribute and picked up again after.
function focusToken(el) {
  if (!el || !el.dataset) return null
  for (const key of ['mark', 'credits', 'letter', 'target', 'scale', 'cut',
                     'dueDate', 'dueTitle', 'dueWeight', 'note']) {
    if (el.dataset[key] !== undefined) return [key, el.dataset[key]]
  }
  return null
}

function restoreFocus(token) {
  if (!token) return
  const attr = token[0].replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())
  const el = document.querySelector(`[data-${attr}="${CSS.escape(token[1])}"]`)
  if (!el) return
  el.focus()
  if (el.select) el.select()
}

// ---- the keyboard cursor ---------------------------------------------------

function cursorRows() {
  return [...document.querySelectorAll('#view tr.rec[data-row]')]
}

function paintCursor() {
  const rows = cursorRows()
  for (const row of rows) row.classList.remove('is-cursor')
  if (!state.cursor) return
  const found = rows.find((r) => r.dataset.row === state.cursor)
  if (found) found.classList.add('is-cursor')
  else state.cursor = null
}

function moveCursor(step) {
  const rows = cursorRows()
  if (!rows.length) return
  const at = rows.findIndex((r) => r.dataset.row === state.cursor)
  const next = at < 0
    ? (step > 0 ? 0 : rows.length - 1)
    : Math.min(rows.length - 1, Math.max(0, at + step))
  state.cursor = rows[next].dataset.row
  paintCursor()
  rows[next].scrollIntoView({ block: 'nearest' })
}

function cursorRow() {
  return state.cursor
    ? cursorRows().find((r) => r.dataset.row === state.cursor)
    : null
}

// ---- deadlines as a calendar file ------------------------------------------

function drawCalendarButton() {
  const button = $('calendar')
  // a calendar full of last term's deadlines is worse than no calendar
  const rows = grades.datedDeadlines(view.currentTermCourses(state.courses))
  button.hidden = rows.length === 0
  if (rows.length) {
    button.textContent = `Add ${rows.length} deadline${rows.length === 1 ? '' : 's'} to a calendar`
  }

  const notes = $('export-notes')
  const written = collectNotes()
  notes.hidden = written.length === 0
  if (written.length) {
    notes.textContent = `Save ${written.length} note${written.length === 1 ? '' : 's'} as text`
  }
}

// every note the student has written, with the reading it belongs to. notes
// were reachable only inside a json backup, which is a file you restore rather
// than one you read, so a term's reading notes could not be taken into an
// essay without retyping them.
function collectNotes() {
  const out = []
  for (const course of state.courses) {
    for (const session of course.parse.sessions) {
      for (const reading of session.readings) {
        const saved = state.progress.get(view.readingKey(course, session, reading)) || {}
        if (!saved.note || !saved.note.trim()) continue
        out.push({
          code: course.code,
          week: session.week_number ? `Week ${session.week_number}` : '',
          date: session.meeting_date || '',
          citation: view.citation(reading.work),
          note: saved.note.trim(),
          read: Boolean(saved.read),
        })
      }
    }
  }
  return out
}

// markdown, because it opens as plain text anywhere and pastes into a document
// with its structure intact
function notesAsMarkdown(rows) {
  const byCourse = new Map()
  for (const row of rows) {
    if (!byCourse.has(row.code)) byCourse.set(row.code, [])
    byCourse.get(row.code).push(row)
  }
  const parts = ['# Reading notes', '']
  for (const [code, entries] of byCourse) {
    parts.push(`## ${code}`, '')
    for (const entry of entries) {
      const where = [entry.week, entry.date].filter(Boolean).join(' · ')
      parts.push(`### ${entry.citation}`)
      if (where) parts.push(`*${where}*`)
      parts.push('', entry.note, '')
    }
  }
  return parts.join('\n')
}

function draw() {
  const focused = focusToken(document.activeElement)
  drawNav()
  const course = state.courses.find((c) => c.id === state.active) || state.courses[0]
  // the first visit gets the welcome and its big drop target; once a course
  // exists, or a parse is waiting on review, the ledger takes over. while the
  // welcome is up, the add-files panel hides: two drop zones on one screen
  // read as two different features.
  const welcome = !course && !state.pending && state.files.length === 0
  $('welcome').hidden = !welcome
  $('tools').hidden = welcome
  $('tools').open = !course
  // the small print stands open on the homepage. a visitor deciding whether
  // to trust the tool should not have to know to click for the numbers.
  if (welcome) $('accuracy').open = true
  if (!course) {
    $('views').hidden = true
    document.title = "Tobyn's Schedule Reader"
    return
  }
  $('views').hidden = false
  drawStyleSelect()

  // editing only means something where there are rows to correct
  const editable = state.currentView === 'week' || state.currentView === 'deadlines'
  const editing = state.editing && editable
  $('edit-toggle').hidden = !editable
  $('edit-toggle').textContent = editing ? 'Done editing' : 'Edit'
  $('edit-toggle').setAttribute('aria-pressed', String(editing))
  document.body.classList.toggle('is-editing', editing)

  // the record header and the rail belong to the ledger, and are cleared on
  // every other view so the sheet does not carry an index of nothing
  $('record').innerHTML = view.recordHeader(course)

  // a course parsed by an older bundle can be better now. the stored pdf
  // makes the re-read one click; a course saved before pdfs were kept has to
  // be dropped again. either way it goes through review, so nothing changes
  // without being looked at, and ticks survive on unchanged readings.
  if (course.parserVersion !== PARSER_VERSION) {
    $('record').insertAdjacentHTML('beforeend',
      `<p class="stale-note">This course was read by an older version of the
        parser.${course.pdf
          ? ' <button type="button" id="reparse" class="quiet">Read it again</button>'
          : ' Drop its syllabus PDF again to refresh it.'}</p>`)
    const again = $('reparse')
    if (again) again.onclick = () => {
      submit([new File([course.pdf], course.name || 'syllabus.pdf',
        { type: 'application/pdf' })])
    }
  }

  const target = $('view')
  $('sheet').classList.toggle('no-rail', state.currentView !== 'week')
  if (state.currentView === 'week') {
    const ledger = view.weekView(course, state.progress, editing, state.filter, state.documents)
    target.innerHTML = ledger.html
    $('rail').innerHTML = view.railView(course, ledger, state.courses, state.filter, state.progress)
  } else {
    // the rail belongs to the ledger. emptying it left its 168px column
    // standing, so every other view opened indented by a blank strip and gave
    // up a fifth of the page for nothing.
    $('rail').innerHTML = ''
    if (state.currentView === 'schedule') target.innerHTML = view.scheduleView(course)
    else if (state.currentView === 'deadlines') target.innerHTML = view.deadlinesView(state.courses, state.active, editing, state.progress)
    else if (state.currentView === 'now') target.innerHTML = view.thisWeekView(state.courses, state.progress)
    else if (state.currentView === 'grades') target.innerHTML = view.gradesView(state.courses, state.active)
    else if (state.currentView === 'bibliography') target.innerHTML = view.bibliographyView(course)
    else if (state.currentView === 'policies') target.innerHTML = view.policiesView(course)
    else if (state.currentView === 'search') drawSearch(target)
  }

  for (const button of document.querySelectorAll('.tabs button[data-view]')) {
    button.setAttribute('aria-current', String(button.dataset.view === state.currentView))
  }

  restoreFocus(focused)
  paintCursor()
  drawCalendarButton()

  // the document line and the sheet number: a record identifies itself
  const stamp = new Date().toISOString().slice(0, 10)
  $('print-meta').textContent =
    `${state.courses.indexOf(course) + 1} of ${state.courses.length} · ${stamp}`

  // a saved pdf takes its filename from the document title, and a title that
  // never changes means every course prints under one name and overwrites the
  // last one. the active course names the tab and the file.
  document.title = `${course.code || 'Course'} - Tobyn's Schedule Reader`
}

function drawSearch(target) {
  target.innerHTML = `<h2>Search</h2>
    <p><label for="q">Query</label><input type="search" id="q" size="40"
      placeholder="a title, a topic, an assignment, your own notes"></p>
    <div id="results"></div>`
  const input = $('q')
  input.oninput = () => {
    const query = input.value.trim().toLowerCase()
    if (!query) {
      $('results').innerHTML = ''
      return
    }
    if (query.length < 2) {
      // saying nothing here reads as "no matches", which is a different answer
      $('results').innerHTML = '<p class="secondary">Keep typing, two letters or more.</p>'
      return
    }

    // everything the student put in or the parser pulled out, not just the
    // citations: a topic, an assignment title and your own note about a
    // reading are all things you go looking for by name later
    const hits = []
    const add = (course, where, kind, text) => hits.push({ course, where, kind, text })

    for (const course of state.courses) {
      for (const session of course.parse.sessions) {
        const week = session.week_number ? `Week ${session.week_number}` : ''
        if ((session.topic || '').toLowerCase().includes(query)) {
          add(course, week, 'Topic', session.topic)
        }
        for (const reading of session.readings) {
          const cited = view.citation(reading.work)
          if (`${cited} ${reading.raw_source_text}`.toLowerCase().includes(query)) {
            add(course, week, 'Reading', cited)
          }
          const note = (state.progress.get(view.readingKey(course, session, reading)) || {}).note
          if (note && note.toLowerCase().includes(query)) {
            add(course, week, 'Your note', `${note} — on ${cited}`)
          }
        }
      }
      for (const item of course.parse.deliverables.items) {
        const body = `${item.title} ${item.requirements_text || ''}`
        if (body.toLowerCase().includes(query)) {
          add(course, item.due_date ? view.shortDate(item.due_date) : '', 'Assignment', item.title)
        }
      }
      for (const policy of course.parse.policies || []) {
        if ((policy.body || '').toLowerCase().includes(query)) {
          const flat = policy.body.replace(/\s+/g, ' ').trim()
          add(course, '', 'Policy', flat.slice(0, 160) + (flat.length > 160 ? '…' : ''))
        }
      }
    }

    $('results').innerHTML = hits.length
      ? `<p class="secondary">${hits.length} match${hits.length === 1 ? '' : 'es'}.</p>
         <table><tbody>${hits.map((h) => `<tr>
           <td class="w-course">${view.esc(h.course.code)}</td>
           <td class="when">${view.esc(h.where)}</td>
           <td class="hitkind">${view.esc(h.kind)}</td>
           <td class="entry">${view.esc(h.text)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="secondary">No matches.</p>'
  }
}

function wireDropZone(zoneId, inputId) {
  const zone = $(zoneId)
  const input = $(inputId)

  input.onchange = () => {
    if (input.files.length) submit([...input.files])
    input.value = ''
  }

  for (const name of ['dragenter', 'dragover']) {
    zone.addEventListener(name, (e) => {
      e.preventDefault()
      zone.dataset.active = 'true'
    })
  }
  for (const name of ['dragleave', 'drop']) {
    zone.addEventListener(name, (e) => {
      e.preventDefault()
      zone.dataset.active = 'false'
    })
  }
  zone.addEventListener('drop', (e) => {
    const all = [...(e.dataTransfer?.files || [])]
    const files = all.filter((f) => f.type === 'application/pdf')
    // a word document dropped alongside the pdfs used to vanish without a
    // word, which reads as the tool having lost it. say what happened.
    for (const skipped of all.filter((f) => f.type !== 'application/pdf')) {
      state.files.push({
        name: skipped.name, kind: '',
        note: 'not a pdf, so it cannot be read. export it as a pdf and drop that.',
        warn: true,
      })
    }
    if (all.length > files.length) drawQueue()
    if (files.length) submit(files)
  })
}

async function boot() {
  state.courses = await store.listCourses()
  state.documents = await store.listDocuments()
  state.progress = new Map((await store.listProgress()).map((e) => [e.id, e]))
  // with nothing parsed yet the drop zone is the only thing worth showing, so
  // it starts open and folds away once there is a schedule to look at
  $('tools').open = state.courses.length === 0
  $('data-tools').hidden = state.courses.length === 0
  if (state.courses.length) {
    state.active = state.courses[0].id
    applyRequiredStyle()
    drawUnmatched()
    draw()
  }

  wireDropZone('file-drop', 'file-input')
  wireDropZone('welcome-drop', 'file-input')
  $('welcome-choose').onclick = () => $('file-input').click()
  // a fresh visit shows the welcome alone, not a folded panel beside it
  $('welcome').hidden = state.courses.length > 0
  $('tools').hidden = state.courses.length === 0

  $('review-table').addEventListener('click', (e) => {
    if (!e.target.closest('#toggle-all')) return
    // keep whatever has been typed before the table is rebuilt under it
    harvestReviewEdits()
    state.reviewShowAll = !state.reviewShowAll
    showReview()
  })

  $('confirm').onclick = confirmParse
  // discarding throws away a parse the visitor may have spent minutes
  // correcting, and there is no way back to it
  $('discard').onclick = () => {
    const name = state.pending ? state.pending.name : 'this file'
    if (!confirm(`Discard ${name} without saving? Any corrections you typed go with it.`)) return
    nextReview()
  }

  $('nav').onclick = (e) => {
    const link = e.target.closest('[data-course]')
    if (!link) return
    e.preventDefault()
    state.active = link.dataset.course
    applyRequiredStyle()
    draw()
  }

  $('style-select').onchange = (e) => {
    view.setStyle(e.target.value)
    draw()
  }

  $('remove-course').onclick = async () => {
    const course = state.courses.find((c) => c.id === state.active)
    if (!course) return
    if (!confirm(`Remove ${course.code} and its checklist from this browser?`)) return
    await store.removeCourse(course.id)
    state.courses = await store.listCourses()
    state.active = state.courses[0]?.id ?? null
    drawNav()
    draw()
  }

  // ticking a box and jotting a note are the two things done most often, so
  // both save immediately rather than behind a save button
  $('view').addEventListener('change', async (e) => {
    const tick = e.target.closest('input[data-progress]')
    if (tick) {
      await setProgress(tick.dataset.progress, { read: tick.checked })
      draw()
      return
    }
    const note = e.target.closest('input[data-note]')
    if (note) {
      await setProgress(note.dataset.note, { note: note.value })
      return
    }
    await handleEdit(e.target)
  })

  // corrections are saved as they are made, same as a tick. nothing here is
  // destructive enough to want a confirm step except removing a row, and that
  // is undone by typing it back.
  $('view').addEventListener('click', async (e) => {
    // copying a citation has to say it worked, or you click it twice and
    // paste twice
    const copy = e.target.closest('[data-copy]')
    if (copy) {
      const was = copy.dataset.label || copy.textContent
      copy.dataset.label = was
      copy.textContent = (await toClipboard(copy.dataset.copy)) ? 'copied' : 'could not copy'
      setTimeout(() => { copy.textContent = was }, 1400)
      return
    }
    // open a stored reading in its own tab. the blob url is deliberately not
    // revoked on the next line: that races the tab still loading it.
    const open = e.target.closest('[data-open-doc]')
    if (open) {
      const doc = state.documents.find((d) => d.id === open.dataset.openDoc)
      if (!doc || !doc.pdf) {
        status('intake-status',
          'That reading was taken in before the file was kept. Drop it in again to open it.')
        $('tools').open = true
        return
      }
      window.open(URL.createObjectURL(new Blob([doc.pdf], { type: 'application/pdf' })),
                  '_blank', 'noopener')
      return
    }
    const del = e.target.closest('[data-remove-reading]')
    if (del) {
      const [si, ri] = del.dataset.removeReading.split('.').map(Number)
      const course = activeCourse()
      course.parse.sessions[si].readings.splice(ri, 1)
      await saveCourse(course)
      return
    }
    const add = e.target.closest('[data-add-reading]')
    if (add) {
      const course = activeCourse()
      const session = course.parse.sessions[Number(add.dataset.addReading)]
      session.readings.push(blankReading(session))
      await saveCourse(course)
      focusLast('input[data-edit-reading]')
      return
    }
    const dueDel = e.target.closest('[data-remove-due]')
    if (dueDel) {
      const { course, index } = dueTarget(dueDel.dataset.removeDue)
      course.parse.deliverables.items.splice(index, 1)
      retotal(course)
      await saveCourse(course)
      return
    }
    const dueAdd = e.target.closest('[data-add-due]')
    if (dueAdd) {
      const course = state.courses.find((c) => c.id === dueAdd.dataset.addDue)
      course.parse.deliverables.items.push({
        title: '', due_date: null, weight_percent: null,
        recurrence: null, requirements_text: '', confidence: 1,
      })
      await saveCourse(course)
      focusLast('input[data-due-title]')
      return
    }
  })

  $('edit-toggle').onclick = () => {
    state.editing = !state.editing
    draw()
  }

  // the index scrolls the ledger to a week rather than navigating anywhere
  $('rail').addEventListener('click', (e) => {
    const chip = e.target.closest('[data-filter]')
    if (chip) {
      const key = chip.dataset.filter
      if (key === 'clear') state.filter = { unread: false, required: false, soon: false }
      else state.filter[key] = !state.filter[key]
      draw()
      return
    }
    const jump = e.target.closest('[data-jump]')
    if (!jump) return
    e.preventDefault()
    const row = document.querySelector(`tr.sep[data-week="${jump.dataset.jump}"]`)
    if (row) row.scrollIntoView({ block: 'start' })
  })

  // the ledger is a document you work down in one sitting, so it takes the
  // keys a document reader takes. anything typed into a field is left alone,
  // and so is any browser or os shortcut.
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const el = document.activeElement
    const typing = el && (el.tagName === 'INPUT' || el.tagName === 'SELECT'
      || el.tagName === 'TEXTAREA' || el.isContentEditable)
    if (typing) {
      if (e.key === 'Escape') el.blur()
      return
    }
    if ($('views').hidden) return

    // the number keys follow the tab strip left to right, so what you see is
    // what you press
    const views = ['now', 'week', 'schedule', 'deadlines', 'grades',
                   'bibliography', 'policies', 'search']
    if (/^[1-8]$/.test(e.key)) {
      state.currentView = views[Number(e.key) - 1]
      draw()
      return
    }
    if (e.key === '/') {
      e.preventDefault()
      state.currentView = 'search'
      draw()
      const box = $('q')
      if (box) box.focus()
      return
    }
    if (state.currentView !== 'week') return

    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); moveCursor(1); return }
    if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); moveCursor(-1); return }
    if (e.key === 't') {
      const here = document.querySelector('tr.sep.current') || document.querySelector('tr.sep')
      if (here) here.scrollIntoView({ block: 'start' })
      return
    }
    const row = cursorRow()
    if (!row) return
    if (e.key === ' ') {
      e.preventDefault()
      const tick = row.querySelector('input[data-progress]')
      if (tick) {
        tick.checked = !tick.checked
        tick.dispatchEvent(new Event('change', { bubbles: true }))
      }
      return
    }
    if (e.key === 'n') {
      e.preventDefault()
      const note = row.querySelector('input[data-note]')
      if (note) note.focus()
    }
  })

  document.querySelector('.tabs').onclick = (e) => {
    const button = e.target.closest('button[data-view]')
    if (!button) return
    state.currentView = button.dataset.view
    draw()
  }

  $('print').onclick = () => window.print()
  $('print-top').onclick = () => window.print()

  $('export').onclick = async () => {
    const data = await store.exportAll()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'schedule-reader.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  $('calendar').onclick = () => {
    const rows = grades.datedDeadlines(view.currentTermCourses(state.courses))
    if (!rows.length) return
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '')
    const blob = new Blob([grades.toIcs(rows, stamp)], { type: 'text/calendar' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'deadlines.ics'
    a.click()
    URL.revokeObjectURL(url)
  }

  $('export-notes').onclick = () => {
    const rows = collectNotes()
    if (!rows.length) return
    const blob = new Blob([notesAsMarkdown(rows)], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'reading-notes.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  $('import-input').onchange = async () => {
    const file = $('import-input').files[0]
    if (!file) return
    try {
      await store.importAll(JSON.parse(await file.text()))
      state.courses = await store.listCourses()
      state.documents = await store.listDocuments()
      // the restored ticks and notes are in the database but not yet in
      // memory, and without this the ledger draws every reading unread as
      // though the backup had lost them
      state.progress = new Map((await store.listProgress()).map((p) => [p.id, p]))
      state.active = state.courses[0]?.id ?? null
      $('views').hidden = !state.courses.length
      $('tools').open = state.courses.length === 0
      $('data-tools').hidden = state.courses.length === 0
      draw()
    } catch (error) {
      status('intake-status', `Import failed: ${error.message}`)
    }
  }

  $('clear').onclick = async () => {
    if (!confirm('Delete every course, reading and note stored in this browser?')) return
    await store.clearAll()
    state.courses = []
    state.documents = []
    state.active = null
    state.files = []
    // the ticks live in memory as well as in the database, and a cleared
    // browser that still remembers what you had read is not cleared
    state.progress = new Map()
    state.pending = null
    state.queue = []
    state.cursor = null
    $('data-tools').hidden = true
    drawQueue()
    // redrawing is what brings the welcome page back. without it the app sat
    // on a blank screen with the deleted course still naming the tab.
    draw()
    status('intake-status', 'All data cleared')
  }

  // the browser decides when installing is on offer; the line only appears
  // once it says so, and goes away again once the app is installed
  let installPrompt = null
  const showInstall = (canPrompt) => {
    $('install').hidden = !canPrompt
    $('install-help').hidden = canPrompt
  }
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    installPrompt = e
    showInstall(true)
  })
  // already installed: neither offer applies, and the line goes quiet
  window.addEventListener('appinstalled', () => {
    installPrompt = null
    $('install').hidden = true
    $('install-help').hidden = true
  })
  if (window.matchMedia('(display-mode: standalone)').matches) {
    $('install').hidden = true
    $('install-help').hidden = true
  }
  $('install').onclick = async () => {
    if (!installPrompt) return
    installPrompt.prompt()
    await installPrompt.userChoice
    installPrompt = null
    showInstall(false)
  }

  draw()

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {})
    // when a deploy replaces the worker, the page it is holding open is still
    // built from the old cache. one reload as the new worker takes control
    // brings the fresh assets in, instead of showing a stale page all visit.
    let reloaded = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (reloaded) return
      reloaded = true
      if (navigator.serviceWorker.controller) location.reload()
    })
  }
}

boot()


// a course that states its own required style overrides the visitor's choice,
// because that is the one that has to be handed in
function applyRequiredStyle() {
  const course = state.courses.find((c) => c.id === state.active)
  const required = course && course.parse.course.citation_style
  if (required && cite.styles().includes(required)) view.setStyle(required)
}
