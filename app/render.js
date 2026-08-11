// views. tables for anything tabular, labels rather than sentences, and colour
// only where it says something actionable.

import * as cite from './cite.js'

// which reference style citations render in. a course that states its own
// required style wins, otherwise this is the visitor's choice.
export let style = 'chicago'

export function setStyle(next) {
  style = next
}

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}

export function shortDate(iso) {
  if (!iso) return ''
  const [, month, day] = iso.split('-')
  return `${Number(month)}/${Number(day)}`
}

export function sortKey(work) {
  const first = (work.authors || [])[0]
  return ((first && (first.surname || first.literal)) || work.title || '').toLowerCase()
}

export function citation(work) {
  return cite.format(work, style)
}


function weekLabel(session) {
  const parts = []
  if (session.week_number) parts.push(`Week ${session.week_number}`)
  if (session.meeting_date) parts.push(shortDate(session.meeting_date))
  if (session.sub_session_label) parts.push(session.sub_session_label)
  return parts.join(' ') || 'Unscheduled'
}

export function scheduleView(course) {
  const rows = course.parse.sessions.map((session) => {
    const readings = session.readings.length
      ? `<ul>${session.readings
          .map((r) => {
            const level = r.requirement_level !== 'required'
              ? ` <span class="secondary">${esc(r.requirement_level)}</span>` : ''
            const warn = r.content_warning
              ? `<div class="secondary">Content warning: ${esc(r.content_warning)}</div>` : ''
            const access = r.access_note
              ? `<div class="secondary">${esc(r.access_note)}</div>` : ''
            return `<li class="entry">${esc(citation(r.work))}${level}${access}${warn}</li>`
          })
          .join('')}</ul>`
      : `<span class="secondary">${esc(session.session_type.replace('_', ' '))}</span>`
    return `<tr>
      <td>${esc(weekLabel(session))}</td>
      <td>${esc(session.topic || '')}</td>
      <td>${readings}</td>
    </tr>`
  })

  return `<h2>${esc(course.code)} schedule</h2>
    <table>
      <thead><tr><th>Week</th><th>Topic</th><th>Readings</th></tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>`
}

