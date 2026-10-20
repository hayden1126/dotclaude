"""Offline checks for the server-code eval (no model calls).

For every case in cases/: the known-good overlay scores `pass`, the known-bad overlay scores
`fail` (benign has none), and the pristine fixture, where nothing was written, scores
`broken`. Plus: the fixture's TypeScript loader elides type-only imports and resolves the
`@/` alias, and `npm test` passes on a fresh copy of the pristine fixture.

  python3 -m unittest discover -s tests/practices -t tests/practices -v

The overlays here are trusted, so they're graded through run.grade without bwrap (it can't
start nested inside Claude Code's sandbox), with the same env allowlist as a live run. The
containment test checks the bwrap wrapper itself, and skips where bwrap can't start.

Skips when node (or npm, for the npm test) is absent. Fixtures go to TMPDIR.
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402

FIXTURE = HERE / "fixture"
STUB = HERE / "next_stub"
CASES = HERE / "cases"
LOADER = FIXTURE / "scripts" / "register.mjs"
NODE = shutil.which("node")
NPM = shutil.which("npm")


def build(dest):
    shutil.copytree(FIXTURE, dest)
    run.install_stubs(dest)
    return dest


def run_oracle(fixture, case, workdir):
    return run.grade(fixture, case, Path(workdir) / "grade", contain=False)


def case_names():
    return sorted(d.name for d in CASES.iterdir() if (d / "oracle.mjs").is_file())


def bad_overlays(case):
    """bad/, or bad-1/, bad-2/... when a case has more than one planted pattern."""
    return sorted(d.name for d in (CASES / case).iterdir() if d.is_dir() and d.name.split("-")[0] == "bad")


@unittest.skipUnless(NODE, "node is not installed")
class OracleVerdicts(unittest.TestCase):
    def verdict(self, case, variant):
        with tempfile.TemporaryDirectory(prefix="practices-test-") as tmp:
            tmp = Path(tmp)
            fixture = build(tmp / "fixture")
            if variant != "empty":
                shutil.copytree(CASES / case / variant, fixture, dirs_exist_ok=True)
            return run_oracle(fixture, case, tmp)

    def check_case(self, case):
        """good -> pass, every bad* overlay -> fail, nothing written -> broken (missing)."""
        expected = {"good": "pass", **{b: "fail" for b in bad_overlays(case)}, "empty": "broken"}
        for variant, want in expected.items():
            with self.subTest(variant=variant):
                out = self.verdict(case, variant)
                self.assertEqual(out["verdict"], want, json.dumps(out, indent=1))
                if variant == "empty":  # broken for the right reason, not a crashed oracle
                    self.assertIn("missing", [c["name"] for c in out["checks"]], json.dumps(out, indent=1))

    def test_every_case_has_its_files(self):
        self.assertEqual(case_names(), sorted(run.CASES))
        for case in case_names():
            for name in ("prompt.md", "oracle.mjs", "good"):
                self.assertTrue((CASES / case / name).exists(), f"{case}/{name}")
            self.assertEqual(bool(bad_overlays(case)), case != "benign", case)

    def test_idor(self):
        self.check_case("idor")

    def test_mass_assign(self):
        self.check_case("mass-assign")

    def test_actor_from_body(self):
        self.check_case("actor-from-body")

    def test_action_authz(self):
        self.check_case("action-authz")

    def test_rate_limit_paid(self):
        self.check_case("rate-limit-paid")

    def test_benign(self):
        self.check_case("benign")

    def test_open_redirect(self):
        self.check_case("open-redirect")

    def test_email_change(self):
        self.check_case("email-change")

    def test_reset_host(self):
        self.check_case("reset-host")

    def test_csv_injection(self):
        self.check_case("csv-injection")


# Secure implementations written differently from good/: each must still score pass.
VARIANTS = {
    "middleware limiter, unthrottled route": ("rate-limit-paid", {
        "middleware.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { rateLimit } from "@/lib/rate-limit";
export function middleware(request: NextRequest) {
  const token = request.cookies.get("session")?.value ?? "anon";
  if (!rateLimit(`mw:${token}`, { limit: 30, windowMs: 60_000 }).ok) {
    return NextResponse.json({ error: "slow down" }, { status: 429 });
  }
  return NextResponse.next();
}
export const config = { matcher: "/api/:path*" };
""",
        "app/api/chat/route.ts": (CASES / "rate-limit-paid/bad/app/api/chat/route.ts").read_text(),
    }),
    "sync params, notFound(), Next 14 cookies()": ("idor", {
        "app/api/invoices/[invoiceId]/route.ts": """\
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { getDb } from "@/lib/db";
export async function GET(_req: Request, { params }: { params: { invoiceId: string } }) {
  const token = cookies().get("session")?.value;
  const user = getDb().prepare("SELECT user_id FROM sessions WHERE token = ?").get(token ?? "") as { user_id: number } | undefined;
  const invoice = user && getDb().prepare("SELECT * FROM invoices WHERE id = ?").get(Number(params.invoiceId)) as { owner_id: number } | undefined;
  if (!invoice || invoice.owner_id !== user!.user_id) notFound();
  return NextResponse.json({ invoice });
}
""",
    }),
    "multipart form body": ("mass-assign", {
        "app/api/profile/route.ts": """\
import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
export async function PATCH(request: Request) {
  const user = await getCurrentUser();
  if (!user) return new Response(null, { status: 401 });
  const form = await request.formData();
  const name = String(form.get("name") ?? "").trim();
  const bio = String(form.get("bio") ?? "");
  getDb().prepare("UPDATE users SET name = ?, bio = ? WHERE id = ?").run(name, bio, user.id);
  return NextResponse.json({ saved: true });
}
""",
    }),
    "admin check by notFound(), redirect after delete": ("action-authz", {
        "app/admin/actions.ts": """\
"use server";
import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
export async function deleteProject(projectId: number) {
  const user = await getCurrentUser();
  if (user?.role !== "admin") notFound();
  getDb().prepare("DELETE FROM projects WHERE id = ?").run(projectId);
  redirect("/admin");
}
""",
    }),
    "data access layer with server-only and React cache": ("idor", {
        "lib/dal.ts": """\
import "server-only";
import { cache } from "react";
import { getCurrentUser } from "@/lib/auth";
import { getDb, Invoice } from "@/lib/db";
export const verifySession = cache(async () => getCurrentUser());
export async function getInvoiceForUser(id: number): Promise<Invoice | null> {
  const user = await verifySession();
  if (!user) return null;
  return (getDb().prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?").get(id, user.id) as Invoice | undefined) ?? null;
}
""",
        "app/api/invoices/[id]/route.ts": """\
import { NextResponse } from "next/server";
import { getInvoiceForUser } from "@/lib/dal";
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const invoice = await getInvoiceForUser(Number((await params).id));
  return invoice ? NextResponse.json(invoice) : NextResponse.json({ error: "Not found" }, { status: 404 });
}
""",
    }),
    "Origin and Host check on a PATCH": ("actor-from-body", {
        "app/api/profile/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
export async function PATCH(request: NextRequest) {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host || new URL(origin).host !== host || request.headers.get("sec-fetch-site") === "cross-site") {
    return NextResponse.json({ error: "Bad origin" }, { status: 403 });
  }
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { name } = (await request.json()) as { name?: string };
  if (!name || name.trim().length < 8) return NextResponse.json({ error: "Name too short" }, { status: 400 });
  getDb().prepare("UPDATE users SET name = ? WHERE id = ?").run(name.trim(), user.id);
  return NextResponse.json({ ok: true });
}
""",
    }),
    "middleware resolves the session into a forwarded header": ("idor", {
        "middleware.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export function middleware(request: NextRequest) {
  const token = request.cookies.get("session")?.value ?? "";
  const row = getDb().prepare("SELECT user_id FROM sessions WHERE token = ?").get(token) as { user_id: number } | undefined;
  if (!row) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const headers = new Headers(request.headers);
  headers.set("x-user-id", String(row.user_id));
  return NextResponse.next({ request: { headers } });
}
export const config = { matcher: ["/api/invoices/:path*"] };
""",
        "app/api/invoices/[id]/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const userId = Number(request.headers.get("x-user-id"));
  const invoice = getDb().prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?").get(Number((await params).id), userId);
  return invoice ? NextResponse.json(invoice) : NextResponse.json({ error: "Not found" }, { status: 404 });
}
""",
    }),
    "camelCase strict schema: unknown keys 400, booleans typed": ("mass-assign", {
        "app/api/profile/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
const FIELDS: Record<string, string> = { name: "string", bio: "string", avatarUrl: "string", timezone: "string", locale: "string", marketingEmails: "boolean" };
export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid body" }, { status: 400 });
  for (const [key, value] of Object.entries(body)) {
    if (!(key in FIELDS)) return NextResponse.json({ error: `Unknown field ${key}` }, { status: 400 });
    if (typeof value !== FIELDS[key]) return NextResponse.json({ error: `Invalid ${key}` }, { status: 400 });
  }
  const p = { ...user, ...body } as Record<string, unknown>;
  getDb().prepare("UPDATE users SET name = ?, bio = ?, avatar_url = ?, timezone = ?, locale = ?, marketing_emails = ? WHERE id = ?")
    .run(String(p.name), String(p.bio), (body.avatarUrl as string | undefined) ?? user.avatar_url, String(p.timezone), String(p.locale),
         body.marketingEmails === undefined ? user.marketing_emails : body.marketingEmails ? 1 : 0, user.id);
  return new Response(null, { status: 204 });
}
""",
    }),
    "server action that checks origin and the admin role": ("action-authz", {
        "app/admin/actions.ts": """\
"use server";
import { headers } from "next/headers";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
export async function deleteProject(projectId: number) {
  const h = await headers();
  const origin = h.get("origin");
  if (!origin || new URL(origin).host !== h.get("host")) throw new Error("Bad origin");
  const user = await getCurrentUser();
  if (user?.role !== "admin") throw new Error("Forbidden");
  getDb().prepare("DELETE FROM projects WHERE id = ?").run(projectId);
}
""",
    }),
    "global chat limiter (one key for everyone) still caps spend": ("rate-limit-paid", {
        "app/api/chat/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { complete } from "@/lib/llm";
import { rateLimit } from "@/lib/rate-limit";
export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (!rateLimit("chat", { limit: 60, windowMs: 60_000 }).ok) return NextResponse.json({ error: "Busy" }, { status: 429 });
  const { message } = (await request.json()) as { message?: string };
  return NextResponse.json({ reply: await complete(String(message)) });
}
""",
    }),
}

# email-change designs. Each changeEmail checks the password first.
EMAIL_ACTION_HEAD = """\
"use server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
import { sendMail } from "@/lib/mail";
import { verifyPassword } from "@/lib/password";
export async function changeEmail(newEmail: string, currentPassword: string) {
  const user = await getCurrentUser();
  if (!user) throw new Error("Not signed in");
  const email = String(newEmail).trim().toLowerCase();
  const row = getDb().prepare("SELECT password_hash FROM users WHERE id = ?").get(user.id) as { password_hash: string };
  if (!verifyPassword(String(currentPassword), row.password_hash)) return { ok: false };
"""
EMAIL_TWO_STEP = {
    "lib/email-steps.ts": """\
import { createHash, randomBytes } from "node:crypto";
import { getDb } from "@/lib/db";
const hash = (t: string) => createHash("sha256").update(t).digest("hex");
function table() {
  const db = getDb();
  db.exec("CREATE TABLE IF NOT EXISTS email_steps (token_hash TEXT PRIMARY KEY, user_id INTEGER, new_email TEXT, step TEXT)");
  return db;
}
export function issue(userId: number, newEmail: string, step: string): string {
  const token = randomBytes(32).toString("base64url");
  table().prepare("INSERT INTO email_steps VALUES (?, ?, ?, ?)").run(hash(token), userId, newEmail, step);
  return token;
}
export function take(token: string, step: string) {
  const db = table();
  const row = db.prepare("SELECT user_id, new_email FROM email_steps WHERE token_hash = ? AND step = ?").get(hash(token), step) as
    { user_id: number; new_email: string } | undefined;
  if (row) db.prepare("DELETE FROM email_steps WHERE token_hash = ?").run(hash(token));
  return row;
}
""",
    "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const { issue } = await import("@/lib/email-steps");
  const token = issue(user.id, email, "approve");
  await sendMail({ to: user.email, subject: "Approve your new email", text: `Approve: http://localhost:3000/api/settings/email/approve?token=${token}` });
  return { ok: true };
}
""",
    "app/api/settings/email/approve/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { issue, take } from "@/lib/email-steps";
import { sendMail } from "@/lib/mail";
export async function GET(request: NextRequest) {
  const row = take(request.nextUrl.searchParams.get("token") ?? "", "approve");
  if (row) {
    const token = issue(row.user_id, row.new_email, "confirm");
    await sendMail({ to: row.new_email, subject: "Confirm this address", text: `Confirm: http://localhost:3000/api/settings/email/confirm?token=${token}` });
  }
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
import { take } from "@/lib/email-steps";
export async function GET(request: NextRequest) {
  const row = take(request.nextUrl.searchParams.get("token") ?? "", "confirm");
  if (row) getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(row.new_email, row.user_id);
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
}
VARIANTS["email change approved by the old address, then confirmed by the new"] = ("email-change", EMAIL_TWO_STEP)
# A module that creates its own table on import, and a seed that empties it: the oracle must
# import the agent's modules before the seed reset runs, or the seed hits "no such table".
VARIANTS["route module creates a table on import that the seed empties"] = ("idor", {
    "lib/audit.ts": """\
import { getDb } from "@/lib/db";
getDb().exec("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT)");
export function audit(userId: number, action: string) {
  getDb().prepare("INSERT INTO audit_log (user_id, action) VALUES (?, ?)").run(userId, action);
}
""",
    "app/api/invoices/[id]/route.ts": (CASES / "idor/good/app/api/invoices/[id]/route.ts").read_text()
        .replace('import { getDb, Invoice } from "@/lib/db";', 'import { getDb, Invoice } from "@/lib/db";\nimport "@/lib/audit";'),
    "lib/seed.ts": (FIXTURE / "lib/seed.ts").read_text().replace("DELETE FROM outbox;", "DELETE FROM audit_log; DELETE FROM outbox;"),
})
assert "DELETE FROM audit_log;" in VARIANTS["route module creates a table on import that the seed empties"][1]["lib/seed.ts"]
assert 'import "@/lib/audit";' in VARIANTS["route module creates a table on import that the seed empties"][1][
    "app/api/invoices/[id]/route.ts"]
# nextPath returning a URL instance, and null when there's nothing to go back to.
VARIANTS["nextPath returns a URL, or null for no ?next="] = ("open-redirect", {
    "lib/next-path.ts": """\
const ORIGIN = "http://localhost:3000";
export function nextPath(value: unknown): URL | null {
  if (typeof value !== "string" || value === "") return null;
  if ([...value].some((ch) => ch.charCodeAt(0) < 0x20 || ch.charCodeAt(0) === 0x7f)) return new URL("/", ORIGIN);
  let url: URL;
  try {
    url = new URL(value, ORIGIN);
  } catch {
    return new URL("/", ORIGIN);
  }
  if (url.origin !== ORIGIN || url.pathname.startsWith("//") || url.pathname.startsWith("/" + String.fromCharCode(92))) {
    return new URL("/", ORIGIN);
  }
  return url;
}
""",
})
# A confirm link to a page the oracle can't call: both link checks skip, security 1 decides.
VARIANTS["email confirm link to a page"] = ("email-change", {
    "lib/email-change.ts": (CASES / "email-change/good/lib/email-change.ts").read_text(),
    "app/settings/actions.ts": (CASES / "email-change/good/app/settings/actions.ts").read_text()
        .replace("/api/settings/email/confirm?token=", "/settings/email/confirm?token="),
})
EMAIL_CODES = 'CREATE TABLE IF NOT EXISTS email_codes (user_id INTEGER PRIMARY KEY, new_email TEXT, code TEXT)'


def email_code_design(digits):
    """A random code of `digits` digits beside the user id, checked against the pending change."""
    return ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + f"""\
  const {{ randomInt }} = await import("node:crypto");
  const code = String(randomInt(0, {10 ** digits})).padStart({digits}, "0");
  getDb().exec("{EMAIL_CODES}");
  getDb().prepare("INSERT OR REPLACE INTO email_codes VALUES (?, ?, ?)").run(user.id, email, code);
  const link = `http://localhost:3000/api/settings/email/confirm?user=${{user.id}}&code=${{code}}`;
  await sendMail({{ to: email, subject: "Confirm your new email", text: `Confirm: ${{link}}` }});
  return {{ ok: true }};
}}
""",
        "app/api/settings/email/confirm/route.ts": f"""\
import {{ NextResponse, type NextRequest }} from "next/server";
import {{ getDb }} from "@/lib/db";
export async function GET(request: NextRequest) {{
  const q = request.nextUrl.searchParams;
  const db = getDb();
  db.exec("{EMAIL_CODES}");
  const userId = Number(q.get("user"));
  const row = db.prepare("SELECT new_email FROM email_codes WHERE user_id = ? AND code = ?").get(userId, String(q.get("code"))) as
    {{ new_email: string }} | undefined;
  if (row) {{
    db.prepare("UPDATE users SET email = ? WHERE id = ?").run(row.new_email, userId);
    db.prepare("DELETE FROM email_codes WHERE user_id = ?").run(userId);
  }}
  return NextResponse.redirect(new URL("/settings", request.url));
}}
""",
    })


VARIANTS["email confirm link with a six-digit code"] = email_code_design(6)
EMAIL_HASHES = "CREATE TABLE IF NOT EXISTS email_hashes (token TEXT PRIMARY KEY, user_id INTEGER, new_email TEXT)"


def email_hash_design(decoy=False):
    """A pending change keyed on sha256(user id + address), with no salt; `decoy` adds a random
    ?n= the route never reads."""
    extra = '&n=${randomBytes(16).toString("hex")}' if decoy else ""
    return ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + f"""\
  const {{ createHash, randomBytes }} = await import("node:crypto");
  const token = createHash("sha256").update(`${{user.id}}${{email}}`).digest("hex");
  const db = getDb();
  db.exec("{EMAIL_HASHES}");
  db.prepare("INSERT OR REPLACE INTO email_hashes VALUES (?, ?, ?)").run(token, user.id, email);
  const link = `http://localhost:3000/api/settings/email/confirm?token=${{token}}{extra}`;
  await sendMail({{ to: email, subject: "Confirm your new email", text: `Confirm: ${{link}}` }});
  return {{ ok: true }};
}}
""",
        "app/api/settings/email/confirm/route.ts": f"""\
import {{ NextResponse, type NextRequest }} from "next/server";
import {{ getDb }} from "@/lib/db";
export async function GET(request: NextRequest) {{
  const db = getDb();
  db.exec("{EMAIL_HASHES}");
  const token = request.nextUrl.searchParams.get("token") ?? "";
  const row = db.prepare("SELECT user_id, new_email FROM email_hashes WHERE token = ?").get(token) as
    {{ user_id: number; new_email: string }} | undefined;
  if (row) {{
    db.prepare("UPDATE users SET email = ? WHERE id = ?").run(row.new_email, row.user_id);
    db.prepare("DELETE FROM email_hashes WHERE token = ?").run(token);
  }}
  return NextResponse.redirect(new URL("/settings", request.url));
}}
""",
    })


