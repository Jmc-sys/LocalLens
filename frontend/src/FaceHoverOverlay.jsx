import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./face-hover-overlay.css";

// LocalLens v0.6.20: label an identified face only while it is hovered.
// Face coordinates are normalized in the already-stored ai_faces rows. No
// image/face processing or per-pointer network request is involved.
function usableFace(face) {
  return face && face.display_name && Number.isFinite(Number(face.x)) &&
    Number.isFinite(Number(face.y)) && Number(face.w) > 0 && Number(face.h) > 0;
}

function visibleViewerImage() {
  const viewer = document.querySelector(".photo-viewer");
  if (!viewer) return null;
  const items = [...viewer.querySelectorAll("img")]
    .filter(img => !img.closest(".ll-v06-annotations") && img.complete &&
      img.naturalWidth > 0 && img.naturalHeight > 0 &&
      img.getBoundingClientRect().width > 90 && img.getBoundingClientRect().height > 90);
  items.sort((a, b) => {
    const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
    return br.width * br.height - ar.width * ar.height;
  });
  return items[0] || null;
}

function objectPositionFraction(part) {
  if (!part) return .5;
  if (part === "left" || part === "top") return 0;
  if (part === "right" || part === "bottom") return 1;
  const pct = /^(-?\d+(?:\.\d+)?)%$/.exec(part);
  return pct ? Number(pct[1]) / 100 : .5;
}

function displayedImageRect(img) {
  const box = img.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  const cs = window.getComputedStyle(img);
  const borderX = parseFloat(cs.borderLeftWidth || "0") || 0;
  const borderY = parseFloat(cs.borderTopWidth || "0") || 0;
  const padX = parseFloat(cs.paddingLeft || "0") || 0;
  const padY = parseFloat(cs.paddingTop || "0") || 0;
  const W = img.clientWidth - (parseFloat(cs.paddingLeft || "0") || 0) - (parseFloat(cs.paddingRight || "0") || 0);
  const H = img.clientHeight - (parseFloat(cs.paddingTop || "0") || 0) - (parseFloat(cs.paddingBottom || "0") || 0);
  if (W <= 0 || H <= 0) return null;
  let width = W, height = H;
  const fit = cs.objectFit || "fill";
  const iw = img.naturalWidth, ih = img.naturalHeight;
  if (fit === "contain" || fit === "cover" || fit === "scale-down" || fit === "none") {
    let factor = fit === "cover" ? Math.max(W / iw, H / ih)
      : fit === "none" ? 1 : Math.min(W / iw, H / ih);
    if (fit === "scale-down") factor = Math.min(factor, 1);
    width = iw * factor; height = ih * factor;
  }
  const pos = cs.objectPosition.trim().split(/\s+/);
  const px = objectPositionFraction(pos[0]);
  const py = objectPositionFraction(pos[1] || "50%");
  return {
    x: box.left + borderX + padX + (W - width) * px,
    y: box.top + borderY + padY + (H - height) * py,
    width, height,
  };
}

function faceBox(base, face) {
  const x = Math.max(0, Math.min(1, Number(face.x)));
  const y = Math.max(0, Math.min(1, Number(face.y)));
  const w = Math.max(0, Math.min(1 - x, Number(face.w)));
  const h = Math.max(0, Math.min(1 - y, Number(face.h)));
  return { left: base.x + x * base.width, top: base.y + y * base.height,
    width: w * base.width, height: h * base.height };
}

export default function FaceHoverOverlay({ photoId, faces = [] }) {
  const [hit, setHit] = useState(null);
  const active = useRef(null);
  const facesRef = useRef(faces);
  facesRef.current = faces;

  useEffect(() => {
    active.current = null;
    setHit(null);
    let frame = 0;
    let pointer = null;
    const refresh = () => {
      frame = 0;
      if (!pointer) return;
      const image = visibleViewerImage();
      const imageArea = image && displayedImageRect(image);
      const candidates = facesRef.current.filter(usableFace);
      let selected = null;
      if (imageArea && candidates.length) {
        // Prefer the smallest face if boxes overlap.
        for (const face of candidates) {
          const bounds = faceBox(imageArea, face);
          if (pointer.x >= bounds.left && pointer.x <= bounds.left + bounds.width &&
              pointer.y >= bounds.top && pointer.y <= bounds.top + bounds.height &&
              (!selected || bounds.width * bounds.height < selected.bounds.width * selected.bounds.height)) {
            selected = { id: face.id, name: face.display_name, bounds };
          }
        }
      }
      const previous = active.current;
      if (selected && previous && selected.id === previous.id &&
          selected.name === previous.name &&
          Math.abs(selected.bounds.left - previous.bounds.left) < .5 &&
          Math.abs(selected.bounds.top - previous.bounds.top) < .5 &&
          Math.abs(selected.bounds.width - previous.bounds.width) < .5 &&
          Math.abs(selected.bounds.height - previous.bounds.height) < .5) return;
      if (selected || previous) {
        active.current = selected;
        setHit(selected);
      }
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(refresh); };
    const move = event => { pointer = { x: event.clientX, y: event.clientY }; schedule(); };
    const clear = () => { pointer = null; if (active.current) { active.current = null; setHit(null); } };
    document.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", clear);
    document.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    // Photo thumbnails, Live Photo images, and the main image may load later.
    document.addEventListener("load", schedule, true);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", clear);
      document.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("load", schedule, true);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [photoId]);

  return hit && createPortal(
    <div className="ll-face-hover-highlight" style={{
      left: hit.bounds.left, top: hit.bounds.top,
      width: hit.bounds.width, height: hit.bounds.height,
    }} aria-hidden="true">
      <span className="ll-face-hover-name">{hit.name}</span>
    </div>,
    document.body
  );
}
