// everything the visitor has parsed, kept in this browser and nowhere else.

const DB_NAME = 'seminar-vault'
const VERSION = 1

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
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
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

function all(store) {
  return new Promise((resolve, reject) => {
    const request = store.getAll()
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
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
  await transact(['courses', 'documents', 'notes'], 'readwrite', (tx) => {
    tx.objectStore('courses').clear()
    tx.objectStore('documents').clear()
    tx.objectStore('notes').clear()
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
  return {
    format: 'seminar-vault',
    version: 1,
    exported: new Date().toISOString(),
    courses: await listCourses(),
    documents: await listDocuments(),
  }
}

export async function importAll(data) {
  if (!data || data.format !== 'seminar-vault') {
    throw new Error('not a seminar vault export')
  }
  for (const course of data.courses || []) await putCourse(course)
  for (const record of data.documents || []) await putDocument(record)
}
