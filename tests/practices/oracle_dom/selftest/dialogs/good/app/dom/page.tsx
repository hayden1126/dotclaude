"use client";

import { useState } from "react";
import { deleteRow } from "./actions";

// The usual guards: a confirm before a delete, an alert after an await, a prompt.
export default function DialogPage() {
  const [after, setAfter] = useState("waiting");
  const [name, setName] = useState("waiting");

  function onDelete() {
    if (confirm("Delete this row?")) void deleteRow();
  }

  async function onAlert() {
    await new Promise((resolve) => setTimeout(resolve, 10));
    alert("Saved");
    setAfter("after the alert");
  }

  return (
    <div>
      <button id="delete" type="button" onClick={onDelete}>Delete</button>
      <button id="alert" type="button" onClick={onAlert}>Alert</button>
      <button id="prompt" type="button" onClick={() => setName(String(prompt("Name?")))}>Prompt</button>
      <p id="after">{after}</p>
      <p id="name">{name}</p>
    </div>
  );
}
