// pdf.js runs here rather than on the main thread, because a twelve page
// syllabus is enough to freeze a tab and a frozen tab reads as a broken site.
//
// the output is the runs contract in text/runs.py: pages of positioned text
// runs with y growing downward.

import * as pdfjs from './vendor/pdf.mjs'

pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdf.worker.mjs', import.meta.url).href

// a page with less text than this is an image and needs ocr
const MIN_CHARS = 40

// operator codes from pdf.js 4.6.82, fixed by the OPS table in pdf.mjs. the
// numbers matter more than the names: getOperatorList hands back integers.
const OP = {
  save: 10, restore: 11, transform: 12,
  moveTo: 13, lineTo: 14, curveTo: 15, curveTo2: 16, curveTo3: 17,
  closePath: 18, rectangle: 19,
  stroke: 20, closeStroke: 21, fill: 22, eoFill: 23,
  fillStroke: 24, eoFillStroke: 25, closeFillStroke: 26, closeEOFillStroke: 27,
  endPath: 28,
  // a form xobject's content is inlined into this same list between these two
  // ops, and the renderer treats them as an implicit save + transform by the
  // form's matrix, then restore. tracking only op 12 misses that matrix, so a
  // table drawn inside a form lands somewhere the text is not; worse, a bare
  // transform inside the form escapes and shifts the rest of the page.
  paintFormXObjectBegin: 74, paintFormXObjectEnd: 75,
  beginGroup: 76, endGroup: 77,
  beginAnnotation: 80, endAnnotation: 81,
  constructPath: 91,
}

const CLOSING_PAINT_OPS = new Set([
  OP.closeStroke, OP.closeFillStroke, OP.closeEOFillStroke,
])

const PAINT_OPS = new Set([
  OP.stroke, OP.closeStroke, OP.fill, OP.eoFill,
  OP.fillStroke, OP.eoFillStroke, OP.closeFillStroke, OP.closeEOFillStroke,
])

const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]

const multiply = (m, n) => [
  m[0] * n[0] + m[2] * n[1],
  m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3],
  m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4],
  m[1] * n[4] + m[3] * n[5] + m[5],
]

// the ruled lines a table is drawn with, from the page's operator list. the
// command line reads these through pdfplumber and finds grading tables the
// text positions alone cannot recover; without them the browser was the less
// accurate half of the same parser. only axis-aligned segments survive, since
// a rule in a document is horizontal or vertical and everything else is
// artwork. any failure returns what was gathered so far: geometry is an aid,
// never a reason extraction fails.
function collectRules(opList, pageHeight) {
  const rules = []
  let ctm = [1, 0, 0, 1, 0, 0]
  const stack = []
  let pending = []
  // where the current subpath started, and the point it reached. a closing
  // paint operator (h S and friends) is emitted on its own rather than folded
  // into the path, so the segment back to the start has to be added here.
  let openSubpath = null
  let cursor = null

  const segment = (x0, y0, x1, y1) => {
    const [ax, ay] = apply(ctm, x0, y0)
    const [bx, by] = apply(ctm, x1, y1)
    pending.push([ax, pageHeight - ay, bx, pageHeight - by])
  }

  const matrixArg = (value) =>
    value && value.length >= 6 && Number.isFinite(value[0]) ? value : null

  const { fnArray, argsArray } = opList
  for (let i = 0; i < fnArray.length; i += 1) {
    const fn = fnArray[i]
    if (fn === OP.save || fn === OP.beginGroup) {
      stack.push(ctm)
    } else if (fn === OP.restore || fn === OP.endGroup || fn === OP.endAnnotation) {
      if (stack.length) ctm = stack.pop()
    } else if (fn === OP.paintFormXObjectBegin || fn === OP.beginAnnotation) {
      // save first, so whatever the form does to the matrix is undone at its
      // end, then fold in every matrix the op carries
      stack.push(ctm)
      for (const arg of argsArray[i] || []) {
        const m = matrixArg(arg)
        if (m) ctm = multiply(ctm, m)
      }
    } else if (fn === OP.paintFormXObjectEnd) {
      if (stack.length) ctm = stack.pop()
    } else if (fn === OP.transform) {
      const a = argsArray[i]
      if (a && a.length >= 6) ctm = multiply(ctm, a)
    } else if (fn === OP.constructPath) {
      const packed = argsArray[i]
      if (!packed || packed.length < 2) continue
      const [ops, args] = packed
      let k = 0
      let cx = 0
      let cy = 0
      let sx = 0
      let sy = 0
      openSubpath = null
      for (const op of ops) {
        if (op === OP.moveTo) {
          cx = args[k]; cy = args[k + 1]; sx = cx; sy = cy; k += 2
          openSubpath = [cx, cy]
        } else if (op === OP.lineTo) {
          segment(cx, cy, args[k], args[k + 1])
          cx = args[k]; cy = args[k + 1]; k += 2
        } else if (op === OP.rectangle) {
          const [x, y, w, h] = [args[k], args[k + 1], args[k + 2], args[k + 3]]
          segment(x, y, x + w, y)
          segment(x, y + h, x + w, y + h)
          segment(x, y, x, y + h)
          segment(x + w, y, x + w, y + h)
          cx = x; cy = y; sx = x; sy = y; k += 4
        } else if (op === OP.closePath) {
          segment(cx, cy, sx, sy)
          cx = sx; cy = sy
        } else if (op === OP.curveTo) {
          cx = args[k + 4]; cy = args[k + 5]; k += 6
        } else if (op === OP.curveTo2 || op === OP.curveTo3) {
          cx = args[k + 2]; cy = args[k + 3]; k += 4
        } else {
          break
        }
      }
      cursor = [cx, cy]
    } else if (PAINT_OPS.has(fn)) {
      if (CLOSING_PAINT_OPS.has(fn) && openSubpath && cursor) {
        segment(cursor[0], cursor[1], openSubpath[0], openSubpath[1])
      }
      openSubpath = null
      for (const [x0, y0, x1, y1] of pending) {
        const dx = Math.abs(x1 - x0)
        const dy = Math.abs(y1 - y0)
        // a rule is straight and long enough to mean something. the short
        // strokes of glyphs drawn as paths and the ticks of chart axes fail
        // one of these and stay out.
        if ((dx <= 0.7 || dy <= 0.7) && Math.max(dx, dy) >= 6) {
          rules.push({
            x0: Math.round(Math.min(x0, x1) * 100) / 100,
            y0: Math.round(Math.min(y0, y1) * 100) / 100,
            x1: Math.round(Math.max(x0, x1) * 100) / 100,
            y1: Math.round(Math.max(y0, y1) * 100) / 100,
          })
        }
        if (rules.length >= 4000) return rules
      }
      pending = []
    } else if (fn === OP.endPath) {
      pending = []
    }
  }
  return rules
}

