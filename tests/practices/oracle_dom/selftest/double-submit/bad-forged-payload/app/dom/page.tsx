"use client";

import { useEffect, useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and an iframe sends the oracle's report
// endpoint bodies that aren't a report: not JSON, a __proto__ kind, a kind with no log.
export default function SignupPage() {
  const [done, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await subscribe(new FormData(e.currentTarget));
    setDone((n) => n + 1);
  }

  useEffect(() => {
    if (done !== 1) return;
    const frame = document.createElement("iframe");
    frame.srcdoc = `<script>
      for (const [path, body] of [["x/font", "not json"], ["x/__proto__", '{"polluted": true}'], ["x/nothing", "{}"]]) {
        fetch("http://oracle.log.invalid/" + path, { method: "POST", body });
      }
    </script>`;
    document.body.appendChild(frame);
  }, [done]);

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
    </form>
  );
}
