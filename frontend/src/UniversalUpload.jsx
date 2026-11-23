import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import PrivateImage from "./PrivateImage";

const IMAGE_EXT = /\.(jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i;
const MOV_EXT = /\.mov$/i;
const VIDEO_EXT = /\.(mp4|m4v|mov|mkv|webm)$/i;
const stem = (name) => name.replace(/\.[^.]+$/, "").toLocaleLowerCase();
const directory = (file) => (file.webkitRelativePath || "").split("/").slice(0, -1).join("/").toLocaleLowerCase();
const group = (file) => `${directory(file)}\0${stem(file.name)}`;

async function withWorkers(items, concurrency, worker) {
  let index = 0;
  await Promise.all(Array.from({ length: Math.min(items.length, concurrency) }, async () => {
    while (index < items.length) await worker(items[index++]);
  }));
}

function suggestedName(name) {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? `${name.slice(0, dot)} (copy)${name.slice(dot)}` : `${name} (copy)`;
}

function etaWeight(file) {
  // A small per-file overhead prevents many tiny files from skewing estimates.
  return Math.max(1, Number(file.size) || 0) + 2 * 1024 * 1024;
}
function etaFormat(seconds) {
  const n = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`
    : m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}
export default function UniversalUpload({ onComplete }) {
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const importing = useRef(false);
  const decisionQueue = useRef([]);
  const activeDecision = useRef(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [current, setCurrent] = useState("");
  const [progress, setProgress] = useState(0);
  const [etaSeconds, setEtaSeconds] = useState(null);
  const uploadEtaState = useRef(null);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => {
      const state = uploadEtaState.current;
      if (!state) return;
      const now = performance.now();
      if (activeDecision.current) {
        if (state.pauseStarted === null) state.pauseStarted = now;
        return;
      }
      if (state.pauseStarted !== null) {
        state.pausedMs += now - state.pauseStarted;
        state.pauseStarted = null;
      }
      const seconds = Math.max(1, (now - state.start - state.pausedMs) / 1000);
      if (state.completedCount < 2 || state.workDone <= 0) {
        setEtaSeconds(null);
        return;
      }
      const raw = seconds * Math.max(0, state.totalWork - state.workDone) / state.workDone;
      // Smooth jitter, but allow the estimate to move as real work finishes.
      state.smoothed = state.smoothed === null ? raw : state.smoothed * 0.7 + raw * 0.3;
      setEtaSeconds(Math.max(0, Math.ceil(state.smoothed)));
    }, 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const [report, setReport] = useState(null);
  const [duplicate, setDuplicate] = useState(null);
  const [newName, setNewName] = useState("");
  const [incomingUrl, setIncomingUrl] = useState("");

  useEffect(() => {
    if (!duplicate?.file) return;
    const url = URL.createObjectURL(duplicate.file);
    setIncomingUrl(url);
    return () => { URL.revokeObjectURL(url); setIncomingUrl(""); };
  }, [duplicate]);

  function activateNextDuplicate() {
    if (activeDecision.current || !decisionQueue.current.length) return;
    const next = decisionQueue.current.shift();
    activeDecision.current = next;
    setNewName(suggestedName(next.file.name));
    setDuplicate(next);
  }

  function requestDuplicateReview(file, existing, inTrash) {
    return new Promise((resolve) => {
      decisionQueue.current.push({ file, existing, inTrash, resolve });
      activateNextDuplicate();
    });
  }

  function resolveDuplicate(keep) {
    const active = activeDecision.current;
    if (!active) return;
    const name = newName.trim();
    if (keep && (!name || name.toLowerCase() === active.file.name.toLowerCase())) return;
    activeDecision.current = null;
    setDuplicate(null);
    active.resolve(keep ? { keep: true, name } : { keep: false });
    // Continue queued duplicate reviews when there are several at once.
    queueMicrotask(activateNextDuplicate);
  }

  async function send(file, route, keepName) {
    const body = new FormData();
    body.append("file", file, file.name);
    if (keepName) {
      body.append("on_duplicate", "keep");
      body.append("new_name", keepName);
    }
    return api(route, { method: "POST", body });
  }

  async function uploadFiles(chosen) {
    const files = [...(chosen || [])].filter((item) => item && item.size > 0);
    if (!files.length || importing.current) return;
    importing.current = true;
    const images = files.filter((f) => IMAGE_EXT.test(f.name));
    const selectedImageGroups = new Set(images.map(group));
    const movs = files.filter((f) => MOV_EXT.test(f.name));
    const videos = files.filter((f) => VIDEO_EXT.test(f.name) && !MOV_EXT.test(f.name));
    const unsupported = files.filter((f) => !IMAGE_EXT.test(f.name) && !VIDEO_EXT.test(f.name));
    const total = images.length + videos.length + movs.length;
    uploadEtaState.current = {
      start: performance.now(), pausedMs: 0, pauseStarted: null,
      totalWork: [...images, ...videos, ...movs].reduce((sum, f) => sum + etaWeight(f), 0),
      workDone: 0, completedCount: 0, smoothed: null,
    };
    setEtaSeconds(null);
    const candidatesByGroup = new Map();
    const photoIds = new Set();
    const warnings = [];
    let nameConflictsSkipped = 0;
    const failures = [];
    let completed = 0;
    let savedPhotos = 0, savedVideos = 0, paired = 0, duplicateSkipped = 0, renamedUploads = 0;
    setBusy(true); setReport(null); setProgress(0);

    function advance(file) {
      completed++;
      const state = uploadEtaState.current;
      if (state) {
        state.completedCount++;
        state.workDone += etaWeight(file);
      }
      setCurrent(`${completed} / ${total} files processed · ${file.name}`);
      setProgress(Math.round(100 * completed / Math.max(total, 1)));
    }

    async function uploadWithReview(file, route) {
      let response = await send(file, route);
      // SHA256-identical originals always skip: no dialog and no extra processing.
      if (response.status === "duplicate") {
        duplicateSkipped++;
        return { ...response, status: "skipped_duplicate" };
      }
      // Only the same filename with DIFFERENT original bytes requires a choice.
      if (response.status === "name_conflict") {
        const decision = await requestDuplicateReview(file, response.existing, response.in_trash);
        if (!decision.keep) {
          nameConflictsSkipped++;
          return { status: "skipped_name_conflict" };
        }
        response = await send(file, route, decision.name);
        if (response.status === "uploaded") renamedUploads++;
        else if (response.status === "duplicate") {
          duplicateSkipped++;
          return { ...response, status: "skipped_duplicate" };
        }
      }
      return response;
    }

    try {
      // Stills must exist before their MOV companion can be paired.
      await withWorkers(images, 3, async (image) => {
        try {
          const result = await uploadWithReview(image, "/photos/upload");
          if (result.status === "uploaded") savedPhotos++;
          if (result.in_trash) warnings.push(`${image.name}: the existing copy is in Trash.`);
          if (result.id && !result.in_trash && ["uploaded", "skipped_duplicate"].includes(result.status)) {
            const key = group(image);
            candidatesByGroup.set(key, [...(candidatesByGroup.get(key) || []), result.id]);
            photoIds.add(result.id);
          }
        } catch (error) {
          failures.push(`${image.name}: ${error.message}`);
        } finally {
          advance(image);
        }
      });

      // Inspect only newly selected stills. The backend caches metadata checks.
      const ids = [...photoIds];
      for (let start = 0; start < ids.length; start += 200) {
        try {
          await api("/media/inspect", {
            method: "POST", body: JSON.stringify({ photo_ids: ids.slice(start, start + 200) }),
          });
        } catch (error) { warnings.push(`Motion metadata: ${error.message}`); }
      }

      // A MOV paired to a still is a companion resource, not an independent video.
      // Unmatched MOVs are imported as regular user videos.
      // One browser transfer per MOV: the API pairs it OR saves it as a video.
      await withWorkers(movs, 2, async (mov) => {
        const candidates = [...new Set(candidatesByGroup.get(group(mov)) || [])];
        const sameNamedStillSelected = selectedImageGroups.has(group(mov));
        try {
          const form = new FormData();
          form.append("file", mov, mov.name);
          form.append("candidate_photo_ids", JSON.stringify(candidates));
          form.append("allow_standalone", sameNamedStillSelected ? "false" : "true");
          const motion = await api("/media/auto-motion", { method: "POST", body: form });
          if (motion.status === "attached") {
            paired++;
            if (motion.match_method === "filename")
              warnings.push(`${mov.name}: paired by filename only; verify the result.`);
          } else if (motion.status === "duplicate") {
            duplicateSkipped++;
          } else if (motion.status === "uploaded") {
            savedVideos++;
          } else if (motion.status === "name_conflict") {
            // Only this rare, user-approved rename requires another upload.
            const decision = await requestDuplicateReview(mov, motion.existing, motion.in_trash);
            if (!decision.keep) {
              nameConflictsSkipped++;
            } else {
              const retry = await send(mov, "/videos/upload", decision.name);
              if (retry.status === "uploaded") { savedVideos++; renamedUploads++; }
              else if (retry.status === "duplicate") duplicateSkipped++;
              else throw new Error(`Unexpected rename result: ${String(retry.status)}`);
            }
          } else if (motion.status === "unmatched") {
            // The video was NOT saved: don't falsely mark an incomplete
            // motion-photo resource as a complete independent video.
            failures.push(`${mov.name}: motion resource not attached or saved (${motion.reason || "unmatched"}). Retry with the matching original photo.`);
          } else {
            throw new Error(`Unexpected motion classification: ${String(motion.status)}`);
          }
        } catch (error) {
          failures.push(`${mov.name}: ${error.message}. File was not confirmed saved.`);
        } finally {
          advance(mov);
        }
      });

      await withWorkers(videos, 2, async (video) => {
        try {
          const result = await uploadWithReview(video, "/videos/upload");
          if (result.status === "uploaded") savedVideos++;
        } catch (error) {
          failures.push(`${video.name}: ${error.message}`);
        } finally { advance(video); }
      });

      let metadataMotionWarnings = 0;
      for (let start = 0; start < ids.length; start += 200) {
        try {
          const data = await api("/media/inspect", {
            method: "POST", body: JSON.stringify({ photo_ids: ids.slice(start, start + 200) }),
          });
          for (const item of data.items || []) {
            if (item.possible_motion_missing) {
              metadataMotionWarnings++;
              warnings.push(`Photo ${item.id}: Live Photo metadata found, but the motion video was not received. The still is preserved; the backup is incomplete.`);
            }
          }
        } catch (error) { warnings.push(`Motion verification: ${error.message}`); }
      }
      if (images.length && !movs.length && metadataMotionWarnings === 0 &&
          /iPhone|iPad|iPod/i.test(navigator.userAgent)) {
        warnings.push("This browser supplied only still images. Motion resources could not be verified. To preserve complete motion photos, export unmodified originals to Files and select the image and MOV together.");
      }
      setReport({ savedPhotos, savedVideos, paired, duplicateSkipped, renamedUploads, nameConflictsSkipped,
                  unsupported: unsupported.map((file) => file.webkitRelativePath || file.name),
                  warnings, failures });
      onComplete?.();
    } catch (error) {
      failures.push(error.message);
      setReport({ savedPhotos, savedVideos, paired, duplicateSkipped, renamedUploads, nameConflictsSkipped,
                  unsupported: unsupported.map((file) => file.webkitRelativePath || file.name),
                  warnings, failures });
    } finally {
      importing.current = false;
      setBusy(false);
      setCurrent("");
      if (fileInput.current) fileInput.current.value = "";
      if (folderInput.current) folderInput.current.value = "";
    }
  }

  return (
    <section className="status-card universal-upload" aria-label="Media uploader">
      <div className={`universal-dropzone ${dragging ? "is-dragging" : ""}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={(event) => { event.preventDefault(); if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
        onDrop={(event) => { event.preventDefault(); setDragging(false); uploadFiles(event.dataTransfer.files); }}>
        <div className="universal-upload-icon" aria-hidden="true">↑</div>
        <strong>Import photos and videos</strong>
        <p>Select original media from your device. Matching still images and motion clips are combined automatically.</p>
        <div className="universal-upload-actions">
          <button type="button" className="primary-button" disabled={busy}
            onClick={() => fileInput.current?.click()}>Upload file</button>
          <button type="button" className="secondary-button" disabled={busy}
            onClick={() => folderInput.current?.click()}>Upload folder</button>
        </div>
        <input ref={fileInput} className="universal-hidden-input" type="file" multiple disabled={busy}
          accept="image/*,video/*,.heic,.heif,.mov,.mp4,.m4v,.webm,.mkv" aria-label="Choose photos and videos"
          onChange={(event) => uploadFiles(event.target.files)} />
        <input ref={folderInput} className="universal-hidden-input" type="file" multiple
          webkitdirectory="" directory="" disabled={busy} aria-label="Choose a media folder"
          onChange={(event) => uploadFiles(event.target.files)} />
        <small>Originals preserved · Automatic pairing · Photos and videos in one library</small>
      </div>
      {busy && <div className="universal-progress" role="status" aria-live="polite">
        <div className="universal-progress-head"><span>{current || "Importing..."}</span><span>{progress}%</span></div>
        <progress max="100" value={progress} aria-label="Files processed" />
        <div className="universal-upload-eta" aria-live="off">
          Estimated time remaining: {etaSeconds === null ? "Calculating…" : etaFormat(etaSeconds)}
        </div>
      </div>}
      {report && <div className="universal-upload-report" role="status">
        <div className="universal-upload-report-header">
          <strong>Import finished</strong>
          <button type="button" className="secondary-button" onClick={() => setReport(null)}>Got it</button>
        </div>
        <p>{report.savedPhotos} photos · {report.savedVideos} videos · {report.paired} motion pairs · {report.duplicateSkipped} duplicates skipped · {report.renamedUploads} renamed on import · {report.nameConflictsSkipped} filename conflicts skipped</p>
        {!!report.unsupported.length && <div className="upload-warning">
          <strong>Unsupported files ({report.unsupported.length})</strong>
          <ul>{report.unsupported.map((name, index) => <li key={`${name}-${index}`}>{name}</li>)}</ul>
        </div>}
        {report.warnings.map((message, index) => <p key={`w${index}`} className="upload-warning">{message}</p>)}
        {report.failures.map((message, index) => <p key={`e${index}`} className="error-message">{message}</p>)}
      </div>}
      {duplicate && <div className="media-duplicate-overlay" role="presentation">
        <div className="media-duplicate-dialog" role="dialog" aria-modal="true" aria-labelledby="duplicate-title">
          <h3 id="duplicate-title">Same filename, different media</h3>
          <p>Another file already uses this name, but its contents are different. Review both versions, then skip the new file or save it with a different name.</p>
          {duplicate.inTrash && <p className="upload-warning">The existing file is in Trash. It will remain there unless you restore it.</p>}
          <div className="media-duplicate-comparison">
            <div><strong>Existing</strong>
              <div className="media-duplicate-preview"><PrivateImage id={duplicate.existing.id} alt="Existing media" /></div>
              <small>{duplicate.existing.original_filename}</small>
            </div>
            <div><strong>Incoming</strong>
              <div className="media-duplicate-preview">
                {VIDEO_EXT.test(duplicate.file.name)
                  ? <video src={incomingUrl} controls preload="metadata" playsInline />
                  : /\.(heic|heif|tiff?)$/i.test(duplicate.file.name)
                    ? <div className="incoming-preview-note"><img src={incomingUrl} alt="Incoming media" onError={(event) => { event.currentTarget.style.display = "none"; }} /><small>HEIC preview depends on your browser. This is a different original file.</small></div>
                    : <img src={incomingUrl} alt="Incoming media" />}
              </div>
              <small>{duplicate.file.name}</small>
            </div>
          </div>
          <label className="duplicate-name-label">Name for new file
            <input value={newName} maxLength={245} onChange={(event) => setNewName(event.target.value)} />
          </label>
          <div className="media-duplicate-buttons">
            <button type="button" className="secondary-button" onClick={() => resolveDuplicate(false)}>Skip incoming file</button>
            <button type="button" className="primary-button"
              disabled={!newName.trim() || newName.trim().toLowerCase() === duplicate.file.name.toLowerCase()}
              onClick={() => resolveDuplicate(true)}>Keep new file and rename</button>
          </div>
          <small>The existing file is never overwritten. The renamed file counts toward your storage quota.</small>
        </div>
      </div>}
    </section>
  );
}
