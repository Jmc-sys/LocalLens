
import { useRef, useState } from "react";
import { api } from "./api";

export default function UploadManager({ onComplete }) {
  const input = useRef(null);
  const running = useRef(false);

  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState([]);

  async function uploadFiles(fileList) {
    if (running.current || !fileList?.length) return;

    running.current = true;

    const files = Array.from(fileList);

    let uploaded = 0;
    let duplicates = 0;
    let failed = 0;
    const failures = [];

    setBusy(true);
    setProgress(0);
    setErrors([]);

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];

        setMessage(
          `Uploading ${i + 1} of ${files.length}: ${file.name}`
        );

        const form = new FormData();
        form.append("file", file);

        try {
          const result = await api("/photos/upload", {
            method: "POST",
            body: form,
          });

          if (result.status === "duplicate") {
            duplicates++;
          } else {
            uploaded++;
          }
        } catch (err) {
          failed++;
          failures.push(`${file.name}: ${err.message}`);
        }

        setProgress(
          Math.round(((i + 1) / files.length) * 100)
        );
      }

      setMessage(
        `${uploaded} uploaded · ${duplicates} duplicates skipped · ${failed} failed`
      );

      setErrors(failures);
      await onComplete?.();

    } finally {
      running.current = false;
      setBusy(false);

      if (input.current) {
        input.current.value = "";
      }
    }
  }

  return (
    <section
      className={`upload-zone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        uploadFiles(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        accept="image/*,.heic,.heif,.jpg,.jpeg,.png,.webp,.gif,.tiff,.tif,.bmp"
        multiple
        hidden
        onChange={(e) => uploadFiles(e.target.files)}
      />

      <button
        className="primary-button"
        disabled={busy}
        onClick={() => input.current.click()}
      >
        + Upload photos
      </button>

      <p>Or drag and drop your photos here.</p>

      <p className="upload-formats">
        JPEG · PNG · HEIC · HEIF · WebP · GIF · TIFF · BMP
      </p>

      <p className="upload-formats">
        Original quality preserved.
      </p>

      {busy && (
        <progress max="100" value={progress} />
      )}

      {message && <p>{message}</p>}

      {errors.map((error, i) => (
        <p className="error-message" key={i}>
          {error}
        </p>
      ))}
    </section>
  );
}