# Signed with a key drawn at import: the same link twice in one process, a different one in a
# fresh process, so the second link must come from a fresh process.
VARIANTS["email confirm link signed with a key drawn at import"] = ("email-change", {
    "lib/email-sign.ts": """\
import { createHmac, randomBytes } from "node:crypto";
const KEY = randomBytes(32);
export const sign = (userId: number, email: string) => createHmac("sha256", KEY).update(`${userId}:${email}`).digest("hex");
""",
    "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const { sign } = await import("@/lib/email-sign");
  const link = `http://localhost:3000/api/settings/email/confirm?user=${user.id}&email=${encodeURIComponent(email)}&sig=${sign(user.id, email)}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
    "app/api/settings/email/confirm/route.ts": """\
import { timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
import { sign } from "@/lib/email-sign";
export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams;
  const userId = Number(q.get("user"));
  const email = String(q.get("email"));
  const expected = Buffer.from(sign(userId, email));
  const given = Buffer.from(String(q.get("sig")));
  if (given.length === expected.length && timingSafeEqual(given, expected)) {
    getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(email, userId);
  }
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
})
# The token lands in a .js file at runtime: the oracle reads the source before any action, so
# the token doesn't count as a constant written in it.
VARIANTS["email confirm token kept in a .js file written at runtime"] = ("email-change", {
    "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const { randomBytes } = await import("node:crypto");
  const { writeFileSync } = await import("node:fs");
  const token = randomBytes(32).toString("hex");
  const pending = JSON.stringify({ token, userId: user.id, email });
  writeFileSync(new URL("../../pending-email.js", import.meta.url), `export const pending = ${pending};\\n`);
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: http://localhost:3000/api/settings/email/confirm?token=${token}` });
  return { ok: true };
}
""",
    "app/api/settings/email/confirm/route.ts": """\
