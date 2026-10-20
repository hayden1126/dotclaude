"use client";

import { useState, type FormEvent } from "react";

type Message = { role: "user" | "assistant"; text: string };

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message) return;
    setMessages((m) => [...m, { role: "user", text: message }]);
    setDraft("");
    setPending(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = (await res.json()) as { reply?: string; error?: string };
      setMessages((m) => [...m, { role: "assistant", text: data.reply ?? data.error ?? "No reply" }]);
    } finally {
      setPending(false);
    }
  }

  return (
    <main>
      <h1>Ask Ledgerly</h1>
      <ul>
        {messages.map((m, i) => (
          <li key={i} data-role={m.role}>
            {m.text}
          </li>
        ))}
      </ul>
      <form onSubmit={handleSubmit}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask about your invoices" />
        <button type="submit" disabled={pending}>
          Send
        </button>
      </form>
    </main>
  );
}