async function sha256(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

async function extract(id, name, buffer) {
  const hash = await sha256(buffer.slice(0))
  const doc = await pdfjs.getDocument({ data: buffer, isEvalSupported: false }).promise

  const pages = []
  const needOcr = []

  for (let number = 1; number <= doc.numPages; number += 1) {
    if (cancelled.has(id)) {
      await doc.destroy()
      return null
    }
    const page = await doc.getPage(number)
    const viewport = page.getViewport({ scale: 1 })
    const content = await page.getTextContent()

    let rules = []
    try {
      rules = collectRules(await page.getOperatorList(), viewport.height)
    } catch {
      // a page whose operator list will not decode still has its text
    }

    const runs = []
    let chars = 0
    for (const item of content.items) {
      if (!item.str) continue
      const t = item.transform
      const size = Math.hypot(t[2], t[3]) || item.height || 0
      const height = item.height || size
      runs.push({
        text: item.str,
        x: t[4],
        // pdf space measures y from the bottom; layout analysis wants it from
        // the top, the same way a reader sees the page
        y: viewport.height - t[5] - height,
        w: item.width,
        h: height,
        size,
      })
      chars += item.str.trim().length
    }

    if (chars < MIN_CHARS) needOcr.push(number)

    pages.push({
      number,
      width: viewport.width,
      height: viewport.height,
      runs,
      rules,
    })

    page.cleanup()
    self.postMessage({ type: 'progress', id, page: number, total: doc.numPages })
  }

  await doc.destroy()
  return { pages, filename: name, sha256: hash, needOcr }
}

const cancelled = new Set()

self.onmessage = async (event) => {
  const { type, id, name, buffer } = event.data

  if (type === 'cancel') {
    cancelled.add(id)
    return
  }

  if (type !== 'extract') return

  try {
    const result = await extract(id, name, buffer)
    if (result === null) {
      self.postMessage({ type: 'cancelled', id })
    } else {
      self.postMessage({ type: 'extracted', id, payload: result })
    }
  } catch (error) {
    self.postMessage({ type: 'error', id, message: String(error && error.message || error) })
  } finally {
    cancelled.delete(id)
  }
}
