"use client";

import { useState } from "react";
import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  const [asking, setAsking] = useState<number | null>(null);

  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {clients.map((client) => (
          <tr key={client.id}>
            <td>{client.name}</td>
            <td>
              {asking === client.id ? (
                <>
                  <button type="button" onClick={() => { void deleteClient(client.id); setAsking(null); }}>Yes, delete</button>
                  <button type="button" onClick={() => setAsking(null)}>Cancel</button>
                </>
              ) : (
                <button type="button" onClick={() => setAsking(client.id)}>Delete</button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
