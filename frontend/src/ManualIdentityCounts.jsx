import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Render a single metric inside Smart Library's primary summary row. */
export default function ManualIdentityCounts() {
  const [count, setCount] = useState(null);
  const [error, setError] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const value = await api("/ai/identity/manual-stats");
      setCount(Number(value.faces_named_by_you || 0));
      setError(false);
    } catch {
      setError(true);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => { if (!document.hidden) void refresh(); }, 60000);
    const onVisible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [refresh]);
  return <span title="Faces manually confirmed by you, excluding automatically named faces">
    <strong>{error ? "—" : count === null ? "…" : count.toLocaleString()}</strong> faces named by you
  </span>;
}