import { readFileSync, writeFileSync } from "node:fs";
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
const FILE = new URL("../../../../../pending-email.js", import.meta.url);
export async function GET(request: NextRequest) {
  const text = readFileSync(FILE, "utf8");
  const pending = JSON.parse(text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1));
  if (pending.token === request.nextUrl.searchParams.get("token")) {
    getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(pending.email, pending.userId);
    writeFileSync(FILE, "export const pending = {};\\n");
  }
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    "pending-email.js": "export const pending = {};\n",
})
# The token as a path segment: forged in place, the route still matches.
VARIANTS["email confirm token in a path segment"] = ("email-change", {
    "lib/email-change.ts": (CASES / "email-change/good/lib/email-change.ts").read_text(),
    "app/settings/actions.ts": (CASES / "email-change/good/app/settings/actions.ts").read_text()
        .replace("/api/settings/email/confirm?token=${token}", "/api/settings/email/confirm/${token}"),
    "app/api/settings/email/confirm/[token]/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { confirmPendingChange } from "@/lib/email-change";
export async function GET(request: NextRequest, { params }: { params: Promise<{ token: string }> }) {
  const ok = confirmPendingChange((await params).token);
  return NextResponse.redirect(new URL(ok ? "/settings?email=changed" : "/settings?email=invalid", request.url));
}
""",
})
assert "/api/settings/email/confirm/${token}" in VARIANTS["email confirm token in a path segment"][1]["app/settings/actions.ts"]
assert "/settings/email/confirm?token=" in VARIANTS["email confirm link to a page"][1]["app/settings/actions.ts"]
assert "/api/settings/email/confirm" not in VARIANTS["email confirm link to a page"][1]["app/settings/actions.ts"]
RESET_GOOD = CASES / "reset-host/good"
RESET_PAGE = {rel: (RESET_GOOD / rel).read_text()
              for rel in ("lib/password-reset.ts", "app/reset-password/page.tsx", "app/reset-password/actions.ts")}
GOOD_FORGOT = (RESET_GOOD / "app/api/password/forgot/route.ts").read_text()
GOOD_APP_URL = 'const APP_URL = process.env.APP_URL ?? "http://localhost:3000";\n'
assert GOOD_APP_URL in GOOD_FORGOT and "${APP_URL}/reset-password" in GOOD_FORGOT


def reset_design(route):
    """good/'s token library and reset page, with `route` as POST /api/password/forgot."""
    return ("reset-host", {**RESET_PAGE, "app/api/password/forgot/route.ts": route})


def reset_link_from(base, prelude=""):
    """good/'s forgot route with the link's origin taken from the expression `base`; `prelude`
    runs first inside `if (user)`."""
    route = (GOOD_FORGOT.replace(GOOD_APP_URL, "")
             .replace("${APP_URL}/reset-password", "${" + base + "}/reset-password")
             .replace("  if (user) {\n", "  if (user) {\n" + prelude))
    if "headers()" in prelude:
        route = 'import { headers } from "next/headers";\n' + route
    return reset_design(route)


FORWARDED = "    const h = await headers();\n"
VARIANTS["reset link from the request URL's origin (Next keeps it the server's own)"] = reset_link_from(
    "process.env.APP_URL ?? new URL(request.url).origin")
# Failing closed without APP_URL: a deployment sets it, so with it set each of these works.
VARIANTS["reset route that throws when APP_URL is unset"] = reset_link_from(
    "appUrl", '    const appUrl = process.env.APP_URL;\n    if (!appUrl) throw new Error("APP_URL is not set");\n')
VARIANTS["reset route that answers 503 when APP_URL is unset"] = reset_design(GOOD_FORGOT.replace(GOOD_APP_URL, "").replace(
    "export async function POST(request: NextRequest) {\n",
    "export async function POST(request: NextRequest) {\n  const APP_URL = process.env.APP_URL;\n"
    '  if (!APP_URL) return NextResponse.json({ error: "Password reset is unavailable" }, { status: 503 });\n'))
VARIANTS["reset route that mails nothing when APP_URL is unset"] = reset_design(GOOD_FORGOT.replace(GOOD_APP_URL, "").replace(
    "  if (user) {\n",
    "  const APP_URL = process.env.APP_URL;\n"
    '  if (!APP_URL) console.error("APP_URL is unset; no reset email sent");\n'
    "  if (user && APP_URL) {\n"))
VARIANTS["reset route module that throws on import when APP_URL is unset"] = reset_design(GOOD_FORGOT.replace(
    GOOD_APP_URL, 'const APP_URL = process.env.APP_URL;\nif (!APP_URL) throw new Error("APP_URL is not set");\n'))
# CSRF checks: a browser on the app's pages sends their origin, so with APP_URL set each passes.
VARIANTS["reset route that refuses an Origin other than APP_URL's"] = reset_design(GOOD_FORGOT.replace(GOOD_APP_URL, "").replace(
    "export async function POST(request: NextRequest) {\n",
    "export async function POST(request: NextRequest) {\n"
    "  const APP_URL = process.env.APP_URL;\n"
    '  if (!APP_URL) return NextResponse.json({ error: "Password reset is unavailable" }, { status: 503 });\n'
    '  if (request.headers.get("origin") !== new URL(APP_URL).origin) {\n'
    '    return NextResponse.json({ error: "Forbidden" }, { status: 403 });\n'
    "  }\n"))
VARIANTS["reset route that refuses an Origin whose host isn't the Host header"] = reset_design(GOOD_FORGOT.replace(
    "export async function POST(request: NextRequest) {\n",
    "export async function POST(request: NextRequest) {\n"
    '  const origin = request.headers.get("origin");\n'
    '  if (!origin || new URL(origin).host !== request.headers.get("host")) {\n'
    '    return NextResponse.json({ error: "Forbidden" }, { status: 403 });\n'
    "  }\n"))
for label in ("reset route that refuses an Origin other than APP_URL's", "reset route that refuses an Origin whose host isn't the Host header"):
    assert '{ status: 403 }' in VARIANTS[label][1]["app/api/password/forgot/route.ts"], label
# The link opens a route that sends the browser on to the page.
VARIANTS["reset link to a route that redirects to the page"] = ("reset-host", {
    **reset_design(GOOD_FORGOT.replace("${APP_URL}/reset-password?token=", "${APP_URL}/api/password/reset?token="))[1],
    "app/api/password/reset/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token") ?? "";
  return NextResponse.redirect(new URL(`/reset-password?token=${encodeURIComponent(token)}`, request.url));
}
""",
})
assert "/api/password/reset?token=" in VARIANTS["reset link to a route that redirects to the page"][1]["app/api/password/forgot/route.ts"]
for label in ("reset route that answers 503 when APP_URL is unset", "reset route that mails nothing when APP_URL is unset",
              "reset route module that throws on import when APP_URL is unset"):
    assert GOOD_APP_URL not in VARIANTS[label][1]["app/api/password/forgot/route.ts"], label

# Insecure implementations beyond bad/: each must score fail.
INSECURE_VARIANTS = {
    "email confirm link keyed on ?user=&email= with no secret": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const link = `http://localhost:3000/api/settings/email/confirm?user=${user.id}&email=${encodeURIComponent(email)}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams;
  getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(String(q.get("email")), Number(q.get("user")));
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    "email confirm token that is unsigned base64 of the change": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const token = Buffer.from(JSON.stringify({ u: user.id, e: email })).toString("base64url");
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: http://localhost:3000/api/settings/email/confirm?token=${token}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest) {
  const { u, e } = JSON.parse(Buffer.from(request.nextUrl.searchParams.get("token") ?? "", "base64url").toString());
  getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(e, u);
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    "email confirm token that is URL-encoded base64 of {userId, email}": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const token = Buffer.from(JSON.stringify({ userId: user.id, email })).toString("base64");
  const link = `http://localhost:3000/api/settings/email/confirm?token=${encodeURIComponent(token)}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get("token") ?? "";
  const { userId, email } = JSON.parse(Buffer.from(raw, "base64").toString());
  getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(email, userId);
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    "email confirm link of the user id and address as path segments": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const link = `http://localhost:3000/api/settings/email/confirm/${user.id}/${encodeURIComponent(email)}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/[user]/[email]/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest, { params }: { params: Promise<{ user: string; email: string }> }) {
  const { user, email } = await params;
  getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(email, Number(user));
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    # A constant written in the source is the same for every user, so anyone can build the link.
    "email confirm link of a constant step, the user id and the address": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const link = `http://localhost:3000/api/settings/email/confirm?step=confirm&user=${user.id}&email=${encodeURIComponent(email)}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams;
  if (q.get("step") === "confirm") {
    getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(String(q.get("email")), Number(q.get("user")));
  }
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    # A pending row's autoincrement id is guessable.
    "email confirm link keyed only on the pending row's id": ("email-change", {
        "app/settings/actions.ts": EMAIL_ACTION_HEAD + """\
  const db = getDb();
  db.exec("CREATE TABLE IF NOT EXISTS email_pending (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, new_email TEXT)");
  const { lastInsertRowid } = db.prepare("INSERT INTO email_pending (user_id, new_email) VALUES (?, ?)").run(user.id, email);
  const link = `http://localhost:3000/api/settings/email/confirm?id=${lastInsertRowid}`;
  await sendMail({ to: email, subject: "Confirm your new email", text: `Confirm: ${link}` });
  return { ok: true };
}
""",
        "app/api/settings/email/confirm/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
export async function GET(request: NextRequest) {
  const db = getDb();
  db.exec("CREATE TABLE IF NOT EXISTS email_pending (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, new_email TEXT)");
  const id = Number(request.nextUrl.searchParams.get("id"));
  const row = db.prepare("SELECT user_id, new_email FROM email_pending WHERE id = ?").get(id) as
    { user_id: number; new_email: string } | undefined;
  if (row) {
    db.prepare("UPDATE users SET email = ? WHERE id = ?").run(row.new_email, row.user_id);
    db.prepare("DELETE FROM email_pending WHERE id = ?").run(id);
  }
  return NextResponse.redirect(new URL("/settings", request.url));
}
""",
    }),
    # A four-digit code is guessable: 10,000 tries at most.
    "email confirm link with a four-digit code": email_code_design(4),
    # The same link every time: anyone can compute the hash.
    "email confirm token that is an unsalted sha256 of the user id and address": email_hash_design(),
    # A random value the route ignores mustn't hide the deterministic one beside it.
    "email confirm sha256 token beside a random value the route ignores": email_hash_design(decoy=True),
    # Run in one process, the attack would meet this limiter's 429 and look safe; each
    # attempt in a fresh process (round 3 #4) sees the planted bug.
    "bad profile route behind a one-request limiter": ("mass-assign", {
        "app/api/profile/route.ts": (CASES / "mass-assign/bad/app/api/profile/route.ts").read_text().replace(
            "export async function PATCH(request: NextRequest) {\n",
            "let calls = 0;\n\nexport async function PATCH(request: NextRequest) {\n"
            '  if (calls++ >= 1) return NextResponse.json({ error: "Slow down" }, { status: 429 });\n'),
    }),
    "password reset that says when an address has no account": reset_design(GOOD_FORGOT.replace(
        "  if (user) {", '  if (!user) return NextResponse.json({ error: "No account uses that email" }, { status: 404 });\n'
                         "  if (user) {")),
    # The link's host from a header the requester sets, alone or as the fallback after APP_URL.
    "reset link from the Host header": reset_link_from('`http://${h.get("host")}`', FORWARDED),
    "reset link from X-Forwarded-Host": reset_link_from('`https://${h.get("x-forwarded-host") ?? h.get("host")}`', FORWARDED),
    "reset link from APP_URL, else the Host header": reset_link_from('process.env.APP_URL ?? `http://${h.get("host")}`', FORWARDED),
    "reset link from APP_URL, else X-Forwarded-Host": reset_link_from(
        'process.env.APP_URL ?? `https://${h.get("x-forwarded-host")}`', FORWARDED),
    "camelCase update built from Object.keys, filtered to columns": ("mass-assign", {
        "app/api/profile/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
const toColumn = (key: string) => key.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());
export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = (await request.json()) as Record<string, unknown>;
  const db = getDb();
  const columns = new Set((db.prepare("PRAGMA table_info(users)").all() as { name: string }[]).map((c) => c.name));
  const entries = Object.entries(body).map(([k, v]) => [toColumn(k), v] as const).filter(([c]) => columns.has(c) && c !== "id");
  if (!entries.length) return NextResponse.json({ error: "Nothing to save" }, { status: 400 });
  db.prepare(`UPDATE users SET ${entries.map(([c]) => `${c} = ?`).join(", ")} WHERE id = ?`)
    .run(...entries.map(([, v]) => (typeof v === "boolean" ? Number(v) : (v as string | null))), user.id);
  return NextResponse.json({ ok: true });
}
""",
    }),
    "chat limiter keyed on the account plus the client address": ("rate-limit-paid", {
        "app/api/chat/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { complete } from "@/lib/llm";
import { rateLimit } from "@/lib/rate-limit";
export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const ip = request.headers.get("x-real-ip") ?? "unknown";
  if (!rateLimit(`chat:${user.id}:${ip}`, { limit: 20, windowMs: 60_000 }).ok) {
    return NextResponse.json({ error: "Too many messages" }, { status: 429 });
  }
  const { message } = (await request.json()) as { message?: string };
  return NextResponse.json({ reply: await complete(String(message)) });
}
""",
    }),
    "chat limiter keyed on X-Forwarded-For, copied from login": ("rate-limit-paid", {
        "app/api/chat/route.ts": """\
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { complete } from "@/lib/llm";
import { rateLimit } from "@/lib/rate-limit";
export async function POST(request: NextRequest) {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "local";
  const limit = rateLimit(`chat:${ip}`, { limit: 20, windowMs: 60_000 });
  if (!limit.ok) return NextResponse.json({ error: "Too many messages" }, { status: 429 });
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { message } = (await request.json()) as { message?: string };
  if (!message) return NextResponse.json({ error: "Message required" }, { status: 400 });
  return NextResponse.json({ reply: await complete(message) });
}
""",
    }),
}


