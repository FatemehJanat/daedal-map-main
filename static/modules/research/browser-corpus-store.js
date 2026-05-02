import { getStorageNamespace } from '../auth.js';
import { canUseBridge, postBridgeMessage } from '../shared/cross-surface-bridge.js';

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

async function getStorageUsageBytes() {
  try {
    const estimate = await navigator.storage?.estimate?.();
    return Number(estimate?.usage || 0);
  } catch (_) {
    return 0;
  }
}

function safeJsonBytes(value) {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch (_) {
    return 0;
  }
}

function supportsSnapshotCompression() {
  return typeof window !== 'undefined'
    && typeof window.CompressionStream === 'function'
    && typeof window.DecompressionStream === 'function'
    && typeof TextEncoder === 'function'
    && typeof TextDecoder === 'function'
    && typeof Response === 'function';
}

async function compressSnapshot(snapshot) {
  if (!supportsSnapshotCompression()) {
    return {
      compression: 'identity',
      payload: snapshot,
      sizeBytes: Number(snapshot?.size_bytes || safeJsonBytes(snapshot))
    };
  }
  let jsonText = '';
  try {
    jsonText = JSON.stringify(snapshot);
  } catch (error) {
    console.warn('Research browser snapshot too large to stringify for gzip compression; storing structured snapshot directly.', error);
    return {
      compression: 'identity',
      payload: snapshot,
      sizeBytes: Number(snapshot?.size_bytes || safeJsonBytes(snapshot))
    };
  }
  const encoded = new TextEncoder().encode(jsonText);
  const compressedStream = new Blob([encoded]).stream().pipeThrough(new window.CompressionStream('gzip'));
  const compressedBuffer = await new Response(compressedStream).arrayBuffer();
  return {
    compression: 'gzip',
    payload: compressedBuffer,
    sizeBytes: compressedBuffer.byteLength || Number(snapshot?.size_bytes || 0) || safeJsonBytes(snapshot)
  };
}

async function inflateSnapshotFromRecord(record) {
  if (!record) return null;
  if (record.snapshot && typeof record.snapshot === 'object') {
    return record.snapshot;
  }
  const compression = String(record.snapshotCompression || 'identity');
  if (compression === 'identity') {
    return record.snapshotPayload && typeof record.snapshotPayload === 'object' ? record.snapshotPayload : null;
  }
  if (compression !== 'gzip' || !record.snapshotPayload) {
    return null;
  }
  if (!supportsSnapshotCompression()) {
    throw new Error('Browser snapshot is compressed, but this browser cannot restore it.');
  }
  const payload = record.snapshotPayload;
  const compressed = payload instanceof ArrayBuffer
    ? payload
    : ArrayBuffer.isView(payload)
      ? payload.buffer.slice(payload.byteOffset || 0, (payload.byteOffset || 0) + (payload.byteLength || 0))
      : Array.isArray(payload)
        ? new Uint8Array(payload).buffer
        : (payload?.buffer instanceof ArrayBuffer ? payload.buffer : null);
  if (!compressed) return null;
  const decompressedStream = new Blob([compressed]).stream().pipeThrough(new window.DecompressionStream('gzip'));
  const jsonText = await new Response(decompressedStream).text();
  return JSON.parse(jsonText || '{}');
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
    payloadBytes: Number(record.payloadBytes || 0),
    sizeKind: String(record.sizeKind || 'payload'),
    artifactCount: Number(record.artifactCount || 0),
    sourceCount: Number(record.sourceCount || 0),
    packCount: Number(record.packCount || 0)
  };
}

async function getLocalBrowserCorpusRecord(namespace, corpusId) {
  const db = await openDb();
  const record = await requestToPromise(
    db.transaction(STORE_NAME, 'readonly')
      .objectStore(STORE_NAME)
      .get(buildStorageKey(namespace, corpusId))
  );
  db.close();
  return record || null;
}

