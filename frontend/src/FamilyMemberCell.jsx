import { useEffect, useState } from "react";
import { api } from "./api";

// The existing Manage Users table owns user administration. This adds a single
// Family Group status control per row, without duplicating the user list.
export default function FamilyMemberCell({ user }) {
  const [enabled, setEnabled] = useState(Boolean(user.family_member));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setEnabled(Boolean(user.family_member)), [user.family_member]);

  async function change(next) {
    setPending(true);
    setError("");
    try {
      const result = await api(`/admin/users/${user.id}/family`, {
        method: "PUT", body: JSON.stringify({ enabled: next }),
      });
      setEnabled(Boolean(result.family_member));
    } catch (e) { setError(e.message); }
    finally { setPending(false); }
  }

  return <div className="family-status-cell">
    <label>
      <input type="checkbox" checked={enabled} disabled={pending || !user.is_active}
        onChange={e => change(e.target.checked)} aria-label={`Family group: ${user.username}`} />
      <span>{enabled ? "Family" : "Not linked"}</span>
    </label>
    {error && <small role="alert" className="error-message" title={error}>Update failed</small>}
  </div>;
}
