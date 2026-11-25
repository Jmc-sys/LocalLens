import LocalLensPasswordPanel from "./LocalLensPasswordPanel";
import AiOperations from "./AiOperations";
import AiPetReview from "./AiPetReview";
import SessionSettings from "./SessionSettings";
import { useEffect, useState } from "react";
import { api, logout } from "./api";
import TrashRetentionSettings from "./TrashRetentionSettings";

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) {
    return "Unlimited";
  }

  const value = Number(bytes);

  if (value < 1024) return `${value} B`;

  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const i = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1
  );

  return `${(value / 1024 ** i).toFixed(2)} ${units[i]}`;
}

function AccountSettings({
  user,
  onUpdate,
}) {
  const [displayName, setDisplayName] =
    useState(user.display_name || "");

  const [email, setEmail] = useState(user.email);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [storage, setStorage] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/users/me/storage")
      .then(setStorage)
      .catch((err) => setError(err.message));
  }, []);

  async function saveProfile(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);

    try {
      await api("/users/me", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: displayName,
          email,
        }),
      });

      const updated = await api("/auth/me");
      onUpdate(updated);

      setMessage("Profile updated successfully.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    setError("");
    setMessage("");

    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }

    setBusy(true);

    try {
      await api("/users/me/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      window.alert(
        "Password changed. Please sign in again."
      );

      logout();

    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const percent = storage?.quota_bytes > 0
    ? storage.used_bytes / storage.quota_bytes * 100
    : 0;

  return (
    <section className="settings-page">
      <h2>Account settings</h2>

      {message && (
        <p className="success-message">{message}</p>
      )}

      {error && (
        <p className="error-message">{error}</p>
      )}

      {storage && (
        <section className="status-card">
          <h2>Your storage</h2>

          <h3>
            {formatBytes(storage.used_bytes)}
            {" / "}
            {formatBytes(storage.quota_bytes)}
          </h3>

          {storage.quota_bytes > 0 && (
            <>
              <div className="storage-track">
                <div
                  className={
                    percent >= 90
                      ? "storage-fill warning"
                      : "storage-fill"
                  }
                  style={{
                    width: `${Math.min(percent, 100)}%`
                  }}
                />
              </div>

              <p>{percent.toFixed(1)}% used</p>
            </>
          )}

          <div className="account-stats">
            <div>
              <strong>
                {storage.total_photos - storage.trash_photos}
              </strong>
              <span>Photos</span>
            </div>

            <div>
              <strong>{storage.total_albums}</strong>
              <span>Albums</span>
            </div>

            <div>
              <strong>{storage.trash_photos}</strong>
              <span>In trash</span>
            </div>

            <div>
              <strong>
                {formatBytes(storage.trash_bytes)}
              </strong>
              <span>Trash storage</span>
            </div>
          </div>
        </section>
      )}

      <section className="status-card settings-card">
        <h2>Personal information</h2>

        <form onSubmit={saveProfile}>
          <label>Username</label>
          <input value={user.username} disabled />

          <label>Account type</label>
          <input value={user.role} disabled />

          <label>Display name</label>
          <input
            value={displayName}
            maxLength={100}
            onChange={(e) =>
              setDisplayName(e.target.value)
            }
          />

          <label>Email address</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <button
            className="primary-button"
            disabled={busy}
          >
            Save profile
          </button>
        </form>
      </section>

      <section className="status-card settings-card">
        <h2>Change password</h2>

        <LocalLensPasswordPanel>
<form onSubmit={changePassword}>
          <label>Current password</label>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) =>
              setCurrentPassword(e.target.value)
            }
            required
          />

          <label>New password</label>
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            minLength={12}
            maxLength={128}
            onChange={(e) =>
              setNewPassword(e.target.value)
            }
            required
          />

          <label>Confirm new password</label>
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) =>
              setConfirmPassword(e.target.value)
            }
            required
          />

          <button
            className="primary-button"
            disabled={busy}
          >
            Change password
          </button>
        </form>
</LocalLensPasswordPanel>
      </section>
 
      <SessionSettings />

      <TrashRetentionSettings />
    </section>
  );
}

// The original Settings component remains unchanged; facial identity review is
// appended only on the user's Settings screen.
export default function SettingsWithAI(props) {
  return <>
    <AiOperations />
    <AiPetReview />
    <AccountSettings {...props} />
  </>;
}
