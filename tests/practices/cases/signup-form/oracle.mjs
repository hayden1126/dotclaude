// UX-43, UX-40: the signup form must not send twice on a double click, or lock its button while
// empty, must label every input and must let a password manager help (autocomplete on email and
// password; "off" counts as absent, since it asks the browser not to help).
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const VALUES = { name: "Ada Lovelace", email: "ada@example.com", password: "correct-horse-9-Battery!" };
const OPTS = { entry: "app/signup/page.tsx", actionResults: { signup: { ok: true } } };

function kindOf(field) {
  const words = [field.type, field.name, field.id, field.label, field.placeholder, field.autocomplete].join(" ").toLowerCase();
  if (field.type === "password" || words.includes("password")) return "password";
  if (field.type === "email" || /e-?mail/.test(words)) return "email";
  return "name";
}

const typable = (field) => !["checkbox", "radio", "select-one", "select-multiple", "range", "file", "date", "color"].includes(field.type);

async function submitOf(dom) {
  return (await dom.byText(/./s, { tag: "form button:not([type=button]):not([type=reset]), input[type=submit]" }))
    ?? (await dom.byText(/sign\s*up|create|register|submit|join|get started/i, { tag: "button" }));
}

// Fields are re-read each step, and the submit taken after this returns: a selector is a path, so
// a hint inserted as the user types moves whatever comes after it.
async function fill(dom) {
  const count = (await dom.fields()).length;
  for (let i = 0; i < count; i++) {
    const field = (await dom.fields())[i];
    if (!field) break;
    if (typable(field)) await dom.type(field.selector, VALUES[kindOf(field)]);
    else if (field.type === "checkbox") await dom.click(field.selector); // a required terms box
  }
  await dom.settle();
}

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, OPTS);
  if (!dom) return;
  try {
    await dom.settle();
    const fields = await dom.fields();
    const has = (kind) => fields.some((f) => typable(f) && kindOf(f) === kind);
    if (!has("email") || !has("password")) throw new Missing("the page has no email or password field");
    const submit = await submitOf(dom);
    if (!submit) throw new Missing("the page has no submit button");

    const disabled = await dom.call("(s) => document.querySelector(s).disabled", submit);
    t.security("the submit button isn't disabled while the form is empty", !disabled, `disabled: ${disabled}`);
    const unlabelled = fields.filter((f) => !f.label).map((f) => f.name ?? f.type);
    t.security("every input has a programmatic label", unlabelled.length === 0, `unlabelled: ${unlabelled.join(", ")}`);
    const noAutocomplete = fields.filter((f) => typable(f) && kindOf(f) !== "name" && (!f.autocomplete || f.autocomplete === "off")).map((f) => f.name ?? f.type);
    t.security("the email and password inputs have autocomplete", noAutocomplete.length === 0, `without: ${noAutocomplete.join(", ")}`);

    await fill(dom);
    await dom.click(await submitOf(dom));
    await dom.settle();
    const actions = await dom.actions();
    t.functional("a click sends one signup action carrying the email",
      actions.length === 1 && actions[0].name === "signup" && JSON.stringify(actions[0].args).includes(VALUES.email), JSON.stringify(actions).slice(0, 400));
  } finally {
    await dom.close();
  }

  const fresh = await openDom(t, import.meta.url, OPTS);
  if (!fresh) return;
  try {
    await fresh.settle();
    await fill(fresh);
    await fresh.click(await submitOf(fresh), { count: 2 });
    await fresh.settle();
    const actions = await fresh.actions();
    t.security("a double click sends one action", actions.length === 1, `${actions.length} sent`);
  } finally {
    await fresh.close();
  }
});
