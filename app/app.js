// main thread. holds state, drives the two workers, draws the views. all the
// heavy work happens in the workers so the page stays responsive.

import * as store from './store.js'
import * as view from './render.js'

const $ = (id) => document.getElementById(id)

const state = {
  courses: [],
  documents: [],
  active: null,
  pending: null,
  currentView: 'schedule',
  jobs: 0,
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
    status(job.statusEl, `Reading ${job.name}, page ${page} of ${total}`)
    return
  }
  if (type === 'error') {
    status(job.statusEl, `Could not read ${job.name}: ${message}`)
    waiting.delete(id)
    return
  }
  if (type === 'cancelled') {
    status(job.statusEl, `Cancelled ${job.name}`)
    waiting.delete(id)
    return
  }
  if (type !== 'extracted') return

  if (payload.needOcr.length) {
    status(
      job.statusEl,
      `${job.name}: ${payload.needOcr.length} page(s) have no text layer and were left empty. ` +
        'Scanned pages need OCR, which is not run without asking.'
    )
  } else {
    status(job.statusEl, `Parsing ${job.name}`)
  }

  const { parseWorker: pw } = workers()
  pw.postMessage({ type: job.kind === 'syllabus' ? 'parse' : 'reading', id, payload })
}

function onParseMessage(event) {
  const { type, id, result, stage, message } = event.data

  if (type === 'boot') {
    for (const job of waiting.values()) status(job.statusEl, `Loading parser: ${stage}`)
    return
  }
  const job = waiting.get(id)
  if (!job) return

  if (type === 'error') {
    status(job.statusEl, `Could not parse ${job.name}: ${message}`)
    waiting.delete(id)
    return
  }

  if (type === 'parsed') {
    waiting.delete(id)
    state.pending = { name: job.name, parse: result }
    status(job.statusEl, `Parsed ${job.name}`)
    showReview()
    return
  }

  if (type === 'reading') {
    waiting.delete(id)
    matchReading(job, result)
  }

  if (type === 'matched') {
    waiting.delete(id)
    finishReading(job, result)
  }
}

async function matchReading(job, extracted) {
  const head = extracted.pages.slice(0, 2).map((p) => p.text).join('\n')
  const candidates = []
  for (const course of state.courses) {
    for (const session of course.parse.sessions) {
      for (const reading of session.readings) {
        candidates.push({
          id: `${course.id}::${reading.work.signature}`,
          title: reading.work.title,
          year: reading.work.year,
          authors: reading.work.authors,
          doi: reading.work.doi,
        })
      }
    }
  }

  if (!candidates.length) {
    finishReading(job, { id: null, score: 0, method: 'no syllabus parsed yet' })
    return
  }

  const id = nextId++
  waiting.set(id, { ...job, extracted })
  const { parseWorker: pw } = workers()
  pw.postMessage({ type: 'match', id, head, candidates })
}

async function finishReading(job, match) {
  const [courseId, workKey] = (match.id || '::').split('::')
  await store.putDocument({
    id: job.hash || job.name,
    filename: job.name,
    courseId: courseId || null,
    workKey: workKey || null,
    matchScore: match.score,
    matchMethod: match.method,
    pageCount: (job.extracted && job.extracted.page_count) || 0,
  })
  state.documents = await store.listDocuments()
  status(
    job.statusEl,
    match.id
      ? `${job.name} matched (${match.score})`
      : `${job.name} not matched: ${match.method}`
  )
  drawUnmatched()
  draw()
}

function submit(files, kind) {
  const { extractWorker: ew } = workers()
  const statusEl = kind === 'syllabus' ? 'intake-status' : 'reading-status'

  for (const file of files) {
    const id = nextId++
    waiting.set(id, { name: file.name, kind, statusEl })
    status(statusEl, `Reading ${file.name}`)
    file.arrayBuffer().then((buffer) => {
      ew.postMessage({ type: 'extract', id, name: file.name, buffer }, [buffer])
    })
  }
}

function showReview() {
  $('review').hidden = false
  $('review-table').innerHTML = view.reviewTable(state.pending.parse)
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
  state.pending = null
  $('review').hidden = true
  $('readings').hidden = false
  $('views').hidden = false
  $('data').hidden = false
  draw()
}

function drawNav() {
  const nav = $('nav')
  if (!state.courses.length) {
    nav.hidden = true
    return
  }
  nav.hidden = false
  nav.innerHTML = state.courses
    .map(
      (c) =>
        `<a href="#" data-course="${view.esc(c.id)}"${
          c.id === state.active ? ' aria-current="page"' : ''
        }>${view.esc(c.code)}</a>`
    )
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

function draw() {
  drawNav()
  const course = state.courses.find((c) => c.id === state.active) || state.courses[0]
  if (!course) return

  const target = $('view')
  if (state.currentView === 'schedule') target.innerHTML = view.scheduleView(course)
  else if (state.currentView === 'week') target.innerHTML = view.weekView(course, state.documents)
  else if (state.currentView === 'deadlines') target.innerHTML = view.deadlinesView(state.courses)
  else if (state.currentView === 'bibliography') target.innerHTML = view.bibliographyView(course)
  else if (state.currentView === 'search') drawSearch(target)

  for (const button of document.querySelectorAll('.tabs button')) {
    button.setAttribute('aria-current', String(button.dataset.view === state.currentView))
  }

  $('print-meta').textContent =
    `${course.code}. Generated ${new Date().toISOString().slice(0, 10)}.`
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

function wireDropZone(zoneId, inputId, kind) {
  const zone = $(zoneId)
  const input = $(inputId)

  input.onchange = () => {
    if (input.files.length) submit([...input.files], kind)
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
    const files = [...(e.dataTransfer?.files || [])].filter((f) => f.type === 'application/pdf')
    if (files.length) submit(files, kind)
  })
}

async function boot() {
  state.courses = await store.listCourses()
  state.documents = await store.listDocuments()
  if (state.courses.length) {
    state.active = state.courses[0].id
    $('readings').hidden = false
    $('views').hidden = false
    $('data').hidden = false
    drawUnmatched()
    draw()
  }

  wireDropZone('syllabus-drop', 'syllabus-input', 'syllabus')
  wireDropZone('reading-drop', 'reading-input', 'reading')

  $('confirm').onclick = confirmParse
  $('discard').onclick = () => {
    state.pending = null
    $('review').hidden = true
    status('intake-status', 'Discarded')
  }

  $('nav').onclick = (e) => {
    const link = e.target.closest('[data-course]')
    if (!link) return
    e.preventDefault()
    state.active = link.dataset.course
    draw()
  }

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
    a.download = 'seminar-vault.json'
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
      $('readings').hidden = !state.courses.length
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
    $('readings').hidden = true
    $('data').hidden = true
    drawNav()
    status('intake-status', 'All data cleared')
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {})
  }
}

boot()
