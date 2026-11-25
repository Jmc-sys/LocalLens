// One download for all original media belonging to a photo. Never download a preview.
import { api, mediaBlob, getToken } from "./api";

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give mobile browsers sufficient time to read the blob before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export async function downloadOwnerOriginal(photo) {
  if (!Number.isSafeInteger(Number(photo?.id)) || Number(photo.id) <= 0) {
    throw new Error("Cannot download: invalid photo ID.");
  }
  // Check the server rather than trusting potentially stale search/album flags.
  const state = await api("/live/status", {
    method: "POST",
    body: JSON.stringify({ photo_ids: [Number(photo.id)] }),
  });
  const isLive = (state?.ids || []).some(id => Number(id) === Number(photo.id));
  if (isLive) {
    const response = await fetch(`/api/live/${photo.id}/originals`, {
      headers: { Authorization: `Bearer ${getToken() || ""}` },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Live Photo download failed (${response.status}).`);
    }
    triggerDownload(await response.blob(), `LivePhoto-${photo.id}.zip`);
  } else {
    const blob = await mediaBlob(photo.id, "file");
    triggerDownload(blob, photo.original_filename || `Original-${photo.id}`);
  }
}
