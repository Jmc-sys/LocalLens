import {useEffect, useState } from "react";
import {api, login } from "./api";

export default function Login({onLogin, onRegister }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [registrationEnabled, setRegistrationEnabled] =
    useState(false);

  useEffect(() => {
    api("/users/registration-status")
      .then((data) => {
        setRegistrationEnabled(data.enabled);
      })
      .catch(() => setRegistrationEnabled(false));
  }, []);
  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);

    try {
      const user = await login(username, password);
      onLogin(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-icon">L</span>
          LocalLens
        </a>

        <span className="local-label">
          PRIVATE BY DESIGN
        </span>
      </header>

      <div className="login-layout">
        <section className="welcome-banner">
          <p className="section-label">
            YOUR PHOTOS. YOUR SERVER.
          </p>

          <h1>Every memory,<br />in one place.</h1>

          <p className="intro">
            A photo library built to run locally.
            <br />
            Why rent a cloud, when you can own one?
          </p>
        </section>

        <section className="status-card login-card">
          <p className="section-label">YOUR PRIVATE CLOUD</p>
          <h2>Welcome back</h2>

          <form onSubmit={handleSubmit}>
            <label htmlFor="username">Username</label>

            <input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />

            <label htmlFor="password">Password</label>

            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) =>
                  setShowPassword(e.target.checked)
                }
              />
              Show password
            </label>

            {error && (
              <p className="error-message">{error}</p>
            )}

            <button
              className="primary-button"
              disabled={busy}
            >
              {busy ? "Signing in..." : "Sign in"}
            </button>
            {registrationEnabled && (
              <>
                <div className="form-divider">
                  <span>OR</span>
                </div>

                <button
                  type="button"
                  className="secondary-button"
                  onClick={onRegister}
                >
                  Create an account
                </button>
              </>
            )}
          </form>
        </section>
      </div>

      <footer>
        <span>LocalLens v0.3.0</span>
        <span>Self-hosted photo management</span>
      </footer>
    </main>
  );
}
