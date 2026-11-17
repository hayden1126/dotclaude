"use client";

import { useState } from "react";
import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  const [asking, setAsking] = useState<Client | null>(null);
  function finish() {
    if (asking) void deleteClient(asking.id);
    setAsking(null);
  }

  return (
    <>
      <table>
        <tbody>
          {clients.map((client) => (
            <tr key={client.id}>
              <td>{client.name}</td>
              <td><button type="button" onClick={() => setAsking(client)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {asking && (
        <div>
          <p>Delete {asking.name}?</p>
          <button type="button" onClick={finish}>Delete</button>
          <button type="button" onClick={() => setAsking(null)}>Cancel</button>
        </div>
      )}
    </>
  );
}
