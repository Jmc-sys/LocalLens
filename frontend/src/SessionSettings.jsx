import { useEffect, useState } from "react";
import { api, logout } from "./api";
export default function SessionSettings() {
  const [sessions, setSessions] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    try { setSessions(await api("/auth/sessions")); }
    catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, []);
  async function revoke(session) {
    if (!window.confirm("Sign out this session?")) return;
    setBusy(true); setError("");
    try {
      if (session.current) { await logout(); return; }
      await api(`/auth/sessions/${session.id}`, {method: "DELETE"});
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section className="status-card settings-card">
    <h2>Active sessions</h2>
    {error && <p className="error-message">{error}</p>}
    <p>Revoke access from another signed-in browser.</p>
    {sessions.map(session => <div key={session.id} style={{marginBottom: 16}}>
      <strong>{session.current ? "Current session" : "Other session"}</strong>
      <p>Expires: {new Date(session.expires_at.replace(" ", "T") + "Z").toLocaleString()}</p>
      <button className="secondary-button" disabled={busy} onClick={() => revoke(session)}>Sign out session</button>
    </div>)}
  </section>;
}
