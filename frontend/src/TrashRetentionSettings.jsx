import { useEffect, useState } from "react";
import { api } from "./api";

const OPTIONS = [
  [0, "Never — manual deletion only"],
  [7, "7 days"], [14, "14 days"], [30, "30 days"],
  [60, "60 days"], [90, "90 days"], [180, "180 days"],
  [365, "1 year"],
];

export default function TrashRetentionSettings() {
  const [days, setDays] = useState(0);
  const [custom, setCustom] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api("/trash/settings")
      .then((data) => {
        setDays(data.days);
        setCustom(!OPTIONS.some(([value]) => value === data.days));
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function save(event) {
    event.preventDefault();
    if (!Number.isInteger(days) || days < 0 || days > 3650) {
      setError("Enter 0 (never), or a whole number of days from 1 to 3650.");
      return;
    }
    const warning = days === 0
      ? "Disable automatic deletion?"
      : `Photos that have already been in trash at least ${days} day(s) may be permanently deleted at the next scheduled cleanup. Save this setting?`;
    if (!window.confirm(warning)) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await api("/trash/settings", { method: "PUT", body: JSON.stringify({ days }) });
      setMessage("Trash retention preference saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="status-card settings-card trash-settings">
      <h2>Recycle bin settings</h2>
      <p>Choose how long deleted photos stay recoverable. This applies to your account only.</p>
      <form onSubmit={save}>
        <label htmlFor="trash-retention">Automatically permanently delete photos after</label>
        <select id="trash-retention" disabled={loading || busy} value={custom ? "custom" : String(days)}
          onChange={(e) => {
            if (e.target.value === "custom") { setCustom(true); setDays(30); }
            else { setCustom(false); setDays(Number(e.target.value)); }
          }}>
          {OPTIONS.map(([value, label]) => <option key={value} value={String(value)}>{label}</option>)}
          <option value="custom">Custom number of days...</option>
        </select>
        {custom && <input aria-label="Custom retention days" type="number" min="1" max="3650" step="1" value={days}
          onChange={(e) => setDays(Number(e.target.value))} required />}
        <p className="form-help">Permanent deletion also removes associated media resources. Deleted files cannot be restored from LocalLens.</p>
        <button className="primary-button" disabled={loading || busy}>{busy ? "Saving..." : "Save trash settings"}</button>
      </form>
      {message && <p role="status" className="success-message">{message}</p>}
      {error && <p role="alert" className="error-message">{error}</p>}
    </section>
  );
}
