import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import PrivateImage from "./PrivateImage";

// Animal candidates are suggestions from photo-level semantic indexing, not
// individual pet detection or visual identity recognition.
export default function AiPetReview() {
  const [items, setItems] = useState([]);
  const [nameByPhoto, setNameByPhoto] = useState({});
  const [error, setError] = useState("");
  const [knownPets, setKnownPets] = useState([]);
  const [busy, setBusy] = useState(null);
  const refresh = useCallback(async () => {
    try { const data = await api("/ai/automation/pet-candidates?limit=60"); setItems(data.items || []); setError(""); }
    catch (err) { setError(err.message); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    let alive=true;
    api("/ai/library-names").then(data => { if (alive) setKnownPets(data.pets || []); }).catch(() => {});
    return () => { alive=false; };
  }, [items.length]);
  async function save(photoId) {
    const name = (nameByPhoto[photoId] || "").trim();
    if (!name) return;
    setBusy(photoId);
    try {
      await api(`/ai/photo/${photoId}/pets`, { method: "POST", body: JSON.stringify({ name }) });
      setNameByPhoto(v => ({ ...v, [photoId]: "" }));
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(null); }
  }
  return <div className="ll-v061-pets">
    <div className="ll-v061-pets-head"><strong>Animals to name</strong>
      <button className="secondary-button" type="button" onClick={() => void refresh()}>Refresh animals</button></div>
    <small>Suggested animal photos, not confirmed pet identities. Name the pet shown in each photo. You can also name pets directly in the photo viewer.</small>
    {items.length ? <div className="ll-v061-petgrid">{items.map(item =>
      <article className="ll-v061-petcard" key={item.photo_id}>
        <div className="ll-v061-petphoto"><PrivateImage id={item.photo_id} alt={`Possible ${item.animal}`} /></div>
        <small>Possible {item.animal}</small>
        <form onSubmit={e => { e.preventDefault(); void save(item.photo_id); }}>
          <datalist id="ll-v065-pet-review-names">
            {knownPets.map(name => <option key={name} value={name} />)}
          </datalist>
          <input list="ll-v065-pet-review-names" aria-label={`Name animal in photo ${item.photo_id}`} placeholder="Pet's name"
            value={nameByPhoto[item.photo_id] || ""} maxLength={100}
            onChange={e => setNameByPhoto(v => ({ ...v, [item.photo_id]: e.target.value }))}/>
          <button className="primary-button" type="submit" disabled={busy !== null || !nameByPhoto[item.photo_id]?.trim()}>Save</button>
        </form>
      </article>)}</div> : <p className="ll-v06-tip">No unnamed animal candidates yet. As indexing progresses, photos tagged as cats, dogs, birds, horses or fish will appear here. You can name any pet manually in the viewer.</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </div>;
}
