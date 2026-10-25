"use client";

import { useEffect, useState } from "react";

export default function Guestbook() {
  const [entries, setEntries] = useState([]);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function refresh() {
    const response = await fetch("/api/entries", { cache: "no-store" });
    setEntries(await response.json());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function sign(event) {
    event.preventDefault();
    setSaving(true);
    const response = await fetch("/api/entries", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, message }),
    });
    setSaving(false);
    if (!response.ok) {
      setError((await response.json()).error);
      return;
    }
    const created = await response.json();
    setError("");
    setMessage("");
    setEntries((list) => [created, ...list]);
  }

  return (
    <main>
      <h1>Guestbook</h1>
      <form onSubmit={sign}>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Message
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} />
        </label>
        <button type="submit" disabled={saving}>
          Sign the guestbook
        </button>
        {error && <p role="alert">{error}</p>}
      </form>
      <p data-testid="entry-count">
        {entries.length} {entries.length === 1 ? "entry" : "entries"}
      </p>
      <ul aria-label="Entries">
        {entries.map((entry) => (
          <li key={entry.id}>
            <strong>{entry.name}</strong>
            <span>{entry.message}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
