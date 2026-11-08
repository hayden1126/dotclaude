"use client";

// crypto.randomUUID and crypto.subtle exist only in a secure context, as on a deployed site.
export default function SecurePage() {
  const uuid = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : "none";
  return (
    <div>
      <p id="secure">{String(window.isSecureContext)}</p>
      <p id="uuid">{uuid}</p>
    </div>
  );
}
