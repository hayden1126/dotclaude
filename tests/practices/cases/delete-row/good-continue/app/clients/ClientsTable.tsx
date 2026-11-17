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
              <td>
                {asking?.id === client.id ? <button type="button" onClick={finish}>Continue</button> : <button type="button" onClick={() => setAsking(client)}>Delete</button>}
                {asking?.id === client.id && <button type="button" onClick={() => setAsking(null)}>Cancel</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
