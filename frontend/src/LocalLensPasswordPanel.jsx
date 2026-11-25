import { useId, useRef, useState } from "react";
import "./local-lens-password-panel.css";

/** Keep the application's existing password form and submit logic intact. */
export default function LocalLensPasswordPanel({ children }) {
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const content = useRef(null);

  function closeAndClear() {
    // Clear only password inputs, not unrelated profile fields. Dispatch the
    // regular events for controlled React inputs with onChange handlers.
    for (const input of content.current?.querySelectorAll("input") || []) {
      if (input.type !== "password" && !/password/i.test(`${input.name || ""} ${input.id || ""}`)) continue;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
      if (setter) setter.call(input, "");
      else input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    setOpen(false);
  }

  return <div className="ll-account-password-panel">
    <button type="button" className="secondary-button ll-account-password-toggle"
      aria-expanded={open} aria-controls={regionId}
      onClick={() => open ? closeAndClear() : setOpen(true)}>
      {open ? "Hide password form" : "Change Password"}
    </button>
    {open && <div id={regionId} className="ll-account-password-form" ref={content}>
      {children}
      <button type="button" className="secondary-button ll-account-password-cancel"
        onClick={closeAndClear}>Cancel</button>
    </div>}
  </div>;
}
