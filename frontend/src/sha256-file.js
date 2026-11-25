import { createSHA256 } from "hash-wasm";

// Chunks rather than file.arrayBuffer(): even multi-GB videos need only ~4 MiB
// of JavaScript-accessible memory at a time. No media bytes leave the device
// until the authenticated duplicate lookup says they're not already stored.
export async function sha256File(file, signal) {
  if (!(file instanceof Blob) || file.size <= 0) {
    throw new Error("Cannot hash an empty or invalid media file");
  }
  const hasher = await createSHA256();
  hasher.init();
  const CHUNK_BYTES = 4 * 1024 * 1024;
  for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
    if (signal?.aborted) throw new Error("Checksum cancelled");
    const chunk = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
    hasher.update(new Uint8Array(chunk));
  }
  return hasher.digest("hex");
}
