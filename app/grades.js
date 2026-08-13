// weighted course grades and a term gpa.
//
// the arithmetic lives here on its own, with no dom and no storage, because it
// is the part that has to be right. a syllabus already gives the weights, so
// the only thing a student has to type is what they scored.

// grade points are a property of the letter, not of where an instructor draws
// the line for it. an A- is 3.7 however it was earned, so this table is shared
// by every scale. there is no A+, and no D+ or D-.
export const POINTS = {
  A: 4.0, 'A-': 3.7,
  'B+': 3.3, B: 3.0, 'B-': 2.7,
  'C+': 2.3, C: 2.0, 'C-': 1.7,
  D: 1.0, F: 0.0,
}

const ORDER = Object.keys(POINTS)

// where the lines sit is the instructor's choice, and syllabi split roughly
// into these two families. anything else is entered as custom cutoffs.
export const SCALES = {
  plusminus: {
    name: 'Plus and minus',
    cutoffs: [
      ['A', 93], ['A-', 90],
      ['B+', 87], ['B', 83], ['B-', 80],
      ['C+', 77], ['C', 73], ['C-', 70],
      ['D', 60], ['F', 0],
    ],
  },
  straight: {
    name: 'Straight letters',
    cutoffs: [['A', 90], ['B', 80], ['C', 70], ['D', 60], ['F', 0]],
  },
}

/** the cutoff table a course actually uses.
 *
 * accepts the stored form: a preset name, a custom object, or nothing. a
 * custom scale keeps only real letters with a usable floor, sorts them, and
 * always ends in F at zero, so a half-typed table still resolves to something
 * that behaves like a scale rather than throwing.
 */
export function resolveScale(spec) {
  if (spec && spec.kind === 'custom') {
    const rows = (spec.cutoffs || [])
      .filter(([letter, floor]) =>
        POINTS[letter] !== undefined && Number.isFinite(Number(floor)) && Number(floor) > 0)
      .map(([letter, floor]) => [letter, Number(floor)])
    rows.sort((a, b) => (b[1] - a[1]) || (ORDER.indexOf(a[0]) - ORDER.indexOf(b[0])))
    rows.push(['F', 0])
    if (rows.length > 1) return rows
  }
  return (SCALES[spec] || SCALES.plusminus).cutoffs
}

export function letterFor(percent, cutoffs = SCALES.plusminus.cutoffs) {
  if (percent === null || percent === undefined || Number.isNaN(percent)) return null
  for (const [letter, floor] of cutoffs) {
    if (percent >= floor) return letter
  }
  return 'F'
}

export function pointsFor(letter) {
  const value = POINTS[letter]
  return value === undefined ? null : value
}

const round = (n, places = 1) => {
  const factor = 10 ** places
  return Math.round(n * factor) / factor
}

/** what the marks entered so far add up to.
 *
 * `average` is the only figure that is true early in a term: it is the score on
 * the work handed back, and says nothing about the work still to come.
 * `banked` and `ceiling` are the floor and the roof of the final mark, and they
 * only close on each other as the term is graded.
 */
// extra credit sits on top of the hundred rather than inside it. counted as
// part of the total it made a course whose weights were exactly right read as
// 103, which suppressed every figure that assumes a hundred. the parser leaves
// it out of its total for the same reason, and these two have to agree.
export const isBonus = (item) => /\b(?:extra\s+credit|bonus)\b/i.test(item.title || '')

export function standing(items) {
  let totalWeight = 0
  let gradedWeight = 0
  let earned = 0
  let bonus = 0
  let bonusEarned = 0
  for (const item of items || []) {
    const weight = Number(item.weight_percent)
    if (!Number.isFinite(weight) || weight <= 0) continue
    const mark = Number(item.mark_percent)
    const marked = !(item.mark_percent === null || item.mark_percent === undefined
      || !Number.isFinite(mark))

    if (isBonus(item)) {
      bonus += weight
      if (marked) bonusEarned += (weight * mark) / 100
      continue
    }

    totalWeight += weight
    if (!marked) continue
    gradedWeight += weight
    earned += (weight * mark) / 100
  }
  const remaining = Math.max(0, totalWeight - gradedWeight)
  return {
    totalWeight: round(totalWeight, 2),
    gradedWeight: round(gradedWeight, 2),
    remaining: round(remaining, 2),
    earned: round(earned, 2),
    // the average is of the graded work proper; bonus marks are not an
    // average of anything, they are points added at the end
    average: gradedWeight ? round((earned / gradedWeight) * 100) : null,
    bonus: round(bonus, 2),
    banked: round(earned + bonusEarned),
    ceiling: round(earned + remaining + bonus),
  }
}

