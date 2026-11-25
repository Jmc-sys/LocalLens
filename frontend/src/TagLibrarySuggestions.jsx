import { useEffect, useMemo, useState } from "react";
import { api } from "./api";

// Client-side helper only: the API remains the authority for account ownership.
// No automatic merging of distinct concepts; near-spellings are suggestions.
export function comparableTag(tag) {
  return String(tag || "").toLowerCase().trim()
    .replace(/[_\s-]+/g, "-").replace(/^-|-$/g, "");
}

export function tagDistance(a, b, limit = 2) {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const row = [i];
    let lowest = i;
    for (let j = 1; j <= b.length; j += 1) {
      const next = Math.min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      row.push(next);
      lowest = Math.min(lowest, next);
    }
    if (lowest > limit) return limit + 1;
    prev = row;
  }
  return prev[b.length];
}

// Display a small set, prioritizing exact/starts-with/infix matches, then typos.
export function suggestedTags(allTags, draft, photoTags, limit = 8) {
  const current = new Set((photoTags || []).map(t => comparableTag(typeof t === "string" ? t : t.tag)));
  const q = comparableTag(draft);
  const deduped = new Map();
  (allTags || []).forEach(item => {
    const tag = typeof item === "string" ? item : item?.tag;
    const key = comparableTag(tag);
    if (!key || current.has(key)) return;
    const count = Number(typeof item === "string" ? 1 : item.count) || 1;
    const prior = deduped.get(key);
    if (!prior || count > prior.count) deduped.set(key, { tag, count, key });
  });
  return [...deduped.values()].map(item => {
    let priority = 1;
    if (q) {
      if (item.key === q) priority = 5;
      else if (item.key.startsWith(q)) priority = 4;
      else if (item.key.includes(q)) priority = 3;
      else if (q.length >= 4 && tagDistance(item.key, q, q.length > 7 ? 2 : 1) <= (q.length > 7 ? 2 : 1)) priority = 2;
      else priority = 0;
    }
    return { ...item, priority };
  }).filter(item => item.priority).sort((a,b) => b.priority - a.priority || b.count - a.count || a.key.localeCompare(b.key)).slice(0,limit);
}

export default function TagLibrarySuggestions({ draft, photoTags = [], disabled = false, onSelect }) {
  const [library, setLibrary] = useState([]);
  const [problem, setProblem] = useState(false);
  useEffect(() => {
    let alive = true;
    // Shared with search suggestions; only tags owned by the logged-in user.
    api("/ai/tags").then(data => {
      if (alive) { setLibrary(Array.isArray(data) ? data : (data?.tags || [])); setProblem(false); }
    }).catch(() => { if (alive) { setLibrary([]); setProblem(true); } });
    return () => { alive = false; };
  }, []);
  const matches = useMemo(() => suggestedTags(library, draft, photoTags), [library, draft, photoTags]);
  if (!matches.length && !problem) return null;
  return <div className="ll-v615-suggestions" aria-label="Existing tags in your library">
    <small className="ll-v615-suggestions-label">
      {problem ? "Tag suggestions unavailable — you can still add tags" :
        (draft.trim() ? "Use an existing tag instead of creating a near-duplicate" : "Tags already used in your library")}
    </small>
    {!!matches.length && <div className="ll-v615-suggestions-items">
      {matches.map(({tag, count}) => <button type="button" key={tag}
        className="ll-v615-suggestion" onClick={() => onSelect?.(tag)}
        disabled={disabled} title={`Use existing tag: ${tag}`}>
        {tag.replace(/[-_]/g, " ")}<span aria-hidden="true"> · {count}</span>
      </button>)}
    </div>}
  </div>;
}
