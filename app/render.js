// views. tables for anything tabular, labels rather than sentences, and colour
// only where it says something actionable.

const NBSP = ' '

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

export function authorList(authors) {
  if (!authors || !authors.length) return ''
  const names = authors.map((a) => (a.literal ? a.literal : [a.surname, a.given].filter(Boolean).join(', ')))
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names[0]} et al.`
}

// a title already carries its closing period inside the quotes, so the joiner
// has to notice that rather than adding a second one
function joinParts(bits) {
  let out = ''
  for (const bit of bits) {
    if (!bit) continue
    if (out) out += /[.?!]["'”’]?$/.test(out) ? ' ' : '. '
    out += bit
  }
  if (!out) return ''
  return /[.?!]["'”’]?$/.test(out) ? out : `${out}.`
}

export function citation(work) {
  if (work.rendered_override) return work.rendered_override
  const bits = []
  const authors = authorList(work.authors)
  if (authors) bits.push(authors)
  if (work.year) {
    let year = String(work.year)
    if (work.year_is_open) year += '-'
    else if (work.year_end) year += `-${work.year_end}`
    bits.push(year)
  }
  if (work.title) bits.push(`"${work.title}."`)
  if (work.container) {
    let container = work.container
    if (work.volume) {
      container += ` ${work.volume}`
      if (work.issue) container += `(${work.issue})`
    }
    if (work.pages) container += `: ${work.pages}`
    bits.push(container)
  } else if (work.pages) {
    bits.push(work.pages)
  }
  if (work.report_number) bits.push(work.report_number)
  return joinParts(bits) || work.raw_source_text || ''
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

export function weekView(course, documents) {
  const matched = new Set(documents.filter((d) => d.courseId === course.id).map((d) => d.workKey))
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
        const workKey = reading.work.signature
        const present = matched.has(workKey)
        rows.push(`<tr class="${present ? '' : 'missing'}">
          <td>${present ? 'have' : 'MISSING'}</td>
          <td>${esc(shortDate(session.meeting_date))}</td>
          <td class="entry">${esc(citation(reading.work))}</td>
        </tr>`)
      }
    }
    const due = course.parse.deliverables.items
      .filter((d) => sessions.some((s) => s.meeting_date && d.due_date === s.meeting_date))
      .map((d) => `<li>${esc(d.title)} due ${esc(shortDate(d.due_date))}</li>`)
      .join('')

    blocks.push(`<h3>Week ${esc(key)}${NBSP}${esc(sessions[0].topic || '')}</h3>
      ${rows.length ? `<table><tbody>${rows.join('')}</tbody></table>`
        : '<p class="secondary">No readings.</p>'}
      ${due ? `<ul>${due}</ul>` : ''}`)
  }

  return `<h2>${esc(course.code)} by week</h2>${blocks.join('')}`
}

export function deadlinesView(courses) {
  const rows = []
  for (const course of courses) {
    for (const item of course.parse.deliverables.items) {
      if (!item.due_date && !item.recurrence && !item.weight_percent) continue
      const when = item.due_date
        ? shortDate(item.due_date)
        : item.recurrence || ''
      rows.push({
        sort: item.due_date || (item.recurrence === 'see schedule' ? '9998' : '9999'),
        html: `<tr>
          <td>${esc(when)}</td>
          <td>${esc(course.code)}</td>
          <td>${esc(item.title)}</td>
          <td class="num">${item.weight_percent ? `${item.weight_percent}%` : ''}</td>
        </tr>`,
      })
    }
  }
  rows.sort((a, b) => a.sort.localeCompare(b.sort))
  return `<h2>Deadlines</h2>
    <table>
      <thead><tr><th>Due</th><th>Course</th><th>Item</th><th class="num">Weight</th></tr></thead>
      <tbody>${rows.map((r) => r.html).join('')}</tbody>
    </table>`
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
    .map((work) => ({ work, sort: (authorList(work.authors) || work.title || '').toLowerCase() }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ work }) => `<li class="entry">${esc(citation(work))}</li>`)

  const style = course.parse.course.citation_style
  return `<h2>${esc(course.code)} bibliography</h2>
    ${style ? `<p class="secondary">Required style: ${esc(style)}</p>` : ''}
    <ul>${entries.join('')}</ul>`
}

export function reviewTable(parse) {
  const flagged = new Set(parse.review.map((r) => r.source_text))
  const rows = []
  parse.sessions.forEach((session, si) => {
    session.readings.forEach((reading, ri) => {
      const low = flagged.has(reading.raw_source_text) || reading.confidence < 0.75
      rows.push(`<tr class="${low ? 'review-row' : ''}">
        <td>${esc(weekLabel(session))}</td>
        <td><input type="text" size="46" data-session="${si}" data-reading="${ri}"
             value="${esc(citation(reading.work))}"></td>
        <td class="num">${reading.confidence.toFixed(2)}</td>
        <td class="secondary">${esc(reading.work.matched_pattern || 'no pattern matched')}</td>
      </tr>
      <tr class="${low ? 'review-row' : ''}">
        <td></td><td colspan="3" class="secondary">from: ${esc(reading.raw_source_text)}</td>
      </tr>`)
    })
  })

  const unresolved = parse.review.filter((r) => r.entity_type !== 'assigned_reading')
  const other = unresolved.length
    ? `<p class="secondary">${unresolved.length} other row(s) flagged: ${
        esc(unresolved.map((r) => r.reason).join('; '))}</p>`
    : ''

  return `<p class="secondary">${parse.sessions.length} sessions,
    ${parse.sessions.reduce((n, s) => n + s.readings.length, 0)} readings,
    ${parse.review.length} flagged</p>
    ${other}
    <table>
      <thead><tr><th>Week</th><th>Citation</th><th class="num">Score</th><th>Pattern</th></tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>`
}
