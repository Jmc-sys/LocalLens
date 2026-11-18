import { useCallback, useEffect, useState } from "react";
import { api, mediaBlob } from "./api";
import PrivateImage from "./PrivateImage";
import UploadManager from "./UploadManager";

export default function PhotoLibrary({ page }) {
  const [result, setResult] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [albums, setAlbums] = useState([]);
  const [activeAlbum, setActiveAlbum] = useState(null);
  const [selected, setSelected] = useState([]);
  const [viewer, setViewer] = useState(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [error, setError] = useState("");
  const [albumName, setAlbumName] = useState("");
  const [targetAlbum, setTargetAlbum] = useState("");
  const PAGE_SIZE = 100;
  const [pageIndex, setPageIndex] = useState(0);

  const isTrash = page === "Trash";
  const albumOverview =
    page === "Albums" && !activeAlbum;

  // Album overview never requests the full photo library.
  // Tag every response with the exact view that requested it.
  const albumId = activeAlbum?.id ?? null;
  const params = new URLSearchParams({
    sort: page === "Recently Added" ? "newest" : sort,
    search,
    favorite: String(page === "Favorites"),
    trash: String(isTrash),
    limit: String(PAGE_SIZE),
    offset: String(pageIndex * PAGE_SIZE),
  });
  const photoPath = albumOverview
    ? null
    : albumId !== null
      ? `/albums/${albumId}/photos`
      : `/photos?${params}`;
  const requestKey = JSON.stringify([page, photoPath, refreshVersion]);
  const currentResult = result?.key === requestKey ? result : null;
  const loadingPhotos = currentResult === null;
  const photos = currentResult?.photos ?? [];
  const loadError = currentResult?.error ?? "";

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
          api("/albums", { signal }),
        ]);
        if (signal.aborted) return;
        setAlbums(albumData);
        setResult({ key: requestKey, photos: photoData, error: "" });
      } catch (err) {
        if (signal.aborted) return;
        setResult({ key: requestKey, photos: [], error: err.message });
      }
    }

    // Debounce only searches in the main photo library.
    const timer = setTimeout(fetchView, photoPath?.startsWith("/photos?") ? 200 : 0);
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

  function addToAlbum() {
    if (!targetAlbum || !selected.length) return;

    action(async () => {
      await api(`/albums/${targetAlbum}/photos`, {
        method: "POST",
        body: JSON.stringify({
          photo_ids: selected,
        }),
      });

      setSelected([]);
    });
  }

  function moveSelected() {
    if (
      !window.confirm(
        `${isTrash ? "Restore" : "Move to trash"} ${selected.length} photo(s)?`
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
    try {
      const blob = await mediaBlob(photo.id, "file");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download = photo.original_filename;
      link.click();

      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err.message);
    }
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

      {page === "Photos" && (
        <UploadManager onComplete={load} />
      )}

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
              <p>{album.photo_count} photos</p>

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
          <div className="library-toolbar">
            <input
              placeholder="Search photos..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPageIndex(0);
                setSelected([]);
              }}
            />

            <select
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
              {visiblePhotos.length} photos displayed
            </p>
          )}

          {!loadingPhotos && !loadError && !visiblePhotos.length && (
            <div className="empty-library">
              No photos found.
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
                  {photo.original_filename}
                </div>
              </article>
            ))}
          </div>
        )}
          {!activeAlbum && (
            <div className="pagination">
              <button
                className="secondary-button"
                disabled={loadingPhotos || pageIndex === 0}
                onClick={() =>
                  { setSelected([]); setPageIndex((index) => Math.max(0, index - 1)); }
                }
              >
                Previous
              </button>

              <span>Page {pageIndex + 1}</span>

              <button
                className="secondary-button"
                disabled={loadingPhotos || !!loadError || photos.length < PAGE_SIZE}
                onClick={() =>
                  { setSelected([]); setPageIndex((index) => index + 1); }
                }
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      {viewer && (
        <div className="photo-viewer">
          <header>
            <span>{viewer.original_filename}</span>

            <button
              className="secondary-button"
              onClick={() => download(viewer)}
            >
              Download original
            </button>

            <button
              className="secondary-button"
              onClick={() => setViewer(null)}
            >
              Close ×
            </button>
          </header>

          <PrivateImage
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
          />
        </div>
      )}
    </section>
  );
}
