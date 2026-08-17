// everything the visitor has parsed, kept in this browser and nowhere else.

const DB_NAME = 'seminar-vault'
const VERSION = 2

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('courses')) {
        db.createObjectStore('courses', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('documents')) {
        db.createObjectStore('documents', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('notes')) {
        db.createObjectStore('notes', { keyPath: 'id', autoIncrement: true })
      }
      // ticking a reading off and jotting a line about it. the point of the
      // tool is knowing what you have read, and that should not require
      // producing the pdf as evidence.
      if (!db.objectStoreNames.contains('progress')) {
        db.createObjectStore('progress', { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function readAll(store) {
  return open().then(
    (db) =>
      new Promise((resolve, reject) => {
        const request = db.transaction(store).objectStore(store).getAll()
        request.onsuccess = () => {
          db.close()
          resolve(request.result)
        }
        request.onerror = () => {
          db.close()
          reject(request.error)
        }
      })
  )
}

export async function putProgress(entry) {
  await transact(['progress'], 'readwrite', (tx) => tx.objectStore('progress').put(entry))
}

export function listProgress() {
  return readAll('progress')
}

async function transact(names, mode, run) {
  const db = await open()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(names, mode)
    const result = run(tx)
    tx.oncomplete = () => {
      db.close()
      resolve(result)
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function putCourse(course) {
  await transact(['courses'], 'readwrite', (tx) => tx.objectStore('courses').put(course))
}

export async function listCourses() {
  const db = await open()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('courses').objectStore('courses').getAll()
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally {
    db.close()
  }
}

export async function putDocument(record) {
  await transact(['documents'], 'readwrite', (tx) => tx.objectStore('documents').put(record))
}

export async function listDocuments() {
  const db = await open()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('documents').objectStore('documents').getAll()
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally {
    db.close()
  }
}

export async function removeCourse(id) {
  await transact(['courses'], 'readwrite', (tx) => tx.objectStore('courses').delete(id))
}

export async function clearAll() {
  await transact(['courses', 'documents', 'notes', 'progress'], 'readwrite', (tx) => {
    tx.objectStore('courses').clear()
    tx.objectStore('documents').clear()
    tx.objectStore('notes').clear()
    tx.objectStore('progress').clear()
  })
  if (navigator.storage && navigator.storage.getDirectory) {
    try {
      const root = await navigator.storage.getDirectory()
      for await (const name of root.keys()) {
        await root.removeEntry(name, { recursive: true }).catch(() => {})
      }
    } catch {
      // origin private file system is optional; nothing to undo if it is absent
    }
  }
}

export async function exportAll() {
  // the stored pdf bytes stay out of the backup: an arraybuffer turns into
  // an empty object under json anyway, and a backup should stay small enough
  // to email. a restored course simply asks for the file again if a re-read
  // is ever wanted.
  const courses = (await listCourses()).map(({ pdf, ...rest }) => rest)
  return {
    format: 'seminar-vault',
    version: 1,
    exported: new Date().toISOString(),
    courses,
    // same reason the syllabus bytes are dropped above: an arraybuffer turns
    // into an empty object under json, and a backup should stay small enough
    // to email
    documents: (await listDocuments()).map(({ pdf, ...rest }) => rest),
    progress: await listProgress(),
  }
}

export async function importAll(data) {
  if (!data || data.format !== 'seminar-vault') {
    throw new Error('not a schedule reader export')
  }
  // the backup leaves pdf bytes out to stay small, and put() replaces whole
  // records. restoring a backup into the browser that made it was therefore
  // wiping every stored pdf while looking like a no-op. a row from the backup
  // keeps the bytes already here under the same id.
  const heldCourses = new Map((await listCourses()).map((c) => [c.id, c]))
  const heldDocs = new Map((await listDocuments()).map((d) => [d.id, d]))
  for (const course of data.courses || []) {
    const kept = heldCourses.get(course.id)
    await putCourse(course.pdf || !kept ? course : { ...course, pdf: kept.pdf })
  }
  for (const record of data.documents || []) {
    const kept = heldDocs.get(record.id)
    await putDocument(record.pdf || !kept ? record : { ...record, pdf: kept.pdf })
  }
  for (const entry of data.progress || []) await putProgress(entry)
}