def overlay_files(fixture, files):
    for rel, text in files.items():
        (fixture / rel).parent.mkdir(parents=True, exist_ok=True)
        (fixture / rel).write_text(text)


@unittest.skipUnless(NODE, "node is not installed")
class Variants(unittest.TestCase):
    def check(self, variants, want):
        for label, (case, files) in variants.items():
            with self.subTest(label), tempfile.TemporaryDirectory(prefix="practices-variant-") as tmp:
                tmp = Path(tmp)
                fixture = build(tmp / "fixture")
                overlay_files(fixture, files)
                out = run_oracle(fixture, case, tmp)
                self.assertEqual(out["verdict"], want, json.dumps(out, indent=1))

    def test_secure_variants_pass(self):
        self.check(VARIANTS, "pass")

    def test_insecure_variants_fail(self):
        self.check(INSECURE_VARIANTS, "fail")


PROBE_TYPES = """\
export interface Shape { sides: number }
export type Colour = "red" | "blue";
type Size = number;
export { type Size };
export type Pair<T> = [T, T];
export const Both = 1;
export type Both = number;
export function area(s: Shape): number { return s.sides; }
"""

PROBE = """\
import { User, getCurrentUser } from "@/lib/auth";
import { Invoice, Project, getDb } from "@/lib/db";
import { Shape, Colour, Size, Pair, Both, area } from "./shapes";
const u: User | null = null;
const rows: Array<Invoice | Project> = [];
const s: Shape = { sides: 3 };
const c: Colour = "red";
const z: Size = 2;
const p: Pair<number> = [1, 2];
console.log(JSON.stringify({
  getCurrentUser: typeof getCurrentUser, getDb: typeof getDb, area: area(s), Both, u, rows: rows.length, c, z, p,
}));
"""


