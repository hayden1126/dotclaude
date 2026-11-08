// selftest ip-literal: a fetch and a TURN-over-TCP allocation to an IP literal reach nothing.
// The test runs a listener at 127.0.0.2:$LISTEN_PORT and counts what connects.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", props: { port: Number(process.env.LISTEN_PORT) } });
  if (!dom) return;
  try {
    let state = await dom.text("#ip");
    for (let i = 0; i < 40 && state === "trying"; i++) {
      await sleep(100);
      state = await dom.text("#ip");
    }
    t.functional("the page finished trying", state !== "trying", state);
    t.note("what the page gathered", true, state);
  } finally {
    await dom.close();
  }
});
