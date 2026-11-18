
import { useEffect, useState } from "react";
import { api } from "./api";
import { formatBytes } from "./AccountSettings";

const GIB = 1024 ** 3;

export default function AdminDashboard() {
  const [users, setUsers] = useState([]);
  const [storage, setStorage] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [quota, setQuota] = useState("5");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [accounts, disk, settings] =
        await Promise.all([
          api("/admin/users"),
          api("/admin/storage"),
          api("/admin/settings"),
        ]);

      setUsers(accounts);
      setStorage(disk);
      setEnabled(settings.registration_enabled);

      setQuota(
        String(settings.default_quota_bytes / GIB)
      );
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function action(work, success) {
    setError("");
    setMessage("");
    setBusy(true);

    try {
      await work();
      await load();
      setMessage(success);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function saveSettings(event) {
    event.preventDefault();

    action(
      () => api("/admin/settings", {
        method: "PATCH",
        body: JSON.stringify({
          enabled,
          default_quota_bytes:
            Math.round(Number(quota) * GIB),
        }),
      }),
      "Registration settings saved."
    );
  }

  function changeQuota(user) {
    const value = window.prompt(
      "Storage quota in GiB. Enter unlimited for no quota.",
      user.storage_quota_bytes === null
        ? "unlimited"
        : String(user.storage_quota_bytes / GIB)
    );

    if (value === null) return;

    const input = value.trim().toLowerCase();

    const bytes = input === "unlimited"
      ? null
      : Math.round(Number(input) * GIB);

    if (
      !input ||
      (bytes !== null &&
        (!Number.isSafeInteger(bytes) || bytes < 0))
    ) {
      setError("Enter a valid storage quota.");
      return;
    }

    action(
      () => api(`/admin/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          storage_quota_bytes: bytes,
        }),
      }),
      "Storage quota updated."
    );
  }

  function resetPassword(user) {
    const password = window.prompt(
      `Enter a new password for ${user.username}. ` +
      "Minimum 12 characters."
    );

    if (!password) return;

    if (password.length < 12 || password.length > 128) {
      setError("Password must be 12–128 characters.");
      return;
    }

    action(
      () => api(`/admin/users/${user.id}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
      "User password reset."
    );
  }

  return (
    <section className="settings-page">
      <h2>Administration</h2>

      {message && (
        <p className="success-message">{message}</p>
      )}

      {error && (
        <p className="error-message">{error}</p>
      )}

      {storage && (
        <>
          <div className="admin-stat-grid">
            {[
              ["Registered users", storage.total_users],
              ["Active users", storage.active_users],
              ["Photos stored", storage.total_photos],
              ["Albums created", storage.total_albums],
            ].map(([label, value]) => (
              <div className="status-card" key={label}>
                <p className="section-label">{label}</p>
                <h2>{value}</h2>
              </div>
            ))}
          </div>

          <section className="status-card">
            <h2>Server storage</h2>

            <p>
              {formatBytes(storage.disk_used_bytes)}
              {" used of "}
              {formatBytes(storage.disk_total_bytes)}
            </p>

            <div className="storage-track">
              <div
                className="storage-fill"
                style={{
                  width: `${
                    storage.disk_used_bytes /
                    storage.disk_total_bytes * 100
                  }%`
                }}
              />
            </div>

            <p>
              Available: {formatBytes(storage.disk_free_bytes)}
            </p>

            <p>
              Original photo storage:
              {" "}
              {formatBytes(storage.media_bytes)}
            </p>
          </section>
        </>
      )}

      <section className="status-card settings-card">
        <h2>Registration settings</h2>

        <form onSubmit={saveSettings}>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) =>
                setEnabled(e.target.checked)
              }
            />
            Allow new account registration
          </label>

          <label>Default storage quota (GiB)</label>

          <input
            type="number"
            min="0"
            max="100000"
            step="0.1"
            value={quota}
            onChange={(e) => setQuota(e.target.value)}
            required
          />

          <button
            className="primary-button"
            disabled={busy || !storage}
          >
            Save settings
          </button>
        </form>
      </section>

      <section className="status-card">
        <h2>Manage users</h2>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Role</th>
                <th>Status</th>
                <th>Photos</th>
                <th>Storage used</th>
                <th>Quota</th>
                <th>Actions</th>
              </tr>
            </thead>

            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.username}</strong>
                    <small>{user.email}</small>
                  </td>

                  <td>{user.role}</td>

                  <td>
                    <span className={
                      user.is_active
                        ? "account-active"
                        : "account-disabled"
                    }>
                      {user.is_active
                        ? "Active"
                        : "Disabled"}
                    </span>
                  </td>

                  <td>{user.photo_count}</td>
                  <td>{formatBytes(user.used_bytes)}</td>

                  <td>
                    {formatBytes(
                      user.storage_quota_bytes
                    )}
                  </td>

                  <td>
                    <div className="admin-actions">
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => changeQuota(user)}
                      >
                        Quota
                      </button>

                      {user.role !== "admin" && (
                        <>
                          <button
                            className="secondary-button"
                            disabled={busy}
                            onClick={() => resetPassword(user)}
                          >
                            Reset password
                          </button>

                          <button
                            className="secondary-button"
                            disabled={busy}
                            onClick={() => {
                              if (!window.confirm(
                                `${user.is_active
                                  ? "Disable"
                                  : "Enable"} this account?`
                              )) return;

                              action(
                                () => api(
                                  `/admin/users/${user.id}`,
                                  {
                                    method: "PATCH",
                                    body: JSON.stringify({
                                      is_active:
                                        !user.is_active,
                                    }),
                                  }
                                ),
                                "Account status updated."
                              );
                            }}
                          >
                            {user.is_active
                              ? "Disable"
                              : "Enable"}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
