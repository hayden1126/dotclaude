// selftest webrtc: an RTCPeerConnection with a STUN server at an IP literal gathers no candidates.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    let state = await dom.text("#rtc");
    for (let i = 0; i < 40 && state === "gathering"; i++) {
      await sleep(100);
      state = await dom.text("#rtc");
    }
    t.functional("gathering ended", state !== "gathering", state);
    t.security("no ICE candidate was gathered", /\[\]$/.test(state), state);
  } finally {
    await dom.close();
  }
});
