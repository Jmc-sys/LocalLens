import { useEffect, useState } from "react";
import { api } from "./api";

// A short-lived, video-scoped playback ticket allows native browser Range
// requests without exposing the account's access token in the video URL.
export default function PrivateVideo({ photo }) {
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setSource(""); setError("");
    api(`/videos/${photo.id}/playback-url`, { method: "POST" })
      .then((result) => { if (!cancelled) setSource(result.url); })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [photo.id]);

  if (error) return <p role="alert" className="error-message">{error}</p>;
  if (!source) return <p role="status">Preparing video…</p>;
  return <div className="private-video-wrapper">
    <video key={photo.id} src={source} controls playsInline preload="metadata"
      onError={() => setError("Your browser cannot play this video format. Download the original to view it.")} />
    <small>Original video preserved without recompression.</small>
  </div>;
}
