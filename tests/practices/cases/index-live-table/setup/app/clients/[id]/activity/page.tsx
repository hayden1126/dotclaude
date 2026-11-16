"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { eventsForClient, type ClientEvent } from "@/lib/events";

export default function ClientActivityPage() {
  const { id } = useParams<{ id: string }>();
  const [events, setEvents] = useState<ClientEvent[]>([]);

  useEffect(() => {
    eventsForClient(Number(id)).then(setEvents);
  }, [id]);

  return (
    <main>
      <h1>Activity</h1>
      <ul>{events.map((event) => <li key={event.id}>{event.kind} at {event.created_at}</li>)}</ul>
    </main>
  );
}
