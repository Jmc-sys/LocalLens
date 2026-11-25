import { useEffect, useMemo, useRef, useState } from "react";
import { api, getToken } from "./api";
import ViewerNavigation from "./ViewerNavigation";

// Shared media is never fetched via owner-only /photos routes.
// The backend authenticates each request and enforces membership and ownership.
export function AuthorizedImage({ url, alt, eager = false }) {
  const visibilityAnchor = useRef(null);
  const [visible, setVisible] = useState(eager);
  const [src, setSrc] = useState("");
  useEffect(() => {
    setVisible(eager);
    if (eager) return;
    if (typeof IntersectionObserver === "undefined") { setVisible(true); return; }
    const anchor = visibilityAnchor.current;
    if (!anchor) { setVisible(true); return; }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some(entry => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "300px" });
    observer.observe(anchor);
    return () => observer.disconnect();
  }, [url, eager]);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    let objectUrl = null;
    setSrc("");
    (async () => {
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${getToken() || ""}` },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Image unavailable (${response.status})`);
        const blob = await response.blob();
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setSrc(objectUrl);
        }
      } catch (error) {
        if (!controller.signal.aborted) console.warn("Shared image unavailable", error);
      }
    })();
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url, visible]);
  return src ? <img src={src} alt={alt} loading="lazy" decoding="async" />
    : <span ref={visibilityAnchor} className="image-placeholder" aria-label="Loading shared image">Loading preview…</span>;
}

function browserDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noreferrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

const PAGE_SIZE = 100;

