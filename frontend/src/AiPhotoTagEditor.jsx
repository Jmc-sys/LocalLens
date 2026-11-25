import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import TagLibrarySuggestions from "./TagLibrarySuggestions";
import "./tag-suggestions.css";

// Local tag feedback, not model retraining. Corrections are private to this photo.
export default function AiPhotoTagEditor({ photoId, onChange }) {
  const [tags, setTags] = useState([]);
  const [hidden, setHidden] = useState([]);
  const [newTag, setNewTag] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const result = await api(`/ai/photo/${photoId}/tags`);
    setTags(result.tags || []);
    setHidden(result.hidden || []);
  }, [photoId]);

  useEffect(() => {
    let active = true;
    setTags([]); setHidden([]); setError(""); setMessage(""); setNewTag("");
    api(`/ai/photo/${photoId}/tags`).then(result => {
      if (active) { setTags(result.tags || []); setHidden(result.hidden || []); }
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [photoId]);

  async function updateTag(tag, action) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api(`/ai/photo/${photoId}/tags`, {
        method: "PUT", body: JSON.stringify({ tag, action }),
      });
      await refresh();
      onChange?.();
      setMessage(action === "reject" ? `Removed “${tag.replace(/[-_]/g, " ")}” from this photo.` : "Tag saved.");
      return true;
    } catch (err) { setError(err.message); return false; }
    finally { setBusy(false); }
  }

  async function addTag(event) {
    event.preventDefault();
    const tag = newTag.trim();
    if (!tag) return;
    if (await updateTag(tag, "add")) setNewTag("");
  }

  async function restore(tag) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api(`/ai/photo/${photoId}/tags/${encodeURIComponent(tag)}`, { method: "DELETE" });
      await refresh();
      onChange?.();
      setMessage("Correction removed. This photo will be checked again.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <section className="ll-v062-tags" aria-label="Photo tags">
    <div className="ll-v062-tag-heading"><strong>Photo tags</strong><small>Correct anything that doesn't belong</small></div>
    <div className="ll-v062-tag-row">
      {tags.map(item => <span className="ll-v062-tag" key={item.tag}>
        <span title={item.source === "manual" ? "Your tag" : "Suggested from photo"}>
          {item.tag.replace(/[-_]/g, " ")}
        </span>
        <button type="button" title={`Remove ${item.tag.replace(/[-_]/g, " ")}`}
          aria-label={`Remove ${item.tag.replace(/[-_]/g, " ")} tag`}
          onClick={() => void updateTag(item.tag, "reject")} disabled={busy}>×</button>
      </span>)}
      {!tags.length && <small className="ll-v062-faint">No tags for this photo yet</small>}
    </div>
    <TagLibrarySuggestions draft={newTag} photoTags={tags} disabled={busy}
      onSelect={(tag) => { if (!busy) void updateTag(tag, "add"); }} />
    <form className="ll-v062-tag-add" onSubmit={addTag}>
      <input aria-label="Add photo tag" placeholder="Add a more accurate tag" maxLength={80}
        value={newTag} onChange={e => setNewTag(e.target.value)} />
      <button type="submit" disabled={busy || !newTag.trim()}>Add tag</button>
    </form>
    {hidden.length > 0 && <div className="ll-v062-hidden">
      <button type="button" onClick={() => setShowHidden(v => !v)}>
        {showHidden ? "Hide removed tags" : `Removed tags (${hidden.length})`}
      </button>
      {showHidden && <div className="ll-v062-tag-row">
        {hidden.map(tag => <button key={tag} type="button" disabled={busy}
          className="ll-v062-restore" onClick={() => void restore(tag)}>
          Restore {tag.replace(/[-_]/g, " ")}
        </button>)}
      </div>}
    </div>}
    {message && <small role="status">{message}</small>}
    {error && <small className="error-message" role="alert">{error}</small>}
  </section>;
}
