"use client";

import { useState, type FormEvent } from "react";

const TIMEZONES = ["UTC", "Europe/London", "Europe/Paris", "Europe/Stockholm", "Africa/Lagos", "America/New_York", "Asia/Tokyo"];
const LOCALES = ["en-US", "en-GB", "fr-FR", "sv-SE", "ja-JP"];

export default function SettingsPage() {
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [locale, setLocale] = useState("en-US");
  const [marketingEmails, setMarketingEmails] = useState(false);

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
        <label>
          Avatar URL
          <input type="url" value={avatarUrl} onChange={(e) => setAvatarUrl(e.target.value)} placeholder="https://" />
        </label>
        <label>
          Time zone
          <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
            {TIMEZONES.map((tz) => (
              <option key={tz}>{tz}</option>
            ))}
          </select>
        </label>
        <label>
          Language
          <select value={locale} onChange={(e) => setLocale(e.target.value)}>
            {LOCALES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={marketingEmails} onChange={(e) => setMarketingEmails(e.target.checked)} />
          Send me product news by email
        </label>
        <button type="submit">Save</button>
      </form>
    </main>
  );
}
