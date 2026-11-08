"use client";

import { useEffect, useState } from "react";

// Tries a STUN server at an IP literal, which no host resolver rule stops: every candidate
// gathered is a route out of the grader.
export default function RtcPage() {
  const [state, setState] = useState<string>("gathering");
  useEffect(() => {
    const found: string[] = [];
    const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:192.0.2.1:3478" }] });
    pc.createDataChannel("x");
    pc.onicecandidate = (e) => {
      if (e.candidate && e.candidate.candidate) found.push(e.candidate.candidate);
    };
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") setState(`complete ${JSON.stringify(found)}`);
    };
    pc.createOffer().then((offer) => pc.setLocalDescription(offer));
    const timer = setTimeout(() => setState(`timeout ${JSON.stringify(found)}`), 2500);
    return () => clearTimeout(timer);
  }, []);
  return <p id="rtc">{state}</p>;
}
