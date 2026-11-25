import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "./api";

function KnownFacePortrait({ faceId, name }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let url = "";
    setSrc("");
    fetch(`/api/ai/faces/${faceId}/crop`, {
      headers: { Authorization: `Bearer ${getToken() || ""}` },
      signal: controller.signal,
    })
      .then(res => res.ok ? res.blob() : Promise.reject(new Error("Unavailable")))
      .then(blob => {
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch(() => {});
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [faceId]);

  return src
    ? <img className="ll-known-face-portrait" src={src} alt={`Recent identified photo of ${name}`} loading="lazy" />
    : <span className="ll-known-face-empty" aria-label="Face thumbnail unavailable">No preview</span>;
}

export default function KnownFacesLibrary() {
  const [open, setOpen] = useState(false);
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api("/ai/faces/known-gallery");
      setPeople(result.items || []);
      setError("");
    } catch (err) {
      setError(err?.message || "Unable to load known faces");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);

  return <section className="ll-known-faces" aria-label="Known faces library">
    <div className="ll-known-faces-header">
      <div>
        <strong>Known faces</strong>
        <small>One recent photo of each person LocalLens knows by name.</small>
      </div>
      <button type="button" className="secondary-button" aria-expanded={open}
        onClick={() => setOpen(value => !value)}>
        {open ? "Hide known faces" : "Show known faces"}
      </button>
    </div>
    {open && <div className="ll-known-faces-body">
      <div className="ll-known-faces-toolbar">
        <small>{loading ? "Loading…" : `${people.length} named ${people.length === 1 ? "person" : "people"}`}</small>
        <button type="button" className="secondary-button" onClick={() => void refresh()} disabled={loading}>Refresh</button>
      </div>
      {error && <p role="alert" className="error-message">{error}</p>}
      {!loading && !error && people.length === 0 && <p className="ll-known-faces-hint">No named faces yet. Names you add will appear here.</p>}
      <div className="ll-known-faces-grid">
        {people.map(person => <article className="ll-known-face" key={person.id}>
          <div className="ll-known-face-name" title={person.display_name}>{person.display_name}</div>
          <KnownFacePortrait faceId={person.face_id} name={person.display_name} />
          <small>{Number(person.face_count || 0).toLocaleString()} identified {Number(person.face_count) === 1 ? "face" : "faces"}</small>
        </article>)}
      </div>
    </div>}
  </section>;
}
