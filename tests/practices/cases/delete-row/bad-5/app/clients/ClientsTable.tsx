"use client";

import { useState } from "react";
import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  const [done, setDone] = useState(false);

  return (
    <>
      <table>
        <tbody>
          {clients.map((client) => (
            <tr key={client.id}>
              <td>{client.name}</td>
              <td><button type="button" onClick={() => { void deleteClient(client.id); setDone(true); }}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {done && <p>Deleted. It is impossible to undo this.</p>}
    </>
  );
}
