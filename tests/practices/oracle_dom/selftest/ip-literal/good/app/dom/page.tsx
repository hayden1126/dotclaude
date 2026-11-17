"use client";

import { useEffect, useState } from "react";

// An IP literal skips the host resolver rule: a fetch to one, and a TURN server over TCP at
// one. The test listens there and counts connections.
export default function IpPage({ port }: { port: number }) {
  const [state, setState] = useState("trying");
  useEffect(() => {
    const found: string[] = [];
    fetch(`http://127.0.0.2:${port}/x`).catch(() => undefined);
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: `turn:127.0.0.2:${port}?transport=tcp`, username: "u", credential: "p" }],
    });
    pc.createDataChannel("x");
    pc.onicecandidate = (e) => {
      if (e.candidate && e.candidate.candidate) found.push(e.candidate.candidate);
    };
    pc.createOffer().then((offer) => pc.setLocalDescription(offer));
    const timer = setTimeout(() => setState(`done ${JSON.stringify(found)}`), 2000);
    return () => clearTimeout(timer);
  }, [port]);
  return <p id="ip">{state}</p>;
}
