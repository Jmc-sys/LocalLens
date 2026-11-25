import KnownFacesLibrary from "./KnownFacesLibrary";
import "./known-faces-library.css";
import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "./api";
import ManualIdentityCounts from "./ManualIdentityCounts";

function FaceCrop({ id }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    const aborter = new AbortController();
    let objectUrl = "";
    fetch(`/api/ai/faces/${id}/crop`, {
      headers: { Authorization: `Bearer ${getToken() || ""}` }, signal: aborter.signal,
    }).then(res => {
      if (!res.ok) throw new Error("Unavailable");
      return res.blob();
    }).then(blob => {
      if (aborter.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setSrc(objectUrl);
    }).catch(() => {});
    return () => { aborter.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id]);
  return src ? <img className="ll-v06-facecrop" src={src} alt="Detected face" /> :
    <span className="ll-v06-facecrop ll-v06-placeholder" aria-label="Face preview loading">Face</span>;
}

export default function AiOperations() {
  const [state, setState] = useState(null);
  const [scan, setScan] = useState(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [pending, setPending] = useState([]);
  const [reviewStats, setReviewStats] = useState(null);
  const [names, setNames] = useState({});
  // A suggestion is the initial editable choice, not a confirmed identity.
  // Preserve the user's edits even when they clear the field.
  const faceDraft = face => Object.prototype.hasOwnProperty.call(names, face.id)
    ? (names[face.id] ?? "") : (face.suggested_name || "");
  const [knownPeople, setKnownPeople] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [status, overall] = await Promise.all([api("/ai/automation/status"), api("/ai/status")]);
      setState(status);
      setScan(overall.scan || null);
      setError("");
    } catch (err) { setError(err.message); }
  }, []);

  useEffect(() => {
    if (!reviewOpen) return;
    let alive = true;
    api("/ai/library-names")
      .then(data => { if (alive) setKnownPeople(data.people || []); })
      .catch(() => {});
    return () => { alive = false; };
  }, [reviewOpen, pending.length]);

  const refreshFaces = useCallback(async () => {
    try { const data=await api("/ai/faces/review-groups?limit=24"); setPending(data.items || []); setReviewStats(data); }
    catch (err) { setError(err.message); }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 6000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => { if (reviewOpen && state?.faces_enabled) void refreshFaces(); }, [reviewOpen, state?.faces_enabled, refreshFaces]);
  // ll-v069-face-queue-poll: refresh only while face review is open.
  useEffect(() => {
    if (!reviewOpen || !state?.faces_enabled) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void refreshFaces();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [reviewOpen, state?.faces_enabled, refreshFaces]);


  async function action(path, method = "POST", body = null, text = "Saved") {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      await refresh();
      if (reviewOpen) await refreshFaces();
      setMessage(typeof result?.queued === "number" ? `${result.queued} photo(s) queued.` : text);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const runState = !state ? "Loading" : !state.auto_enabled ? "Paused" :
    !state.scheduler_online ? "Scheduler not started" :
    state.idle_reason === "uploading" ? "Paused for upload" :
    state.idle_reason === "recent_upload" ? "Finishing upload" :
    state.idle_reason === "high_demand" ? "Waiting for resources" :
    scan && ["starting", "running"].includes(scan.state) ? "Looking through photos" :
    Number(state.remaining) ? "Ready to analyze" : "All photos checked";

  return <section className="ll-v06-panel" aria-label="LocalLens Smart Library faces and photo analysis">
    <div className="ll-v06-head">
      <div>
        <div className="ll-v06-eyebrow">SMART LIBRARY</div>
        <h3>Recognizing faces &amp; analyzing photos <span className="ll-v06-pill">{runState}</span></h3>
        <small>Finds faces and makes photos searchable in the background. Yields only for uploads or high server demand.</small>
      </div>
      <button type="button" className={state?.auto_enabled ? "secondary-button" : "primary-button"}
        disabled={busy || !state} onClick={() => void action("/ai/automation/control", "PUT",
          { auto_enabled: !state.auto_enabled }, state.auto_enabled ? "Photo analysis paused" : "Photo analysis enabled") }>
        {state?.auto_enabled ? "Pause photo analysis" : "Start photo analysis"}
      </button>
    </div>
    {state && <div className="ll-v06-stats" role="status">
      <span><strong>{Number(state.remaining || 0).toLocaleString()}</strong> photos to analyze</span>
      <span><strong>{Number(state.faces_detected || 0).toLocaleString()}</strong> faces found</span>
      <span><strong>{Number(state.auto_named_faces || 0).toLocaleString()}</strong> faces named automatically</span>
      <ManualIdentityCounts />
    </div>}
    {scan && ["starting", "running"].includes(scan.state) && <div>
      <small>Current batch: {scan.batch_processed || 0} / {scan.batch_total || 0}</small>
      <progress value={scan.batch_processed || 0} max={Math.max(scan.batch_total || 1, 1)} />
    </div>}
    {state?.auto_enabled && !state.scheduler_online &&
      <p className="ll-v06-tip">Background photo analysis is enabled, but the processing service is offline. Start it once using <code>bash ai/start-auto.sh</code> on the Ubuntu server.</p>}
    <div className="ll-v06-actions">
      <button type="button" className="secondary-button" disabled={busy || !state?.failed_photos}
        onClick={() => void action("/ai/automation/retry-failed")}>Retry photos</button>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => void refresh()}>Refresh</button>
    </div>

    <div className="ll-v06-review">
      <div className="ll-v06-review-head">
        <div><strong>People & pets</strong>
          <small>{state?.faces_enabled ? reviewStats ? `${reviewStats.people_to_review || 0} unfamiliar people need review` : "Open review to see unfamiliar people" : "Private facial recognition is off"}</small></div>
        <button type="button" className="secondary-button" onClick={() => setReviewOpen(v => !v)}>
          {reviewOpen ? "Close review" : "Review faces"}{reviewStats?.people_to_review > 0 ? ` (${reviewStats.people_to_review})` : ""}
        </button>
      </div>
      {reviewOpen && state && <div className="ll-v06-review-body">
        {!state.faces_enabled ? <div className="ll-v06-empty">
          <p>Turn on private facial recognition to scan the people in your photos.</p>
          <button className="primary-button" type="button" disabled={busy}
            onClick={() => void action("/ai/face-settings", "PUT", { enabled: true }, "Facial recognition enabled. Photos will be queued for detection.")}>Enable facial recognition</button>
        </div> : <>
          <div className="ll-v06-stats">
            <span>{state.photos_face_scanned || 0} photos checked for faces</span>
            <span>{state.faces_detected || 0} faces detected</span>
            <span>Model: {state.face_model?.state || "not tested"}</span>
          </div>
          {state.face_model?.state === "failed" && <p className="error-message">Face detector could not load: {state.face_model?.detail || "Check worker logs"}</p>}

          {!Number(state.faces_detected) && <p className="ll-v06-tip">No faces detected yet. Check that face analysis is enabled, rescan, then inspect the model status and worker logs. Small or side-facing faces can be missed.</p>}
          <datalist id="ll-v065-review-people">
            {knownPeople.map(n => <option key={n.id} value={n.display_name} />)}
          </datalist>
          <div className="ll-v06-facegrid">
            {pending.map(face => <article key={face.id} className="ll-v06-facecard">
              <FaceCrop id={face.id} />
              <div><small>{face.suggested_name ? `Suggested: ${face.suggested_name} · ${face.count} similar face${face.count === 1 ? "" : "s"}` : `${face.count} similar face${face.count === 1 ? "" : "s"} · Who is this?`}</small>
                <input list="ll-v065-review-people" type="text" maxLength={100} value={faceDraft(face)} placeholder="Person's name"
                  aria-label={`Name face ${face.id}`}
                  onChange={event => setNames(v => ({ ...v, [face.id]: event.target.value }))}/>
                <div className="ll-v06-actions">
                  <button className="primary-button" type="button" disabled={busy || !faceDraft(face).trim()}
                    onClick={() => void action(`/ai/faces/review-groups/${face.id}/name`, "POST", { name: faceDraft(face).trim() }, "Name saved")}>Save</button>

                  <button className="secondary-button" type="button" disabled={busy}
                    onClick={() => void action(`/ai/faces/review-groups/${face.id}/unknown`, "POST", null, "Marked unknown")}>Unknown</button>
                </div>
              </div>
            </article>)}
          </div>
          {!pending.length && <small>No unfamiliar face groups need review. You can still correct names in the photo viewer.</small>}
        </>}
      </div>}
    </div>
    <KnownFacesLibrary />
    {message && <p role="status" className="ll-v06-success">{message}</p>}
    {error && <p role="alert" className="error-message">{error}</p>}
  </section>;
}
