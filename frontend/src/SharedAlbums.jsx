import { useEffect, useState } from "react";
import { api, getToken } from "./api";

function ProtectedThumbnail({ url, label }) {
  const [blobUrl, setBlobUrl] = useState("");
  useEffect(() => {
    const ctrl = new AbortController();
    let objectUrl = null;
    setBlobUrl("");
    (async () => {
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${getToken() || ""}` }, signal: ctrl.signal,
        });
        if (!response.ok) return;
        const blob = await response.blob();
        if (ctrl.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch (error) { if (!ctrl.signal.aborted) console.warn("Thumbnail unavailable", error); }
    })();
    return () => { ctrl.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url]);
  return blobUrl ? <img src={blobUrl} alt={label || "Media thumbnail"} loading="lazy" />
    : <span className="shared-thumbnail-placeholder" aria-hidden="true">▧</span>;
}

function openProtectedDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noreferrer";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export default function SharedAlbums() {
  const [me, setMe] = useState(null);
  const [albums, setAlbums] = useState([]);
  const [albumId, setAlbumId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [users, setUsers] = useState([]);
  const [albumName, setAlbumName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [ownerId, setOwnerId] = useState("");
  const [search, setSearch] = useState("");
  const [candidatePage, setCandidatePage] = useState(0);
  const [candidates, setCandidates] = useState([]);
  const [chosen, setChosen] = useState(new Set());
  const [candidateMore, setCandidateMore] = useState(false);
  const [itemsOffset, setItemsOffset] = useState(0);
  const [viewer, setViewer] = useState(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [isWorking, setIsWorking] = useState(false);
  const isAdmin = me?.role === "admin";

  async function refreshAlbums() { setAlbums(await api("/shared-albums")); }
  async function refreshDetail(id, offset = 0, append = false) {
    const data = await api(`/shared-albums/${id}?limit=100&offset=${offset}`);
    setDetail(old => append && old && old.album.id === id
      ? { ...data, items: [...old.items, ...data.items] }
      : data);
    setItemsOffset(offset);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const identity = await api("/auth/me");
        const [listed, directory] = await Promise.all([
          api("/shared-albums"),
          identity.role === "admin" ? api("/shared-albums/users") : Promise.resolve([]),
        ]);
        if (cancelled) return;
        setMe(identity); setAlbums(listed); setUsers(directory);
      } catch (e) { if (!cancelled) setError(e.message); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!albumId) { setDetail(null); return; }
    let cancelled = false;
    setDetail(null); setViewer(null);
    api(`/shared-albums/${albumId}?limit=100&offset=0`)
      .then(data => { if (!cancelled) { setDetail(data); setItemsOffset(0); } })
      .catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [albumId]);

  useEffect(() => {
    if (!isAdmin || !ownerId || !albumId) { setCandidates([]); setCandidateMore(false); return; }
    let cancelled = false;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ owner_id: ownerId, search, offset: String(candidatePage * 100), limit: "100" });
      api(`/shared-albums/owner-media?${params}`)
        .then(data => { if (!cancelled) { setCandidates(data); setCandidateMore(data.length === 100); } })
        .catch(e => { if (!cancelled) setError(e.message); });
    }, 150);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [albumId, isAdmin, ownerId, candidatePage, search]);

  async function perform(operation, message = "") {
    setError(""); setNotice(""); setIsWorking(true);
    try { await operation(); if (message) setNotice(message); }
    catch (e) { setError(e.message); }
    finally { setIsWorking(false); }
  }

  async function createAlbum(event) {
    event.preventDefault();
    const name = albumName.trim();
    if (!name) return;
    await perform(async () => {
      const result = await api("/shared-albums", {
        method: "POST", body: JSON.stringify({ name }),
      });
      setAlbumName("");
      await refreshAlbums();
      setAlbumId(result.id);
    }, "Shared album created. Add members and select media from the owners' libraries.");
  }

  async function setMembership(userId, isMember) {
    if (!albumId) return;
    await perform(async () => {
      if (isMember) await api(`/shared-albums/${albumId}/members/${userId}`, { method: "DELETE" });
      else await api(`/shared-albums/${albumId}/members`, {
        method: "POST", body: JSON.stringify({ ids: [userId] }),
      });
      await refreshDetail(albumId);
    }, isMember ? "Album access removed." : "Album access granted.");
  }

  async function addMedia() {
    const ids = [...chosen];
    if (!ids.length) return;
    await perform(async () => {
      // In batches to respect the API's bounded transaction limits.
      for (let start = 0; start < ids.length; start += 100) {
        await api(`/shared-albums/${albumId}/items`, {
          method: "POST", body: JSON.stringify({ ids: ids.slice(start, start + 100) }),
        });
      }
      setChosen(new Set());
      await refreshDetail(albumId);
      await refreshAlbums();
    }, `${ids.length} selected item(s) added. The original files remain owned by their users.`);
  }

  async function removeMedia(photoId) {
    if (!window.confirm("Remove this item from the shared album? The owner's original will not be deleted.")) return;
    await perform(async () => {
      await api(`/shared-albums/${albumId}/items/${photoId}`, { method: "DELETE" });
      await refreshDetail(albumId);
      await refreshAlbums();
    }, "Item removed from sharing; original preserved.");
  }

  async function removeAlbum() {
    if (!window.confirm("Delete this shared album and its access list? Original photos and videos remain untouched.")) return;
    await perform(async () => {
      await api(`/shared-albums/${albumId}`, { method: "DELETE" });
      setAlbumId(null); await refreshAlbums();
    }, "Shared album deleted. Owners' original media was not changed.");
  }

  async function downloadMedia(item, motion = false) {
    await perform(async () => {
      const endpoint = motion ? "motion-access-url" : "access-url";
      const result = await api(`/shared-albums/${albumId}/media/${item.id}/${endpoint}`, { method: "POST" });
      const downloadUrl = !motion && result.video ? `${result.url}&download=1` : result.url;
      openProtectedDownload(downloadUrl);
    });
  }

  async function viewMedia(item) {
    setViewer(item); setVideoUrl("");
    if (item.media_type === "video") {
      try {
        const result = await api(`/shared-albums/${albumId}/media/${item.id}/access-url`, { method: "POST" });
        setVideoUrl(result.url);
      } catch (e) { setError(e.message); }
    }
  }

  if (loading) return <section className="shared-albums-page"><p>Loading shared albums…</p></section>;

  return <section className="shared-albums-page">
    <div className="shared-albums-heading">
      <div><h2>Shared Albums</h2><p>Private albums for approved members. Originals stay with their owners.</p></div>
      {albumId && <button className="secondary-button" onClick={() => setAlbumId(null)}>All shared albums</button>}
    </div>
    {error && <p role="alert" className="error-message">{error}</p>}
    {notice && <p role="status" className="shared-albums-notice">{notice}</p>}

    {!albumId ? <>
      {isAdmin && <form className="shared-albums-create" onSubmit={createAlbum}>
        <label htmlFor="shared-new-name">New shared album</label>
        <input id="shared-new-name" placeholder="e.g. Family Photos" maxLength={150}
          value={albumName} onChange={e => setAlbumName(e.target.value)} />
        <button className="primary-button" type="submit" disabled={isWorking || !albumName.trim()}>Create album</button>
      </form>}
      <div className="shared-album-grid">
        {albums.map(album => <button className="shared-album-tile" key={album.id} onClick={() => setAlbumId(album.id)}>
          <strong>{album.name}</strong>
          <span>{album.item_count} media items · {album.member_count} members</span>
        </button>)}
        {!albums.length && <p>{isAdmin ? "No shared albums yet. Create one to get started." : "No shared albums have been shared with you yet."}</p>}
      </div>
    </> : !detail ? <p>Loading album…</p> : <>
      <header className="shared-album-detail-header">
        <div><h3>{detail.album.name}</h3><p>{detail.album.description || "Shared photos and videos"}</p></div>
        {isAdmin && <button className="secondary-button" disabled={isWorking} onClick={removeAlbum}>Delete shared album</button>}
      </header>

      {isAdmin && <div className="shared-admin-panels">
        <section className="shared-admin-panel" aria-label="Album members">
          <h4>Who has access</h4>
          <p>Only selected users can open and download from this album.</p>
          <div className="shared-member-list">
            {users.map(u => <label key={u.id}>
              <input type="checkbox" disabled={isWorking}
                checked={detail.members.includes(u.id)}
                onChange={() => setMembership(u.id, detail.members.includes(u.id))} />
              <span>{u.display_name || u.username} <small>({u.username})</small></span>
            </label>)}
          </div>
        </section>
        <section className="shared-admin-panel" aria-label="Add owner media">
          <h4>Add photos or videos</h4>
          <p>Select an owner, then choose media to share. No copies are created.</p>
          <label>Media owner
            <select value={ownerId} onChange={e => { setOwnerId(e.target.value); setCandidatePage(0); setChosen(new Set()); }}>
              <option value="">Select a user</option>
              {users.map(u => <option key={u.id} value={String(u.id)}>{u.username}</option>)}
            </select>
          </label>
          {ownerId && <>
            <input placeholder="Search this user's filenames" value={search}
              onChange={e => { setSearch(e.target.value); setCandidatePage(0); }} />
            <div className="shared-candidate-list">
              {candidates.map(item => <label key={item.id}>
                <input type="checkbox" checked={chosen.has(item.id)} onChange={() => setChosen(prev => {
                  const next = new Set(prev); next.has(item.id) ? next.delete(item.id) : next.add(item.id); return next;
                })} />
                <ProtectedThumbnail url={`/api/shared-albums/owner-media/${item.id}/thumbnail?owner_id=${ownerId}`} label={item.original_filename} />
                <span title={item.original_filename}>{item.original_filename}</span>
                {item.media_type === "video" && <small>Video</small>}
              </label>)}
              {!candidates.length && <p>No matching media found.</p>}
            </div>
            <div className="shared-admin-actions">
              <button type="button" className="secondary-button" disabled={candidatePage === 0} onClick={() => setCandidatePage(p => p - 1)}>Previous</button>
              <span>Page {candidatePage + 1}</span>
              <button type="button" className="secondary-button" disabled={!candidateMore} onClick={() => setCandidatePage(p => p + 1)}>Next</button>
            </div>
            <button className="primary-button" disabled={isWorking || !chosen.size} onClick={addMedia}>Share selected ({chosen.size})</button>
          </>}
        </section>
      </div>}

      <h4>Shared media</h4>
      <div className="shared-media-grid">
        {detail.items.map(item => <article className="shared-media-tile" key={item.id}>
          <button className="shared-media-preview" onClick={() => viewMedia(item)} aria-label={`Open ${item.original_filename}`}>
            <ProtectedThumbnail url={`/api/shared-albums/${albumId}/media/${item.id}/thumbnail`} label={item.original_filename} />
            {item.media_type === "video" && <span className="shared-video-badge">▶ Video</span>}
            {!!item.has_live_motion && <span className="shared-video-badge">Live Photo</span>}
          </button>
          <div className="shared-media-info"><strong title={item.original_filename}>{item.original_filename}</strong>
            <small>Owned by {item.owner_username}</small></div>
          <div className="shared-media-actions">
            <button className="secondary-button" onClick={() => downloadMedia(item)}>Download</button>
            {!!item.has_live_motion && <button className="secondary-button" onClick={() => downloadMedia(item, true)}>Motion MOV</button>}
            {isAdmin && <button className="secondary-button" onClick={() => removeMedia(item.id)}>Unshare</button>}
          </div>
        </article>)}
        {!detail.items.length && <p>No media has been added to this album.</p>}
      </div>
      {detail.has_more && <button className="secondary-button" onClick={() => perform(() => refreshDetail(albumId, itemsOffset + 100, true))}>Load more media</button>}
    </>}

    {viewer && <div className="shared-viewer-backdrop" role="presentation" onClick={() => { setViewer(null); setVideoUrl(""); }}>
      <div className="shared-viewer" role="dialog" aria-modal="true" aria-label={viewer.original_filename}
        onClick={e => e.stopPropagation()}>
        <button className="secondary-button" onClick={() => { setViewer(null); setVideoUrl(""); }}>Close</button>
        <h3>{viewer.original_filename}</h3>
        {viewer.media_type === "video"
          ? videoUrl ? <video key={viewer.id} src={videoUrl} controls playsInline preload="metadata" /> : <p>Preparing video…</p>
          : <ProtectedThumbnail url={`/api/shared-albums/${albumId}/media/${viewer.id}/thumbnail`} label={viewer.original_filename} />}
        <button className="primary-button" onClick={() => downloadMedia(viewer)}>Download original</button>
        {!!viewer.has_live_motion && <button className="secondary-button" onClick={() => downloadMedia(viewer, true)}>Download motion MOV</button>}
      </div>
    </div>}
  </section>;
}
