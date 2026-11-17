"use client";

import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  async function handleDelete(client: Client) {
    if (!window.confirm(`Delete ${client.name}?`)) return;
    await deleteClient(client.id);
  }

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
              <button type="button" onClick={() => handleDelete(client)}>Delete</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
