
import { useState } from "react";
import { api, login } from "./api";

export default function Register({
  onLogin,
  onCancel,
}) {
  const [form, setForm] = useState({
    display_name: "",
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function update(event) {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));
  }

  async function submit(event) {
    event.preventDefault();

    setError("");

    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setBusy(true);

    const username = form.username.trim().toLowerCase();

    try {
      await api("/users/register", {
        method: "POST",
        body: JSON.stringify({
          display_name: form.display_name,
          username,
          email: form.email,
          password: form.password,
        }),
      });

      try {
        const user = await login(
          username,
          form.password
        );

        onLogin(user);

      } catch {
        onCancel();
        window.alert(
          "Account created. Please sign in."
        );
      }

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
            Your memories belong to you.
            <br />
            Create your own private cloud account.
          </p>
        </section>

        <section className="status-card login-card">
          <p className="section-label">
            YOUR PRIVATE CLOUD
          </p>

          <h2>Create your account</h2>

          <form onSubmit={submit}>
            <label>Display name</label>

            <input
              name="display_name"
              value={form.display_name}
              onChange={update}
              autoComplete="name"
              maxLength={100}
              placeholder="Your name"
            />

            <label>Username</label>

            <input
              name="username"
              value={form.username}
              onChange={update}
              autoComplete="username"
              minLength={3}
              maxLength={50}
              required
            />

            <label>Email address</label>

            <input
              name="email"
              type="email"
              value={form.email}
              onChange={update}
              autoComplete="email"
              maxLength={255}
              required
            />

            <label>Password</label>

            <input
              name="password"
              type={showPassword ? "text" : "password"}
              value={form.password}
              onChange={update}
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
              required
            />

            <label>Confirm password</label>

            <input
              name="confirmPassword"
              type={showPassword ? "text" : "password"}
              value={form.confirmPassword}
              onChange={update}
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
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
              Show passwords
            </label>

            <p className="form-help">
              Passwords must contain at least
              12 characters.
            </p>

            {error && (
              <p className="error-message">{error}</p>
            )}

            <button
              className="primary-button"
              disabled={busy}
            >
              {busy
                ? "Creating account..."
                : "Create account"}
            </button>

            <button
              type="button"
              className="text-button"
              onClick={onCancel}
              disabled={busy}
            >
              Already have an account? Sign in
            </button>
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
