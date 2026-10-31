"""bin/cache-unlink: finds project files that are hardlinks into a shared package cache (uv, pnpm,
bun) and, with --apply, gives each a copy of its own (sandbox gap N3: a sandboxed edit to such a
file would reach the cache and every later install). Stdlib only.

Each test builds caches and projects in a temp dir, points the cache env vars at them, and runs
the tool as a subprocess."""
import os
import subprocess
import tempfile
import shutil
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(REPO, "bin", "cache-unlink")


class CacheUnlink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        self.uv = os.path.join(self.home, ".cache", "uv")
        self.pnpm = os.path.join(self.home, ".local", "share", "pnpm", "store")
        self.code = os.path.join(self.home, "code")
        for d in (self.uv, self.pnpm, self.code):
            os.makedirs(d)

    def put(self, path, text="x", mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def link(self, cache_file, project_file):
        os.makedirs(os.path.dirname(project_file), exist_ok=True)
        os.link(cache_file, project_file)
        return project_file

    def run_tool(self, *args):
        env = {k: v for k, v in os.environ.items()
               if k not in ("UV_CACHE_DIR", "PNPM_STORE_DIR", "BUN_INSTALL_CACHE_DIR",
                            "XDG_CACHE_HOME", "XDG_DATA_HOME")}
        env["HOME"] = self.home
        return subprocess.run([TOOL, *args], capture_output=True, text=True, timeout=30, env=env)

    def test_the_report_groups_by_project_and_cache_and_exits_1(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "requests", "api.py"))
        b = self.put(os.path.join(self.pnpm, "v3", "files", "00", "abc"))
        self.link(a, os.path.join(self.code, "py", ".venv", "lib", "requests", "api.py"))
        self.link(b, os.path.join(self.code, "web", "node_modules", "x", "index.js"))
        self.link(b, os.path.join(self.code, "web", "node_modules", "y", "index.js"))
        p = self.run_tool(self.code)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("pnpm         2 files  ~/code/web", p.stdout)
        self.assertIn("uv           1 files  ~/code/py", p.stdout)
        self.assertEqual(os.stat(a).st_nlink, 2)  # a report changes nothing

    def test_apply_gives_each_file_its_own_copy(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "mod.py"), "print(1)\n", 0o755)
        proj = self.link(a, os.path.join(self.code, "py", ".venv", "mod.py"))
        os.utime(a, (1_000_000_000, 1_000_000_000))
        p = self.run_tool("--apply", self.code)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("un-linked 1 files", p.stdout)
        self.assertFalse(os.path.samefile(a, proj))
        self.assertEqual((os.stat(a).st_nlink, os.stat(proj).st_nlink), (1, 1))
        with open(proj) as f:
            self.assertEqual(f.read(), "print(1)\n")
        self.assertEqual(os.stat(proj).st_mode & 0o777, 0o755)
        self.assertEqual(int(os.stat(proj).st_mtime), 1_000_000_000)
        self.assertEqual(os.listdir(os.path.dirname(proj)), ["mod.py"])  # no temp left
        self.assertEqual(self.run_tool(self.code).returncode, 0)

    def test_links_inside_a_cache_never_count(self):
        # uv links its own entries to each other; a DIR that holds the cache doesn't count it.
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        os.link(a, os.path.join(self.uv, "archive-v0", "h1", "m2.py"))
        p = self.run_tool(self.home)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("no file under", p.stdout)

    def test_links_between_projects_alone_dont_count(self):
        a = self.put(os.path.join(self.code, "one", "f"))
        self.link(a, os.path.join(self.code, "two", "f"))
        self.assertEqual(self.run_tool(self.code).returncode, 0)

    def test_a_symlink_into_the_cache_is_left_alone(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        os.link(a, os.path.join(self.uv, "archive-v0", "h1", "m2.py"))
        os.makedirs(os.path.join(self.code, "py"))
        os.symlink(a, os.path.join(self.code, "py", "m.py"))
        p = self.run_tool("--apply", self.code)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertTrue(os.path.islink(os.path.join(self.code, "py", "m.py")))

    def test_the_cache_env_vars_and_extra_caches_count(self):
        other = self.put(os.path.join(self.tmp, "store", "f"))
        bun = self.put(os.path.join(self.tmp, "bun cache", "g"))
        self.link(other, os.path.join(self.code, "a", "f"))
        self.link(bun, os.path.join(self.code, "b", "g"))
        env_bun = dict(BUN_INSTALL_CACHE_DIR=os.path.join(self.tmp, "bun cache"))
        p = subprocess.run([TOOL, "--cache", os.path.join(self.tmp, "store"), self.code],
                           capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, HOME=self.home, **env_bun))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("other        1 files  ~/code/a", p.stdout)
        self.assertIn("bun          1 files  ~/code/b", p.stdout)

    def test_a_file_directly_in_dir_is_grouped_under_dir(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        self.link(a, os.path.join(self.code, "m.py"))
        self.assertIn("1 files  ~/code\n", self.run_tool(self.code).stdout)

    def test_a_missing_dir_is_a_usage_error(self):
        p = self.run_tool(os.path.join(self.tmp, "nope"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("not a dir", p.stderr)


if __name__ == "__main__":
    unittest.main()