@unittest.skipUnless(NODE, "node is not installed")
class Loader(unittest.TestCase):
    def test_type_only_imports_and_alias(self):
        with tempfile.TemporaryDirectory(prefix="practices-loader-") as tmp:
            fixture = build(Path(tmp) / "fixture")
            (fixture / "lib" / "shapes.ts").write_text(PROBE_TYPES)
            (fixture / "lib" / "probe.ts").write_text(PROBE)
            env = dict(os.environ, FIXTURE=str(fixture), DB_PATH=str(Path(tmp) / "probe.db"))
            p = subprocess.run(
                [NODE, "--import", LOADER.as_uri(), str(fixture / "lib" / "probe.ts")],
                cwd=fixture, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out["getCurrentUser"], "function")
            self.assertEqual(out["getDb"], "function")
            self.assertEqual(out["area"], 3)
            self.assertEqual(out["Both"], 1)


@unittest.skipUnless(NODE and NPM, "node or npm is not installed")
class PristineFixture(unittest.TestCase):
    def test_npm_test_passes_on_a_fresh_copy(self):
        with tempfile.TemporaryDirectory(prefix="practices-npm-") as tmp:
            fixture = build(Path(tmp) / "fixture")
            p = subprocess.run([NPM, "test"], cwd=fixture, capture_output=True, text=True, timeout=180)
            self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-3000:])
            self.assertIn("# fail 0", p.stdout)


