import { sha256File } from "./sha256-file";

// A speed-only hint, NEVER a substitute for the owner's server-side hash check.
// A fast rescan trusts filename/path/length/mtime plus a hash of three samples.
// This cannot prove unchanged bytes in the un-sampled portions of a file.
const DATABASE = "locallens-import-receipts";
const STORE = "files";
const SAMPLE = 64 * 1024;
const BATCH = 200;

function fileKey(userId, file) {
  if (!Number.isFinite(file.lastModified) || file.lastModified <= 0) return null;
  return JSON.stringify([
    String(userId), file.webkitRelativePath || file.name,
    file.size, file.lastModified, file.type || "",
  ]);
}

function openDB() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("IndexedDB unavailable")); return; }
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function readRecords(db, keys) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const store = tx.objectStore(STORE);
    const values = new Map();
    for (const key of keys) {
      const req = store.get(key);
      req.onsuccess = () => { if (req.result) values.set(key, req.result); };
    }
    tx.oncomplete = () => resolve(values);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function writeRecords(db, records) {
  return new Promise((resolve, reject) => {
    if (!records.length) { resolve(); return; }
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    for (const record of records) store.put(record);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

async function sampleDigest(file) {
  // Read <192 KiB instead of multi-GB file. This is deliberately a quick
  // modification indicator, NOT a cryptographic duplicate proof.
  const spans = [[0, Math.min(file.size, SAMPLE)]];
  if (file.size > SAMPLE * 2) {
    const mid = Math.floor(file.size / 2);
    spans.push([mid, Math.min(file.size, mid + SAMPLE)]);
  }
  if (file.size > SAMPLE) spans.push([Math.max(0, file.size - SAMPLE), file.size]);
  const parts = spans.map(([start, end]) => file.slice(start, end));
  return sha256File(new Blob(parts));
}

async function bounded(items, limit, task) {
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) await task(items[next++]);
  }));
}

function isDigest(value) { return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value); }

export async function prepareFastRepeat(files, api, { verifyEveryFile = false } = {}) {
  const empty = { matches: new Map(), async remember() {} };
  if (verifyEveryFile || !files.length) return empty;
  let db;
  let userId;
  try {
    const me = await api("/auth/me");
    userId = me?.id ?? me?.user_id;
    if (!userId) return empty;
    db = await openDB();
    const keys = files.map(file => fileKey(userId, file)).filter(Boolean);
    const stored = await readRecords(db, [...new Set(keys)]);
    const valid = [];
    await bounded(files, 5, async (file) => {
      const key = fileKey(userId, file);
      const record = key && stored.get(key);
      if (!record || !isDigest(record.sha256) || record.size !== file.size) return;
      try {
        if (await sampleDigest(file) === record.sample) valid.push({ file, record });
      } catch { /* Unreadable sample -> use full-hash preflight. */ }
    });
    const matches = new Map();
    for (let start = 0; start < valid.length; start += BATCH) {
      const batch = valid.slice(start, start + BATCH);
      const response = await api("/media/check-duplicates-batch", {
        method: "POST", body: JSON.stringify({items: batch.map(({record}) => ({
          sha256: record.sha256, size_bytes: record.size,
        }))}),
      });
      if (!Array.isArray(response.results) || response.results.length !== batch.length) {
        throw new Error("Invalid fast duplicate response");
      }
      response.results.forEach((result, i) => {
        if (result.status === "duplicate") matches.set(batch[i].file, result);
      });
    }
    return {
      matches,
      async remember(saved) {
        // Server receipts are the checksums of bytes that were ACTUALLY stored.
        // Never cache only the incoming filename/length without a server receipt.
        const byId = new Map();
        for (const entry of saved) {
          if (!Number.isSafeInteger(entry.id) || entry.id < 1) continue;
          const entries = byId.get(entry.id) || [];
          entries.push(entry);
          byId.set(entry.id, entries);
        }
        const ids = [...byId.keys()];
        const receipts = [];
        for (let start = 0; start < ids.length; start += BATCH) {
          const response = await api("/media/import-receipts", {
            method: "POST", body: JSON.stringify({ ids: ids.slice(start, start + BATCH) }),
          });
          receipts.push(...(response.entries || []));
        }
        const toSave = [];
        await bounded(receipts, 5, async (receipt) => {
          if (!isDigest(receipt.sha256)) return;
          for (const source of byId.get(receipt.id) || []) {
            if (source.kind !== receipt.kind || source.file.size !== receipt.size_bytes) continue;
            const key = fileKey(userId, source.file);
            if (!key) continue;
            try {
              toSave.push({ key, sha256: receipt.sha256.toLowerCase(),
                size: receipt.size_bytes, sample: await sampleDigest(source.file) });
            } catch { /* Keep upload successful even if caching is blocked. */ }
          }
        });
        await writeRecords(db, toSave);
      },
    };
  } catch {
    // Private browsing, unsupported IndexedDB, or offline backend must never
    // block normal uploads or normal full-file SHA256 duplicate checks.
    return empty;
  }
}
