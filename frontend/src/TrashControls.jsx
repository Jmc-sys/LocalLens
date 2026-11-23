import { useEffect, useState } from "react";
import { api } from "./api";

export default function TrashControls({ selected = [], onDeleted }) {
  const [retention, setRetention] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api("/trash/settings", { signal: controller.signal })
      .then((data) => setRetention(data.days))
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(`Could not load trash settings: ${err.message}`);
        }
      });
    return () => controller.abort();
  }, []);

  async function refreshGallery() {
    if (typeof onDeleted === "function") {
      await onDeleted();
    }
  }

  async function deleteSelected() {
    if (busy || selected.length === 0) return;
    const count = selected.length;
    if (!window.confirm(
      `Permanently delete ${count} selected photo(s) and all associated media?\n\n` +
      "This action cannot be undone.\n\n" +
      "Press OK to permanently delete, or Cancel to keep them."
    )) return;

    setBusy(true);
    setError("");
    setMessage("");
    let deleted = 0;
    try {
      for (const id of selected) {
        await api(`/trash/photos/${id}`, { method: "DELETE" });
        deleted += 1;
      }
      setMessage(`${deleted} photo(s) permanently deleted.`);
    } catch (err) {
      setError(`Deletion stopped after ${deleted} photo(s): ${err.message}`);
    } finally {
      try { if (deleted > 0) await refreshGallery(); }
      catch (err) { setError(`Photos deleted, but the gallery could not refresh: ${err.message}`); }
      setBusy(false);
    }
  }

  async function emptyTrash() {
    if (busy) return;
    if (!window.confirm(
      "Permanently delete ALL photos in your trash and their associated media?\n\n" +
      "WARNING: This action cannot be undone.\n\n" +
      "Press OK to permanently delete, or Cancel to keep your photos."
    )) return;

    setBusy(true);
    setError("");
    setMessage("Deleting photos from trash...");
    let deleted = 0;
    try {
      // The backend handles at most 100 photos per request.
      for (;;) {
        const result = await api("/trash/empty", { method: "POST" });
        const batchCount = Number(result.deleted || 0);
        deleted += batchCount;
        setMessage(`Permanently deleted ${deleted} photo(s)...`);
        if (!result.has_more || batchCount === 0) break;
      }
      setMessage(`${deleted} photo(s) permanently deleted. Associated files are queued for removal.`);
    } catch (err) {
      setError(`Empty trash failed after ${deleted} photo(s): ${err.message}`);
    } finally {
      try { await refreshGallery(); }
      catch (err) { setError(`Trash updated, but the gallery could not refresh: ${err.message}`); }
      setBusy(false);
    }
  }

  return (
    <section className="trash-controls status-card">
      <div>
        <h3>Recycle bin</h3>
        <p>
          {retention === null ? "Loading retention setting..." : retention === 0
            ? "Automatic deletion is off. Trashed photos remain until permanently deleted."
            : `Photos become eligible for permanent deletion after ${retention} day(s) in trash.`}
        </p>
        <small>Change automatic deletion under Account Settings.</small>
      </div>
      <div className="trash-control-buttons">
        <button type="button" className="secondary-button" disabled={busy || selected.length === 0} onClick={deleteSelected}>
          Permanently delete selected ({selected.length})
        </button>
        <button type="button" className="secondary-button trash-danger" disabled={busy} onClick={emptyTrash}>
          {busy ? "Deleting..." : "Empty trash"}
        </button>
      </div>
      {message && <p role="status" className="success-message">{message}</p>}
      {error && <p role="alert" className="error-message">{error}</p>}
    </section>
  );
}
