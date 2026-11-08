"use client";

import { useRef, useState } from "react";
import { deleteClient } from "./actions";

export type Client = { id: number; name: string };

export default function ClientsTable({ clients }: { clients: Client[] }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState<Client | null>(null);

  function ask(client: Client) {
    setTarget(client);
    dialog.current?.showModal();
  }

  function finish() {
    if (target) void deleteClient(target.id);
    dialog.current?.close();
  }

  return (
    <>
      <table>
        <tbody>
          {clients.map((client) => (
            <tr key={client.id}>
              <td>{client.name}</td>
              <td><button type="button" onClick={() => ask(client)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <dialog ref={dialog}>
        <p>Delete this client?</p>
        <button type="button" onClick={finish}>Delete</button>
        <button type="button" onClick={() => dialog.current?.close()}>Cancel</button>
      </dialog>
    </>
  );
}
