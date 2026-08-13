// views. tables for anything tabular, labels rather than sentences, and colour
// only where it says something actionable.

import * as cite from './cite.js'
import * as grades from './grades.js'

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

// the link the parser already pulled off a reading. a doi is turned into a
// resolver url because a bare "10.1093/..." is not something a student can
// click. trailing punctuation is trimmed: extraction routinely leaves a bullet
// or a full stop welded to the end of a url, and following that 404s.
export function readingLink(work) {
  const doi = (work.doi || '').trim()
  if (doi) return { href: `https://doi.org/${encodeURI(doi.replace(/[.,;)\]•]+$/, ''))}`, label: 'doi' }
  const url = (work.url || '').trim().replace(/[.,;)\]•·]+$/, '')
  if (/^https?:\/\/\S+$/i.test(url)) return { href: url, label: 'link' }
  return null
}

function linkTag(work) {
  const link = readingLink(work)
  if (!link) return ''
  return ` <a class="golink" href="${esc(link.href)}" target="_blank"
    rel="noopener noreferrer">${esc(link.label)}</a>`
}

export function sortKey(work) {
  const first = (work.authors || [])[0]
  return ((first && (first.surname || first.literal)) || work.title || '').toLowerCase()
}

export function citation(work) {
  return cite.format(work, style)
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
    // the week and its date on separate lines. run together and wrapped by a
    // narrow column they read as one number: "Week" over "1 1/13".
    const when = [
      session.week_number ? `Week ${session.week_number}` : '',
      session.sub_session_label || '',
    ].filter(Boolean).join(' ')
    return `<tr>
      <td class="wk">${esc(when || (session.meeting_date ? '' : 'Unscheduled'))}
        ${session.meeting_date
          ? `<span class="wk-date">${esc(shortDate(session.meeting_date))}</span>` : ''}</td>
      <td>${esc(session.topic || '')}</td>
      <td>${readings}</td>
    </tr>`
  })

  return `<h2>${esc(course.code)} schedule</h2>
    <table class="schedule">
      <thead><tr><th class="wk">Week</th><th class="topic">Topic</th>
        <th>Readings</th></tr></thead>
      <tbody>${rows.join('')}</tbody>
    </table>`
}

