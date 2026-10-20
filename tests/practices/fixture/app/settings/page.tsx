"use client";

import { useState, type FormEvent } from "react";

export default function SettingsPage() {
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }

  return (
    <main>
      <h1>Profile</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
        </label>
        <label>
          Bio
          <textarea value={bio} onChange={(e) => setBio(e.target.value)} maxLength={500} rows={4} />
        </label>
        <button type="submit">Save</button>
      </form>
    </main>
  );
}
