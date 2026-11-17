// selftest timeout: an oracle that opens a page, plants a long-lived child and never finishes, so
// run.grade's timeout has to clean up. It records its process group and pids in the fixture
// (oracle-pids.json) before it hangs, for the test to check /proc by.
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  const sleeper = spawn("sleep", ["300"], { stdio: "ignore" });
  const group = Number(readFileSync("/proc/self/stat", "utf8").split(") ")[1].split(" ")[2]);
  writeFileSync(path.join(process.env.FIXTURE, "oracle-pids.json"),
    JSON.stringify({ oracle: process.pid, group, sleeper: sleeper.pid, chrome: dom.chrome.child.pid }));
  await new Promise(() => setInterval(() => {}, 1000));
});
