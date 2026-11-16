"use client";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
        </tr>
      </thead>
      <tbody>
        {clients.map((client) => (
          <tr key={client.id}>
            <td>{client.name}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
