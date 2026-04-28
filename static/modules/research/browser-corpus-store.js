import { getStorageNamespace } from '../auth.js';

const DB_NAME = 'countymap-research-browser-store';
const DB_VERSION = 1;
const STORE_NAME = 'corpora';

function openDb() {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error || new Error('IndexedDB open failed'));
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'storageKey' });
        store.createIndex('namespace', 'namespace', { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'));
    request.onsuccess = () => resolve(request.result);
  });
}

function buildStorageKey(namespace, corpusId) {
  return `${namespace}::${corpusId}`;
}

function safeJsonBytes(value) {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch (_) {
    return 0;
  }
}

function summarizeRecord(record) {
  if (!record) return null;
  return {
    corpusId: record.corpusId,
    corpusName: record.corpusName,
    namespace: record.namespace,
    corpusUpdatedAt: record.corpusUpdatedAt || null,
    savedAt: record.savedAt || null,
    status: record.status || 'complete',
    sizeBytes: Number(record.sizeBytes || 0),
    artifactCount: Number(record.artifactCount || 0),
    sourceCount: Number(record.sourceCount || 0),
    packCount: Number(record.packCount || 0)
  };
}

export async function saveBrowserCorpusSnapshot({ corpusId, corpusName, corpusUpdatedAt, snapshot }) {
  if (!corpusId || !snapshot) throw new Error('Missing corpus snapshot');
  const namespace = getStorageNamespace();
  const db = await openDb();
  const savedCorpus = snapshot.saved_corpus || {};
  const record = {
    storageKey: buildStorageKey(namespace, corpusId),
    namespace,
    corpusId,
    corpusName: corpusName || savedCorpus.name || corpusId,
    corpusUpdatedAt: corpusUpdatedAt || savedCorpus.updated_at || null,
    savedAt: new Date().toISOString(),
    status: 'complete',
    sizeBytes: Number(snapshot.size_bytes || safeJsonBytes(snapshot)),
    artifactCount: Number((snapshot.artifacts || []).length || 0),
    sourceCount: Number(savedCorpus.source_count || 0),
    packCount: Number(savedCorpus.pack_count || 0),
    snapshot
  };
  const tx = db.transaction(STORE_NAME, 'readwrite');
  await requestToPromise(tx.objectStore(STORE_NAME).put(record));
  db.close();
  return summarizeRecord(record);
}

export async function getBrowserCorpusSnapshot(corpusId) {
  if (!corpusId) return null;
  const namespace = getStorageNamespace();
  const db = await openDb();
  const record = await requestToPromise(db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(buildStorageKey(namespace, corpusId)));
  db.close();
  return record || null;
}

export async function listBrowserCorpusRecords() {
  const namespace = getStorageNamespace();
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const index = tx.objectStore(STORE_NAME).index('namespace');
  const records = await requestToPromise(index.getAll(namespace));
  db.close();
  return Array.isArray(records) ? records : [];
}

export async function listBrowserCorpusSummaries() {
  const records = await listBrowserCorpusRecords();
  return records.map(summarizeRecord);
}

export async function removeBrowserCorpusSnapshot(corpusId) {
  if (!corpusId) return;
  const namespace = getStorageNamespace();
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readwrite');
  await requestToPromise(tx.objectStore(STORE_NAME).delete(buildStorageKey(namespace, corpusId)));
  db.close();
}

export async function clearAllBrowserCorpusSnapshots() {
  const namespace = getStorageNamespace();
  const records = await listBrowserCorpusRecords();
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readwrite');
  const store = tx.objectStore(STORE_NAME);
  for (const record of records) {
    if (record?.namespace === namespace && record?.storageKey) {
      store.delete(record.storageKey);
    }
  }
  await new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error || new Error('IndexedDB clear failed'));
    tx.onabort = () => reject(tx.error || new Error('IndexedDB clear aborted'));
  });
  db.close();
}

export async function getBrowserCorpusStorageSummary() {
  const summaries = await listBrowserCorpusSummaries();
  const totalBytes = summaries.reduce((sum, item) => sum + Number(item?.sizeBytes || 0), 0);
  const estimate = await navigator.storage?.estimate?.().catch(() => null);
  return {
    totalBytes,
    corpusCount: summaries.length,
    quotaBytes: Number(estimate?.quota || 0),
    usageBytes: Number(estimate?.usage || 0),
    summaries
  };
}

