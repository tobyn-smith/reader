// citation styles.
//
// only the parts a reading list actually needs: author, year, title, container,
// volume, issue, pages. anything the parser did not find is left out rather
// than filled with a guess, so a thin citation reads as thin.

const STYLES = ['chicago', 'apa', 'mla', 'apsr', 'harvard']

export const STYLE_NAMES = {
  chicago: 'Chicago (author-date)',
  apa: 'APA',
  mla: 'MLA',
  apsr: 'APSR',
  harvard: 'Harvard',
}

export function styles() {
  return STYLES
}

function surnameFirst(a) {
  if (a.literal) return a.literal
  return [a.surname, a.given].filter(Boolean).join(', ')
}

function givenFirst(a) {
  if (a.literal) return a.literal
  return [a.given, a.surname].filter(Boolean).join(' ').trim()
}

function initials(given) {
  if (!given) return ''
  return given
    .split(/\s+/)
    .map((part) => (part.endsWith('.') ? part : `${part[0]}.`))
    .join(' ')
}

function surnameInitials(a) {
  if (a.literal) return a.literal
  return [a.surname, initials(a.given)].filter(Boolean).join(', ')
}

function names(authors, style) {
  const list = (authors || []).filter((a) => a.literal !== 'et al.')
  const truncated = (authors || []).some((a) => a.literal === 'et al.')
  if (!list.length) return ''

  const format = style === 'apa' || style === 'harvard' ? surnameInitials : surnameFirst
  const rest = style === 'mla' || style === 'chicago' || style === 'apsr' ? givenFirst : format

  let out
  if (list.length === 1) out = format(list[0])
  else if (list.length === 2) out = `${format(list[0])}, and ${rest(list[1])}`
  else out = `${format(list[0])}, ${list.slice(1, -1).map(rest).join(', ')}, and ${rest(list[list.length - 1])}`

  return truncated ? `${format(list[0])} et al.` : out
}

function yearOf(work) {
  if (!work.year) return ''
  if (work.year_is_open) return `${work.year}-`
  if (work.year_end) return `${work.year}-${work.year_end}`
  return String(work.year)
}

function volumeIssuePages(work, style) {
  let out = ''
  if (work.volume) {
    out += work.volume
    if (work.issue) out += style === 'apa' ? `(${work.issue})` : `(${work.issue})`
  }
  if (work.pages) out += out ? `: ${work.pages}` : work.pages
  return out
}

function join(parts) {
  let out = ''
  for (const part of parts) {
    if (!part) continue
    if (out) out += /[.?!]["'”’]?$/.test(out) ? ' ' : '. '
    out += part
  }
  if (!out) return ''
  return /[.?!]["'”’)]?$/.test(out) ? out : `${out}.`
}

export function format(work, style = 'chicago') {
  if (work.rendered_override) return work.rendered_override

  const author = names(work.authors, style)
  const year = yearOf(work)
  const title = work.title ? `"${work.title}."` : ''
  const container = work.container || ''
  const detail = volumeIssuePages(work, style)

  let parts
  if (style === 'apa') {
    parts = [author, year ? `(${year})` : '', work.title ? `${work.title}.` : '', container, detail]
  } else if (style === 'mla') {
    parts = [author, title, container, detail, year]
  } else if (style === 'harvard') {
    parts = [author, year ? `(${year})` : '', title, container, detail]
  } else {
    // chicago author-date and apsr share this shape closely enough
    parts = [author, year, title, container, detail]
  }

  if (work.report_number) parts.push(work.report_number)
  if (!work.container && work.publisher) parts.push(work.publisher)

  const rendered = join(parts.filter(Boolean))
  return rendered || work.raw_source_text || ''
}

// how the same work reads in a checklist, where the full citation is too long.
// a work the parser could not read has no author or title to show, so its raw
// line stands in, clipped so one bad row does not make the whole list ragged.
export function short(work, limit = 96) {
  // a line someone typed or corrected by hand wins everywhere it is shown,
  // not only in the full citation. otherwise a fix made in the week view
  // appears to have been thrown away.
  if (work.rendered_override) {
    const fixed = work.rendered_override
    return fixed.length > limit ? `${fixed.slice(0, limit - 1).trimEnd()}...` : fixed
  }
  const authors = work.authors || []
  const first = authors.length ? authors[0].surname || authors[0].literal : ''
  const year = work.year ? ` ${work.year}` : ''
  const title = work.title || work.container || work.raw_source_text || ''
  const head = [first, year].filter(Boolean).join('')
  const out = head ? `${head}, ${title}` : title
  return out.length > limit ? `${out.slice(0, limit - 1).trimEnd()}...` : out
}