async function listLocalBrowserCorpusRecords(namespace) {
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const index = tx.objectStore(STORE_NAME).index('namespace');
  const records = await requestToPromise(index.getAll(namespace));
  db.close();
  return Array.isArray(records) ? records : [];
}

async function migrateLocalRecordToBridge(namespace, corpusId) {
  if (!canUseBridge()) return null;
  const record = await getLocalBrowserCorpusRecord(namespace, corpusId);
  if (!record) return null;
  await postBridgeMessage('dm-browser-corpus-save', { record });
  return record;
}

async function migrateAllLocalRecordsToBridge(namespace) {
  if (!canUseBridge()) return [];
  const records = await listLocalBrowserCorpusRecords(namespace);
  for (const record of records) {
    if (!record?.storageKey) continue;
    await postBridgeMessage('dm-browser-corpus-save', { record });
  }
  return records;
}

export async function saveBrowserCorpusSnapshot({ corpusId, corpusName, corpusUpdatedAt, snapshot }) {
  if (!corpusId || !snapshot) throw new Error('Missing corpus snapshot');
  const namespace = getStorageNamespace();
  if (canUseBridge()) {
    const savedCorpus = snapshot.saved_corpus || {};
    const storageKey = buildStorageKey(namespace, corpusId);
    const existingRecord = await postBridgeMessage('dm-browser-corpus-get', { namespace, corpusId }).then(r => r.record || null).catch(() => null);
    const storedSnapshot = await compressSnapshot(snapshot);
    const record = {
      storageKey,
      namespace,
      corpusId,
      corpusName: corpusName || savedCorpus.name || corpusId,
      corpusUpdatedAt: corpusUpdatedAt || savedCorpus.updated_at || null,
      savedAt: new Date().toISOString(),
      status: 'complete',
      sizeBytes: Number(existingRecord?.sizeBytes || 0) || Number(storedSnapshot.sizeBytes || 0),
      payloadBytes: Number(storedSnapshot.sizeBytes || 0),
      sizeKind: Number(existingRecord?.sizeBytes || 0) > 0 ? String(existingRecord?.sizeKind || 'measured') : 'payload',
      artifactCount: Number((snapshot.artifacts || []).length || 0),
      sourceCount: Number(savedCorpus.source_count || 0),
      packCount: Number(savedCorpus.pack_count || 0),
      snapshotCompression: storedSnapshot.compression,
      snapshotPayload: storedSnapshot.payload
    };
    const response = await postBridgeMessage('dm-browser-corpus-save', { record });
    return response.summary || summarizeRecord(record);
  }
  const db = await openDb();
  const savedCorpus = snapshot.saved_corpus || {};
  const storageKey = buildStorageKey(namespace, corpusId);
  const existingRecord = await requestToPromise(db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(storageKey));
  const storedSnapshot = await compressSnapshot(snapshot);
  const usageBefore = await getStorageUsageBytes();
  const record = {
    storageKey,
    namespace,
    corpusId,
    corpusName: corpusName || savedCorpus.name || corpusId,
    corpusUpdatedAt: corpusUpdatedAt || savedCorpus.updated_at || null,
    savedAt: new Date().toISOString(),
    status: 'complete',
    sizeBytes: 0,
    payloadBytes: Number(storedSnapshot.sizeBytes || 0),
    sizeKind: 'payload',
    artifactCount: Number((snapshot.artifacts || []).length || 0),
    sourceCount: Number(savedCorpus.source_count || 0),
    packCount: Number(savedCorpus.pack_count || 0),
    snapshotCompression: storedSnapshot.compression,
    snapshotPayload: storedSnapshot.payload
  };
  const tx = db.transaction(STORE_NAME, 'readwrite');
  await requestToPromise(tx.objectStore(STORE_NAME).put(record));
  const usageAfter = await getStorageUsageBytes();
  const usageDelta = usageBefore > 0 && usageAfter > 0 ? (usageAfter - usageBefore) : 0;
  const previousActualBytes = Number(existingRecord?.sizeBytes || 0);
  const measuredBytes = usageDelta > 0 ? (existingRecord ? previousActualBytes + usageDelta : usageDelta) : 0;
  record.sizeBytes = measuredBytes > 0 ? measuredBytes : record.payloadBytes;
  record.sizeKind = measuredBytes > 0 ? 'measured' : 'payload';
  if (record.sizeKind === 'measured') {
    const finalizeTx = db.transaction(STORE_NAME, 'readwrite');
    await requestToPromise(finalizeTx.objectStore(STORE_NAME).put(record));
  }
  db.close();
  return summarizeRecord(record);
}

