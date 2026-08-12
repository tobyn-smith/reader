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

// a reading's identity for stored progress and for matching. the citation
// signature is the stable choice across re-parses, but a reading no pattern
// claimed has an empty one, and every such reading in a course would then
// share a key: ticking one ticked them all. those fall back to their position.
// how many days from today, negative for past. dates are compared as calendar
// days rather than instants, so something due at 9am today reads as "today"
// all day rather than flipping to overdue at breakfast.
export function daysUntil(iso) {
  if (!iso) return null
  const parts = String(iso).slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some((n) => !n)) return null
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((Date.UTC(parts[0], parts[1] - 1, parts[2]) - today) / 86400000)
}

// a date is not the question a student is asking. "in 3 days" is.
export function whenLabel(iso) {
  const n = daysUntil(iso)
  if (n === null) return ''
  if (n === 0) return 'today'
  if (n === 1) return 'tomorrow'
  if (n === -1) return 'yesterday'
  if (n < 0) return `${-n} days ago`
  if (n <= 14) return `in ${n} days`
  return ''
}

export function readingKey(course, session, reading) {
  const signature = (reading.work.signature || '').replace(/\|/g, '').trim()
  if (signature) return `${course.id}::${reading.work.signature}`
  return `${course.id}::s${session.ordinal}r${reading.ordinal}`
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

export function weekView(course, progress, editing = false) {
  // the ledger runs in date order, not parse order. a deadlines list at the
  // top of a syllabus parses into dated week-less rows, and in parse order
  // they all sat above week 1; by date they interleave where they belong.
  // only a mostly-dated schedule is sorted, so a dateless course keeps its
  // written order.
  let ordered = course.parse.sessions.map((session, si) => ({ session, si }))
  const datedCount = ordered.filter((e) => e.session.meeting_date).length
  if (datedCount >= 3 && datedCount >= ordered.length * 0.8) {
    ordered = [...ordered].sort((a, b) =>
      String(a.session.meeting_date || '9999').localeCompare(
        String(b.session.meeting_date || '9999')) || a.si - b.si)
  }

  const groups = new Map()
  ordered.forEach(({ session, si }) => {
    const key = session.week_number ?? `x${session.ordinal}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push({ session, si })
  })

  const stamps = []
  const rows = []
  // records are numbered on their own, not by position in the table, which
  // also counts the week separators spliced between them
  let entryNo = 0
  let held = 0
  let heldTotal = 0
  let pagesDone = 0
  let pagesTotal = 0
  const index = []

  for (const [, entries] of groups) {
    const sessions = entries.map((e) => e.session)
    const first = sessions[0]
    const start = sessions.map((s) => s.meeting_date).filter(Boolean).sort()[0] || null
    const days = daysUntil(start)
    const title = first.week_number
      ? String(first.week_number).padStart(2, '0')
      : '\u2014'
    const topic = first.topic || first.section_heading || ''

    const due = course.parse.deliverables.items.filter((d) =>
      sessions.some((s) => s.meeting_date && d.due_date === s.meeting_date))

    let count = 0
    let doneHere = 0
    const body = []
    for (const { session, si } of entries) {
      session.readings.forEach((reading, ri) => {
        const id = readingKey(course, session, reading)
        const saved = progress.get(id) || {}
        count += 1
        heldTotal += 1
        const pages = pageCount(reading.page_range)
        pagesTotal += pages
        if (saved.read) { doneHere += 1; held += 1; pagesDone += pages }

        const cited = editing
          ? `<input type="text" class="cite" data-edit-reading="${si}.${ri}"
               value="${esc(citation(reading.work))}" aria-label="Entry">`
          : `${esc(cite.short(reading.work, 400))}
             ${reading.content_warning
               ? `<span class="cwarn">Content warning \u00b7 ${esc(reading.content_warning)}</span>`
               : ''}
             <input type="text" class="note" data-note="${esc(id)}"
               value="${esc(saved.note || '')}" placeholder="\u2014">`

        entryNo += 1
        // the date belongs to the week, and is printed on its separator. it is
        // repeated on a record only where a week meets more than once and this
        // one falls on a different day.
        const ownDate = session.meeting_date && session.meeting_date !== start
          ? shortDate(session.meeting_date) : ''
        // not held is the state nearly every row is in before term starts, so
        // it is not an exception and takes no accent. only a reading wanted
        // within the week does.
        const wanted = !saved.read && days !== null && days >= -6 && days <= 7
        rows.push(`<tr class="rec${saved.read ? ' struck' : ''}">
          <td class="c-tick">${editing
            ? `<button type="button" class="rowdel" data-remove-reading="${si}.${ri}"
                 aria-label="Remove this entry">\u00d7</button>`
            : `<input type="checkbox" data-progress="${esc(id)}"
                 ${saved.read ? 'checked' : ''} aria-label="Mark as read">`}</td>
          <td class="c-num">${String(entryNo).padStart(2, '0')}</td>
          <td class="c-date">${esc(ownDate)}</td>
          <td class="c-title">${cited}</td>
          <td class="c-src">${esc(sourceOf(reading))}</td>
          <td class="c-pp">${esc(reading.page_range || '')}</td>
          <td class="c-stat${wanted ? ' is-due' : ''}">${
            saved.read ? 'Read' : wanted ? 'Due' : ''}</td>
        </tr>`)
      })
    }

    // a week is marked only when something is actually due in it. marking
    // every current week too meant the accent was on screen constantly, which
    // is the same as it meaning nothing.
    const flagged = due.length > 0
    index.push({ n: title, topic, count, flagged })
    stamps.push({ row: rows.length, days })

    // the week number sits across the tick and number columns so it starts at
    // the left margin. sharing the number column with the record numbers put a
    // big 02 directly above a small 01 and read as two of the same thing.
    const sep = `<tr class="sep" data-week="${index.length - 1}">
        <td class="c-tick sep-n" colspan="2">${esc(title)}</td>
        <td class="c-date sep-d">${esc(shortDate(start))}</td>
        <td class="c-title sep-t" colspan="3">
          <span class="sep-topic">${esc(topic || 'No topic listed')}
            ${count ? `<span class="sep-count">${count} reading${count === 1 ? '' : 's'}</span>` : ''}</span>
          ${due.length
            ? `<span class="sep-sub">${due.map((d) => esc(d.title)).join('; ')} due</span>`
            : ''}
        </td>
        <td class="c-stat sep-c${flagged ? ' is-flag' : ''}">${flagged ? 'Due' : ''}</td>
      </tr>`

    // the separator has to precede this week's records, which are already in
    // the list, so it is spliced in ahead of them
    rows.splice(rows.length - count, 0, sep)

    if (!count) {
      rows.push(`<tr class="rec empty"><td class="c-tick"></td><td class="c-num"></td>
        <td class="c-date"></td>
        <td class="c-title"><em>No reading listed for this week.</em></td>
        <td class="c-src"></td><td class="c-pp"></td>
        <td class="c-stat is-none">\u2014</td></tr>`)
    }

    if (editing) {
      rows.push(`<tr class="rec addrow-row"><td class="c-tick"></td><td class="c-num"></td>
        <td class="c-date"></td>
        <td class="c-title" colspan="4"><button type="button" class="addrow"
          data-add-reading="${entries[0].si}">Add entry</button></td></tr>`)
    }
  }

  const upcoming = stamps.filter((s) => s.days !== null && s.days >= -6)
  const currentIdx = upcoming.length
    ? stamps.indexOf(upcoming.reduce((b, s) => (s.days < b.days ? s : b)))
    : -1

  let html = rows.join('')
  if (currentIdx >= 0) {
    html = html.replace(`<tr class="sep" data-week="${currentIdx}">`,
      `<tr class="sep current" data-week="${currentIdx}">`)
  }

  return {
    html: `<table class="ledger">
      <thead><tr>
        <th class="c-tick"></th>
        <th class="c-num">\u2116</th>
        <th class="c-date">Date</th>
        <th class="c-title">Author / Title</th>
        <th class="c-src">Source</th>
        <th class="c-pp">Pages</th>
        <th class="c-stat">Status</th>
      </tr></thead>
      <tbody>${html}</tbody>
    </table>`,
    index,
    current: currentIdx,
    holdings: { held, heldTotal, pagesDone, pagesTotal },
  }
}

// a page range as a number of pages, for the holdings count. an unparseable
// range contributes nothing rather than a guess.
function pageCount(range) {
  if (!range) return 0
  const m = String(range).match(/(\d+)\s*[-\u2013]\s*(\d+)/)
  if (m) return Math.max(0, Number(m[2]) - Number(m[1]) + 1)
  return /^\d+$/.test(String(range).trim()) ? 1 : 0
}

// where the thing lives: the journal, the book, or the note the syllabus gave
function sourceOf(reading) {
  const w = reading.work || {}
  return w.container || w.publisher || reading.access_note || ''
}


// the catalogue card above the ledger: what this record is, and its facts in
// a fixed grid so two courses read the same way.
export function recordHeader(course) {
  const p = course.parse
  const readings = p.sessions.reduce((n, s) => n + s.readings.length, 0)
  const policy = (p.ai_stance || '').replace(/_/g, ' ')
  const restricted = /prohibit|restrict|ban|not permitted/i.test(policy)
  // front matter often keeps its own label on the value it captured, so a
  // course reads "Title: Comparative Politics". the label is stripped for display.
  const title = (course.title || p.course?.title || '')
    .replace(/^\s*(course\s+)?title\s*[:–-]\s*/i, '')
    .trim()
  // a fact with nothing behind it is dropped rather than printed as a dash.
  // six columns of em dashes is a grid that says nothing loudly.
  // a term comes through as "spring" when no year was found beside it, and a
  // lowercase word beside capitalised labels reads as a glitch
  const term = String(course.term || p.course?.term || '')
    .replace(/\b[a-z]/g, (c) => c.toUpperCase())

  const facts = [
    ['Term', term, false],
    ['Instructor', p.course?.instructor, false],
    ['Meets', p.course?.meeting_pattern, false],
    ['Weeks', String(p.sessions.length), false],
    ['Readings', String(readings), false],
    ['AI policy', p.ai_stance ? policy : null, restricted],
  ].filter(([, v]) => v)

  return `<header class="record">
    <div class="record-id">
      <h2 class="record-code">${esc(course.code || 'Untitled')}</h2>
      ${title ? `<p class="record-title">${esc(title)}</p>` : ''}
    </div>
    <dl class="record-facts">
      ${facts.map(([k, v, flag]) => `<div${flag ? ' class="is-flag"' : ''}>
        <dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}
    </dl>
  </header>`
}

// the left rail: where you are, what you hold, what falls next.
export function railView(course, ledger, courses) {
  const { index, current, holdings } = ledger
  // the count column is dropped. it repeated what the ledger already shows and
  // took a third of the width the topic needed to be legible.
  const entries = index.map((w, i) => `<li class="${i === current ? 'is-current' : ''}">
      <a href="#w${i}" data-jump="${i}" title="${esc(w.topic)}">
        <span class="rail-n${w.flagged ? ' is-flag' : ''}">${esc(w.n)}</span>
        <span class="rail-t">${esc(w.topic || '—')}</span>
      </a></li>`).join('')

  const rows = [
    ['Read', `${holdings.held} of ${holdings.heldTotal}`, false],
    // plenty of syllabi record no page ranges at all. "0 of 0" states a
    // total that was never counted, so an em dash says so instead.
    ['Pages', holdings.pagesTotal
      ? `${holdings.pagesDone} of ${holdings.pagesTotal}` : '—', false],
  ]

  const upcoming = []
  for (const c of courses) {
    for (const d of c.parse.deliverables.items) {
      const days = daysUntil(d.due_date)
      if (days === null || days < 0) continue
      upcoming.push({ days, title: d.title, code: c.code, date: d.due_date })
    }
  }
  upcoming.sort((a, b) => a.days - b.days)

  return `<nav class="rail" aria-label="Index">
    <details class="rail-sec rail-fold">
      <summary>Index</summary>
      <ol class="rail-index">${entries}</ol>
    </details>
    <section class="rail-sec">
      <h3>Progress</h3>
      <dl class="rail-facts">
        ${rows.map(([k, v, flag]) => `<div><dt>${esc(k)}</dt>
          <dd${flag ? ' class="is-flag"' : ''}>${esc(v)}</dd></div>`).join('')}
      </dl>
    </section>
    <section class="rail-sec">
      <h3>Next due</h3>
      ${upcoming.length
        ? `<ul class="rail-due">${upcoming.slice(0, 2).map((d) => `<li>
            <span class="rail-due-d${d.days <= 7 ? ' is-flag' : ''}">${esc(shortDate(d.date))}</span>
            <span class="rail-due-t">${esc(d.title)}</span></li>`).join('')}</ul>`
        : '<p class="rail-none">None</p>'}
    </section>
  </nav>`
}

export function courseTag(course) {
  const meta = course.parse.course
  const term = meta.term ? meta.term[0].toUpperCase() + meta.term.slice(1) : ''
  return [term, meta.year].filter(Boolean).join(' ')
}

export function deadlinesView(courses, activeId, editing = false) {
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
    course.parse.deliverables.items.forEach((item, di) => {
      const when = item.due_date
        ? shortDate(item.due_date)
        : item.recurrence === 'see schedule'
          ? 'see schedule'
          : item.recurrence || ''
      // a date moved in class is the single most common correction, so in
      // edit mode the date is a real date field rather than text to retype
      const row = {
        sort: item.due_date || '9999-99-99',
        html: editing
          ? `<tr>
              <td class="when"><input type="date" data-due-date="${course.id}|${di}"
                value="${esc(item.due_date || '')}" aria-label="Due date"></td>
              <td><input type="text" data-due-title="${course.id}|${di}"
                value="${esc(item.title)}" aria-label="Item"></td>
              <td class="num"><input type="number" class="pct" min="0" max="100"
                data-due-weight="${course.id}|${di}"
                value="${item.weight_percent ?? ''}" aria-label="Weight"></td>
              <td class="num"><button type="button" class="rowdel"
                data-remove-due="${course.id}|${di}">Remove</button></td>
            </tr>`
          : `<tr>
              <td class="when">${esc(when)}
                ${whenLabel(item.due_date)
                  ? `<span class="relday">${esc(whenLabel(item.due_date))}</span>` : ''}</td>
              <td>${esc(item.title)}</td>
              <td class="num">${item.weight_percent ? `${item.weight_percent}%` : ''}</td>
            </tr>`,
      }
      row.days = daysUntil(item.due_date)
      // graded work is what the term is assessed on. presentation slots and
      // sign-ups are real dates but not deadlines, and mixing them buries the
      // few items that carry the grade. while editing, everything is listed
      // together, because a row cannot be corrected in a table it is hidden
      // from.
      if (editing || item.weight_percent) graded.push(row)
      else if (item.due_date) events.push(row)
    })
    graded.sort((a, b) => a.sort.localeCompare(b.sort))
    events.sort((a, b) => a.sort.localeCompare(b.sort))

    const table = (rows) => `<table>
        <thead><tr><th class="when">Due</th><th>Item</th><th class="num">Weight</th>
          ${editing ? '<th class="num"></th>' : ''}</tr></thead>
        <tbody>${rows.map((r) => r.html).join('')}</tbody>
      </table>`

    // sorted by date is not the same as sorted by what matters. a term list
    // opens on things that happened in February unless it is banded by how
    // close they are, and the band a student actually needs is "this week".
    const bands = [
      ['Overdue', (r) => r.days !== null && r.days < 0, 'band-late'],
      ['Next 7 days', (r) => r.days !== null && r.days >= 0 && r.days <= 7, 'band-soon'],
      ['Later', (r) => r.days !== null && r.days > 7, ''],
      ['No date found', (r) => r.days === null, ''],
    ]

    const banded = editing
      ? table(graded)
      : bands
          .map(([label, test, cls]) => {
            const rows = graded.filter(test)
            if (!rows.length) return ''
            return `<h4 class="band ${cls}">${label}
              <span class="bandcount">${rows.length}</span></h4>${table(rows)}`
          })
          .join('')

    const total = course.parse.deliverables.weight_total
    // a shared course code alone cannot tell two editions apart
    const tag = codeCounts.get(course.code) > 1 ? ` ${courseTag(course)}` : ''
    const off = total && Math.abs(total - 100) > 1

    return `<section class="course-deadlines">
      <h3>${esc(course.code)}${esc(tag)}
        ${total
          ? `<span class="${off ? 'flagged' : 'secondary'}">adds up to ${total}%</span>`
          : ''}</h3>
      ${graded.length ? banded : '<p class="secondary">Nothing weighted found.</p>'}
      ${events.length && !editing
        ? `<h4 class="band">On the schedule, not separately weighted</h4>${table(events)}`
        : ''}
      ${editing
        ? `<button type="button" class="addrow" data-add-due="${course.id}">
             Add something due</button>`
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

export function reviewTable(parse, showAll = false) {
  const flagged = new Set(parse.review.map((r) => r.source_text))
  let checkCount = 0
  let cleanCount = 0
  // one running count down the whole review, not one per week. most weeks
  // show a single row, so a number that restarts every heading says nothing,
  // where "14" out of 25 says how much is left.
  let seq = 0

  const blocks = []
  parse.sessions.forEach((session, index) => {
    if (!session.readings.length) return

    const rows = []
    session.readings.forEach((reading, ri) => {
      const low = flagged.has(reading.raw_source_text) || reading.confidence < 0.75
      if (low) checkCount += 1
      else cleanCount += 1
      // by default only the rows that need a decision are drawn. reviewing
      // fifty clean citations to find four doubtful ones is the work this
      // step is supposed to save.
      if (!low && !showAll) return
      // the flag is a rule down the side rather than the word "check" set
      // twenty five times. the colour already says it, and repeating it turns
      // the page into a column of the same word.
      seq += 1
      rows.push(`<li class="rrow${low ? ' needs-check' : ''}">
        <span class="rnum">${seq}</span>
        <div class="rbody">
          <input type="text" class="cite" aria-label="Citation"
            data-session="${index}" data-reading="${ri}"
            value="${esc(citation(reading.work))}">
          ${low ? `<p class="rsource">${esc(reading.raw_source_text)}</p>` : ''}
        </div>
      </li>`)
    })

    if (!rows.length) return
    const when = [
      session.week_number ? `Week ${session.week_number}` : '',
      shortDate(session.meeting_date),
      session.sub_session_label || '',
    ].filter(Boolean).join(' ')

    blocks.push(`<section class="week">
      <h3 class="whead">
        <span class="when">${esc(when || 'Unscheduled')}</span>
        <span class="wtopic">${esc(session.topic || '')}</span>
      </h3>
      <ol class="rlist">${rows.join('')}</ol>
    </section>`)
  })

  const sessions = parse.sessions.length
  const readings = checkCount + cleanCount
  const weights = parse.deliverables.weight_total

  // labelled figures rather than a sentence of them joined by middots, since
  // they are there to be compared against the syllabus. the words are the
  // ones on a syllabus: weeks and readings, not sessions and rows. "weeks
  // with no readings" is left out because it is usually a break, and a figure
  // in this strip reads as something gone wrong; it is said in full below
  // when it needs saying at all.
  const stats = [
    ['Weeks', sessions, false],
    ['Readings', readings, false],
    ['To check', checkCount, checkCount > 0],
    // this is the sum of the assignment weights, not a mark. "Your grade
    // 100%" read as a result rather than a check that the grading adds up.
    weights ? ['Graded work', `${weights}%`, Math.abs(weights - 100) > 1] : null,
  ].filter(Boolean)

  const strip = `<dl class="rstats">${stats.map(
    ([label, value, warn]) => `<div>
      <dt>${esc(label)}</dt>
      <dd${warn ? ' class="flagged"' : ''}>${esc(String(value))}</dd>
    </div>`).join('')}</dl>`

  // warnings a person can act on. "4 sessions with no readings" is a fact
  // about a term that has breaks in it, and is already in the figures above.
  const warnings = (parse.warnings || []).filter((w) => !/^\d+ session/.test(w))

  const lead = checkCount
    ? `<p class="rlead">These ${checkCount} didn't come out cleanly, so give them
        a look against your syllabus. <span class="quiet-note">The other
        ${cleanCount} look fine.</span>
        <button type="button" id="toggle-all" class="quiet">${
          showAll ? 'just show the doubtful ones' : 'show every reading'}</button></p>`
    : `<p class="rlead">Everything came out cleanly.
        <button type="button" id="toggle-all" class="quiet">${
          showAll ? 'hide' : 'show every reading'}</button></p>`

  return `${strip}
    ${lead}
    ${warnings.length
      ? `<ul class="rwarn">${warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`
      : ''}
    ${blocks.join('')}`
}


