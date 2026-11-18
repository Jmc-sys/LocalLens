
import { useEffect, useState } from "react";
import { mediaBlob } from "./api";

export default function PrivateImage({
  id,
  type = "thumbnail",
  alt = "",
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    let active = true;

    setUrl("");
    setError(false);

    mediaBlob(id, type, controller.signal)
      .then((blob) => {
        if (!active) return;

        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((err) => {
        if (active && err.name !== "AbortError") {
          setError(true);
        }
      });

    return () => {
      active = false;
      controller.abort();

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [id, type]);

  if (!url || error) {
    return (
      <div className="image-placeholder">
        {error ? "Image unavailable" : "Loading..."}
      </div>
    );
  }

  return <img src={url} alt={alt} />;
}
