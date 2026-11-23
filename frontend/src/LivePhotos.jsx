import { useEffect, useState, useRef } from "react";
import { api, getToken } from "./api";

export function LiveUpload({ onComplete }) {
  const [still, setStill] = useState(null);
  const [motion, setMotion] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const formRef = useRef(null);
  async function submit(e) {
    e.preventDefault();
    if (!still || !motion || busy) return;
    setBusy(true); setMessage("Uploading original still image...");
    try {
      const image = new FormData(); image.append("file", still);
      const result = await api("/photos/upload", { method: "POST", body: image });
      if (!result.id || result.in_trash) throw new Error("Restore the still image from trash first, or upload it again.");
      setMessage("Verifying and attaching original motion file...");
      const video = new FormData(); video.append("file", motion);
      await api(`/live/${result.id}/motion`, { method: "POST", body: video });
      setMessage("Live Photo saved. Both originals retained.");
      setStill(null); setMotion(null); formRef.current?.reset();
    } catch (e) { setMessage(`${e.message}. If the still was uploaded, it remains in your library.`); }
    finally { setBusy(false); onComplete?.(); }
  }
  return <details className="status-card live-upload"><summary>Import Apple Live Photo</summary>
    <form ref={formRef} onSubmit={submit}>
      <p>Select the two unmodified Apple originals. Their embedded content identifiers must match.</p>
      <label>Still image <input type="file" accept=".heic,.heif,.jpg,.jpeg" required disabled={busy} onChange={e=>setStill(e.target.files[0])}/></label>
      <label>Motion original <input type="file" accept=".mov,video/quicktime" required disabled={busy} onChange={e=>setMotion(e.target.files[0])}/></label>
      <button className="primary-button" disabled={busy || !still || !motion}>{busy ? "Importing…" : "Import Live Photo"}</button>
      <p role="status">{message}</p>
    </form></details>;
}

async function liveBlob(id, type, signal) {
  const response = await fetch(`/api/live/${id}/${type}`, {headers:{Authorization:`Bearer ${getToken()}`},signal});
  if (!response.ok) {
    const data = await response.json().catch(()=>({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  }
  return response.blob();
}

export function LiveViewer({ photo, children }) {
  const [playing,setPlaying] = useState(false);
  const [url,setUrl] = useState("");
  const [error,setError] = useState("");
  useEffect(()=>{
    if (!playing) return;
    const controller=new AbortController(); let objectUrl;
    setError(""); setUrl("");
    liveBlob(photo.id,"preview",controller.signal).then(blob=>{
      if(controller.signal.aborted) return;
      objectUrl=URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(e=>{if(!controller.signal.aborted) setError(e.message);});
    return ()=>{controller.abort(); if(objectUrl) URL.revokeObjectURL(objectUrl);};
  },[playing,photo.id]);
  async function downloadOriginals(){
    try {
      const blob=await liveBlob(photo.id,"originals");
      const link=document.createElement("a"); link.href=URL.createObjectURL(blob);
      link.download=`LivePhoto-${photo.id}.zip`; link.click();
      setTimeout(()=>URL.revokeObjectURL(link.href),1000);
    } catch(e){setError(e.message);}
  }
  return <div className="live-viewer">
    <div className="live-controls">
      <button className="secondary-button" onClick={()=>setPlaying(p=>!p)}>{playing?"Show still":"▶ Play Live Photo"}</button>
      <button className="secondary-button" onClick={downloadOriginals}>Download both originals</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {playing ? (url ? <video src={url} controls autoPlay playsInline onError={()=>setError("Browser could not play preview.")}/> : <p>{error?"Preview unavailable":"Preparing motion preview…"}</p>) : children}
  </div>;
}
