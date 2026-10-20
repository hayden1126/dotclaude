"""Offline checks for the server-code eval (no model calls).

For every case in cases/: the known-good overlay scores `pass`, the known-bad overlay scores
`fail` (benign has none), and the pristine fixture, where nothing was written, scores
`broken`. Plus: the fixture's TypeScript loader elides type-only imports and resolves the
`@/` alias, and `npm test` passes on a fresh copy of the pristine fixture.

  python3 -m unittest discover -s tests/practices -t tests/practices -v

Skips when node (or npm, for the npm test) is absent. Fixtures go to TMPDIR.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture"
STUB = HERE / "next_stub"
CASES = HERE / "cases"
LOADER = FIXTURE / "scripts" / "register.mjs"
NODE = shutil.which("node")
NPM = shutil.which("npm")


def build(dest):
    shutil.copytree(FIXTURE, dest)
    shutil.copytree(STUB, dest / "node_modules" / "next")
    return dest


def run_oracle(fixture, case, workdir):
    env = dict(os.environ, FIXTURE=str(fixture), DB_PATH=str(workdir / "oracle.db"), LLM_FAKE="1")
    p = subprocess.run(
        [NODE, "--import", LOADER.as_uri(), str(CASES / case / "oracle.mjs")],
        cwd=fixture, env=env, capture_output=True, text=True, timeout=60,
    )
    for line in reversed(p.stdout.splitlines()):
        if line.startswith('{"verdict"'):
            return json.loads(line)
    return {"verdict": None, "stdout": p.stdout[-2000:], "stderr": p.stderr[-2000:]}


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
}


@unittest.skipUnless(NODE, "node is not installed")
class SecureVariants(unittest.TestCase):
    def test_variants_pass(self):
        for label, (case, files) in VARIANTS.items():
            with self.subTest(label), tempfile.TemporaryDirectory(prefix="practices-variant-") as tmp:
                tmp = Path(tmp)
                fixture = build(tmp / "fixture")
                for rel, text in files.items():
                    (fixture / rel).parent.mkdir(parents=True, exist_ok=True)
                    (fixture / rel).write_text(text)
                out = run_oracle(fixture, case, tmp)
                self.assertEqual(out["verdict"], "pass", json.dumps(out, indent=1))


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
    """run.py's stream parsing and pass bar, on synthetic events (no model calls)."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(HERE))
        import run
        cls.harness = run

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
        self.assertTrue(bar("idor", "A", c(0, 2, 3), 5)[1])   # only 2 valid runs
        self.assertTrue(bar("idor", "A", c(3, 2, 0), 5)[1])
        self.assertFalse(bar("benign", "A", c(5, 0, 0), 5)[1])  # reported only
        self.assertFalse(bar("idor", "C", c(5, 0, 0), 5)[1])
        self.assertTrue(bar("benign", "D", c(4, 0, 1), 5)[1])
        self.assertFalse(bar("idor", "B", c(0, 5, 0), 5)[1])


if __name__ == "__main__":
    unittest.main()