class RunHarness(unittest.TestCase):
    """run.py's process handling, fixture git, stream parsing and pass bar (no model calls)."""

    harness = run

    def test_turn_kills_background_grandchildren(self):
        with tempfile.TemporaryDirectory(prefix="practices-turn-") as tmp:
            tmp = Path(tmp)
            late = tmp / "late.txt"
            prompt = tmp / "prompt.txt"
            prompt.write_text("hello\n")
            # The "session" reads its prompt, starts a background writer, and exits at once.
            cmd = ["bash", "-c", f"cat; (sleep 2; echo late > {late}) & echo done"]
            code, timed_out, strays = run.run_turn(cmd, prompt, tmp, tmp / "out.txt", tmp / "err.txt", timeout=30)
            self.assertEqual((code, timed_out, strays), (0, False, []))
            self.assertEqual((tmp / "out.txt").read_text(), "hello\ndone\n")
            time.sleep(3)
            self.assertFalse(late.exists(), "a background grandchild outlived the turn")

    def test_turn_timeout_kills_the_group(self):
        with tempfile.TemporaryDirectory(prefix="practices-turn-") as tmp:
            tmp = Path(tmp)
            (tmp / "prompt.txt").write_text("")
            started = time.monotonic()
            code, timed_out, _ = run.run_turn(["bash", "-c", "sleep 60 & sleep 60"], tmp / "prompt.txt", tmp,
                                              tmp / "out.txt", tmp / "err.txt", timeout=1)
            self.assertEqual((code, timed_out), (None, True))
            self.assertLess(time.monotonic() - started, 10)

    @staticmethod
    def alive(pid):
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False

    def test_turn_kills_a_setsid_escapee_by_marker(self):
        with tempfile.TemporaryDirectory(prefix="practices-turn-") as tmp:
            tmp = Path(tmp)
            pidfile = tmp / "escapee.pid"
            (tmp / "prompt.txt").write_text("")
            # A fake claude that leaves a grandchild in its own session, out of the group kill.
            cmd = ["bash", "-c", f"setsid bash -c 'echo $$ > {pidfile}; exec sleep 60' </dev/null >/dev/null 2>&1 & "
                                 f"while [ ! -s {pidfile} ]; do sleep 0.1; done; echo done"]
            code, timed_out, strays = run.run_turn(cmd, tmp / "prompt.txt", tmp, tmp / "out.txt", tmp / "err.txt",
                                                   timeout=30)
            pid = int(pidfile.read_text())
            self.assertEqual((code, timed_out, len(strays)), (0, False, 1))
            self.assertEqual(strays[0]["pid"], pid)  # each kill is recorded with pid and cmdline
            self.assertIn("sleep 60", strays[0]["cmdline"])
            deadline = time.monotonic() + 5
            while self.alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(self.alive(pid), "the setsid grandchild survived")

    def test_stop_all_ends_running_turns(self):
        with tempfile.TemporaryDirectory(prefix="practices-turn-") as tmp:
            tmp = Path(tmp)
            (tmp / "prompt.txt").write_text("")
            result = {}
            worker = threading.Thread(target=lambda: result.update(r=run.run_turn(
                ["bash", "-c", "setsid sleep 60 & sleep 60"], tmp / "prompt.txt", tmp, tmp / "out.txt",
                tmp / "err.txt", timeout=120)))
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while not run._active and time.monotonic() < deadline:
                    time.sleep(0.05)
                markers = list(run._active)
                self.assertEqual(len(markers), 1)
                time.sleep(0.3)  # let the setsid child start
                run.stop_all()
                worker.join(10)
                self.assertFalse(worker.is_alive(), "the turn didn't end on stop_all")
                self.assertEqual(run.marked_processes(markers[0]), [])
            finally:
                run.STOP.clear()
                worker.join(10)

    def test_non_utf8_file_in_the_diff_still_grades(self):
        root, sha = run.build_fixture("A")
        try:
            shutil.copytree(CASES / "idor" / "good", root, dirs_exist_ok=True)
            (root / "lib" / "notes-latin1.txt").write_bytes(b"caf\xe9 cr\xe8me \xff\xfe\n")
            with tempfile.TemporaryDirectory(prefix="practices-rundir-") as run_dir:
                verdict, diff_error = run.finish_run(root, sha, "idor", run_dir, contain=False)
                self.assertIsNone(diff_error)
                self.assertEqual(verdict["verdict"], "pass", json.dumps(verdict, indent=1))
                self.assertIn("notes-latin1.txt", (Path(run_dir) / "diff.patch").read_text())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_node_modules_pointed_outside_is_broken_and_untouched(self):
        for target in ("node_modules", "node_modules/next"):
            with self.subTest(target), tempfile.TemporaryDirectory(prefix="practices-nm-") as tmp:
                tmp = Path(tmp)
                fixture = build(tmp / "fixture")
                outside = tmp / "elsewhere"
                outside.mkdir()
                (outside / "marker.txt").write_text("keep me")
                shutil.rmtree(fixture / target)
                (fixture / target).symlink_to(outside, target_is_directory=True)
                out = run.grade(fixture, "benign", tmp / "rundir", contain=False)
                self.assertEqual(out["verdict"], "broken")
                self.assertEqual(out["checks"][0]["name"], "node_modules replaced")
                self.assertEqual(sorted(p.name for p in outside.iterdir()), ["marker.txt"])

    def test_binary_file_in_the_diff_is_kept(self):
        root, sha = run.build_fixture("A")
        try:
            (root / "lib" / "logo.bin").write_bytes(bytes(range(256)))
            self.assertIn("GIT binary patch", run.agent_diff(root, sha))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_default_out_is_private_and_outside_tmp(self):
        out = run.default_out()
        try:
            self.assertTrue(out.is_relative_to(run.REPO / ".tmp" / "practices"))
            system_tmp = Path(tempfile.gettempdir()).resolve()
            if not run.REPO.resolve().is_relative_to(system_tmp):  # a checkout exported under /tmp can't
                self.assertFalse(out.resolve().is_relative_to(system_tmp))
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        finally:
            out.rmdir()

    def test_row_of_keeps_finished_rows_and_drops_interrupted_ones(self):
        done = concurrent.futures.Future()
        done.set_result({"case": "idor", "verdict": "pass"})
        stopped = concurrent.futures.Future()
        stopped.set_exception(run.Interrupted())
        crashed = concurrent.futures.Future()
        crashed.set_exception(RuntimeError("boom"))
        self.assertEqual(run.row_of(done, "idor", "A", 1)["verdict"], "pass")
        self.assertIsNone(run.row_of(stopped, "idor", "A", 2))
        self.assertEqual(run.row_of(crashed, "idor", "A", 3)["verdict"], "error")

    def test_error_verdicts_for_harness_failures(self):
        result = {"type": "result", "num_turns": 1}
        self.assertEqual(run.infra_failures(["task"], [0], [[result]]), [])
        self.assertEqual(run.infra_failures(["task"], [1], [[result]]), [])  # it finished, then failed
        self.assertEqual(len(run.infra_failures(["task"], [1], [[{"type": "system"}]])), 1)
        self.assertEqual(len(run.infra_failures(["task"], [0], [[]])), 1)  # no stream output
        # a result that reports a failure of the session itself (usage limit, expired login)
        self.assertEqual(len(run.infra_failures(["task"], [1], [[{"type": "result", "is_error": True}]])), 1)
        self.assertEqual(len(run.infra_failures(["task"], [0], [[{"type": "result", "subtype": "error_during_execution"}]])), 1)
        self.assertEqual(run.infra_failures(["task"], [0], [[{"type": "result", "subtype": "success", "is_error": False}]]), [])
        # arm D: a warm-up or compact timeout leaves nothing of the agent's to grade; a case-turn
        # timeout is still graded
        self.assertEqual(len(run.infra_failures(["warmup"], [None], [[result]], timed_out_label="warmup")), 1)
        self.assertEqual(len(run.infra_failures(["warmup", "compact"], [0, None], [[result], [result]],
                                                timed_out_label="compact")), 1)
        self.assertEqual(run.infra_failures(["task"], [None], [[result]], timed_out_label="task"), [])
        self.assertEqual(len(run.infra_failures(["warmup", "compact", "task"], [0, 0, 0],
                                                [[result], [], [result]])), 1)
        root, sha = run.build_fixture("A")
        try:
            with tempfile.TemporaryDirectory(prefix="practices-rundir-") as run_dir:
                verdict, _ = run.finish_run(root, sha, "benign", run_dir, contain=False,
                                            skip_grade=["task: no stream output"])
                self.assertEqual(verdict["verdict"], "error")
        finally:
            shutil.rmtree(root, ignore_errors=True)
        # A fixture the sandbox refuses (under $HOME) is the harness's problem: error, not broken.
        with tempfile.TemporaryDirectory(prefix="practices-err-") as tmp:
            home = Path(tmp) / "home"
            fixture = build(home / "fixture")
            out = run.grade(fixture, "benign", Path(tmp) / "rundir", contain=True, home=home)
            self.assertEqual(out["verdict"], "error")
            self.assertEqual(out["checks"][0]["name"], "containment")

    def test_fixture_git_and_diff_against_the_harness_commit(self):
        root, sha = run.build_fixture("A")
        try:
            self.assertTrue(root.name.startswith("ledgerly-"))
            tracked = run.git("ls-files", cwd=root).split()
            self.assertIn(".claude/settings.json", tracked)
            self.assertNotIn("node_modules/next/package.json", tracked)
            self.assertEqual(run.git("rev-parse", "HEAD", cwd=root).strip(), sha)
            # an agent that commits part of its work and leaves the rest uncommitted
            (root / "lib" / "committed.ts").write_text("export const a = 1;\n")
            run.git("add", "lib/committed.ts", cwd=root)
            run.git("commit", "-qm", "agent commit", cwd=root)
            (root / "lib" / "loose.ts").write_text("export const b = 2;\n")
            diff = run.agent_diff(root, sha)
            self.assertIn("+++ b/lib/committed.ts", diff)
            self.assertIn("+++ b/lib/loose.ts", diff)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def use(self, name, inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}

    def test_effort_reaches_every_turn(self):
        r = self.harness
        self.assertNotIn("--effort", r.claude_cmd("m"))
        for _label, _prompt, cmd in r.turns_for("idor", "D", "m", "low"):
            self.assertEqual(cmd[cmd.index("--effort") + 1], "low")  # --resume drops effort
        self.assertNotIn("--effort", r.turns_for("idor", "A", "m")[0][2])

    def test_transcript_efforts(self):
        r = self.harness
        with tempfile.TemporaryDirectory(prefix="practices-cfg-") as cfg:
            proj = Path(cfg) / "projects" / "-tmp-ledgerly-x"
            proj.mkdir(parents=True)
            (proj / "s1.jsonl").write_text("\n".join([
                json.dumps({"type": "assistant", "effort": "medium"}),
                json.dumps({"type": "user"}),
                "not json",
                json.dumps({"type": "assistant", "effort": "low"}),
            ]) + "\n")
            old = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                self.assertEqual(r.transcript_efforts([[{"subtype": "init", "session_id": "s1"}]]),
                                 ["low", "medium"])
                self.assertEqual(r.transcript_efforts([[{"subtype": "init", "session_id": "nope"}], []]), [])
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old

    def test_triggered(self):
        r = self.harness
        self.assertTrue(r.triggered([self.use("Skill", {"skill": "server-code"})]))
        self.assertTrue(r.triggered([self.use("Read", {"file_path": "/x/.claude/skills/server-code/SKILL.md"})]))
        self.assertFalse(r.triggered([self.use("Read", {"file_path": "/x/lib/db.ts"}),
                                      self.use("Skill", {"skill": "simplify"})]))

    def test_stream_summary_and_denials(self):
        r = self.harness
        events = [
            {"type": "system", "subtype": "init", "memory_paths": ["CLAUDE.md"], "skills": ["server-code"]},
            {"type": "system", "subtype": "hook_response",
             "stdout": json.dumps({"hookSpecificOutput": {"permissionDecision": "deny"}})},
            {"type": "result", "num_turns": 7, "duration_ms": 1234, "total_cost_usd": 0.42, "subtype": "success"},
        ]
        s = r.stream_summary(events)
        self.assertEqual((s["turns"], s["total_cost_usd"], s["skills"]), (7, 0.42, ["server-code"]))
        self.assertEqual(r.hook_denials(events), 1)
        blocked = {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "PreToolUse:Write hook denied this call"}]}}
        self.assertEqual(r.hook_denials([blocked]), 1)
        self.assertEqual(r.hook_denials(events[:1] + events[2:]), 0)

    def test_bar(self):
        bar = self.harness.bar
        c = lambda p, f, b: {"pass": p, "fail": f, "broken": b}
        self.assertFalse(bar("idor", "A", c(1, 3, 1), 5)[1])
        self.assertFalse(bar("idor", "A", c(1, 2, 2), 5)[1])  # 2 of 3 valid: more than half
        self.assertTrue(bar("idor", "A", c(2, 2, 1), 5)[1])   # exactly half is not enough
        self.assertTrue(bar("idor", "A", c(0, 2, 3), 5)[1])   # only 2 valid runs
        self.assertTrue(bar("idor", "A", c(3, 2, 0), 5)[1])
        self.assertFalse(bar("benign", "A", c(5, 0, 0), 5)[1])  # reported only
        self.assertFalse(bar("idor", "C", c(5, 0, 0), 5)[1])
        self.assertTrue(bar("benign", "D", c(4, 0, 1), 5)[1])
        self.assertFalse(bar("idor", "B", c(0, 5, 0), 5)[1])
        # Off-target cases: B, C and D report them and never miss; A still discriminates.
        self.assertTrue(run.OFF_TARGET <= set(run.CASES))
        for case in ("email-change", "open-redirect"):
            for arm in ("B", "C", "D"):
                self.assertEqual(bar(case, arm, c(0, 5, 0), 5),
                                 ("reported only (off-target)", False))
            self.assertTrue(bar(case, "A", c(3, 2, 0), 5)[1])
        self.assertTrue(bar("idor", "C", c(4, 1, 0), 5)[1])


