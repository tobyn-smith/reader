// the parser is the python already used by the command line, run under pyodide.
// rewriting it in javascript would mean reintroducing every bug the fixture
// suite has already caught, so the same modules are loaded here instead.
//
// pyodide is a large download, so nothing in this file runs until the visitor
// has actually picked a file.

let pyodide = null
let loading = null

async function boot() {
  if (pyodide) return pyodide
  if (loading) return loading

  loading = (async () => {
    self.postMessage({ type: 'boot', stage: 'downloading' })
    importScripts('./vendor/pyodide/pyodide.js')
    // single threaded build. github pages cannot send the cross origin
    // isolation headers that a threaded build needs, so threading is not an
    // option here and the single threaded one works everywhere.
    pyodide = await self.loadPyodide({ indexURL: './vendor/pyodide/' })

    self.postMessage({ type: 'boot', stage: 'loading parser' })
    const response = await fetch('./vendor/vault.zip')
    if (!response.ok) throw new Error('parser bundle missing')
    const bytes = new Uint8Array(await response.arrayBuffer())
    pyodide.unpackArchive(bytes, 'zip', { extractDir: '/lib/vault-src' })
    pyodide.runPython(`
import sys
if "/lib/vault-src" not in sys.path:
    sys.path.insert(0, "/lib/vault-src")
import vault.web
`)
    web = pyodide.pyimport('vault.web')
    self.postMessage({ type: 'boot', stage: 'ready' })
    return pyodide
  })()

  return loading
}

// the module is imported once and held. importing it per call and destroying
// the proxy afterwards left later imports failing with ModuleNotFoundError,
// which showed up as every file after the first refusing to parse.
let web = null

function call(name, args) {
  const fn = web[name]
  const result = fn(...args)
  const value = typeof result === 'string' ? result : result.toString()
  if (result && typeof result.destroy === 'function') result.destroy()
  if (fn && typeof fn.destroy === 'function') fn.destroy()
  return value
}

// pyodide is single threaded, and overlapping calls into it interleave badly.
// each request waits for the one before it.
let chain = Promise.resolve()

function serialize(work) {
  const next = chain.then(work, work)
  chain = next.catch(() => {})
  return next
}

self.onmessage = (event) => serialize(async () => {
  const { type, id, payload, threshold, head, candidates } = event.data

  try {
    if (type === 'preload') {
      await boot()
      self.postMessage({ type: 'ready' })
      return
    }

    await boot()

    if (type === 'ingest') {
      // one call works out whether this is a syllabus or a reading and returns
      // whichever is appropriate, so the page never has to ask the visitor
      const json = call('ingest_pdf', [JSON.stringify(payload), threshold ?? 0.75])
      self.postMessage({ type: 'ingested', id, result: JSON.parse(json) })
      return
    }

    if (type === 'parse') {
      const json = call('parse_runs', [JSON.stringify(payload), threshold ?? 0.75])
      self.postMessage({ type: 'parsed', id, result: JSON.parse(json) })
      return
    }

    if (type === 'reading') {
      const json = call('extract_reading', [JSON.stringify(payload)])
      self.postMessage({ type: 'reading', id, result: JSON.parse(json) })
      return
    }

    if (type === 'match') {
      const json = call('match_reading', [head, JSON.stringify(candidates), event.data.filename || ''])
      self.postMessage({ type: 'matched', id, result: JSON.parse(json) })
    }
  } catch (error) {
    self.postMessage({ type: 'error', id, message: String((error && error.message) || error) })
  }
})
