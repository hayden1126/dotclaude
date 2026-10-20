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
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
        expected = {"good": "pass", "bad": "fail", "empty": "broken"}
        if not (CASES / case / "bad").is_dir():
            del expected["bad"]
        for variant, want in expected.items():
            with self.subTest(variant=variant):
                out = self.verdict(case, variant)
                self.assertEqual(out["verdict"], want, json.dumps(out, indent=1))
                if variant == "empty":  # broken for the right reason, not a crashed oracle
                    self.assertIn("missing", [c["name"] for c in out["checks"]], json.dumps(out, indent=1))

    def test_every_case_has_its_files(self):
        self.assertEqual(
            case_names(),
            ["action-authz", "actor-from-body", "benign", "idor", "mass-assign", "rate-limit-paid"],
        )
        for case in case_names():
            for name in ("prompt.md", "oracle.mjs", "good"):
                self.assertTrue((CASES / case / name).exists(), f"{case}/{name}")
            self.assertEqual((CASES / case / "bad").is_dir(), case != "benign", case)

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
}

# Insecure implementations beyond bad/: each must score fail.
INSECURE_VARIANTS = {
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
            code, timed_out = run.run_turn(cmd, prompt, tmp, tmp / "out.txt", tmp / "err.txt", timeout=30)
            self.assertEqual((code, timed_out), (0, False))
            self.assertEqual((tmp / "out.txt").read_text(), "hello\ndone\n")
            time.sleep(3)
            self.assertFalse(late.exists(), "a background grandchild outlived the turn")

    def test_turn_timeout_kills_the_group(self):
        with tempfile.TemporaryDirectory(prefix="practices-turn-") as tmp:
            tmp = Path(tmp)
            (tmp / "prompt.txt").write_text("")
            started = time.monotonic()
            code, timed_out = run.run_turn(["bash", "-c", "sleep 60 & sleep 60"], tmp / "prompt.txt", tmp,
                                           tmp / "out.txt", tmp / "err.txt", timeout=1)
            self.assertEqual((code, timed_out), (None, True))
            self.assertLess(time.monotonic() - started, 10)

    def test_fixture_git_and_diff_against_the_harness_commit(self):
        root, sha = run.build_fixture("A")
        try:
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


CONTAINMENT_PROBE = """\
import { readFileSync, writeFileSync } from "node:fs";
const [work] = process.argv.slice(2);
const home = process.env.HOME;
const tryIt = (fn) => { try { fn(); return true; } catch { return false; } };
const out = {
  wroteWork: tryIt(() => writeFileSync(`${work}/ok.txt`, "x")),
  wroteHome: tryIt(() => writeFileSync(`${home}/planted-by-probe.txt`, "x")),
  readSecret: tryIt(() => readFileSync(`${home}/secret.txt`, "utf8")),
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


class Containment(unittest.TestCase):
    def test_grade_env_is_an_allowlist(self):
        with tempfile.TemporaryDirectory(prefix="practices-env-") as tmp:
            env = run.grade_env("/fx", tmp)
        self.assertEqual(sorted(env), ["DB_PATH", "FIXTURE", "HOME", "LANG", "LLM_API_KEY", "PATH", "TMPDIR"])
        self.assertTrue(env["DB_PATH"].startswith(tmp) and env["TMPDIR"].startswith(tmp))
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

    @unittest.skipUnless(NODE and run.bwrap_usable(), "bwrap can't start here (nested in Claude Code's sandbox)")
    def test_probe_cannot_touch_home_or_network(self):
        with tempfile.TemporaryDirectory(prefix="practices-contain-") as tmp:
            tmp = Path(tmp)
            home, work = tmp / "home", tmp / "work"
            home.mkdir()
            work.mkdir()
            (home / "secret.txt").write_text("not for the oracle")
            probe = work / "probe.mjs"
            probe.write_text(CONTAINMENT_PROBE)
            env = run.grade_env(work, work)
            env["HOME"] = str(home)
            cmd = run.contained([NODE, str(probe), str(work)], home=home, writable=[work], cwd=work)
            p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertTrue(out["wroteWork"], "the writable bind must work, or the test proves nothing")
            self.assertFalse(out["wroteHome"])
            self.assertFalse((home / "planted-by-probe.txt").exists())
            self.assertFalse(out["readSecret"])
            self.assertFalse(out["network"])
            self.assertEqual(out["env"], sorted([*env, "PWD"]))  # bwrap's --chdir sets PWD

    def test_writable_path_under_home_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="practices-contain-") as tmp:
            home = Path(tmp) / "home"
            with self.assertRaises(ValueError):
                run.contained(["true"], home=home, writable=[home / "deep" / "rundir"])
            with self.assertRaises(ValueError):
                run.contained(["true"], home=home, writable=[home])
            run.contained(["true"], home=home, writable=[Path(tmp) / "fixture"])  # a sibling is fine

    @unittest.skipUnless(NODE and run.bwrap_usable(), "bwrap can't start here (nested in Claude Code's sandbox)")
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
