"""skills/exam-prep/scripts/save_handback.py (12-retro step 3).

From a synthetic agent output file holding two SubagentHandback calls among other records (a deep
JSON line among them), the script saves the last call's longest string field (`message`, between
a shorter field before it and one after) as NAME.md, mode 0600, and prints only its size. An
output file with no handback, one that can't be read, or a report that can't be written (a
directory in its place) exits 1 while the other reports are still saved. It refuses an out dir
inside a git work tree (a `.git` file, a symlink into one), an out dir it can't make, a NAME that
isn't a plain file name (no path can climb out of the out dir) or is given twice, and bad usage. A
handback a hook refused (its result an error) doesn't count, and a link planted at a report's
path is replaced, never written through."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "exam-prep", "scripts", "save_handback.py")

spec = importlib.util.spec_from_file_location("save_handback", SCRIPT)
save_handback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(save_handback)

FINAL = "FINAL report: C1 the student asked for two columns"


def handback(report, call_id):
    return {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "done"},
        {"type": "tool_use", "id": call_id, "name": "SubagentHandback",
         "input": {"status": "done", "message": report, "z": "s"}}]}}


def refused(call_id):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "is_error": True,
         "content": "a hook refused the handback"}]}}


class SaveHandback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "reports")
        self.output = os.path.join(self.tmp, "agent.output")
        with open(self.output, "w", encoding="utf-8") as f:
            # Longer than FINAL, so only "the last call" picks FINAL.
            f.write(json.dumps(handback("FIRST draft report " + "x" * 80, "h1")) + "\n")
            f.write("not json\n")
            f.write("[" * 20000 + "]" * 20000 + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": "a turn"}}) + "\n")
            f.write(json.dumps(handback(FINAL, "h2")) + "\n")
            f.write(json.dumps(handback("REFUSED later report " + "y" * 90, "h3")) + "\n")
            f.write(json.dumps(refused("h3")) + "\n")
        self.empty = os.path.join(self.tmp, "empty.output")
        with open(self.empty, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": "no handback"}}) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = save_handback.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_saves_the_last_report(self):
        code, out, err = self.run_main(self.out, f"C1={self.output}")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, f"C1: {len(FINAL)} chars\n")
        with open(os.path.join(self.out, "C1.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), FINAL)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.out, "C1.md")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)

    def test_a_missing_report_still_saves_the_rest(self):
        code, out, err = self.run_main(self.out, f"C0={self.empty}",
                                       f"C9={os.path.join(self.tmp, 'gone')}", f"C1={self.output}")
        self.assertEqual(code, 1)
        self.assertIn("C0: no SubagentHandback report", err)
        self.assertIn("C9:", err)
        self.assertTrue(os.path.exists(os.path.join(self.out, "C1.md")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "C0.md")))

    def test_an_unwritable_report_still_saves_the_rest(self):
        os.makedirs(os.path.join(self.out, "C1.md"))
        code, out, err = self.run_main(self.out, f"C1={self.output}", f"C2={self.output}")
        self.assertEqual(code, 1)
        self.assertIn("C1:", err)
        self.assertNotIn("FINAL", err)
        self.assertEqual(out, f"C2: {len(FINAL)} chars\n")

    def test_refusals(self):
        repo = os.path.join(self.tmp, "hub")
        os.makedirs(os.path.join(repo, ".git"))
        code, _, err = self.run_main(os.path.join(repo, "r"), f"C1={self.output}")
        self.assertEqual((code, "git work tree" in err), (2, True))
        for bad in (f"../C1={self.output}", f"a/b={self.output}", f".x={self.output}",
                    "C1", f"={self.output}", "C1="):
            self.assertEqual(self.run_main(self.out, bad)[0], 2, bad)
        self.assertEqual(self.run_main(self.out)[0], 2)
        self.assertEqual(self.run_main(self.out, f"C1={self.output}", f"C1={self.empty}")[0], 2)
        self.assertFalse(os.path.exists(self.out))
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        before = sorted(os.listdir(self.tmp))
        for flag in ("-h", "--help"):
            code, _, err = self.run_main(flag, f"C1={self.output}", f"C2={self.output}")
            self.assertEqual(code, 2, flag)
            self.assertIn("save_handback.py", err)
            self.assertEqual(sorted(os.listdir(self.tmp)), before)

    def test_planted_links_and_work_tree_forms(self):
        os.makedirs(self.out)
        os.chmod(self.out, 0o755)
        target = os.path.join(self.tmp, "target.txt")
        kept = os.path.join(self.tmp, "kept.md")
        with open(kept, "w") as f:
            f.write("KEPT")
        os.symlink(target, os.path.join(self.out, "C1.md"))
        os.link(kept, os.path.join(self.out, "C2.md"))
        code, _, err = self.run_main(self.out, f"C1={self.output}", f"C2={self.output}")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(target))
        with open(kept) as f:
            self.assertEqual(f.read(), "KEPT")
        for name in ("C1.md", "C2.md"):
            self.assertFalse(os.path.islink(os.path.join(self.out, name)))
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)
        lane = os.path.join(self.tmp, "lane")
        os.makedirs(os.path.join(lane, "notes"))
        with open(os.path.join(lane, ".git"), "w") as f:
            f.write("gitdir: /elsewhere\n")
        self.assertEqual(self.run_main(os.path.join(lane, "r"), f"C1={self.output}")[0], 2)
        link = os.path.join(self.tmp, "looks-private")
        os.symlink(os.path.join(lane, "notes"), link)
        self.assertEqual(self.run_main(os.path.join(link, "r"), f"C1={self.output}")[0], 2)
        self.assertFalse(os.path.exists(os.path.join(lane, "notes", "r")))
        afile = os.path.join(self.tmp, "afile")
        with open(afile, "w") as f:
            f.write("x")
        self.assertEqual(self.run_main(afile, f"C1={self.output}")[0], 2)

    def test_runs_isolated(self):
        r = subprocess.run([sys.executable, "-I", SCRIPT, self.out, f"C1={self.output}"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