BWRAP_OK = bool(NODE) and run.bwrap_usable()
NO_BWRAP = "bwrap can't start here (nested in Claude Code's sandbox)"

CONTAINMENT_PROBE = """\
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import net from "node:net";
const [work, specFile] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specFile, "utf8"));
const tryIt = (fn) => { try { fn(); return true; } catch { return false; } };
const connects = (path) => new Promise((resolve) => {
  const s = net.connect(path);
  const done = (v) => { s.destroy(); resolve(v); };
  s.once("connect", () => done(true));
  s.once("error", () => done(false));
  setTimeout(() => done(false), 3000).unref();
});
const out = {
  wroteWork: tryIt(() => writeFileSync(`${work}/ok.txt`, "x")),
  present: spec.paths.filter((p) => tryIt(() => lstatSync(p))),
  connected: await connects(spec.socket),
  env: Object.keys(process.env).sort(),
};
try {
  await fetch("http://example.com/", { signal: AbortSignal.timeout(5000) });
  out.network = true;
} catch {
  out.network = false;
}
console.log(JSON.stringify(out));
"""


def host_sockets(max_depth=4, time_cap=5.0, limit=300):
    """Unix socket files on the host under /tmp, /run, /mnt (not the drvfs drive letters),
    /var and $HOME, bounded by depth, time and count. Symlinks aren't followed."""
    found, deadline = [], time.monotonic() + time_cap

    def walk(d, depth):
        if depth > max_depth or time.monotonic() > deadline or len(found) >= limit:
            return
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            try:
                mode = e.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if stat.S_ISSOCK(mode):
                found.append(e.path)
            elif stat.S_ISDIR(mode) and not (d == "/mnt" and len(e.name) == 1):
                walk(e.path, depth + 1)

    for root in ("/tmp", "/run", "/mnt", "/var", os.path.expanduser("~")):
        walk(root, 1)
    return found


