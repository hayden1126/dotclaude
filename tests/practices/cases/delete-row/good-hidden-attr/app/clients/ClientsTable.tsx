"use client";

import { useState } from "react";
import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  const [target, setTarget] = useState<Client | null>(null);

  return (
    <>
      <table>
        <tbody>
          {clients.map((client) => (
            <tr key={client.id}>
              <td>{client.name}</td>
              <td><button type="button" onClick={() => setTarget(client)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div hidden={target === null}>
        <p>Delete this client?</p>
        <button type="button" onClick={() => { if (target) void deleteClient(target.id); setTarget(null); }}>Delete</button>
        <button type="button" onClick={() => setTarget(null)}>Cancel</button>
      </div>
    </>
  );
}
