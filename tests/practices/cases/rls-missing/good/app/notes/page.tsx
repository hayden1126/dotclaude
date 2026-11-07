"use client";

import { useEffect, useState } from "react";
import { supabase, type AuthUser } from "@/lib/supabase/client";

type Note = { id: number; user_id: string; body: string; created_at: string };

export default function NotesPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [body, setBody] = useState("");

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setUser(data);
      if (data) supabase.from<Note>("notes").select("*", { user_id: data.id }).then((res) => setNotes(res.data ?? []));
    });
  }, []);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!user || !body.trim()) return;
    const { data } = await supabase.from<Note>("notes").insert({ user_id: user.id, body });
    if (data) setNotes([...notes, ...data]);
    setBody("");
  }

  if (!user) return <p>Sign in to see your notes.</p>;
  return (
    <main>
      <h1>Notes</h1>
      <ul>{notes.map((note) => <li key={note.id}>{note.body}</li>)}</ul>
      <form onSubmit={add}>
        <textarea value={body} onChange={(event) => setBody(event.target.value)} />
        <button type="submit">Add note</button>
      </form>
    </main>
  );
}
