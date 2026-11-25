import FaceHoverOverlay from "./FaceHoverOverlay";
import { useEffect, useState } from "react";
import { getToken } from "./api";
import { api } from "./api";
import AiPhotoTagEditor from "./AiPhotoTagEditor";

function FaceThumb({ faceId }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    const aborter = new AbortController();
    let url = "";
    fetch(`/api/ai/faces/${faceId}/crop`, {
      headers: { Authorization: `Bearer ${getToken() || ""}` }, signal: aborter.signal,
    }).then(res => res.ok ? res.blob() : Promise.reject(new Error("Unavailable")))
      .then(blob => { if (!aborter.signal.aborted) { url = URL.createObjectURL(blob); setSrc(url); } })
      .catch(() => {});
    return () => { aborter.abort(); if (url) URL.revokeObjectURL(url); };
  }, [faceId]);
  return src ? <img className="ll-v06-mini-face" src={src} alt="" aria-hidden="true" /> : null;
}

// Compact annotation strip inside the owner's fullscreen viewer. It uses the
// existing private face-crop endpoint; no names are sent to any external API.
export default function AiPhotoAnnotations({ photoId }) {
  const [data, setData] = useState({ faces: [], pets: [] });
  const [active, setActive] = useState(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [knownNames, setKnownNames] = useState({ people: [], pets: [] });
  const [busy, setBusy] = useState(false);

  async function load() {
    try { setData(await api(`/ai/photo/${photoId}/labels`)); setError(""); }
    catch { /* No annotations for this image or AI disabled. */ }
  }
  useEffect(() => { setData({ faces: [], pets: [] }); setActive(null); void load(); }, [photoId]);

  useEffect(() => {
    if (active === null) return;
    let alive = true;
    api("/ai/library-names")
      .then(data => { if (alive) setKnownNames(data); })
      .catch(() => {});
    return () => { alive = false; };
  }, [active]);

  async function submit() {
    if (!value.trim()) return;
    setBusy(true); setError("");
    try {
      if (active === "pet") await api(`/ai/photo/${photoId}/pets`, {
        method: "POST", body: JSON.stringify({ name: value.trim() }),
      });
      else if (typeof active === "string" && active.startsWith("pet:")) await api(`/ai/pet-labels/${active.slice(4)}`, {
        method: "PATCH", body: JSON.stringify({ name: value.trim() }),
      });
      else if (typeof active === "number") await api(`/ai/faces/${active}/name`, {
        method: "POST", body: JSON.stringify({ name: value.trim() }),
      });
      setActive(null); setValue(""); await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function removePet(id) {
    try { await api(`/ai/pet-labels/${id}`, { method: "DELETE" }); await load(); }
    catch (err) { setError(err.message); }
  }

  return <aside className="ll-v06-annotations" aria-label="Photo identities">
    <FaceHoverOverlay photoId={photoId} faces={data.faces || []} />
    <div className="ll-v06-annotation-row"><strong>People</strong>
      {(data.faces || []).map((face, index) =>
        <button key={face.id} type="button" className="ll-v06-chip"
          title={face.display_name ? "Edit person name" : face.suggested_name ? "Suggested match — edit if incorrect" : "Name unfamiliar face"} onClick={() => { setActive(face.id); setValue(face.display_name || face.suggested_name || ""); }}>
          <FaceThumb faceId={face.id} />{face.display_name || face.suggested_name || `Face ${index + 1}`} <span aria-hidden="true">✎</span>
        </button>)}
      {!data.faces?.length && <small>No detected faces</small>}
    </div>
    <div className="ll-v06-annotation-row"><strong>Pets</strong>
      {(data.pets || []).map(pet => <span key={pet.id} className="ll-v06-chip ll-v06-chip-static">
        <button type="button" className="ll-v06-pet-edit" title="Rename pet"
          onClick={() => { setActive(`pet:${pet.id}`); setValue(pet.display_name); }}>{pet.display_name} ✎</button><button type="button" aria-label={`Remove ${pet.display_name}`} onClick={() => void removePet(pet.id)}>×</button>
      </span>)}
      <button type="button" className="ll-v06-chip" onClick={() => { setActive("pet"); setValue(""); }}>+ Name pet</button>
    </div>
    {active !== null && <form className="ll-v06-inline-edit" onSubmit={event => { event.preventDefault(); void submit(); }}>
      <input list={typeof active === "string" && active.startsWith("pet") ? "ll-v065-pet-names" : "ll-v065-person-names"} autoFocus type="text" maxLength={100} aria-label={typeof active === "string" && active.startsWith("pet") ? "Pet's name" : "Person's name"}
        placeholder={typeof active === "string" && active.startsWith("pet") ? "Pet's name" : "Person's name"}
        value={value} onChange={event => setValue(event.target.value)}/>
      <datalist id="ll-v065-person-names">{(knownNames.people || []).map(n => <option key={n.id} value={n.display_name} />)}</datalist>
      <datalist id="ll-v065-pet-names">{(knownNames.pets || []).map(n => <option key={n} value={n} />)}</datalist>
      <button type="submit" className="primary-button" disabled={busy || !value.trim()}>Save</button>
      <button type="button" className="secondary-button" onClick={() => setActive(null)}>Cancel</button>
    </form>}
    {error && <small className="error-message" role="alert">{error}</small>}
    <AiPhotoTagEditor key={photoId} photoId={photoId} />
  </aside>;
}