export function weekView(course, progress, editing = false, filter = {}, documents = []) {
  // which readings have their pdf on file, keyed the way ingest matched them
  const onFile = new Map()
  for (const doc of documents) {
    if (doc.courseId === course.id && doc.workKey) onFile.set(doc.workKey, doc)
  }
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

    // a filter never changes what the course holds, only what is drawn, so the
    // totals below are counted before anything is hidden
    const weekSoon = days !== null && days >= -6 && days <= 30
    let count = 0
    let doneHere = 0
    const weekRows = []
    for (const { session, si } of entries) {
      session.readings.forEach((reading, ri) => {
        const id = readingKey(course, session, reading)
        const saved = progress.get(id) || {}
        count += 1
        heldTotal += 1
        const pages = pageCount(reading.page_range)
        pagesTotal += pages
        if (saved.read) { doneHere += 1; held += 1; pagesDone += pages }

        if (filter.unread && saved.read) return
        if (filter.required && reading.requirement_level !== 'required') return
        if (filter.soon && !weekSoon) return

        const cited = editing
          ? `<input type="text" class="cite" data-edit-reading="${si}.${ri}"
               value="${esc(citation(reading.work))}" aria-label="Entry">`
          : `${esc(cite.short(reading.work, 400))}${linkTag(reading.work)}${
              onFile.has(reading.work.signature)
                ? ` <button type="button" class="golink onfile"
                     data-open-doc="${esc(onFile.get(reading.work.signature).id)}"
                     >open pdf</button>`
                : ''}
             ${reading.content_warning
               ? `<span class="cwarn">Content warning \u00b7 ${esc(reading.content_warning)}</span>`
               : ''}
             <input type="text" class="note" data-note="${esc(id)}"
               value="${esc(saved.note || '')}" placeholder="Add a note"
               aria-label="Note">`

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
        weekRows.push(`<tr class="rec${saved.read ? ' struck' : ''}" data-row="${esc(id)}">
          <td class="c-tick">${editing
            ? `<button type="button" class="rowdel" data-remove-reading="${si}.${ri}"
                 aria-label="Remove this entry">\u00d7</button>`
            : `<input type="checkbox" data-progress="${esc(id)}"
                 ${saved.read ? 'checked' : ''} aria-label="Mark as read">`}</td>
          <td class="c-num">${String(entryNo).padStart(2, '0')}</td>
          <td class="c-date">${esc(ownDate)}</td>
          <td class="c-title">${cited}</td>
          <td class="c-src"><span>${esc(sourceOf(reading))}</span></td>
          <td class="c-pp">${esc(reading.page_range || '')}</td>
          <td class="c-stat${wanted ? ' is-due' : ''}">${
            saved.read ? 'Read' : wanted ? 'Due' : ''}</td>
        </tr>`)
      })
    }

    // with a filter on, a week that keeps nothing is dropped whole. leaving
    // the heading behind would fill the screen with empty weeks, which is the
    // thing the filter was turned on to get away from.
    const filtering = filter.unread || filter.required || filter.soon
    if (filtering && !weekRows.length) continue

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
            ${count
              ? `<span class="sep-count${doneHere === count ? ' is-done' : ''}">${
                  doneHere ? `${doneHere} of ${count} read` :
                  `${count} reading${count === 1 ? '' : 's'}`}</span>`
              : ''}</span>
          ${due.length
            ? `<span class="sep-sub">${due.map((d) => esc(d.title)).join('; ')} due</span>`
            : ''}
        </td>
        <td class="c-stat sep-c${flagged ? ' is-flag' : ''}">${flagged ? 'Due' : ''}</td>
      </tr>`

    rows.push(sep, ...weekRows)

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

  // a filter that matches nothing has to say so, and say how to get back. an
  // empty table reads as a course that lost its readings.
  if (!rows.length) {
    // two different emptinesses. a filter hiding everything is the visitor's
    // doing and has a way out; a syllabus with no schedule in it is the
    // parser's answer, and blaming a filter nobody turned on was nonsense.
    const filtering = filter.unread || filter.required || filter.soon
    const message = filtering
      ? 'Nothing matches what you asked for. Turn a filter off under Show to bring the ledger back.'
      : 'No weekly schedule came out of this PDF. Often it has none and the '
        + 'schedule lives on the course site instead. Anything you add by hand under Edit stays here.'
    rows.push(`<tr class="rec empty"><td class="c-tick"></td><td class="c-num"></td>
      <td class="c-date"></td>
      <td class="c-title" colspan="4"><em>${esc(message)}</em></td></tr>`)
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

  const shown = rows.filter((r) => r.startsWith('<tr class="rec') && !r.includes('empty')).length

  return {
    shown,
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

// one dash is not enough. a pdf carries whichever the typesetter used, and the
// page text keeps the original rather than the normalised one, so the display
// string arriving here can hold any of these.
const DASHES = '\\u002d\\u2010\\u2011\\u2012\\u2013\\u2014\\u2015\\u2212'
const DASH = new RegExp(`\\s*[${DASHES}]\\s*`)

const ROMAN = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 }

// roman only where the whole token is roman, so a reading numbered "c" or "l"
// is not silently read as 100 or 50 pages
function fromRoman(token) {
  const t = token.toLowerCase()
  if (!/^[ivxlcdm]+$/.test(t)) return null
  let total = 0
  for (let i = 0; i < t.length; i += 1) {
    const here = ROMAN[t[i]]
    const next = ROMAN[t[i + 1]] || 0
    total += here < next ? -here : here
  }
  return total > 0 ? total : null
}

// chicago and mla write the upper bound short: "231-45" means 231 to 245, and
// "1064-79" means 1064 to 1079. borrow the missing leading digits back off the
// lower bound, but only when doing so actually yields a range.
function upperBound(lo, hi) {
  const plain = Number(hi)
  if (hi.length >= lo.length) return plain
  const borrowed = Number(lo.slice(0, lo.length - hi.length) + hi)
  return borrowed > Number(lo) ? borrowed : plain
}

// one segment of a range: "12-25", "231-45", "xi-xxiv", "S1-S8", "7", "231ff."
function segmentPages(part) {
  const seg = part.trim().replace(/^(?:pp?\.|pages?)\s*/i, '').replace(/[.,;]+$/, '')
  if (!seg) return 0

  const halves = seg.split(DASH)
  if (halves.length === 2) {
    const [a, b] = halves.map((h) => h.trim())

    const romanLo = fromRoman(a)
    const romanHi = fromRoman(b)
    if (romanLo !== null && romanHi !== null) {
      return Math.max(0, romanHi - romanLo + 1)
    }

    // an optional matching label on each side, as supplements and appendices
    // number their pages "S1-S8" or "A4-A9"
    const lo = a.match(/^([A-Za-z]*)(\d+)$/)
    const hi = b.match(/^([A-Za-z]*)(\d+)$/)
    if (lo && hi && (!hi[1] || hi[1].toLowerCase() === lo[1].toLowerCase())) {
      const top = upperBound(lo[2], hi[2])
      return Math.max(0, top - Number(lo[2]) + 1)
    }
    return 0
  }

  // "231ff." says the reading starts here and runs on, with no end given. it is
  // at least a page, and guessing further would be inventing a number.
  if (/^[A-Za-z]*\d+\s*ff\.?$/i.test(seg)) return 1
  if (/^[A-Za-z]*\d+$/.test(seg)) return 1
  if (fromRoman(seg) !== null) return 1
  return 0
}

// a page range as a number of pages, for the holdings count. a range that
// cannot be read contributes nothing rather than a guess, so the meter
// undercounts rather than inventing pages nobody was set.
function pageCount(range) {
  if (!range) return 0
  // "1-5, 9-12" is two stretches of the same work, so it is worth both
  return String(range)
    .split(/[,;]/)
    .reduce((n, part) => n + segmentPages(part), 0)
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
    // the parser calls these instructor_name and meeting_time. reading the
    // wrong keys meant both facts came back undefined and the filter below
    // dropped them, so the record header has never once shown who teaches the
    // course or when it meets.
    ['Instructor', p.course?.instructor_name, false],
    ['Meets', p.course?.meeting_time, false],
    ['Room', p.course?.location, false],
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
export function railView(course, ledger, courses, filter = {}, progress = new Map()) {
  const { index, current, holdings } = ledger
  // the count column is dropped. it repeated what the ledger already shows and
  // took a third of the width the topic needed to be legible.
  const entries = index.map((w, i) => `<li class="${i === current ? 'is-current' : ''}">
      <a href="#w${i}" data-jump="${i}" title="${esc(w.topic)}">
        <span class="rail-n${w.flagged ? ' is-flag' : ''}">${esc(w.n)}</span>
        <span class="rail-t">${esc(w.topic || '—')}</span>
      </a></li>`).join('')

  // a bar reads at a glance where a fraction has to be worked out. it is ruled
  // and squared off like everything else, and the figure stays beside it: the
  // bar is the impression, the numbers are the record.
  const meter = (label, done, total) => {
    if (!total) {
      return `<div class="meter"><dt>${esc(label)}</dt><dd>—</dd></div>`
    }
    const pct = Math.round((done / total) * 100)
    return `<div class="meter">
      <dt>${esc(label)}</dt>
      <dd>${done} of ${total}</dd>
      <div class="bar" role="img" aria-label="${pct}% of ${label.toLowerCase()} done">
        <span style="width:${pct}%"></span>
      </div>
    </div>`
  }

  const toggles = [
    ['unread', 'Unread'],
    ['required', 'Required'],
    ['soon', 'Next 30 days'],
  ]
  const filtering = toggles.some(([key]) => filter[key])

  const upcoming = []
  for (const c of currentTermCourses(courses)) {
    c.parse.deliverables.items.forEach((d, index) => {
      const days = daysUntil(d.due_date)
      if (days === null || days < 0) return
      if ((progress.get(dueKey(c, d, index)) || {}).read) return
      upcoming.push({ days, title: d.title, code: c.code, date: d.due_date })
    })
  }
  upcoming.sort((a, b) => a.days - b.days)

  return `<nav class="rail" aria-label="Index">
    <details class="rail-sec rail-fold">
      <summary>Index</summary>
      <ol class="rail-index">${entries}</ol>
    </details>
    <section class="rail-sec">
      <h3>Show</h3>
      <div class="rail-filters">
        ${toggles.map(([key, label]) => `<button type="button" class="chip"
          data-filter="${key}" aria-pressed="${filter[key] ? 'true' : 'false'}">
          ${esc(label)}</button>`).join('')}
      </div>
      ${filtering
        ? `<p class="rail-none">${ledger.shown} of ${holdings.heldTotal} shown ·
            <button type="button" class="quiet" data-filter="clear">show all</button></p>`
        : ''}
    </section>
    <section class="rail-sec">
      <h3>Progress</h3>
      <dl class="rail-facts">
        ${meter('Read', holdings.held, holdings.heldTotal)}
        ${meter('Pages', holdings.pagesDone, holdings.pagesTotal)}
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
    <section class="rail-sec">
      <h3>Keys</h3>
      <dl class="rail-keys">
        <div><dt>J K</dt><dd>move</dd></div>
        <div><dt>Space</dt><dd>tick off</dd></div>
        <div><dt>N</dt><dd>note</dd></div>
        <div><dt>T</dt><dd>this week</dd></div>
        <div><dt>/</dt><dd>search</dd></div>
        <div><dt>1&ndash;7</dt><dd>switch view</dd></div>
      </dl>
    </section>
  </nav>`
}

export function courseTag(course) {
  const meta = course.parse.course
  const term = meta.term ? meta.term[0].toUpperCase() + meta.term.slice(1) : ''
  return [term, meta.year].filter(Boolean).join(' ')
}

// terms in the order they happen, so "which is the current one" is answerable
const TERM_ORDER = { spring: 0, summer: 1, fall: 2, autumn: 2, winter: 3 }

export function termKey(course) {
  const meta = course.parse.course || {}
  if (!meta.year) return ''
  return `${meta.year}-${TERM_ORDER[String(meta.term || '').toLowerCase()] ?? 9}`
}

/** the newest term any stored course belongs to, or '' if none say. */
export function latestTerm(courses) {
  const keys = (courses || []).map(termKey).filter(Boolean).sort()
  return keys.length ? keys[keys.length - 1] : ''
}

/** the courses of the current term, for the views that answer "right now".
 *
 * a student keeps last semester's syllabi in the browser, and every one of
 * them was still turning up in the deadline bands and, worse, in the term gpa,
 * which quietly averaged two terms together. a course that never said which
 * term it belongs to stays in: dropping it would be a guess.
 */
export function currentTermCourses(courses) {
  const newest = latestTerm(courses)
  if (!newest) return courses
  return courses.filter((c) => {
    const key = termKey(c)
    return !key || key === newest
  })
}

// a deliverable's tick, keyed so it survives a re-read of the syllabus. the
// title carries it rather than the row number, because a re-parse can shift
// the order and a handed-in essay must not become an outstanding one.
export function dueKey(course, item, index) {
  const stem = (item.title || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)
  return `${course.id}::due::${stem || index}`
}

// what the syllabus said the thing has to be. the parser has pulled the page
// limit, the word limit and the format sentence off every assignment since it
// was written, and none of it has ever reached the screen, so a student
// checking how long an essay may run went back to the pdf every time.
function spec(item) {
  const parts = []
  if (item.page_limit) parts.push(`${item.page_limit} pages max`)
  if (item.word_limit) parts.push(`${item.word_limit} words max`)
  const notes = (item.format_notes || '').replace(/\s+/g, ' ').trim()
  if (notes) parts.push(notes.length > 90 ? `${notes.slice(0, 90)}…` : notes)
  if (!parts.length) return ''
  return `<span class="due-spec">${esc(parts.join(' · '))}</span>`
}

export function deadlinesView(courses, activeId, editing = false, progress = new Map()) {
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
      const key = dueKey(course, item, di)
      const done = Boolean((progress.get(key) || {}).read)
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
          : `<tr class="${done ? 'struck' : ''}">
              <td class="c-tick"><input type="checkbox" data-progress="${esc(key)}"
                ${done ? 'checked' : ''} aria-label="Mark ${esc(item.title)} as handed in"></td>
              <td class="when">${esc(when)}
                ${!done && whenLabel(item.due_date)
                  ? `<span class="relday">${esc(whenLabel(item.due_date))}</span>` : ''}</td>
              <td>${esc(item.title)}${spec(item)}</td>
              <td class="num">${item.weight_percent ? `${item.weight_percent}%` : ''}</td>
            </tr>`,
      }
      row.days = daysUntil(item.due_date)
      row.done = done
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

    const table = (rows) => `<table class="marks">
        <thead><tr>${editing ? '' : '<th class="c-tick"></th>'}
          <th class="when">Due</th><th>Item</th><th class="num">Weight</th>
          ${editing ? '<th class="num"></th>' : ''}</tr></thead>
        <tbody>${rows.map((r) => r.html).join('')}</tbody>
      </table>`

    // sorted by date is not the same as sorted by what matters. a term list
    // opens on things that happened in February unless it is banded by how
    // close they are, and the band a student actually needs is "this week".
    //
    // handed in comes out of the dated bands entirely: an essay submitted last
    // week is not overdue, and leaving it in the red band meant the one band
    // that should mean "do something" filled up with work already done.
    const bands = [
      ['Overdue', (r) => !r.done && r.days !== null && r.days < 0, 'band-late'],
      ['Next 7 days', (r) => !r.done && r.days !== null && r.days >= 0 && r.days <= 7, 'band-soon'],
      ['Later', (r) => !r.done && r.days !== null && r.days > 7, ''],
      ['No date found', (r) => !r.done && r.days === null, ''],
      ['Handed in', (r) => r.done, 'band-done'],
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

  // dates the term turns on that are nobody's assignment: the drop deadline,
  // the exam period, reading week. the parser has always found these and the
  // interface has never shown one, so the day a student could still withdraw
  // was sitting in the payload and nowhere else.
  const notable = []
  for (const course of ordered) {
    for (const entry of course.parse.important_dates || []) {
      if (!entry.start) continue
      notable.push({ course, entry, days: daysUntil(entry.start) })
    }
  }
  notable.sort((a, b) => String(a.entry.start).localeCompare(String(b.entry.start)))

  const dates = notable.length
    ? `<section class="course-deadlines">
        <h3>Dates to know</h3>
        <table class="marks"><tbody>${notable.map(({ course, entry, days }) => `
          <tr class="${days !== null && days < 0 ? 'struck' : ''}">
            <td class="w-course">${esc(course.code)}</td>
            <td class="when">${esc(shortDate(entry.start))}
              ${entry.end && entry.end !== entry.start
                ? `&ndash; ${esc(shortDate(entry.end))}` : ''}
              <span class="relday">${esc(whenLabel(entry.start) || '')}</span></td>
            <td>${esc(entry.label || entry.raw || '')}</td>
          </tr>`).join('')}</tbody></table>
      </section>`
    : ''

  return `<h2>Deadlines</h2>${sections.join('')}${dates}`
}

// what a target grade asks of the work that is left. the three dead ends are
// spelled out, because "you need 112%" and "you need -4%" are both answers a
// student has to translate, and the translation is the useful part.
function targetLine(st, target, letter) {
  if (!st.remaining) {
    return `Everything is marked. Nothing left to change it.`
  }
  const needed = grades.neededFor(st, target)
  if (needed <= 0) {
    return `${letter} is already secured, whatever happens to the rest.`
  }
  if (needed > 100) {
    return `${letter} is out of reach now: it would take ${needed}% on the
      remaining ${st.remaining}%.`
  }
  return `To finish on ${letter} you need <strong>${needed}%</strong> average
    across the remaining ${st.remaining}% of the course.`
}

export function gradesView(allCourses, activeId) {
  // a term gpa across two terms is not a term gpa
  const courses = currentTermCourses(allCourses)
  const dropped = allCourses.length - courses.length
  if (!courses.length) return '<h2>Grades</h2><p class="secondary">No courses yet.</p>'

  const ordered = [...courses].sort((a, b) =>
    (a.id === activeId ? 0 : 1) - (b.id === activeId ? 0 : 1)
  )

  const sections = ordered.map((course) => {
    const items = course.parse.deliverables.items
    const st = grades.standing(items)
    const cutoffs = grades.resolveScale(course.grade_scale)
    const scaleKind = course.grade_scale && course.grade_scale.kind === 'custom'
      ? 'custom'
      : (grades.SCALES[course.grade_scale] ? course.grade_scale : 'plusminus')
    // the default target is the top letter of whichever scale is in force,
    // not a hardcoded 93: an A starts at 90 on a straight scale
    const target = Number(course.grade_target ?? cutoffs[0][1])
    const targetLetter = grades.letterFor(target, cutoffs)

    const graded = items
      .map((item, di) => ({ item, di }))
      .filter(({ item }) => item.weight_percent)
      .sort((a, b) =>
        (a.item.due_date || '9999-99-99').localeCompare(b.item.due_date || '9999-99-99')
      )

    // a course that dates none of its graded work does not need a due column
    // standing empty down the whole table
    const dated = graded.some(({ item }) => item.due_date)

    const rows = graded
      .map(({ item, di }) => `<tr>
        ${dated ? `<td class="when">${esc(shortDate(item.due_date))}</td>` : ''}
        <td>${esc(item.title)}${grades.isBonus(item)
          ? ' <span class="ontop">on top</span>' : ''}</td>
        <td class="num">${grades.isBonus(item) ? '+' : ''}${item.weight_percent}%</td>
        <td class="num"><input type="number" class="pct" min="0" step="0.1"
          data-mark="${course.id}|${di}" value="${item.mark_percent ?? ''}"
          placeholder="&mdash;" aria-label="Your mark on ${esc(item.title)}"></td>
      </tr>`)
      .join('')

    if (!rows) {
      return `<section class="course-grades">
        <h3>${esc(course.code)}</h3>
        <p class="secondary">No weighted work found for this course, so there is
          nothing to calculate. You can add the weights under Deadlines.</p>
      </section>`
    }

    const letter = grades.letterFor(st.average, cutoffs)
    // the average is a weighted average of the work handed back, so it holds
    // whatever the weights add up to. everything else here is a share of a
    // hundred, and against a total of 150 it reads as nonsense: "full marks on
    // the rest finishes you on 145%". those lines wait for a believable total.
    const off = st.totalWeight && Math.abs(st.totalWeight - 100) > 1

    // the figures go in a fact column beside the table rather than under it as
    // sentences. three numbers a student wants at a glance were costing three
    // lines of prose apiece and left the right half of the page empty.
    const summary = st.average === null
      ? `<p class="secondary">Type a mark beside anything that has come back and
          the total works itself out.</p>`
      : `<p class="standing"><span class="standing-figure">${st.average}%</span>
           <span class="standing-letter">${esc(letter)}</span></p>
         <dl class="sumfacts">
           <div><dt>Marked so far</dt><dd>${st.gradedWeight}%</dd></div>
           ${off ? '' : `<div><dt>Worst case</dt><dd>${st.banked}%</dd></div>
           <div><dt>Best case</dt><dd>${st.ceiling}%</dd></div>`}
           ${st.bonus ? `<div><dt>Extra credit</dt><dd>+${st.bonus}%</dd></div>` : ''}
         </dl>`

    const aiming = off
      ? `<p class="secondary">Fix the weights under Deadlines and this will work
          out what you need for a target grade.</p>`
      : `<p class="targetrow">
          <label for="target-${esc(course.id)}">Aiming for</label>
          <select id="target-${esc(course.id)}" data-target="${course.id}">
            ${cutoffs.filter(([, floor]) => floor > 0)
              .map(([name, floor]) =>
                `<option value="${floor}" ${floor === target ? 'selected' : ''}>${name}</option>`)
              .join('')}
          </select>
          <span class="targetsay">${st.average === null
            ? 'Type a mark or two and this fills in.'
            : targetLine(st, target, targetLetter)}</span>
        </p>`

    return `<section class="course-grades">
      <h3>${esc(course.code)}
        ${off
          ? `<span class="flagged">weights add up to ${st.totalWeight}%, so these
              figures are only as good as that</span>`
          : ''}</h3>
      <div class="gradebody">
        <div class="gradework">
          <table class="marks">
            <thead><tr>${dated ? '<th class="when">Due</th>' : ''}<th>Item</th>
              <th class="num">Weight</th><th class="num">Your mark</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
          <p class="targetrow">
            <label for="scale-${esc(course.id)}">Scale</label>
            <select id="scale-${esc(course.id)}" data-scale="${course.id}">
              ${Object.entries(grades.SCALES).map(([key, s]) =>
                `<option value="${key}" ${key === scaleKind ? 'selected' : ''}>${s.name}</option>`)
                .join('')}
              <option value="custom" ${scaleKind === 'custom' ? 'selected' : ''}>Custom cutoffs</option>
            </select>
            ${scaleKind === 'custom'
              ? `<span class="cuts">${Object.keys(grades.POINTS)
                  .filter((name) => name !== 'F')
                  .map((name) => {
                    const row = (course.grade_scale.cutoffs || []).find(([l]) => l === name)
                    return `<label class="cut">${name}<input type="number" min="0" max="120"
                      step="0.1" data-cut="${course.id}|${name}" value="${row ? row[1] : ''}"
                      aria-label="Lowest percent for ${name}"></label>`
                  }).join('')}
                <span class="cutnote">Lowest percent for each letter. Leave it blank
                  if your course doesn't give that letter.</span></span>`
              : `<span class="targetsay secondary">${cutoffs
                  .filter(([, floor]) => floor > 0)
                  .map(([name, floor]) => `${name} ${floor}`)
                  .join(' &middot; ')}</span>`}
          </p>
        </div>
        <aside class="gradesum">${summary}${aiming}</aside>
      </div>
    </section>`
  })

  const gpaRows = ordered.map((course) => {
    const st = grades.standing(course.parse.deliverables.items)
    const cutoffs = grades.resolveScale(course.grade_scale)
    const computed = grades.letterFor(st.average, cutoffs)
    const chosen = course.grade_letter ?? computed ?? ''
    return `<tr>
      <td>${esc(course.code)}</td>
      <td class="num"><input type="number" class="pct" min="0" max="12" step="0.5"
        data-credits="${course.id}" value="${course.credits ?? 3}"
        aria-label="Credit hours for ${esc(course.code)}"></td>
      <td class="num"><select data-letter="${course.id}"
        aria-label="Grade for ${esc(course.code)}">
        <option value="">&mdash;</option>
        ${cutoffs.map(([name]) =>
          `<option value="${name}" ${name === chosen ? 'selected' : ''}>${name}</option>`)
          .join('')}
      </select></td>
      <td class="secondary src">${computed && !course.grade_letter
        ? `from your marks` : course.grade_letter ? 'set by you' : ''}</td>
    </tr>`
  }).join('')

  const gpa = grades.termGpa(ordered.map((course) => {
    const st = grades.standing(course.parse.deliverables.items)
    return {
      credits: course.credits ?? 3,
      letter: course.grade_letter
        ?? grades.letterFor(st.average, grades.resolveScale(course.grade_scale)),
    }
  }))

  return `<h2>Grades</h2>
    ${sections.join('')}
    <section class="course-grades">
      <h3>Term GPA</h3>
      <div class="gradebody">
        <div class="gradework">
          <table class="marks">
            <thead><tr><th>Course</th><th class="num">Credits</th>
              <th class="num">Grade</th><th class="src"></th></tr></thead>
            <tbody>${gpaRows}</tbody>
          </table>
        </div>
        <aside class="gradesum">
          <p class="standing">
            ${gpa.gpa === null
              ? '<span class="secondary">Set a grade on at least one course.</span>'
              : `<span class="standing-figure">${gpa.gpa}</span>
                 <span class="standing-letter">GPA</span>`}
          </p>
          ${gpa.gpa === null ? '' : `<dl class="sumfacts">
            <div><dt>Courses</dt><dd>${gpa.counted}</dd></div>
            <div><dt>Credit hours</dt><dd>${gpa.credits}</dd></div>
          </dl>
          <p class="secondary">Four point scale, with no D plus or D minus. Set
            each course's scale above to match its syllabus.</p>
          ${dropped
            ? `<p class="secondary">${dropped} course${dropped === 1 ? '' : 's'} from
                an earlier term left out, so this is the term and not the
                degree.</p>`
            : ''}`}
        </aside>
      </div>
    </section>`
}


// every other view answers "what does this course want". a student carrying
// four of them is asking the other question: what is wanted of me this week,
// by anybody. the data was already here, gathered one course at a time.
export function thisWeekView(allCourses, progress) {
  // last term's syllabus has nothing to say about this week
  const courses = currentTermCourses(allCourses)
  if (!courses.length) return '<h2>This week</h2><p class="secondary">No courses yet.</p>'

  // a window that opens a couple of days back, because work set last Thursday
  // is still this week's work on Monday, and runs a week forward
  const inWindow = (days) => days !== null && days >= -3 && days <= 7

  const readings = []
  const due = []

  for (const course of courses) {
    for (const session of course.parse.sessions) {
      const days = daysUntil(session.meeting_date)
      if (!inWindow(days)) continue
      for (const reading of session.readings) {
        const id = readingKey(course, session, reading)
        const saved = progress.get(id) || {}
        readings.push({ course, session, reading, id, saved, days })
      }
    }
    course.parse.deliverables.items.forEach((item, index) => {
      const days = daysUntil(item.due_date)
      if (!inWindow(days)) return
      // something already handed in is not something to do this week
      if ((progress.get(dueKey(course, item, index)) || {}).read) return
      due.push({ course, item, days })
    })
  }

  readings.sort((a, b) => a.days - b.days || a.course.code.localeCompare(b.course.code))
  due.sort((a, b) => a.days - b.days)

  if (!readings.length && !due.length) {
    // nothing this week is a real answer, and a dated course can say so with
    // confidence. an undated one cannot, and must not pretend to.
    const dated = courses.some((c) => c.parse.sessions.some((s) => s.meeting_date))
    return `<h2>This week</h2>
      <p class="secondary">${dated
        ? 'Nothing falls in the next seven days across your courses.'
        : 'None of your courses came out with dates on them, so there is no '
          + 'way to say what lands this week. The Week view has everything in order.'}</p>`
  }

  const rows = readings.map(({ course, session, reading, id, saved, days }) => `
    <tr class="rec${saved.read ? ' struck' : ''}" data-row="${esc(id)}">
      <td class="c-tick"><input type="checkbox" data-progress="${esc(id)}"
        ${saved.read ? 'checked' : ''} aria-label="Mark as read"></td>
      <td class="w-course">${esc(course.code)}</td>
      <td class="c-date">${esc(shortDate(session.meeting_date))}</td>
      <td class="c-title">${esc(cite.short(reading.work, 400))}
        ${reading.content_warning
          ? `<span class="cwarn">Content warning · ${esc(reading.content_warning)}</span>`
          : ''}</td>
      <td class="c-pp">${esc(reading.page_range || '')}</td>
      <td class="c-stat${days <= 1 ? ' is-due' : ''}">${esc(whenLabel(session.meeting_date) || '')}</td>
    </tr>`).join('')

  const held = readings.filter((r) => r.saved.read).length
  const pages = readings.reduce((n, r) => n + pageCount(r.reading.page_range), 0)

  return `<h2>This week</h2>
    <dl class="weekfacts">
      <div><dt>Readings</dt><dd>${held} of ${readings.length} read</dd></div>
      ${pages ? `<div><dt>Pages</dt><dd>${pages}</dd></div>` : ''}
      <div><dt>Due</dt><dd>${due.length}</dd></div>
      <div><dt>Courses</dt><dd>${new Set(readings.concat(due).map((r) => r.course.code)).size}</dd></div>
    </dl>

    ${due.length ? `<h3 class="band${due.some((d) => d.days <= 2) ? ' band-soon' : ''}">Due</h3>
      <table class="marks"><tbody>${due.map(({ course, item, days }) => `
        <tr>
          <td class="w-course">${esc(course.code)}</td>
          <td class="when">${esc(shortDate(item.due_date))}
            <span class="relday">${esc(whenLabel(item.due_date) || '')}</span></td>
          <td>${esc(item.title)}</td>
          <td class="num">${item.weight_percent ? `${item.weight_percent}%` : ''}</td>
        </tr>`).join('')}</tbody></table>` : ''}

    ${readings.length ? `<h3 class="band">To read</h3>
      <table class="ledger">
        <thead><tr>
          <th class="c-tick"></th><th class="w-course">Course</th><th class="c-date">Date</th>
          <th class="c-title">Author / Title</th><th class="c-pp">Pages</th><th class="c-stat">When</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>` : ''}`
}

// the policy kinds a student actually goes looking for, in the order they go
// looking. boilerplate is the university's standard block, which is the same
// on every syllabus and helps nobody, so it stays folded away.
const POLICY_LABELS = {
  late_work: 'Late work',
  attendance: 'Attendance',
  academic_honesty: 'Academic honesty',
  ai_use: 'AI',
  accommodations: 'Accommodations',
  other: 'Also stated',
}

const POLICY_ORDER = ['late_work', 'attendance', 'ai_use', 'academic_honesty',
                      'accommodations', 'other']

export function policiesView(course) {
  const all = course.parse.policies || []
  const shown = all.filter((p) => p.policy_type !== 'boilerplate' && (p.body || '').trim())

  if (!shown.length) {
    return `<h2>${esc(course.code)} policies</h2>
      <p class="secondary">Nothing came out of this syllabus that reads as a
        policy. They are usually under a heading like "Course policies", so if
        yours has one this is a gap worth telling me about.</p>`
  }

  const byKind = new Map()
  for (const policy of shown) {
    const kind = POLICY_ORDER.includes(policy.policy_type) ? policy.policy_type : 'other'
    if (!byKind.has(kind)) byKind.set(kind, [])
    byKind.get(kind).push(policy)
  }

  const sections = POLICY_ORDER.filter((k) => byKind.has(k)).map((kind) => {
    const entries = byKind.get(kind).map((policy) => {
      const body = collapse(policy.body)
      // long policies open on demand: the answer is usually the first line,
      // and four screens of quoted regulation buries it
      const long = body.length > 320
      return long
        ? `<details class="policy">
             <summary>${esc(body.slice(0, 300))}&hellip;</summary>
             <p>${esc(body)}</p>
           </details>`
        : `<p class="policy-body">${esc(body)}</p>`
    }).join('')
    return `<section class="policy-block">
      <h3>${esc(POLICY_LABELS[kind] || kind)}</h3>
      ${entries}
    </section>`
  }).join('')

  // only real boilerplate counts as left out. the parser writes an empty
  // "ai use unstated" record when a syllabus says nothing about it, and
  // counting that as a suppressed block told the reader something was being
  // held back when nothing was.
  const hidden = all.filter(
    (p) => p.policy_type === 'boilerplate' && (p.body || '').trim()).length
  return `<h2>${esc(course.code)} policies</h2>
    <p class="secondary">Taken from the syllabus as written, not summarised.
      Check the PDF before relying on any of it.</p>
    ${sections}
    ${hidden
      ? `<p class="secondary">${hidden} standard university
         ${hidden === 1 ? 'block' : 'blocks'} left out.</p>`
      : ''}`
}

function collapse(text) {
  return String(text || '').replace(/\s+/g, ' ').trim()
}

export function bibliographyView(course) {
  const seen = new Map()
  for (const session of course.parse.sessions) {
    for (const reading of session.readings) {
      const key = reading.work.signature || reading.work.raw_source_text
      if (!seen.has(key)) seen.set(key, reading.work)
    }
  }
  const works = [...seen.values()]
    .map((work) => ({ work, sort: sortKey(work) }))
    .sort((a, b) => a.sort.localeCompare(b.sort))
    .map(({ work }) => work)

  // a bibliography you cannot get out of the page is a bibliography you type
  // again by hand into whatever you are writing in
  const entries = works.map((work) => {
    const text = citation(work)
    return `<li class="entry">
      <span class="cite-text">${esc(text)}</span>
      <button type="button" class="copyone" data-copy="${esc(text)}"
        aria-label="Copy this citation">copy</button>
    </li>`
  })

  const required = course.parse.course.citation_style
  const all = works.map((w) => citation(w)).join('\n')
  return `<h2>${esc(course.code)} bibliography</h2>
    ${required
      ? `<p class="secondary">This course requires ${esc(required.toUpperCase())}.</p>`
      : ''}
    <p class="bibtools">
      <button type="button" id="copy-all" data-copy="${esc(all)}">Copy all
        ${works.length}</button>
      <span class="secondary">In ${esc(cite.STYLE_NAMES[style] || style)}. Change
        it with Style, above.</span>
    </p>
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