export default function SharedAlbums({ embedded = false, onOpenChange, openedAlbumId = null, onBack }) {
  const [me, setMe] = useState(null);
  const [albums, setAlbums] = useState([]);
  const [albumId, setAlbumId] = useState(openedAlbumId);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState([]);
  const [viewer, setViewer] = useState(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [motionUrl, setMotionUrl] = useState("");
  const [motionReady, setMotionReady] = useState(false);
  const [motionLoading, setMotionLoading] = useState(false);
  const [motionPlaybackError, setMotionPlaybackError] = useState("");
  const motionRequest = useRef(0);

  function clearMotionPlayback() {
    motionRequest.current += 1; // Invalidate a pending signed-URL response.
    setMotionUrl("");
    setMotionReady(false);
    setMotionLoading(false);
    setMotionPlaybackError("");
  }
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);

  useEffect(() => { onOpenChange?.(!!albumId); }, [albumId, onOpenChange]);
  useEffect(() => {
    let cancelled = false;
    Promise.all([api("/auth/me"), openedAlbumId != null ? Promise.resolve([]) : api("/shared-albums")])
      .then(([identity, list]) => { if (!cancelled) { setMe(identity); setAlbums(list); } })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!albumId) { setDetail(null); setViewer(null); setSelected([]); clearMotionPlayback(); return; }
    let cancelled = false;
    setLoadingDetail(true);
    setError(""); setNotice(""); setSelected([]); setViewer(null); clearMotionPlayback(); setDetail(null);
    api(`/shared-albums/${albumId}?limit=${PAGE_SIZE}&offset=0`)
      .then(data => { if (!cancelled) { setDetail(data); setOffset(0); } })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoadingDetail(false); });
    return () => { cancelled = true; };
  }, [albumId]);

  useEffect(() => {
    const handler = (event) => {
      if (event.key === "Escape") closeSharedViewer();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const items = detail?.items || [];
  const ownItems = useMemo(() => items.filter(item => Number(item.user_id) === Number(me?.id)), [items, me?.id]);
  const ownSelected = useMemo(() => selected.filter(id => ownItems.some(item => item.id === id)), [selected, ownItems]);

  async function refresh(offsetToLoad = 0, append = false) {
    const data = await api(`/shared-albums/${albumId}?limit=${PAGE_SIZE}&offset=${offsetToLoad}`);
    setDetail(previous => append && previous?.album?.id === data.album.id
      ? { ...data, items: [...previous.items, ...data.items] }
      : data);
    setOffset(offsetToLoad);
  }

  async function removeSelected() {
    if (!ownSelected.length || busy) return;
    if (!window.confirm(`Remove ${ownSelected.length} of your items from this album? The original files will be kept. This cannot remove other users' items.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      for (let start = 0; start < ownSelected.length; start += 100) {
        await api(`/shared-albums/${albumId}/items/remove-owned`, {
          method: "POST", body: JSON.stringify({ ids: ownSelected.slice(start, start + 100) }),
        });
      }
      setSelected([]);
      await refresh(0);
      setNotice(`${ownSelected.length} items removed from this album. Your originals were kept.`);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  function toggleSelected(id) {
    setSelected(before => before.includes(id) ? before.filter(n => n !== id) : [...before, id]);
  }

  async function downloadMedia(item) {
    try {
      setError("");
      const result = await api(`/shared-albums/${albumId}/media/${item.id}/bundle-access-url`, { method: "POST" });
      if (!result?.url) throw new Error("Original media is unavailable.");
      browserDownload(result.url);
    } catch (e) { setError(e.message); }
  }

  const sharedVideoRef = useRef(null);
  const viewerRequest = useRef(0);
  const pagingRef = useRef(false);
  function closeSharedViewer() {
    // Stop video playback and invalidate an in-flight signed URL request.
    try { sharedVideoRef.current?.pause(); } catch { /* Already stopped. */ }
    clearMotionPlayback();
    viewerRequest.current += 1;
    setVideoUrl("");
    setViewer(null);
  }

  useEffect(() => {
    if (!viewer) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [viewer]);

  async function playLiveMotion(item) {
    if (!item.has_live_motion || item.media_type === "video") return;
    const requestId = ++motionRequest.current;
    setMotionLoading(true);
    setMotionUrl("");
    setMotionPlaybackError("");
    try {
      const result = await api(`/shared-albums/${albumId}/media/${item.id}/motion-play-url`, {
        method: "POST",
      });
      if (!result?.url) throw new Error("The motion video could not be opened.");
      if (motionRequest.current === requestId) setMotionUrl(result.url);
    } catch (e) {
      if (motionRequest.current === requestId) setMotionPlaybackError(e.message);
    } finally {
      if (motionRequest.current === requestId) setMotionLoading(false);
    }
  }

  async function openViewer(item) {
    const requestId = ++viewerRequest.current;
    try { sharedVideoRef.current?.pause(); } catch { /* Already stopped. */ }
    setViewer(item);
    setVideoUrl(""); clearMotionPlayback(); setError("");
    if (item.has_live_motion && item.media_type !== "video") {
      void playLiveMotion(item);
    }
    if (item.media_type === "video") {
      try {
        const result = await api(`/shared-albums/${albumId}/media/${item.id}/access-url`, { method: "POST" });
        if (viewerRequest.current === requestId) setVideoUrl(result.url);
      } catch (e) { if (viewerRequest.current === requestId) setError(e.message); }
    }
  }

  async function nextSharedPage() {
    if (!detail?.has_more || busy || pagingRef.current) return;
    pagingRef.current = true;
    try {
      const nextOffset = offset + PAGE_SIZE;
      const next = await api(`/shared-albums/${albumId}?limit=${PAGE_SIZE}&offset=${nextOffset}`);
      if (!next.items?.length) return;
      setDetail(previous => previous?.album?.id === next.album.id
        ? { ...next, items: [...previous.items, ...next.items] }
        : next);
      setOffset(nextOffset);
      void openViewer(next.items[0]);
    } catch (e) { setError(e.message); }
    finally { pagingRef.current = false; }
  }

  if (loading) return <section className="shared-albums-page"><p>Loading family albums…</p></section>;

  return <section className="shared-albums-page photo-library">
    <div className="library-heading shared-albums-heading">
      <h2>{albumId && detail ? detail.album.name : embedded ? "Family albums" : "Shared albums"}</h2>
      {albumId && <button type="button" className="secondary-button" onClick={() => onBack ? onBack() : setAlbumId(null)}>Back to albums</button>}
    </div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {notice && <p className="shared-albums-notice" role="status">{notice}</p>}

    {!albumId ? <div className="album-grid">
      {albums.map(album => <article className="album-card" key={album.id}>
        <button type="button" className="album-cover shared-family-card" onClick={() => setAlbumId(album.id)}>
          <span aria-hidden="true">▧</span>
          <strong>{album.name}</strong>
        </button>
        <h3>{album.name}</h3>
        <p>{Number(album.item_count || 0).toLocaleString()} items · Shared</p>
      </article>)}
      {!albums.length && <p>No family albums are available for your account.</p>}
    </div> : loadingDetail ? <p>Loading album…</p> : detail ? <>
      <div className="library-toolbar">
        <span>{items.length.toLocaleString()} items loaded</span>
        <button type="button" className="secondary-button" disabled={!ownItems.length || busy}
          onClick={() => setSelected(ownItems.map(item => item.id))}>Select my items</button>
      </div>
      {selected.length > 0 && <div className="library-toolbar selection-bar">
        <strong>{ownSelected.length} of your items selected</strong>
        <button type="button" className="secondary-button" disabled={busy || !ownSelected.length}
          onClick={removeSelected}>Remove selected from album</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => setSelected([])}>Clear</button>
      </div>}
      <div className="photo-grid shared-photo-grid">
        {items.map(item => <article className={`photo-card ${selected.includes(item.id) ? "selected" : ""}`} key={item.id}>
          <button type="button" className="photo-preview" onClick={() => openViewer(item)}
            aria-label={`Open ${item.original_filename} full screen`}>
            <AuthorizedImage url={`/api/shared-albums/${albumId}/media/${item.id}/thumbnail`}
              alt={item.original_filename} />
            {item.media_type === "video" && <span className="shared-video-badge">▶ Video</span>}
            {!!item.has_live_motion && <span className="shared-video-badge">Live</span>}
          </button>
          {Number(item.user_id) === Number(me?.id) && <input type="checkbox" className="photo-checkbox"
            aria-label={`Select ${item.original_filename} to remove from shared album`}
            checked={selected.includes(item.id)} onChange={() => toggleSelected(item.id)} />}
          <div className="photo-name" title={item.original_filename}>{item.original_filename}</div>
          <small className="shared-owner">Shared by {item.owner_username}</small>
        </article>)}
        {!items.length && <p>No photos or videos have been shared yet.</p>}
      </div>
      {detail.has_more && <button type="button" className="secondary-button"
        onClick={async () => { setError(""); try { await refresh(offset + PAGE_SIZE, true); } catch (e) { setError(e.message); } }}>
        Load more
      </button>}
    </> : null}

    {viewer && <div className="photo-viewer shared-fullscreen-viewer" role="dialog" aria-modal="true"
      aria-label={viewer.original_filename}>
      <ViewerNavigation items={items} currentId={viewer.id} onNavigate={openViewer}
        onAfterLast={detail?.has_more ? nextSharedPage : null}/>
      <button type="button" className="shared-viewer-dismiss" onClick={closeSharedViewer}
        aria-label="Close full-screen viewer">Close ×</button>
      <header>
        <span>{viewer.original_filename}</span>
        <button type="button" className="secondary-button" onClick={() => downloadMedia(viewer)}>Download</button>
        {!!viewer.has_live_motion && viewer.media_type !== "video" &&
          <button type="button" className="secondary-button"
            onClick={() => motionUrl || motionLoading ? clearMotionPlayback() : playLiveMotion(viewer)}>
            {motionUrl || motionLoading ? "Show photo only" : "▶ Play Live Photo"}
          </button>}

        <button type="button" className="secondary-button" onClick={closeSharedViewer}>Close ×</button>
      </header>
      {viewer.media_type === "video"
        ? videoUrl
          ? <video ref={sharedVideoRef} key={viewer.id} src={videoUrl} controls playsInline preload="metadata" />
          : <p>Preparing video…</p>
        : <div className="ll-shared-live-stage">
            <div className="ll-shared-live-still">
              <AuthorizedImage eager url={`/api/shared-albums/${albumId}/media/${viewer.id}/preview`}
                alt={viewer.original_filename} />
            </div>
            {!!viewer.has_live_motion && motionUrl && <video ref={sharedVideoRef}
              key={`${viewer.id}-${motionUrl}`} src={motionUrl}
              className={motionReady ? "ll-shared-live-motion ll-live-ready" : "ll-shared-live-motion"}
              autoPlay muted loop playsInline preload="auto"
              onCanPlay={() => setMotionReady(true)}
              onError={() => { setMotionReady(false); setMotionPlaybackError(
                "This motion video's codec cannot play in this browser. You can still download the MOV."); }} />}
          </div>}
      {motionPlaybackError && <p className="error-message" role="alert">{motionPlaybackError}</p>}
    </div>}
  </section>;
}
