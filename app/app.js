// main thread. holds state, drives the two workers, draws the views. all the
// heavy work happens in the workers so the page stays responsive.

import * as store from './store.js'
import * as view from './render.js'
import * as cite from './cite.js'

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
      state.queue.push({ name: job.name, parse: result })
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
    id: job.hash || job.name,
    filename: job.name,
    courseId: courseId || null,
    workKey: workKey || null,
    matchScore: match.score,
    matchMethod: match.method,
    pageCount: (extracted && extracted.page_count) || 0,
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
  status('intake-status', `${files.length} file(s) queued`)

  for (const file of files) {
    const id = nextId++
    const job = { name: file.name, kind: '', note: 'queued' }
    state.files.push(job)
    waiting.set(id, job)
    file.arrayBuffer().then((buffer) => {
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

async function confirmParse() {
  const parse = state.pending.parse

  // apply any edits the visitor made to a citation line
  for (const input of $('review-table').querySelectorAll('input[data-session]')) {
    const session = parse.sessions[Number(input.dataset.session)]
    const reading = session.readings[Number(input.dataset.reading)]
    const edited = input.value.trim()
    if (edited && edited !== view.citation(reading.work)) {
      reading.work.rendered_override = edited
      reading.work.title = reading.work.title || edited
      reading.confidence = 1
    }
  }

  const code = parse.course.code || state.pending.name.replace(/\.pdf$/i, '')
  const course = {
    id: parse.file_hash || code,
    code,
    title: parse.course.title || '',
    parse,
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
  nav.innerHTML = state.courses
    .map((c) => {
      const tag = codeCounts.get(c.code) > 1 ? ` ${view.courseTag(c)}` : ''
      return `<a href="#" data-course="${view.esc(c.id)}" title="${view.esc(courseLabel(c))}"${
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
  }
}

function focusLast(selector) {
  const all = document.querySelectorAll(selector)
  if (all.length) all[all.length - 1].focus()
}

function draw() {
  drawNav()
  const course = state.courses.find((c) => c.id === state.active) || state.courses[0]
  if (!course) {
    $('views').hidden = true
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

  const target = $('view')
  if (state.currentView === 'week') {
    const ledger = view.weekView(course, state.progress, editing)
    target.innerHTML = ledger.html
    $('rail').innerHTML = view.railView(course, ledger, state.courses)
  } else {
    $('rail').innerHTML = ''
    if (state.currentView === 'schedule') target.innerHTML = view.scheduleView(course)
    else if (state.currentView === 'deadlines') target.innerHTML = view.deadlinesView(state.courses, state.active, editing)
    else if (state.currentView === 'bibliography') target.innerHTML = view.bibliographyView(course)
    else if (state.currentView === 'search') drawSearch(target)
  }

  for (const button of document.querySelectorAll('.tabs button[data-view]')) {
    button.setAttribute('aria-current', String(button.dataset.view === state.currentView))
  }

  // the document line and the sheet number: a record identifies itself
  const stamp = new Date().toISOString().slice(0, 10)
  // the term can live on the course row or in the parsed front matter, and
  // reading only one of them printed a dash next to a course that has a term
  const term = (course.term || course.parse.course?.term || '')
    .replace(/\b[a-z]/g, (c) => c.toUpperCase())
  $('docline').textContent =
    [course.code || 'Untitled', term, stamp].filter(Boolean).join(' · ')
  $('print-meta').textContent =
    `${state.courses.indexOf(course) + 1} of ${state.courses.length} · ${stamp}`
}

function drawSearch(target) {
  target.innerHTML = `<h2>Search</h2>
    <p><label for="q">Query</label><input type="search" id="q" size="40"></p>
    <div id="results"></div>`
  const input = $('q')
  input.oninput = () => {
    const query = input.value.trim().toLowerCase()
    if (query.length < 2) {
      $('results').innerHTML = ''
      return
    }
    const hits = []
    for (const course of state.courses) {
      for (const session of course.parse.sessions) {
        for (const reading of session.readings) {
          const text = `${view.citation(reading.work)} ${reading.raw_source_text}`.toLowerCase()
          if (text.includes(query)) {
            hits.push(`<tr><td>${view.esc(course.code)}</td>
              <td>${view.esc(session.week_number ? `Week ${session.week_number}` : '')}</td>
              <td class="entry">${view.esc(view.citation(reading.work))}</td></tr>`)
          }
        }
      }
    }
    $('results').innerHTML = hits.length
      ? `<table><tbody>${hits.join('')}</tbody></table>`
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

  $('review-table').addEventListener('click', (e) => {
    if (!e.target.closest('#toggle-all')) return
    state.reviewShowAll = !state.reviewShowAll
    showReview()
  })

  $('confirm').onclick = confirmParse
  $('discard').onclick = () => {
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
    const jump = e.target.closest('[data-jump]')
    if (!jump) return
    e.preventDefault()
    const row = document.querySelector(`tr.sep[data-week="${jump.dataset.jump}"]`)
    if (row) row.scrollIntoView({ block: 'start' })
  })

  document.querySelector('.tabs').onclick = (e) => {
    const button = e.target.closest('button[data-view]')
    if (!button) return
    state.currentView = button.dataset.view
    draw()
  }

  $('print').onclick = () => window.print()

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

  $('import-input').onchange = async () => {
    const file = $('import-input').files[0]
    if (!file) return
    try {
      await store.importAll(JSON.parse(await file.text()))
      state.courses = await store.listCourses()
      state.documents = await store.listDocuments()
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
    $('views').hidden = true
    $('tools').open = true
    $('data-tools').hidden = true
    state.files = []
    drawQueue()
    drawNav()
    status('intake-status', 'All data cleared')
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
