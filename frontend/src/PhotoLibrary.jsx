import { downloadOwnerOriginal } from "./downloadOriginals";
import PhotoPageNavigator from "./PhotoPageNavigator";
import ViewerNavigation from "./ViewerNavigation";
import SharedAlbums, { AuthorizedImage } from "./SharedAlbums";
import AiOperations from "./AiOperations";
import AiActivityTracker from "./AiActivityTracker";
import AiPhotoAnnotations from "./AiPhotoAnnotations";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, mediaBlob } from "./api";
import PopularPhotoTags from "./PopularPhotoTags";
import PrivateImage from "./PrivateImage";
import UniversalUpload from "./UniversalUpload";
import PrivateVideo from "./PrivateVideo";

const isStandaloneVideo = (item) => item?.media_type === "video" ||
  item?.mime_type?.startsWith("video/");
import TrashControls from "./TrashControls";
import { LiveViewer } from "./LivePhotos";

function OwnerPhotoLibrary({ page, onOpenSharedAlbum }) {
  const [result, setResult] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [albums, setAlbums] = useState([]);
  const [activeAlbum, setActiveAlbum] = useState(null);
  const [selected, setSelected] = useState([]);
  const [viewer, setViewer] = useState(null);
  const [viewerJump, setViewerJump] = useState(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [error, setError] = useState("");
  const [albumName, setAlbumName] = useState("");
  const [targetAlbum, setTargetAlbum] = useState("");
  const [sharedTargetAlbums, setSharedTargetAlbums] = useState([]);
  const albumCache = useRef(null);
  const PAGE_SIZE = 100;
  const [pageIndex, setPageIndex] = useState(0);
  const [libraryTotal, setLibraryTotal] = useState(null);

  const isTrash = page === "Trash";
  const albumOverview =
    page === "Albums" && !activeAlbum;

  // Album overview never requests the full photo library.
  // Tag every response with the exact view that requested it.
  const albumId = activeAlbum?.id ?? null;
  const params = new URLSearchParams({
    sort: sort,
    search,
    favorite: String(page === "Favorites"),
    trash: String(isTrash),
    media: page === "Videos" ? "video" : page === "Photos" ? "photo" : "all",
    limit: String(PAGE_SIZE),
    offset: String(pageIndex * PAGE_SIZE),
  });
  const defaultPhotoPath = albumOverview
    ? null
    : albumId !== null
      ? `/albums/${albumId}/photos`
      : `/photos?${params}`;
  // Reuse the EXISTING toolbar search for all media and owner albums.
  // The backend searches names/tags as well as filenames with account isolation.
  const smartSearchActive = search.trim().length > 0 && !albumOverview;
  const smartParams = new URLSearchParams({
    sort: page === "Recently Added" ? "newest" : sort,
    search: search.trim(),
    media: page === "Videos" ? "video" : page === "Photos" ? "photo" : "all",
    favorite: String(page === "Favorites"),
    trash: String(isTrash),
    limit: String(PAGE_SIZE),
    offset: String(pageIndex * PAGE_SIZE),
  });
  if (activeAlbum?.id != null) smartParams.set("album_id", String(activeAlbum.id));
  const photoPath = smartSearchActive ? `/ai/unified-search?${smartParams}` : defaultPhotoPath;
  const requestKey = JSON.stringify([page, photoPath, refreshVersion]);
  const currentResult = result?.key === requestKey ? result : null;
  const loadingPhotos = currentResult === null;
  const photos = currentResult?.photos ?? [];
  const loadError = currentResult?.error ?? "";

  // Fetch the real database total separately from the current 100-item page.
  useEffect(() => {
    if (!["Photos", "Videos", "Favorites", "Trash"].includes(page) || activeAlbum) {
      setLibraryTotal(null);
      return;
    }
    const controller = new AbortController();
    const query = new URLSearchParams({
      media: page === "Videos" ? "video" : page === "Photos" ? "photo" : "all",
      search,
      favorite: String(page === "Favorites"),
      trash: String(page === "Trash"),
    });
    api(`${search.trim() ? "/ai/unified-search/count" : "/media/library-count"}?${query}`, { signal: controller.signal })
      .then(response => { if (!controller.signal.aborted) setLibraryTotal(Number(response.total)); })
      .catch(() => { if (!controller.signal.aborted) setLibraryTotal(null); });
    return () => controller.abort();
  }, [page, search, activeAlbum?.id, refreshVersion]);

  // Mutations and uploads request a refresh of the CURRENT view,
  // even if the user navigated while the operation was running.
  const load = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  function openAlbum(album) {
    setSelected([]);
    setViewer(null);
    setPageIndex(0);
    setActiveAlbum(album);
    setError("");
    load();
  }

  function closeAlbum() {
    setSelected([]);
    setViewer(null);
    setPageIndex(0);
    setActiveAlbum(null);
    setError("");
    load();
  }

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchView() {
      try {
        const [photoData, albumData] = await Promise.all([
          photoPath ? api(photoPath, { signal }) : Promise.resolve([]),
          albumCache.current?.version === refreshVersion
            ? Promise.resolve(albumCache.current.data)
            : api("/albums", { signal }),
        ]);
        if (signal.aborted) return;
        albumCache.current = { version: refreshVersion, data: albumData };
        setAlbums(albumData);
        const liveIds = new Set();
        const missingMotionIds = new Set();
        for (let i=0; i<photoData.length; i+=500) {
          const data = await api("/live/status", { method:"POST", body:JSON.stringify({photo_ids:photoData.slice(i,i+500).map(p=>p.id)}), signal });
          data.ids.forEach(id=>liveIds.add(id));
          (data.missing_ids || []).forEach(id=>missingMotionIds.add(id));
        }
        if (signal.aborted) return;
        setResult({ key: requestKey, photos: photoData.map(p=>({...p,is_live:liveIds.has(p.id),motion_missing:missingMotionIds.has(p.id)})), error: "" });
      } catch (err) {
        if (signal.aborted) return;
        setResult({ key: requestKey, photos: [], error: err.message });
      }
    }

    // Debounce only searches in the main photo library.
    const timer = setTimeout(fetchView, (photoPath?.startsWith("/photos?") || photoPath?.startsWith("/ai/unified-search?")) ? 300 : 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [photoPath, requestKey]);

  useEffect(() => {
    setSelected([]);
  }, [page, sort, search, albumId, pageIndex]);

  useEffect(() => {
    function close(e) {
      if (e.key === "Escape") setViewer(null);
    }

    window.addEventListener("keydown", close);

    return () => window.removeEventListener("keydown", close);
  }, []);

  async function action(work) {
    try {
      setError("");
      await work();
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function toggleSelection(id) {
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id]
    );
  }

  function createAlbum(event) {
    event.preventDefault();

    if (!albumName.trim()) return;

    action(async () => {
      const album = await api("/albums", {
        method: "POST",
        body: JSON.stringify({
          name: albumName.trim(),
        }),
      });

      if (selected.length && !isTrash) {
        await api(`/albums/${album.id}/photos`, {
          method: "POST",
          body: JSON.stringify({
            photo_ids: selected,
          }),
        });
      }

      setAlbumName("");
      setSelected([]);
    });
  }

  // Load shared/family destinations independently of gallery search and sorting.
  useEffect(() => {
    if (page === "Trash") return;
    let cancelled = false;
    api("/shared-albums")
      .then(list => { if (!cancelled) setSharedTargetAlbums(list); })
      .catch(() => { if (!cancelled) setSharedTargetAlbums([]); });
    return () => { cancelled = true; };
  }, [page]);

  function addToAlbum() {
    if (!targetAlbum || !selected.length) return;

    action(async () => {
      if (String(targetAlbum).startsWith("shared:")) {
        const id = Number(String(targetAlbum).slice(7));
        if (!Number.isSafeInteger(id) || id <= 0) throw new Error("Invalid shared album");
        for (let n = 0; n < selected.length; n += 100) {
          await api(`/shared-albums/${id}/items`, {
            method: "POST", body: JSON.stringify({ ids: selected.slice(n, n + 100) }),
          });
        }
      } else {
        await api(`/albums/${targetAlbum}/photos`, {
          method: "POST", body: JSON.stringify({ photo_ids: selected }),
        });
      }

      setSelected([]);
    });
  }

  async function downloadSelectedOriginals() {
    if (!selected.length || selected.length > 100) {
      setError("Select between 1 and 100 media items to download together.");
      return;
    }
    try {
      setError("");
      const result = await api("/media/bulk-prepare", {
        method: "POST",
        body: JSON.stringify({ photo_ids: selected }),
      });
      if (!result?.url || !result.url.startsWith("/api/media/bulk-download/")) {
        throw new Error("Could not prepare the bulk download.");
      }
      // A native HTTP attachment download: no giant JS Blob or local ZIP assembly.
      // Navigation remains reliable on mobile Safari after an async prepare call.
      window.location.assign(result.url);
    } catch (err) { setError(err.message || "Bulk download failed."); }
  }

  function moveSelected() {
    if (
      !window.confirm(
        `${isTrash ? "Restore" : "Move to trash"} ${selected.length} item(s)?`
      )
    ) return;

    action(async () => {
      for (const id of selected) {
        await api(
          isTrash
            ? `/photos/${id}/restore`
            : `/photos/${id}`,
          {
            method: isTrash ? "POST" : "DELETE",
          }
        );
      }

      setSelected([]);
    });
  }

  async function download(photo) {
    try { await downloadOwnerOriginal(photo); }
    catch (err) { setError(err.message); }
  }

  let visiblePhotos = [...photos];

  if (activeAlbum) {
    visiblePhotos = visiblePhotos.filter((p) =>
      p.original_filename.toLowerCase().includes(
        search.toLowerCase()
      )
    );

    visiblePhotos.sort((a, b) => {
      switch (sort) {
        case "oldest":
          return new Date(a.uploaded_at) - new Date(b.uploaded_at);
        case "name_asc":
          return a.original_filename.localeCompare(b.original_filename);
        case "name_desc":
          return b.original_filename.localeCompare(a.original_filename);
        case "largest":
          return b.size_bytes - a.size_bytes;
        case "smallest":
          return a.size_bytes - b.size_bytes;
        case "captured":
          return new Date(b.captured_at || b.uploaded_at)
               - new Date(a.captured_at || a.uploaded_at);
        default:
          return new Date(b.uploaded_at) - new Date(a.uploaded_at);
      }
    });
  }

  // When an arrow crosses a 100-item page, show the first/last item after
  // the next server page completes. The current viewer stays open meanwhile.
  useEffect(() => {
    if (!viewerJump || loadingPhotos || !visiblePhotos.length) return;
    if (pageIndex !== viewerJump.page) return;
    setViewer(viewerJump.edge === 'first' ? visiblePhotos[0] : visiblePhotos[visiblePhotos.length - 1]);
    setViewerJump(null);
  }, [viewerJump, loadingPhotos, pageIndex, currentResult]);

  return (
    <section className="photo-library">
      <div className="library-heading">
        <h2>{activeAlbum?.name || page}</h2>

        {activeAlbum && (
          <button
            className="secondary-button"
            onClick={closeAlbum}
          >
            Back to albums
          </button>
        )}
      </div>

      {isTrash && <TrashControls selected={selected} onDeleted={() => { setSelected([]); setPageIndex(0); load(); }} />}

      {(page === "Photos" || page === "Videos") && (
        <><UniversalUpload onComplete={load} /></>
      )}


      <AiActivityTracker />

      {(error || loadError) && (
        <p className="error-message">{error || loadError}</p>
      )}
      {loadError && (
        <button className="secondary-button" onClick={load}>Retry</button>
      )}

      {(albumOverview || (!loadingPhotos && !loadError && selected.length > 0 && !isTrash)) && (
        <form className="library-toolbar" onSubmit={createAlbum}>
          <input
            placeholder="New album name"
            value={albumName}
            maxLength={150}
            onChange={(e) => setAlbumName(e.target.value)}
          />

          <button className="primary-button">
            + Create album
          </button>
        </form>
      )}

      {albumOverview ? (
        loadingPhotos ? (
          <div className="photo-loading" role="status">
            <div className="photo-spinner" />
            <p>Loading albums...</p>
          </div>
        ) : loadError ? null : (
        <div className="album-grid">
          {/* Family comes first, inside the SAME album grid as personal albums. */}
          {sharedTargetAlbums.slice().sort((a, b) =>
            Number(b.name === "Family Album" || b.is_family) -
            Number(a.name === "Family Album" || a.is_family)
          ).map((album) => (
            <article className="album-card" key={`shared-${album.id}`}>
              <button type="button" className="album-cover shared-family-card"
                onClick={() => onOpenSharedAlbum(album.id)}
                aria-label={`Open shared album ${album.name}`}>
                {album.cover_photo_id
                  ? <AuthorizedImage
                      url={`/api/shared-albums/${album.id}/media/${album.cover_photo_id}/thumbnail`}
                      alt={`Cover for ${album.name}`} />
                  : <div className="shared-cover-placeholder" aria-hidden="true">▧</div>}

              </button>
              <h3>{album.name}</h3>
              <p>{Number(album.item_count || 0).toLocaleString()} items · Shared</p>
            </article>
          ))}
          {albums.map((album) => (
            <article className="album-card" key={album.id}>
              <button
                className="album-cover"
                onClick={() => openAlbum(album)}
              >
                {album.cover_photo_id ? (
                  <PrivateImage id={album.cover_photo_id} />
                ) : (
                  <div className="image-placeholder">
                    Empty album
                  </div>
                )}
              </button>

              <h3>{album.name}</h3>
              <p>{album.photo_count} items</p>

              <button
                className="secondary-button"
                onClick={() => {
                  const name = window.prompt(
                    "Album name", album.name
                  );

                  if (!name?.trim()) return;

                  action(() =>
                    api(`/albums/${album.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({
                        name,
                        description: album.description || "",
                      }),
                    })
                  );
                }}
              >
                Rename
              </button>

              <button
                className="secondary-button"
                onClick={() => {
                  if (
                    window.confirm(
                      "Delete this album? Original photos will be kept."
                    )
                  ) {
                    action(() =>
                      api(`/albums/${album.id}`, {
                        method: "DELETE",
                      })
                    );
                  }
                }}
              >
                Delete
              </button>
            </article>
          ))}
        </div>
        )
      ) : (
        <>
          {page === "Photos" && <PopularPhotoTags onSearch={(tag) => {
            setSearch(tag); setPageIndex(0); setSelected([]);
          }} />}
          <div className="library-toolbar">
            <input
              placeholder="Search filenames, tags, people or pets..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPageIndex(0);
                setSelected([]);
              }}
            />

            <select
              className="locallens-sort-compact"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPageIndex(0);
                setSelected([]);
              }}
            >
              <option value="newest">Newest uploaded</option>
              <option value="oldest">Oldest uploaded</option>
              <option value="captured">Date captured</option>
              <option value="name_asc">Filename A–Z</option>
              <option value="name_desc">Filename Z–A</option>
              <option value="largest">Largest first</option>
              <option value="smallest">Smallest first</option>
            </select>

            <button
              className="secondary-button"
              disabled={loadingPhotos || !!loadError || !visiblePhotos.length}
              onClick={() =>
                setSelected(visiblePhotos.map((p) => p.id))
              }
            >
              Select all
            </button>
          </div>

          {!loadingPhotos && !loadError && selected.length > 0 && (
            <div className="library-toolbar selection-bar">
              <strong>{selected.length} selected</strong>
              {!isTrash && (
                <button type="button" className="secondary-button"
                  onClick={() => void downloadSelectedOriginals()}>
                  Download selected
                </button>
              )}

              {!isTrash && (
                <>
                  <select
                    value={targetAlbum}
                    onChange={(e) => setTargetAlbum(e.target.value)}
                  >
                    <option value="">Choose album</option>

                    {albums.map((album) => (
                      <option key={album.id} value={album.id}>
                        {album.name}
                      </option>
                    ))}
                  <optgroup label="Family and shared albums">
                      {sharedTargetAlbums.map(album => (
                        <option key={`shared-${album.id}`} value={`shared:${album.id}`}>
                          {album.name} (Shared)
                        </option>
                      ))}
                    </optgroup>
                  </select>

                  <button
                    className="primary-button"
                    onClick={addToAlbum}
                  >
                    Add to album
                  </button>
                </>
              )}

              {activeAlbum && (
                <button
                  className="secondary-button"
                  onClick={() =>
                    action(async () => {
                      for (const id of selected) {
                        await api(
                          `/albums/${activeAlbum.id}/photos/${id}`,
                          { method: "DELETE" }
                        );
                      }

                      setSelected([]);
                    })
                  }
                >
                  Remove from album
                </button>
              )}

              <button
                className="secondary-button"
                onClick={moveSelected}
              >
                {isTrash ? "Restore" : "Move to trash"}
              </button>

              <button
                className="secondary-button"
                onClick={() => setSelected([])}
              >
                Clear
              </button>
            </div>
          )}

          {!loadingPhotos && !loadError && (
            <p className="media-count">
              {activeAlbum
                ? `${visiblePhotos.length.toLocaleString()} items in album`
                : `Showing ${visiblePhotos.length.toLocaleString()} of ${libraryTotal === null ? "…" : libraryTotal.toLocaleString()} ${page === "Photos" ? "photos" : page === "Videos" ? "videos" : "items"}`}
            </p>
          )}

          {!loadingPhotos && !loadError && !visiblePhotos.length && (
            <div className="empty-library">
              No media found.
            </div>
          )}

          {loadingPhotos ? (
            <div className="photo-loading" role="status">
              <div className="photo-spinner" />
              <p>Loading photos...</p>
            </div>
          ) : loadError ? null : (
            <div className="photo-grid">
            {visiblePhotos.map((photo) => (
              <article
                key={photo.id}
                className={
                  `photo-card ${
                    selected.includes(photo.id) ? "selected" : ""
                  }`
                }
              >
                <button
                  className="photo-preview"
                  onClick={() => setViewer(photo)}
                >
                  <PrivateImage
                    id={photo.id}
                    alt={photo.original_filename}
                  />
                </button>

                <input
                  className="photo-checkbox"
                  type="checkbox"
                  aria-label={`Select ${photo.original_filename}`}
                  checked={selected.includes(photo.id)}
                  onChange={() => toggleSelection(photo.id)}
                />

                {!isTrash && (
                  <button
                    className="favorite-button"
                    aria-label="Toggle favorite"
                    onClick={() =>
                      action(() =>
                        api(`/photos/${photo.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({
                            is_favorite: !photo.is_favorite,
                          }),
                        })
                      )
                    }
                  >
                    {photo.is_favorite ? "♥" : "♡"}
                  </button>
                )}

                <div className="photo-name">
                  {isStandaloneVideo(photo) && <span className="media-video-tag">▶ VIDEO</span>}
                  {photo.is_live && <span className="live-tag">LIVE </span>}{photo.original_filename}
                </div>
              </article>
            ))}
          </div>
        )}
          {!activeAlbum && (
            <PhotoPageNavigator
              pageIndex={pageIndex}
              pageSize={PAGE_SIZE}
              totalItems={libraryTotal}
              loading={loadingPhotos}
              hasError={!!loadError}
              hasMore={photos.length === PAGE_SIZE}
              onChangePage={(nextIndex) => {
                setSelected([]);
                setPageIndex(nextIndex);
              }}
            />
          )}
        </>
      )}

      {viewer && (
        <div className="photo-viewer">
          <ViewerNavigation items={visiblePhotos} currentId={viewer.id} onNavigate={setViewer}
            onBeforeFirst={!activeAlbum && pageIndex > 0 ? () => {
              setViewerJump({page: pageIndex - 1, edge:'last'});
              setPageIndex(pageIndex - 1);
            } : null}
            onAfterLast={!activeAlbum && libraryTotal !== null &&
                (pageIndex + 1) * PAGE_SIZE < libraryTotal ? () => {
              setViewerJump({page: pageIndex + 1, edge:'first'});
              setPageIndex(pageIndex + 1);
            } : null}/>

          <header>
            <span>{viewer.original_filename}</span>

            <button
              className="secondary-button"
              onClick={() => download(viewer)}
            >
              Download
            </button>

            <button
              className="secondary-button"
              onClick={() => setViewer(null)}
            >
              Close ×
            </button>
          </header>
          <AiPhotoAnnotations photoId={viewer.id} />

          {viewer.is_live ? <LiveViewer key={viewer.id} photo={viewer}>
          {isStandaloneVideo(viewer) ? <PrivateVideo photo={viewer} /> : (<PrivateImage
            id={viewer.id}
            type={
              [
                "image/heic",
                "image/heif",
                "image/tiff",
                "image/bmp",
                "image/mpo",
              ].includes(viewer.mime_type)
                ? "preview"
                : "file"
            }
            alt={viewer.original_filename}
          />)}
          </LiveViewer> : (
          isStandaloneVideo(viewer) ? <PrivateVideo photo={viewer} /> : (<PrivateImage
            id={viewer.id}
            type={
              [
                "image/heic",
                "image/heif",
                "image/tiff",
                "image/bmp",
                "image/mpo",
              ].includes(viewer.mime_type)
                ? "preview"
                : "file"
            }
            alt={viewer.original_filename}
          />)
          )}
        </div>
      )}
    </section>
  );
}

// One Albums overview for personal and admin-managed family albums.
// Shared detail REPLACES the overview; it is never mounted above personal cards.
export default function PhotoLibrary(props) {
  const [activeSharedAlbumId, setActiveSharedAlbumId] = useState(null);
  useEffect(() => {
    if (props.page !== "Albums") setActiveSharedAlbumId(null);
  }, [props.page]);

  if (props.page === "Albums" && activeSharedAlbumId !== null) {
    return <SharedAlbums
      embedded
      openedAlbumId={activeSharedAlbumId}
      onBack={() => setActiveSharedAlbumId(null)}
    />;
  }
  return <OwnerPhotoLibrary {...props} onOpenSharedAlbum={setActiveSharedAlbumId} />;
}