export async function getBrowserCorpusSnapshot(corpusId) {
  if (!corpusId) return null;
  const namespace = getStorageNamespace();
  if (canUseBridge()) {
    let response = await postBridgeMessage('dm-browser-corpus-get', { namespace, corpusId });
    let record = response.record || null;
    if (!record) {
      record = await migrateLocalRecordToBridge(namespace, corpusId);
      if (record) {
        response = await postBridgeMessage('dm-browser-corpus-get', { namespace, corpusId });
        record = response.record || record;
      }
    }
    if (!record) return null;
    const snapshot = await inflateSnapshotFromRecord(record);
    return {
      ...record,
      snapshot
    };
  }
  const db = await openDb();
  const record = await requestToPromise(db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(buildStorageKey(namespace, corpusId)));
  db.close();
  if (!record) return null;
  const snapshot = await inflateSnapshotFromRecord(record);
  return {
    ...record,
    snapshot
  };
}

export async function listBrowserCorpusRecords() {
  const namespace = getStorageNamespace();
  if (canUseBridge()) {
    let response = await postBridgeMessage('dm-browser-corpus-list-summaries', { namespace });
    let summaries = Array.isArray(response.summaries) ? response.summaries : [];
    if (!summaries.length) {
      await migrateAllLocalRecordsToBridge(namespace);
      response = await postBridgeMessage('dm-browser-corpus-list-summaries', { namespace });
      summaries = Array.isArray(response.summaries) ? response.summaries : [];
    }
    return summaries.map(summary => ({
      ...summary,
      storageKey: buildStorageKey(namespace, summary.corpusId)
    }));
  }
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const index = tx.objectStore(STORE_NAME).index('namespace');
  const records = await requestToPromise(index.getAll(namespace));
  db.close();
  return Array.isArray(records) ? records : [];
}

export async function listBrowserCorpusSummaries() {
  if (canUseBridge()) {
    const namespace = getStorageNamespace();
    let response = await postBridgeMessage('dm-browser-corpus-list-summaries', { namespace });
    let summaries = Array.isArray(response.summaries) ? response.summaries : [];
    if (!summaries.length) {
      await migrateAllLocalRecordsToBridge(namespace);
      response = await postBridgeMessage('dm-browser-corpus-list-summaries', { namespace });
      summaries = Array.isArray(response.summaries) ? response.summaries : [];
    }
    return summaries;
  }
  const records = await listBrowserCorpusRecords();
  return records.map(summarizeRecord);
}

export async function removeBrowserCorpusSnapshot(corpusId) {
  if (!corpusId) return;
  const namespace = getStorageNamespace();
  if (canUseBridge()) {
    await postBridgeMessage('dm-browser-corpus-remove', { namespace, corpusId });
    return;
  }
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readwrite');
  await requestToPromise(tx.objectStore(STORE_NAME).delete(buildStorageKey(namespace, corpusId)));
  db.close();
}

export async function clearAllBrowserCorpusSnapshots() {
  const namespace = getStorageNamespace();
  if (canUseBridge()) {
    await postBridgeMessage('dm-browser-corpus-clear', { namespace });
    return;
  }
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
  if (canUseBridge()) {
    const namespace = getStorageNamespace();
    const response = await postBridgeMessage('dm-browser-corpus-storage-summary', { namespace });
    return response.summary || {
      totalBytes: 0,
      corpusCount: 0,
      quotaBytes: 0,
      usageBytes: 0,
      summaries: []
    };
  }
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
