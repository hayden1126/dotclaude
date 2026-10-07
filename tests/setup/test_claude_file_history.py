"""bin/claude-file-history: list and restore Claude Code's own backups of a file (stdlib only).

Claude Code copies a file to <config>/file-history/<session>/<hash>@v<n> before each tool write
and records it in the transcript as a file-history-delta (trackingPath, backup) or in a
file-history-snapshot's trackedFileBackups. The shapes here are copied from a real transcript
(karaoke, 2026-10-06). A subagent's transcript files its backups under the parent session."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(REPO, "bin", "claude-file-history")
SID = "4c9dfc5e-45ab-47c6-8a18-8c674f3ff52b"
OLD = "0f2b1e81-c017-40ee-92ee-4d0eeb5bb491"


def backup(name, when):
    return {"backupFileName": name, "version": int(name.split("@v")[1]) if name else 1,
            "backupTime": when, "realParentDir": "/x"}


class FileHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cfg = os.path.join(self.tmp, "claude")
        proj = os.path.join(self.cfg, "projects", "-home-hayden-code-karaoke")
        os.makedirs(os.path.join(proj, SID, "subagents"))
        self.target = os.path.join(proj, "memory", "karaoke-personal-product.md")
        os.makedirs(os.path.dirname(self.target))
        self.put(self.target, "PLACEHOLDER")
        self.put(os.path.join(self.cfg, "file-history", OLD, "7d1be6026214695c@v1"), "first")
        self.put(os.path.join(self.cfg, "file-history", SID, "7d1be6026214695c@v1"), "vision " * 900)
        self.put(os.path.join(self.cfg, "file-history", SID, "7d1be6026214695c@v2"), "PLACEHOLDER")
        self.put(os.path.join(self.cfg, "file-history", SID, "aaaa@v1"), "other file")
        self.lines(os.path.join(proj, OLD + ".jsonl"), [
            {"type": "file-history-delta", "trackingPath": self.target,
             "backup": backup("7d1be6026214695c@v1", "2026-09-28T20:14:23.476Z")}])
        self.lines(os.path.join(proj, SID + ".jsonl"), [
            {"type": "user", "message": {"content": f"cat {self.target}"}},
            # A file the session created has no backup: backupFileName null.
            {"type": "file-history-delta", "trackingPath": self.target + ".new",
             "backup": {"backupFileName": None, "version": 1, "backupTime": "x"}},
            {"type": "file-history-delta", "trackingPath": self.target,
             "backup": backup("7d1be6026214695c@v1", "2026-10-06T23:29:41.324Z")},
            {"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {
                self.target: backup("7d1be6026214695c@v2", "2026-10-06T23:46:19.971Z"),
                "/elsewhere/x.md": backup("aaaa@v1", "2026-10-06T23:46:19.970Z")}}},
            # The same backup recorded again by a later snapshot: listed once.
            {"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {
                self.target: backup("7d1be6026214695c@v2", "2026-10-06T23:46:19.971Z")}}},
            "not json " + self.target])
        self.lines(os.path.join(proj, SID, "subagents", "agent-a1.jsonl"), [
            {"type": "file-history-delta", "trackingPath": self.target,
             "backup": backup("7d1be6026214695c@v3", "2026-10-07T00:00:00.000Z")}])

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def lines(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else
                         json.dumps(r, separators=(",", ":"), ensure_ascii=False)) + "\n")

    def run_cli(self, *args, ok=True):
        p = subprocess.run(["python3", "-I", CLI, self.target, *args], capture_output=True,
                           text=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=self.cfg), timeout=30)
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return p

    def test_lists_every_backup_oldest_first_across_sessions(self):
        out = self.run_cli().stdout.splitlines()
        rows = [l for l in out if l.lstrip()[:1].isdigit()]
        self.assertEqual(len(rows), 3, out)
        self.assertIn(OLD[:8], rows[0])
        self.assertIn("6300 bytes", rows[1])
        self.assertIn("11 bytes", rows[2])
        self.assertIn("now: 11 bytes", out[0])
        # The subagent's backup names a file that doesn't exist: not listed.
        self.assertNotIn("@v3", "\n".join(out))

    def test_show_prints_a_version(self):
        self.assertEqual(self.run_cli("--show", "1").stdout, "first")

    def test_restore_keeps_the_current_file(self):
        out = self.run_cli("--restore", "2").stdout
        with open(self.target) as f:
            self.assertEqual(f.read(), "vision " * 900)
        kept = [n for n in os.listdir(os.path.dirname(self.target)) if ".before-restore-" in n]
        self.assertEqual(len(kept), 1, out)
        with open(os.path.join(os.path.dirname(self.target), kept[0])) as f:
            self.assertEqual(f.read(), "PLACEHOLDER")

    def test_a_subagent_transcript_files_backups_under_its_parent_session(self):
        self.put(os.path.join(self.cfg, "file-history", SID, "7d1be6026214695c@v3"), "agent")
        self.assertIn("2026-10-07", self.run_cli().stdout)

    def test_a_path_inside_the_working_directory_is_recorded_relative_to_it(self):
        # Real transcripts: "trackingPath":"docs/finances.md", resolved against the session's
        # cwd; "../capella-studio/x.tsx" reaches a sibling. A symlink to the file matches too.
        repo = os.path.join(self.tmp, "code", "aikido")
        doc = os.path.join(repo, "docs", "café — finances.md")
        sibling = os.path.join(self.tmp, "code", "studio", "x.tsx")
        self.put(doc, "now")
        self.put(sibling, "now")
        sid = "9c42100b-0000-4000-8000-000000000000"
        for name, text in (("aaaa@v1", "doc v1"), ("bbbb@v1", "sibling v1"), ("cccc@v1", "far")):
            self.put(os.path.join(self.cfg, "file-history", sid, name), text)
        self.lines(os.path.join(self.cfg, "projects", "-code-aikido", sid + ".jsonl"), [
            {"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {
                "docs/café — finances.md": backup("aaaa@v1", "2026-09-28T10:00:00.000Z")}}},
            {"type": "user", "cwd": repo, "message": {"content": "hi"}},
            {"type": "file-history-delta", "trackingPath": "../studio/x.tsx",
             "backup": backup("bbbb@v1", "2026-09-28T11:00:00.000Z")},
            # Same name, another directory: not this file.
            {"type": "file-history-delta", "trackingPath": "lib/café — finances.md",
             "backup": backup("cccc@v1", "2026-09-28T12:00:00.000Z")}])
        link = os.path.join(self.tmp, "fin.md")
        os.symlink(doc, link)
        for path, want in ((doc, "doc v1"), (link, "doc v1"), (sibling, "sibling v1")):
            with self.subTest(path=path):
                self.target = path
                rows = [l for l in self.run_cli().stdout.splitlines() if l.lstrip()[:1].isdigit()]
                self.assertEqual(len(rows), 1, rows)
                self.assertEqual(self.run_cli("--show", "1").stdout, want)

    def test_a_backup_recorded_under_a_links_name_is_found_through_that_link(self):
        real = os.path.join(self.tmp, "real.md")
        link = os.path.join(self.tmp, "link.md")
        self.put(real, "now")
        os.symlink(real, link)
        self.put(os.path.join(self.cfg, "file-history", SID, "dddd@v1"), "via link")
        self.lines(os.path.join(self.cfg, "projects", "-x", SID + ".jsonl"), [
            {"type": "file-history-delta", "trackingPath": link,
             "backup": backup("dddd@v1", "2026-10-01T00:00:00.000Z")}])
        self.target = link
        self.assertEqual(self.run_cli("--show", "1").stdout, "via link")

    def test_the_cli_is_executable(self):
        # setup.sh links only an executable bin/* into ~/.local/bin.
        self.assertTrue(os.access(CLI, os.X_OK))

    def test_a_bad_index_or_an_unknown_file_fails(self):
        self.assertIn("1 to 3", self.run_cli("--show", "9", ok=False).stderr)
        self.target += ".unknown"
        self.assertIn("no backups", self.run_cli(ok=False).stderr)


if __name__ == "__main__":
    unittest.main()
