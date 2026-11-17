"use client";

import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
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
              <button type="button" onClick={() => deleteClient(client.id)}>Delete</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