/** the score needed, on average, across everything not yet marked.
 *
 * returns null when there is nothing left to count. the caller is expected to
 * say plainly when the answer is above 100 or at or below zero, since both are
 * more useful to a student than a number.
 */
export function neededFor(st, target) {
  if (!st || !st.remaining) return null
  return round(((target - st.earned) / st.remaining) * 100)
}

// ---- calendar --------------------------------------------------------------

// a deadline with no date cannot be put in a calendar, and guessing one is
// worse than leaving it out, so only dated items travel. everything is built
// here as plain text: no network, nothing leaves the machine until the visitor
// saves the file themselves.

const icsEscape = (text) => String(text ?? '')
  .replace(/\\/g, '\\\\')
  .replace(/;/g, '\\;')
  .replace(/,/g, '\\,')
  .replace(/\r?\n/g, '\\n')

// rfc 5545 wants lines folded at 75 octets, continued by a leading space
function fold(line) {
  if (line.length <= 73) return line
  const parts = [line.slice(0, 73)]
  let rest = line.slice(73)
  while (rest.length > 72) {
    parts.push(' ' + rest.slice(0, 72))
    rest = rest.slice(72)
  }
  if (rest) parts.push(' ' + rest)
  return parts.join('\r\n')
}

const plainDate = (iso) => String(iso).slice(0, 10).replace(/-/g, '')

function nextDay(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number)
  const at = new Date(Date.UTC(y, m - 1, d + 1))
  return `${at.getUTCFullYear()}${String(at.getUTCMonth() + 1).padStart(2, '0')}${String(at.getUTCDate()).padStart(2, '0')}`
}

/** which deadlines across these courses can honestly be put in a calendar.
 *
 * the dates a term turns on go in as well, because a drop deadline is exactly
 * the kind of thing a student wants their phone to remind them of, and it was
 * being parsed and then dropped on the floor.
 */
export function datedDeadlines(courses) {
  const out = []
  const dated = (value) => value && /^\d{4}-\d{2}-\d{2}/.test(value)
  for (const course of courses || []) {
    for (const item of course.parse?.deliverables?.items || []) {
      if (!dated(item.due_date)) continue
      out.push({ code: course.code, title: item.title, date: item.due_date,
                 weight: item.weight_percent ?? null })
    }
    for (const entry of course.parse?.important_dates || []) {
      if (!dated(entry.start)) continue
      const label = (entry.label || entry.raw || '').replace(/\s+/g, ' ').trim()
      if (!label) continue
      out.push({ code: course.code, title: label, date: entry.start, weight: null })
    }
  }
  return out.sort((a, b) => a.date.localeCompare(b.date))
}

/** an all day event per deadline. `stamp` is passed in so this stays pure. */
export function toIcs(rows, stamp) {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//schedule reader//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ]
  rows.forEach((row, i) => {
    const summary = `${row.code}: ${row.title}`
    lines.push(
      'BEGIN:VEVENT',
      fold(`UID:${plainDate(row.date)}-${i}-schedule-reader`),
      `DTSTAMP:${stamp}`,
      // an all day event is a date with no time, and DTEND is exclusive
      `DTSTART;VALUE=DATE:${plainDate(row.date)}`,
      `DTEND;VALUE=DATE:${nextDay(row.date)}`,
      fold(`SUMMARY:${icsEscape(summary)}`),
      fold(`DESCRIPTION:${icsEscape(
        row.weight ? `Worth ${row.weight}% of the course grade.` : 'From your syllabus.')}`),
      'TRANSP:TRANSPARENT',
      'END:VEVENT'
    )
  })
  lines.push('END:VCALENDAR')
  return lines.join('\r\n') + '\r\n'
}

/** credit weighted term gpa over the courses that have a letter. */
export function termGpa(rows) {
  let points = 0
  let credits = 0
  let counted = 0
  for (const row of rows || []) {
    const hours = Number(row.credits)
    const value = pointsFor(row.letter)
    if (!Number.isFinite(hours) || hours <= 0 || value === null) continue
    points += value * hours
    credits += hours
    counted += 1
  }
  return {
    gpa: credits ? round(points / credits, 2) : null,
    credits: round(credits, 1),
    counted,
  }
}
