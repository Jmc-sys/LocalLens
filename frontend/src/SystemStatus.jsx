import { useEffect, useState } from "react";
import { api } from "./api";

export default function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
  api("/status")
    .then(setStatus)
    .catch((err) => setError(err.message));
  }, []);

  return (
    <main className="page">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-icon">L</span>
          LocalLens
        </a>
        <span className="local-label">PRIVATE BY DESIGN</span>
      </header>

      <section className="welcome-banner">
        <p className="section-label">YOUR PHOTOS. YOUR SERVER.</p>
        <h1>Every memory,<br />in one place.</h1>
        <p className="intro">
          A photo library built to run locally<br />Why rent a cloud, when you can own one?</p>
      </section>

      <section className="status-card">
        <div className="card-heading">
          <div>
            <p className="section-label">UNDER CONSTRUCTION!</p>
            <h2>System Status</h2>
          </div>
          <span className={`status-pill ${status ? "good" : error ? "bad" : ""}`}>
            {status ? "Cloud Online" : error ? "Unavailable" : "Checking…"}
          </span>
        </div>

        <div className="status-grid">
          <div className="status-item">
            <span className="status-dot" />
            <span>React Frontend</span>
            <strong>Running</strong>
          </div>
          <div className="status-item">
            <span className={`status-dot ${error ? "offline" : ""}`} />
            <span>Python API</span>
            <strong>{status ? "Connected" : error ? "Check logs" : "Checking…"}</strong>
          </div>
          <div className="status-item">
            <span className={`status-dot ${error ? "offline" : ""}`} />
            <span>MySQL Database</span>
            <strong>{status?.database ?? (error ? "Check logs" : "Checking…")}</strong>
          </div>
        </div>

        {status && (
          <div className="stats">
            <div>
              <strong>{status.photos}</strong>
              <span>Total Photos Stored</span>
            </div>
            <div>
              <strong>{status.albums}</strong>
              <span>Total Albums Created</span>
            </div>
          </div>
        )}

        {error && (
          <p className="error-message">
            Could not load status: {error}. Check that all Docker services
            are running, then refresh this page.
          </p>
        )}
      </section>

      <footer>
        <span>LocalLens v0.1.0</span>
        <span>Self-hosted photo management</span>
      </footer>
    </main>
  );
}
