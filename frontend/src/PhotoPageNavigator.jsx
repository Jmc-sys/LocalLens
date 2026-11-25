import { useEffect, useState } from "react";
import "./photo-page-navigator.css";

/**
 * Accessible, account-neutral pagination for a server-side filtered photo list.
 * pageIndex is zero-based; the UI and jump form are one-based.
 */
export default function PhotoPageNavigator({
  pageIndex,
  pageSize = 100,
  totalItems,
  loading = false,
  hasError = false,
  hasMore = false,
  onChangePage,
}) {
  const current = pageIndex + 1;
  const knownTotal = typeof totalItems === "number" && Number.isFinite(totalItems) && totalItems >= 0;
  const totalPages = knownTotal ? Math.max(1, Math.ceil(totalItems / pageSize)) : null;
  const [pageText, setPageText] = useState(String(current));
  const [pageError, setPageError] = useState("");

  useEffect(() => {
    setPageText(String(current));
    setPageError("");
  }, [current, totalPages]);

  const canPrevious = !loading && !hasError && pageIndex > 0;
  const canNext = !loading && !hasError && (totalPages !== null ? current < totalPages : hasMore);
  const canLast = !loading && !hasError && totalPages !== null && current < totalPages;

  function visit(page) {
    if (loading || hasError || !Number.isSafeInteger(page) || page < 1) return;
    if (totalPages !== null && page > totalPages) return;
    if (page === current) return;
    setPageError("");
    onChangePage(page - 1);
  }

  function submit(event) {
    event.preventDefault();
    const input = pageText.trim();
    if (!/^\d+$/.test(input)) {
      setPageError("Enter a whole page number.");
      return;
    }
    const page = Number(input);
    // Bound the requested offset even if the older backend does not return a count.
    const highestAllowed = totalPages ?? 100000;
    if (!Number.isSafeInteger(page) || page < 1 || page > highestAllowed) {
      setPageError(`Choose a page between 1 and ${highestAllowed.toLocaleString()}.`);
      return;
    }
    visit(page);
  }

  // Show the first and last page, the current page, and nearby pages.
  const values = new Set([1, current]);
  if (totalPages !== null) values.add(totalPages);
  for (let page = Math.max(1, current - 2); page <= current + 2; page++) {
    if (totalPages === null || page <= totalPages) values.add(page);
  }
  const numberedPages = Array.from(values).filter(n => n >= 1 && (totalPages === null || n <= totalPages)).sort((a, b) => a - b);

  return (
    <nav className="ll-page-nav" aria-label="Photo pages">
      <div className="ll-page-nav-buttons">
        <button type="button" className="secondary-button" disabled={!canPrevious} onClick={() => visit(1)} aria-label="First page">First</button>
        <button type="button" className="secondary-button" disabled={!canPrevious} onClick={() => visit(current - 1)}>Previous</button>
        <div className="ll-page-nav-numbers">
          {numberedPages.map((page, i) => (
            <span key={page} className="ll-page-nav-entry">
              {i > 0 && numberedPages[i - 1] < page - 1 && <span className="ll-page-nav-ellipsis" aria-hidden="true">…</span>}
              <button
                type="button"
                className={`secondary-button ${page === current ? "ll-page-nav-active" : ""}`}
                disabled={loading || hasError || page === current}
                onClick={() => visit(page)}
                aria-label={`Page ${page}`}
                aria-current={page === current ? "page" : undefined}
              >{page}</button>
            </span>
          ))}
        </div>
        <button type="button" className="secondary-button" disabled={!canNext} onClick={() => visit(current + 1)}>Next</button>
        {totalPages !== null && <button type="button" className="secondary-button" disabled={!canLast} onClick={() => visit(totalPages)} aria-label="Last page">Last</button>}
      </div>
      <div className="ll-page-nav-jump">
        <span className="ll-page-nav-current">Page {current}{totalPages !== null ? ` of ${totalPages.toLocaleString()}` : ""}</span>
        <form onSubmit={submit} className="ll-page-nav-form">
          <label htmlFor="ll-photo-jump-page">Go to page</label>
          <input
            id="ll-photo-jump-page"
            type="number"
            inputMode="numeric"
            min="1"
            max={totalPages ?? 100000}
            value={pageText}
            disabled={loading || hasError}
            onChange={(event) => { setPageText(event.target.value); setPageError(""); }}
          />
          <button type="submit" className="secondary-button" disabled={loading || hasError}>Go</button>
        </form>
      </div>
      {pageError && <p className="ll-page-nav-error" role="alert">{pageError}</p>}
    </nav>
  );
}
