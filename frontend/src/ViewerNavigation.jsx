import { useEffect, useMemo } from "react";

/** Navigates the currently loaded, ordered gallery items without crossing albums. */
export default function ViewerNavigation({ items = [], currentId, onNavigate, onBeforeFirst = null, onAfterLast = null }) {
  const index = useMemo(
    () => items.findIndex(item => String(item.id) === String(currentId)),
    [items, currentId]
  );
  const previous = index > 0 ? items[index - 1] : null;
  const next = index >= 0 && index < items.length - 1 ? items[index + 1] : null;
  const canBack = !!previous || (index === 0 && !!onBeforeFirst);
  const canForward = !!next || (index === items.length - 1 && !!onAfterLast);

  useEffect(() => {
    function onKeyDown(event) {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.target instanceof HTMLElement &&
          event.target.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft" && canBack) {
        event.preventDefault();
        if (previous) onNavigate(previous);
        else onBeforeFirst?.();
      } else if (event.key === "ArrowRight" && canForward) {
        event.preventDefault();
        if (next) onNavigate(next);
        else onAfterLast?.();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previous, next, onNavigate, onBeforeFirst, onAfterLast, canBack, canForward]);

  return <>
    {canBack && <button type="button" className="ll-viewer-arrow ll-viewer-prev"
      aria-label="Previous photo" title="Previous (←)" onClick={() => previous ? onNavigate(previous) : onBeforeFirst?.()}>‹</button>}
    {canForward && <button type="button" className="ll-viewer-arrow ll-viewer-next"
      aria-label="Next photo" title="Next (→)" onClick={() => next ? onNavigate(next) : onAfterLast?.()}>›</button>}
  </>;
}
