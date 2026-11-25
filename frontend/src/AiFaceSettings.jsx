import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "./api";

function FaceCrop({ id }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let url = "";
    fetch(`/api/ai/faces/${id}/crop`, {
      headers: { Authorization: `Bearer ${getToken() || ""}` }, signal: controller.signal,
    }).then(response => {
      if (!response.ok) throw new Error("Face preview unavailable");
      return response.blob();
    }).then(blob => {
      if (controller.signal.aborted) return;
      url = URL.createObjectURL(blob);
      setSrc(url);
    }).catch(() => {});
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [id]);
  return src ? <img className="ll-face-thumb" src={src} alt="Detected face" />
    : <div className="ll-face-thumb ll-face-empty" aria-label="Face preview loading">Face</div>;
}

export default function AiFaceSettings() {
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState([]);
  const [unknown, setUnknown] = useState([]);
  const [people, setPeople] = useState([]);
  const [showUnknown, setShowUnknown] = useState(false);
  const [names, setNames] = useState({});
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const settings = await api("/ai/status");
      setStatus(settings);
      if (settings.faces_enabled) {
        const [newFaces, oldFaces, savedPeople] = await Promise.all([
          api("/ai/faces?review=pending&limit=100"),
          api("/ai/faces?review=unknown&limit=100"),
          api("/ai/people"),
        ]);
        setPending(newFaces);
        setUnknown(oldFaces);
        setPeople(savedPeople);
      } else { setPending([]); setUnknown([]); setPeople([]); }
      setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void refresh();
    // A scanner may find more faces while Settings is open. Keep the prompt fresh.
    const timer = window.setInterval(() => { void refresh(); }, 45000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function changeEnabled(enabled) {
    if (!enabled && !window.confirm(
      "Turn off facial recognition? This permanently deletes your saved face embeddings and person names. Original photos are not deleted."
    )) return;
    setBusy(true);
    try {
      await api("/ai/face-settings", { method: "PUT", body: JSON.stringify({ enabled }) });
      setMessage(enabled
        ? "Face recognition enabled. Run the private AI indexer to discover faces in your photos."
        : "Face recognition disabled; stored face data and names deleted.");
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function act(path, body = null) {
    setBusy(true); setMessage("");
    try {
      await api(path, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
      await refresh();
      setMessage("Face review saved.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function renamePerson(person) {
    const entered = window.prompt("Update this person's name", person.display_name);
    if (entered === null) return;
    const name = entered.trim();
    if (!name) { setError("A person's name cannot be blank."); return; }
    setBusy(true); setMessage("");
    try {
      await api(`/ai/people/${person.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
      await refresh();
      setMessage("Saved person name.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const selected = showUnknown ? unknown : pending;
  return <section className="ll-ai-settings status-card" aria-label="AI face settings">
    <h3>AI facial recognition</h3>
    <p>Recognize people in your private library. Names and face embeddings are saved locally for your account only; no automatic name is accepted without your confirmation.</p>
    {loading && <p role="status">Loading AI settings…</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <label className="ll-face-toggle">
      <input type="checkbox" checked={!!status?.faces_enabled} disabled={busy || !status}
        onChange={e => void changeEnabled(e.target.checked)} />
      Enable private facial recognition and save named people
    </label>
    <small>Disabling this feature erases stored face data and names. Original photos and videos remain unchanged.</small>
    {status?.faces_enabled && <>
      <div className="ll-ai-review-notice" role="status">
        {pending.length > 0
          ? <strong>{pending.length}{pending.length === 100 ? "+" : ""} unidentified faces need your review</strong>
          : <strong>No new unidentified faces to review.</strong>}
        <span> Results update when you visit Settings and periodically while it stays open.</span>
      </div>
      <div className="library-toolbar ll-review-toolbar">
        <button type="button" className={!showUnknown ? "primary-button" : "secondary-button"}
          onClick={() => setShowUnknown(false)}>Needs review ({pending.length}{pending.length === 100 ? "+" : ""})</button>
        <button type="button" className={showUnknown ? "primary-button" : "secondary-button"}
          onClick={() => setShowUnknown(true)}>Marked unknown ({unknown.length}{unknown.length === 100 ? "+" : ""})</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void refresh()}>Refresh</button>
      </div>
      <div className="ll-face-grid">
        {selected.map(face => <article className="ll-face-review-card" key={face.id}>
          <FaceCrop id={face.id}/>
          <div className="ll-face-review-controls">
            <strong>{face.suggested_name ? `Possible: ${face.suggested_name}` : "Who is this?"}</strong>
            {!showUnknown ? <>
              <label>
                <span className="ll-face-field-label">Person's name</span>
                <input type="text" maxLength="100" placeholder="Enter a name"
                  aria-label={`Name face ${face.id}`}
                  value={names[face.id] || ""}
                  onChange={e => setNames(old => ({ ...old, [face.id]: e.target.value }))}/>
              </label>
              <div className="ll-face-actions">
                <button type="button" className="primary-button" disabled={busy || !names[face.id]?.trim()}
                  onClick={() => void act(`/ai/faces/${face.id}/name`, { name: names[face.id].trim() })}>Save name</button>
                {face.suggested_person_id && <button type="button" className="secondary-button" disabled={busy}
                  onClick={() => void act(`/ai/faces/${face.id}/confirm`)}>Confirm suggested name</button>}
                <button type="button" className="secondary-button" disabled={busy}
                  onClick={() => void act(`/ai/faces/${face.id}/unknown`)}>Mark unknown</button>
              </div>
            </> : <button type="button" className="secondary-button" disabled={busy}
              onClick={() => void act(`/ai/faces/${face.id}/reopen`)}>Review again</button>}
          </div>
        </article>)}
      </div>
      {!selected.length && <p>{showUnknown ? "No faces marked unknown." : "No faces waiting for a name."}</p>}
      {selected.length === 100 && <small>Showing the newest 100 faces. Review some to load the next group.</small>}
      <h4>Saved people</h4>
      <div className="ll-people-list">
        {people.map(person => <div className="ll-person-row" key={person.id}>
          <span><strong>{person.display_name}</strong> · {Number(person.photo_count || 0)} faces</span>
          <button type="button" className="secondary-button" disabled={busy}
            onClick={() => void renamePerson(person)}>Rename</button>
        </div>)}
        {!people.length && <p>No people named yet.</p>}
      </div>
    </>}
  </section>;
}