export function weekView(course, progress) {
  const groups = new Map()
  for (const session of course.parse.sessions) {
    const key = session.week_number ?? `x${session.ordinal}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(session)
  }

  const blocks = []
  for (const [key, sessions] of groups) {
    const rows = []
    for (const session of sessions) {
      for (const reading of session.readings) {
        const id = `${course.id}::${reading.work.signature}`
        const saved = progress.get(id) || {}
        const label = session.sub_session_label ? ` ${session.sub_session_label}` : ''
        rows.push(`<tr class="entry">
          <td class="tick"><input type="checkbox" data-progress="${esc(id)}"
            ${saved.read ? 'checked' : ''} aria-label="read"></td>
          <td class="when">${esc(shortDate(session.meeting_date))}${esc(label)}</td>
          <td>
            <div class="${saved.read ? 'done' : ''}">${esc(cite.short(reading.work))}</div>
            ${reading.requirement_level !== 'required'
              ? `<span class="secondary">${esc(reading.requirement_level)}</span> ` : ''}
            ${reading.page_range ? `<span class="secondary">pp. ${esc(reading.page_range)}</span> ` : ''}
            ${reading.access_note ? `<span class="secondary">${esc(reading.access_note)}</span>` : ''}
            ${reading.content_warning
              ? `<div class="secondary">Content warning: ${esc(reading.content_warning)}</div>` : ''}
            <div><input type="text" class="note" data-note="${esc(id)}"
              value="${esc(saved.note || '')}" placeholder="note"></div>
          </td>
        </tr>`)
      }
    }

    const due = course.parse.deliverables.items
      .filter((d) => sessions.some((s) => s.meeting_date && d.due_date === s.meeting_date))
      .map((d) => `<li>${esc(d.title)}${d.weight_percent ? ` (${d.weight_percent}%)` : ''}</li>`)
      .join('')

    const heading = sessions[0].topic || sessions[0].section_heading || ''
    const done = rows.filter((r) => r.includes('checked')).length
    // a break or a cancelled class has no week number, so it is titled by its
    // date rather than by an invented one
    const title = sessions[0].week_number
      ? `Week ${sessions[0].week_number}`
      : shortDate(sessions[0].meeting_date) || 'Unscheduled'
    blocks.push(`<section class="week">
      <h3>${esc(title)} <span class="secondary">${esc(heading)}</span></h3>
      ${rows.length
        ? `<p class="secondary">${done} of ${rows.length} read</p>
           <table class="checklist"><tbody>${rows.join('')}</tbody></table>`
        : `<p class="secondary">${esc(sessions[0].session_type.replace('_', ' '))}</p>`}
      ${due ? `<p class="secondary">Due this week</p><ul>${due}</ul>` : ''}
    </section>`)
  }

  return `<h2>${esc(course.code)} by week</h2>${blocks.join('')}`
}


export function courseTag(course) {
  const meta = course.parse.course
  const term = meta.term ? meta.term[0].toUpperCase() + meta.term.slice(1) : ''
  return [term, meta.year].filter(Boolean).join(' ')
}

export function deadlinesView(courses, activeId) {
  // one section per course. merging every course into one table made the same
  // assignment appear once per parsed edition and detached the weights from
  // the course they belong to, and it also meant switching course changed
  // nothing on this view. the active course leads.
  const ordered = [...courses].sort((a, b) =>
    (a.id === activeId ? 0 : 1) - (b.id === activeId ? 0 : 1)
  )

  const codeCounts = new Map()
  for (const course of courses) {
    codeCounts.set(course.code, (codeCounts.get(course.code) || 0) + 1)
  }

  const sections = ordered.map((course) => {
    const graded = []
    const events = []
    for (const item of course.parse.deliverables.items) {
      const when = item.due_date
        ? shortDate(item.due_date)
        : item.recurrence === 'see schedule'
          ? 'see schedule'
          : item.recurrence || ''
      const row = {
        sort: item.due_date || '9999-99-99',
        html: `<tr>
          <td class="when">${esc(when)}</td>
          <td>${esc(item.title)}</td>
          <td class="num">${item.weight_percent ? `${item.weight_percent}%` : ''}</td>
        </tr>`,
      }
      // graded work is what the term is assessed on. presentation slots and
      // sign-ups are real dates but not deadlines, and mixing them buries the
      // few items that carry the grade.
      if (item.weight_percent) graded.push(row)
      else if (item.due_date) events.push(row)
    }
    graded.sort((a, b) => a.sort.localeCompare(b.sort))
    events.sort((a, b) => a.sort.localeCompare(b.sort))

    const table = (rows) => `<table>
        <thead><tr><th class="when">Due</th><th>Item</th><th class="num">Weight</th></tr></thead>
        <tbody>${rows.map((r) => r.html).join('')}</tbody>
      </table>`

    const total = course.parse.deliverables.weight_total
    // a shared course code alone cannot tell two editions apart
    const tag = codeCounts.get(course.code) > 1 ? ` ${courseTag(course)}` : ''

    return `<section class="course-deadlines">
      <h3>${esc(course.code)}${esc(tag)}
        ${total ? `<span class="secondary">weights total ${total}%</span>` : ''}</h3>
      ${graded.length ? table(graded) : '<p class="secondary">No weighted work found.</p>'}
      ${events.length
        ? `<p class="secondary">On the schedule, not separately weighted</p>${table(events)}`
        : ''}
    </section>`
  })

  return `<h2>Deadlines</h2>${sections.join('')}`
}


export function bibliographyView(course) {
  const seen = new Map()
  for (const session of course.parse.sessions) {
    for (const reading of session.readings) {
      const key = reading.work.signature || reading.work.raw_source_text
      if (!seen.has(key)) seen.set(key, reading.work)
    }
  }
  const entries = [...seen.values()]
    .map((work) => ({ work, sort: sortKey(work) }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ work }) => `<li class="entry">${esc(citation(work))}</li>`)

  const required = course.parse.course.citation_style
  return `<h2>${esc(course.code)} bibliography</h2>
    ${required
      ? `<p class="secondary">This course requires ${esc(required.toUpperCase())}.</p>`
      : ''}
    <ol class="bibliography">${entries.join('')}</ol>`
}

export function reviewTable(parse) {
  const flagged = new Set(parse.review.map((r) => r.source_text))
  const blocks = []

  parse.sessions.forEach((session, si) => {
    if (!session.readings.length) return
    const rows = session.readings.map((reading, ri) => {
      // the source text only earns its space where the parse is doubtful.
      // printing it under every row buries the rows that need attention.
      const low = flagged.has(reading.raw_source_text) || reading.confidence < 0.75
      const source = low
        ? `<div class="secondary source">${esc(reading.raw_source_text)}</div>`
        : ''
      return `<tr class="${low ? 'review-row' : ''}">
        <td class="flagcol">${low ? 'check' : ''}</td>
        <td>
          <input type="text" data-session="${si}" data-reading="${ri}"
            value="${esc(citation(reading.work))}">
          ${source}
        </td>
        <td class="num secondary">${reading.confidence.toFixed(2)}</td>
      </tr>`
    })

    const when = [
      session.week_number ? `Week ${session.week_number}` : '',
      shortDate(session.meeting_date),
      session.sub_session_label || '',
    ]
      .filter(Boolean)
      .join(' ')

    blocks.push(`<section class="week">
      <h3>${esc(when || 'Unscheduled')} <span class="secondary">${esc(session.topic || '')}</span></h3>
      <table class="review"><tbody>${rows.join('')}</tbody></table>
    </section>`)
  })

  const empty = parse.sessions.filter((s) => !s.readings.length)
  const notes = []
  if (empty.length) {
    notes.push(`${empty.length} session(s) with no readings: ${
      esc([...new Set(empty.map((s) => s.session_type.replace('_', ' ')))].join(', '))}`)
  }
  for (const warning of parse.warnings || []) notes.push(esc(warning))

  return `<p class="secondary">${parse.sessions.length} sessions,
    ${parse.sessions.reduce((n, s) => n + s.readings.length, 0)} readings,
    ${parse.review.length} to check</p>
    ${notes.length ? `<ul class="secondary">${notes.map((n) => `<li>${n}</li>`).join('')}</ul>` : ''}
    ${blocks.join('')}`
}
