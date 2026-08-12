// weighted course grades and a term gpa.
//
// the arithmetic lives here on its own, with no dom and no storage, because it
// is the part that has to be right. a syllabus already gives the weights, so
// the only thing a student has to type is what they scored.

// grade points are a property of the letter, not of where an instructor draws
// the line for it. an A- is 3.7 however it was earned, so this table is shared
// by every scale. there is no A+ or D+/D-, which is how uga counts it.
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
export function standing(items) {
  let totalWeight = 0
  let gradedWeight = 0
  let earned = 0
  for (const item of items || []) {
    const weight = Number(item.weight_percent)
    if (!Number.isFinite(weight) || weight <= 0) continue
    totalWeight += weight
    const mark = Number(item.mark_percent)
    if (item.mark_percent === null || item.mark_percent === undefined || !Number.isFinite(mark)) {
      continue
    }
    gradedWeight += weight
    earned += (weight * mark) / 100
  }
  const remaining = Math.max(0, totalWeight - gradedWeight)
  return {
    totalWeight: round(totalWeight, 2),
    gradedWeight: round(gradedWeight, 2),
    remaining: round(remaining, 2),
    earned: round(earned, 2),
    average: gradedWeight ? round((earned / gradedWeight) * 100) : null,
    banked: round(earned),
    ceiling: round(earned + remaining),
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
