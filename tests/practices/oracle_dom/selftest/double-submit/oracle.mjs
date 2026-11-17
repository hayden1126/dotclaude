// selftest double-submit: a double click on the submit button sends the server action once.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.click("button[type=submit]", { count: 2 });
    await dom.settle();
    const actions = await dom.actions();
    t.functional("the form sends the action", actions.length >= 1, JSON.stringify(actions));
    t.functional("the action carries the email", actions[0]?.args[0]?.formData?.some(([k, v]) => k === "email" && v === "a@example.com"), JSON.stringify(actions[0]));
    t.security("a double click sends one action", actions.length === 1, `${actions.length} sent`);
  } finally {
    await dom.close();
  }
});