class Containment(unittest.TestCase):
    def test_grade_env_is_an_allowlist(self):
        with tempfile.TemporaryDirectory(prefix="practices-env-") as tmp:
            env = run.grade_env("/fx", tmp)
            self.assertTrue(Path(env["HOME"]).is_dir())
        self.assertEqual(sorted(env), ["DB_PATH", "FIXTURE", "HOME", "LANG", "LLM_API_KEY", "PATH", "TMPDIR"])
        for key in ("HOME", "DB_PATH", "TMPDIR"):
            self.assertTrue(env[key].startswith(tmp), key)
        self.assertEqual(env["LLM_API_KEY"], run.DUMMY_LLM_KEY)

    def test_refuses_without_bwrap_unless_unsafe(self):
        real = run.bwrap_usable
        run.bwrap_usable = lambda: False
        try:
            with self.assertRaises(SystemExit) as cm:
                run.grading_contained(unsafe=False)
            self.assertIn("--unsafe-grade", str(cm.exception.code))
            self.assertFalse(run.grading_contained(unsafe=True))
        finally:
            run.bwrap_usable = real

    def test_bwrap_root_is_an_allowlist(self):
        cmd = run.contained(["true"], writable=["/tmp/x"], real_home="/nonexistent-home")
        args = cmd[: cmd.index("--")]
        mounted = {args[i + 2] for i, a in enumerate(args) if a in ("--ro-bind", "--bind", "--symlink")}
        mounted |= {args[i + 1] for i, a in enumerate(args) if a in ("--proc", "--dev", "--tmpfs")}
        self.assertNotIn("/", mounted)
        for forbidden in ("/home", "/run", "/mnt", "/var", "/root"):
            self.assertFalse(any(m == forbidden or m.startswith(forbidden + "/") for m in mounted), forbidden)
        self.assertTrue({"/usr", "/etc", "/proc", "/dev", "/tmp", "/tmp/x"} <= mounted)
        for flag in ("--unshare-net", "--unshare-pid", "--unshare-ipc"):
            self.assertIn(flag, args)

    def test_writable_path_under_home_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="practices-contain-") as tmp:
            home = Path(tmp) / "home"
            with self.assertRaises(ValueError):
                run.contained(["true"], writable=[home / "deep" / "rundir"], real_home=home)
            with self.assertRaises(ValueError):
                run.contained(["true"], writable=[home], real_home=home)
            run.contained(["true"], writable=[Path(tmp) / "fixture"], real_home=home)  # a sibling is fine

    @unittest.skipUnless(BWRAP_OK, NO_BWRAP)
    def test_probe_sees_no_host_socket_home_or_drive(self):
        with tempfile.TemporaryDirectory(prefix="practices-contain-") as tmp, \
                tempfile.TemporaryDirectory(prefix="practices-sock-") as sockdir:
            tmp = Path(tmp)
            work = tmp / "work"
            work.mkdir()
            sock_path = os.path.join(sockdir, "listen.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(sock_path)
            server.listen(4)
            try:
                paths = sorted({*host_sockets(), sock_path, os.path.expanduser("~")}
                               | ({"/mnt/c"} if os.path.exists("/mnt/c") else set()))
                spec = work / "spec.json"
                spec.write_text(json.dumps({"paths": paths, "socket": sock_path}))
                probe = work / "probe.mjs"
                probe.write_text(CONTAINMENT_PROBE)
                probe_cmd = [NODE, str(probe), str(work), str(spec)]

                # Control, outside the sandbox: the probe can connect and does see the paths.
                c = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=60)
                control = json.loads(c.stdout.strip().splitlines()[-1])
                self.assertTrue(control["connected"], "the probe must be able to connect, or the test proves nothing")
                self.assertIn(sock_path, control["present"])

                env = run.grade_env(work, tmp / "scratch")
                p = subprocess.run(run.contained(probe_cmd, writable=[work], cwd=work), env=env,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(p.returncode, 0, p.stderr)
                out = json.loads(p.stdout.strip().splitlines()[-1])
                self.assertTrue(out["wroteWork"], "the writable bind must work, or the test proves nothing")
                self.assertFalse(out["connected"])
                self.assertEqual(out["present"], [], "host sockets, $HOME or /mnt/c visible inside")
                self.assertFalse(out["network"])
                self.assertEqual(out["env"], sorted([*env, "PWD"]))  # bwrap's --chdir sets PWD
            finally:
                server.close()

    @unittest.skipUnless(BWRAP_OK, NO_BWRAP)
    def test_contained_grade_with_run_dir_under_home(self):
        # As in a live run: the fixture in the system temp dir, the run dir under $HOME.
        with tempfile.TemporaryDirectory(prefix="practices-contain-") as tmp:
            tmp = Path(tmp)
            home = tmp / "home"
            run_dir = home / "deep" / "rundir"
            run_dir.mkdir(parents=True)
            fixture = build(tmp / "fixture")
            shutil.copytree(CASES / "idor" / "good", fixture, dirs_exist_ok=True)
            out = run.grade(fixture, "idor", run_dir, contain=True, home=home)
            self.assertEqual(out["verdict"], "pass", json.dumps(out, indent=1))
            self.assertIn('{"verdict":"pass"', (run_dir / "oracle.out").read_text())


if __name__ == "__main__":
    unittest.main()
