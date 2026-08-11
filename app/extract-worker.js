// pdf.js runs here rather than on the main thread, because a twelve page
// syllabus is enough to freeze a tab and a frozen tab reads as a broken site.
//
// the output is the runs contract in text/runs.py: pages of positioned text
// runs with y growing downward.

import * as pdfjs from './vendor/pdf.mjs'

pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdf.worker.mjs', import.meta.url).href

// a page with less text than this is an image and needs ocr
const MIN_CHARS = 40

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
