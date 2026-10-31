"""bin/cache-unlink: finds project files that are hardlinks into a shared package cache (uv, pnpm,
bun) and, with --apply, gives each a copy of its own (sandbox gap N3: a sandboxed edit to such a
file would reach the cache and every later install). Stdlib only.

Most tests build caches and projects in a temp dir, point HOME and the cache env vars at them,
and run the tool as a subprocess. The race tests load it in-process, so they can swap a dir for a
link between the walk and the write, as a sandboxed session working in the project could."""
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(REPO, "bin", "cache-unlink")
CACHE_ENV = ("SANDBOX_RUNTIME", "UV_CACHE_DIR", "PNPM_HOME", "BUN_INSTALL", "BUN_INSTALL_CACHE_DIR",
             "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME")


def load_tool():
    sys.dont_write_bytecode = True  # no bin/__pycache__
    loader = importlib.machinery.SourceFileLoader("cache_unlink", TOOL)
    spec = importlib.util.spec_from_loader("cache_unlink", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
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

    def read(self, path):
        with open(path) as f:
            return f.read()


class CacheUnlink(Base):
    def run_tool(self, *args, **extra):
        env = {k: v for k, v in os.environ.items() if k not in CACHE_ENV}
        env.update(HOME=self.home, **extra)
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

    def test_the_report_names_every_cache_it_searched(self):
        # So a store it missed shows, rather than passing for an all-clear.
        p = self.run_tool(self.code)
        self.assertIn("searched uv ~/.cache/uv; pnpm ~/.local/share/pnpm/store; bun (none found)",
                      p.stdout)

    def test_apply_gives_each_file_its_own_copy(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "mod.py"), "print(1)\n", 0o755)
        proj = self.link(a, os.path.join(self.code, "py", ".venv", "mod.py"))
        os.utime(a, (1_000_000_000, 1_000_000_000))
        p = self.run_tool("--apply", self.code)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("un-linked 1 files", p.stdout)
        self.assertFalse(os.path.samefile(a, proj))
        self.assertEqual((os.stat(a).st_nlink, os.stat(proj).st_nlink), (1, 1))
        self.assertEqual(self.read(proj), "print(1)\n")
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

    def test_a_dir_inside_a_cache_is_refused(self):
        p = self.run_tool(os.path.join(self.uv))
        self.assertEqual(p.returncode, 2)
        self.assertIn("is inside the cache", p.stderr)

    def test_links_between_projects_alone_dont_count(self):
        a = self.put(os.path.join(self.code, "one", "f"))
        self.link(a, os.path.join(self.code, "two", "f"))
        self.assertEqual(self.run_tool(self.code).returncode, 0)

    def test_a_symlink_in_a_project_is_never_walked(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        os.link(a, os.path.join(self.uv, "archive-v0", "h1", "m2.py"))
        os.makedirs(os.path.join(self.code, "py"))
        os.symlink(a, os.path.join(self.code, "py", "m.py"))
        p = self.run_tool("--apply", self.code)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertTrue(os.path.islink(os.path.join(self.code, "py", "m.py")))

    def test_overlapping_dirs_walk_each_file_once(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        self.link(a, os.path.join(self.code, "web", "m.py"))
        web = os.path.join(self.code, "web")
        p = self.run_tool("--apply", self.code, web, web)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("un-linked 1 files\n", p.stdout)

    def test_pnpm_home_and_an_rc_store_dir_count(self):
        home_store = self.put(os.path.join(self.tmp, "pnpm home", "store", "v3", "f"))
        rc_store = self.put(os.path.join(self.tmp, "rc store", "v3", "g"))
        self.put(os.path.join(self.home, ".npmrc"), f"store-dir = {os.path.dirname(rc_store)}\n")
        self.link(home_store, os.path.join(self.code, "a", "f"))
        self.link(rc_store, os.path.join(self.code, "b", "g"))
        p = self.run_tool(self.code, PNPM_HOME=os.path.join(self.tmp, "pnpm home"))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("pnpm         1 files  ~/code/a", p.stdout)
        self.assertIn("pnpm         1 files  ~/code/b", p.stdout)

    def test_the_cache_env_vars_and_extra_caches_count(self):
        other = self.put(os.path.join(self.tmp, "store", "f"))
        bun = self.put(os.path.join(self.tmp, "bun cache", "g"))
        self.link(other, os.path.join(self.code, "a", "f"))
        self.link(bun, os.path.join(self.code, "b", "g"))
        p = self.run_tool("--cache", os.path.join(self.tmp, "store"), self.code,
                          BUN_INSTALL_CACHE_DIR=os.path.join(self.tmp, "bun cache"))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("other        1 files  ~/code/a", p.stdout)
        self.assertIn("bun          1 files  ~/code/b", p.stdout)

    def test_a_file_directly_in_dir_is_grouped_under_dir(self):
        a = self.put(os.path.join(self.uv, "archive-v0", "h1", "m.py"))
        self.link(a, os.path.join(self.code, "m.py"))
        self.assertIn("1 files  ~/code\n", self.run_tool(self.code).stdout)

    def test_inside_the_sandbox_it_refuses(self):
        # There the cache vars name the sandbox's own caches: the report would miss the real ones.
        p = self.run_tool(self.code, SANDBOX_RUNTIME="1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("run it from a terminal", p.stderr)

    def test_a_missing_dir_is_a_usage_error(self):
        p = self.run_tool(os.path.join(self.tmp, "nope"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("not a dir", p.stderr)


class Races(Base):
    """A sandboxed session can rewrite the project while --apply runs outside the sandbox."""

    def setUp(self):
        super().setUp()
        self.mod = load_tool()
        self.cache_file = self.put(os.path.join(self.uv, "archive-v0", "h1", "authorized_keys"),
                                   "payload\n")
        self.proj = os.path.join(self.code, "p")
        self.target = self.link(self.cache_file, os.path.join(self.proj, "d1", "authorized_keys"))
        # The dir a swapped-in link would aim the write at, with a file there to overwrite.
        self.victim_dir = os.path.join(self.tmp, "dot-ssh")
        self.victim = self.put(os.path.join(self.victim_dir, "authorized_keys"), "real key\n")
        self.shared = self.mod.find_shared([self.code], {"uv": [self.uv]})
        self.assertEqual(sum(len(f) for f in self.shared.values()), 1)

    def swap_d1_for_a_link(self):
        os.rename(os.path.join(self.proj, "d1"), os.path.join(self.proj, "d1.real"))
        os.symlink(self.victim_dir, os.path.join(self.proj, "d1"))

    def assert_victim_untouched(self):
        self.assertEqual(self.read(self.victim), "real key\n")
        self.assertEqual(os.listdir(self.victim_dir), ["authorized_keys"])

    def test_a_dir_swapped_for_a_link_mid_copy_cant_redirect_it(self):
        # The swap lands just before the temp file is made: a path-based copy would create it,
        # and rename it, inside the link's target.
        real_open = os.open

        def open_then_swap(path, flags, *a, **kw):
            if ".cache-unlink." in str(path) and not os.path.islink(os.path.join(self.proj, "d1")):
                self.swap_d1_for_a_link()
            return real_open(path, flags, *a, **kw)

        with mock.patch.object(self.mod.os, "open", side_effect=open_then_swap):
            done, failed = self.mod.apply(self.shared)
        self.assertEqual((done, failed), (1, []))
        self.assert_victim_untouched()
        moved = os.path.join(self.proj, "d1.real", "authorized_keys")
        self.assertEqual(os.stat(moved).st_nlink, 1)  # the copy went where the file really was
        self.assertEqual(os.listdir(os.path.dirname(moved)), ["authorized_keys"])

    def test_a_dir_already_swapped_for_a_link_fails_that_file(self):
        self.swap_d1_for_a_link()
        done, failed = self.mod.apply(self.shared)
        self.assertEqual((done, len(failed)), (0, 1))
        self.assert_victim_untouched()

    def test_a_file_replaced_since_the_walk_is_left_alone(self):
        os.remove(self.target)
        self.put(self.target, "new\n")
        done, failed = self.mod.apply(self.shared)
        self.assertEqual((done, [e for _, e in failed]), (0, ["changed since the walk"]))
        self.assertEqual(self.read(self.target), "new\n")

    def test_a_file_swapped_for_a_link_is_refused(self):
        os.remove(self.target)
        os.symlink(self.victim, self.target)
        done, failed = self.mod.apply(self.shared)
        self.assertEqual((done, len(failed)), (0, 1))
        self.assert_victim_untouched()
        self.assertTrue(os.path.islink(self.target))


if __name__ == "__main__":
    unittest.main()
