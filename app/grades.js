// weighted course grades and a term gpa.
//
// the arithmetic lives here on its own, with no dom and no storage, because it
// is the part that has to be right. a syllabus already gives the weights, so
// the only thing a student has to type is what they scored.

// the scale most uga courses print. an instructor is free to set their own, and
// plenty do, so the percentage is what the app leads with and the letter is
// offered beside it rather than instead of it. there is no D+ or D-.
export const SCALE = [
  ['A', 93, 4.0],
  ['A-', 90, 3.7],
  ['B+', 87, 3.3],
  ['B', 83, 3.0],
  ['B-', 80, 2.7],
  ['C+', 77, 2.3],
  ['C', 73, 2.0],
  ['C-', 70, 1.7],
  ['D', 60, 1.0],
  ['F', 0, 0.0],
]

export const LETTERS = SCALE.map(([letter]) => letter)

export function letterFor(percent) {
  if (percent === null || percent === undefined || Number.isNaN(percent)) return null
  for (const [letter, floor] of SCALE) {
    if (percent >= floor) return letter
  }
  return 'F'
}

export function pointsFor(letter) {
  const row = SCALE.find(([name]) => name === letter)
  return row ? row[2] : null
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
