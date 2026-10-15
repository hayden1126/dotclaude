"""tmux/paste-inbox: the image inbox behind Alt+V (stdlib only).

`receive` and `paste` run as subprocesses against a stub tmux that logs each call as a JSON line
(and keeps what load-buffer reads), with PATH narrowed to the stubs and /usr/bin:/bin so no real
cmd.exe or tmux is reached. A real tmux server on a private socket checks that the paste
arrives bracketed; the Bash sandbox blocks tmux's socket, so that class skips there."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "paste-inbox")
CONF = os.path.join(REPO, "tmux", "claude.conf")
CHEATSHEET = os.path.join(REPO, "tmux", "cheatsheet.txt")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x01" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x02" * 40
GIF87 = b"GIF87a" + b"\x03" * 40
GIF89 = b"GIF89a" + b"\x03" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x04" * 40
CAP = 50 * 1024 * 1024
NAME = re.compile(r"^\d{8}T\d{6}Z-(?P<device>[a-z0-9._-]+)-[0-9a-f]{6}\.(?P<ext>png|jpg|gif|webp)$")

STUB_TMUX = """#!%s -I
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["tmux"] + args) + "\\n")
if args[:1] == ["load-buffer"]:
    with open(os.environ["STUB_BUFFER"], "wb") as f:
        f.write(sys.stdin.buffer.read())
elif args[:1] == ["display-message"] and "-p" in args:
    print(os.environ.get("STUB_IN_MODE", "0"))
sys.exit(int(os.environ.get("STUB_RC", "0")))
""" % sys.executable

STUB_CMD = """#!%s -I
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["cmd.exe"] + sys.argv[1:]) + "\\n")
sys.stdout.write("C:\\\\Users\\\\tester\\r\\n")
""" % sys.executable

STUB_WSLPATH = """#!%s -I
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["wslpath"] + sys.argv[1:]) + "\\n")
print(os.environ["STUB_WINHOME"])
""" % sys.executable


class Inbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.inbox = os.path.join(self.tmp, "inbox")
        self.downloads = os.path.join(self.tmp, "Downloads")
        os.mkdir(self.downloads)
        self.stubs = os.path.join(self.tmp, "stubs")
        os.mkdir(self.stubs)
        for name, text in (("tmux", STUB_TMUX), ("cmd.exe", STUB_CMD), ("wslpath", STUB_WSLPATH)):
            self.stub(name, text)
        os.mkdir(os.path.join(self.tmp, "home"))
        self.log = os.path.join(self.tmp, "calls.log")
        self.buffer = os.path.join(self.tmp, "buffer")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "PASTE_INBOX"))}
        self.env = {**env, "HOME": os.path.join(self.tmp, "home"),
                    "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "PATH": self.stubs + os.pathsep + "/usr/bin:/bin",
                    "PASTE_INBOX_DIR": self.inbox, "PASTE_INBOX_DOWNLOADS": self.downloads,
                    "STUB_LOG": self.log, "STUB_BUFFER": self.buffer,
                    "STUB_WINHOME": os.path.join(self.tmp, "winhome")}

    def stub(self, name, text):
        path = os.path.join(self.stubs, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def run_script(self, args, data=b"", **env):
        return subprocess.run([SCRIPT, *args], input=data, capture_output=True, timeout=30,
                              env={**self.env, **env})

    def receive(self, data, device="laptop", **env):
        return self.run_script(["receive", device], data, **env)

    def paste(self, **env):
        p = self.run_script(["paste", "%5", "/dev/pts/12"], **env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"", b""))
        return p

    def calls(self):
        try:
            with open(self.log) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def pasted(self):
        """The text load-buffer took, or None when nothing was pasted."""
        try:
            with open(self.buffer, "rb") as f:
                return f.read().decode()
        except FileNotFoundError:
            return None

    def put(self, folder, name, age=0, data=PNG):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(data)
        when = time.time() - age
        os.utime(path, (when, when))
        return path

    def files(self):
        return sorted(os.listdir(self.inbox)) if os.path.isdir(self.inbox) else []


class Receive(Inbox):
    def test_a_png_lands_in_the_inbox_and_its_path_is_printed(self):
        p = self.receive(PNG)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        path = p.stdout.decode().strip()
        self.assertEqual(os.path.dirname(path), self.inbox)
        match = NAME.match(os.path.basename(path))
        self.assertIsNotNone(match, path)
        self.assertEqual((match["device"], match["ext"]), ("laptop", "png"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), PNG)
        self.assertEqual(self.files(), [os.path.basename(path)])

    def test_the_extension_comes_from_the_magic_bytes(self):
        for data, ext in ((JPEG, "jpg"), (GIF87, "gif"), (GIF89, "gif"), (WEBP, "webp")):
            with self.subTest(ext=ext, head=data[:4]):
                p = self.receive(data)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(NAME.match(os.path.basename(p.stdout.decode().strip()))["ext"],
                                 ext)

    def test_anything_else_is_refused_and_leaves_nothing(self):
        for data in (b"", b"hello", b"%PDF-1.7\n" + b"x" * 40, b"RIFF\x24\x00\x00\x00WAVEfmt ",
                     b"BM" + b"\x00" * 40, PNG[:7]):
            with self.subTest(head=data[:8]):
                p = self.receive(data)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, b"")
                self.assertNotEqual(p.stderr, b"")
                self.assertEqual(self.files(), [])

    def test_an_image_over_the_cap_is_refused_and_leaves_nothing(self):
        p = self.receive(PNG + b"\x00" * (CAP + 1 - len(PNG)))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn(b"50 MB", p.stderr)
        self.assertEqual(self.files(), [])

    def test_the_device_name_cannot_steer_the_path(self):
        for device, slug in (("../../x y/z", "x-y-z"), ("LAPTOP-7F", "laptop-7f"), ("", "device"),
                             ("...", "device"), ("a" * 80, "a" * 32)):
            with self.subTest(device=device):
                path = self.receive(PNG, device).stdout.decode().strip()
                self.assertEqual(os.path.dirname(path), self.inbox)
                self.assertEqual(NAME.match(os.path.basename(path))["device"], slug)

    def test_old_inbox_files_are_pruned_on_receive(self):
        day = 24 * 3600
        old = self.put(self.inbox, "20261001T000000Z-laptop-aaaaaa.png", age=day + 60)
        fresh = self.put(self.inbox, "20261015T000000Z-laptop-bbbbbb.png", age=day - 60)
        stale_tmp = self.put(self.inbox, ".incoming-1234.tmp", age=day + 60)
        foreign = self.put(self.inbox, "notes.txt", age=day + 60, data=b"mine")
        p = self.receive(PNG)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(old))
        self.assertFalse(os.path.exists(stale_tmp))
        self.assertTrue(os.path.exists(fresh))
        self.assertTrue(os.path.exists(foreign))

    def test_the_inbox_and_its_files_are_private(self):
        path = self.receive(PNG).stdout.decode().strip()
        self.assertEqual(os.stat(self.inbox).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class Paste(Inbox):
    def test_the_newest_fresh_image_is_pasted_bracketed_into_the_pane(self):
        self.put(self.inbox, "20261015T000000Z-laptop-aaaaaa.png", age=60)
        newest = self.put(self.downloads, "phone.jpg", age=30, data=JPEG)
        self.paste()
        self.assertEqual(self.pasted(), newest)
        tmux = [c[1:] for c in self.calls() if c[0] == "tmux"]
        self.assertEqual(tmux[-2:], [["load-buffer", "-b", "claude-paste", "-"],
                                     ["paste-buffer", "-p", "-d", "-b", "claude-paste",
                                      "-t", "%5"]])

    def test_the_inbox_image_wins_when_it_is_newer(self):
        upload = self.put(self.inbox, "20261015T000000Z-laptop-aaaaaa.png", age=5)
        self.put(self.downloads, "older.png", age=120)
        self.paste()
        self.assertEqual(self.pasted(), upload)

    def test_stale_images_and_non_images_are_skipped(self):
        self.put(self.inbox, "20261015T000000Z-laptop-aaaaaa.png", age=11 * 60)
        self.put(self.downloads, "report.pdf", age=5, data=b"%PDF-1.7")
        self.put(self.downloads, "big.png.crdownload", age=1)
        self.put(self.downloads, ".hidden.png", age=1)
        os.mkdir(os.path.join(self.downloads, "folder.png"))
        self.paste()
        self.assertIsNone(self.pasted())
        said = [c for c in self.calls() if c[1:2] == ["display-message"] and "-p" not in c]
        self.assertEqual(len(said), 1, self.calls())
        self.assertEqual(said[0][1:6], ["display-message", "-c", "/dev/pts/12", "-d", "5000"])
        self.assertIn("10 minutes", said[0][6])

    def test_extensions_match_in_any_case(self):
        shot = self.put(self.downloads, "IMG_0042.JPEG", age=5, data=JPEG)
        self.paste()
        self.assertEqual(self.pasted(), shot)

    def test_a_path_with_spaces_is_quoted(self):
        shot = self.put(self.downloads, "Screenshot 2026-10-15 173847.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), '"%s"' % shot)

    def test_a_pane_in_copy_mode_leaves_it_first(self):
        self.put(self.downloads, "a.png", age=5)
        self.paste(STUB_IN_MODE="1")
        tmux = [c[1:] for c in self.calls() if c[0] == "tmux"]
        cancel = tmux.index(["send-keys", "-X", "-t", "%5", "cancel"])
        self.assertLess(cancel, tmux.index(["load-buffer", "-b", "claude-paste", "-"]))

    def test_a_pane_not_in_a_mode_gets_no_cancel(self):
        self.put(self.downloads, "a.png", age=5)
        self.paste()
        self.assertNotIn("send-keys", [c[1] for c in self.calls() if c[0] == "tmux"])

    def test_a_failing_tmux_still_exits_zero_and_silent(self):
        self.put(self.downloads, "a.png", age=5)
        self.paste(STUB_RC="1")

    def test_missing_folders_only_bring_the_message(self):
        shutil.rmtree(self.downloads)
        self.paste()
        self.assertIsNone(self.pasted())
        self.assertIn("display-message", [c[1] for c in self.calls() if c[0] == "tmux"])

    def test_downloads_is_found_through_windows_once_then_cached(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        shot = self.put(os.path.join(self.tmp, "winhome", "Downloads"), "a.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), shot)
        self.assertEqual([c[0] for c in self.calls() if c[0] != "tmux"], ["cmd.exe", "wslpath"])
        self.assertEqual(self.calls()[0][1:], ["/c", "echo", "%USERPROFILE%"])
        self.assertEqual(self.calls()[1][1:], ["-u", "C:\\Users\\tester"])
        os.remove(self.log)
        os.remove(self.buffer)
        os.remove(os.path.join(self.stubs, "cmd.exe"))
        self.paste()
        self.assertEqual(self.pasted(), shot)
        self.assertEqual([c[0] for c in self.calls() if c[0] != "tmux"], [])

    def test_without_windows_the_inbox_alone_is_used(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        os.remove(os.path.join(self.stubs, "cmd.exe"))
        upload = self.put(self.inbox, "20261015T000000Z-laptop-aaaaaa.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), upload)
        self.paste()   # nothing was cached: a later run still looks for Windows
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state", "dotclaude",
                                                     "paste-inbox", "downloads")))

    def test_an_empty_override_turns_downloads_off(self):
        self.put(self.downloads, "a.png", age=5)
        self.paste(PASTE_INBOX_DOWNLOADS="")
        self.assertIsNone(self.pasted())
        self.assertEqual([c[0] for c in self.calls() if c[0] != "tmux"], [])


class Cli(Inbox):
    def test_the_cli_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_help_and_bad_usage(self):
        p = self.run_script(["--help"])
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"paste-inbox receive", p.stdout)
        self.assertIn(b"paste-inbox paste", p.stdout)
        for args in ([], ["receive"], ["paste", "%5"], ["bogus"]):
            with self.subTest(args=args):
                p = self.run_script(args)
                self.assertEqual(p.returncode, 2)
                self.assertIn(b"usage", p.stderr)


class Wiring(unittest.TestCase):
    def test_alt_v_runs_the_script_and_falls_back_to_the_key(self):
        with open(CONF) as f:
            lines = [line for line in f.read().splitlines() if "M-v" in line
                     and not line.startswith("#")]
        self.assertEqual(lines, [
            "bind -n M-v if-shell '[ -x \"$HOME/.local/bin/paste-inbox\" ]' "
            "{ run-shell '\"$HOME/.local/bin/paste-inbox\" paste \"#{pane_id}\" "
            "\"#{client_name}\" >/dev/null 2>&1; true' } { send-keys M-v }"])

    def test_the_cheatsheet_names_alt_v(self):
        with open(CHEATSHEET) as f:
            self.assertRegex(f.read(), r"\n    M-v +\S")


class RealTmux(unittest.TestCase):
    """The paste on a real tmux server: a pane that turned bracketed paste on (mode 2004) gets
    the path between ESC[200~ and ESC[201~, which is what makes Claude Code attach it. tmux
    can't start inside the Bash sandbox, where this skips: run it sandbox-off once per change
    (`python3 -m unittest tests.setup.test_paste_inbox.RealTmux`)."""

    READER = r"""
import os, select, sys, termios, time, tty
out, ready = sys.argv[1], sys.argv[2]
tty.setraw(0)
os.write(1, b"\x1b[?2004h")
open(ready, "w").close()
got, end = b"", time.time() + 10
while time.time() < end and b"\x1b[201~" not in got:
    if select.select([0], [], [], 0.2)[0]:
        got += os.read(0, 4096)
with open(out, "wb") as f:
    f.write(got)
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        tmux = shutil.which("tmux")
        if not tmux:
            self.skipTest("tmux not installed")
        sock = os.path.join(self.tmp, "sock")
        self.server = [tmux, "-S", sock, "-f", "/dev/null"]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "PASTE_INBOX"))}
        reader = os.path.join(self.tmp, "reader.py")
        with open(reader, "w") as f:
            f.write(self.READER)
        self.out, self.ready = os.path.join(self.tmp, "out"), os.path.join(self.tmp, "ready")
        try:
            start = subprocess.run(self.server + ["new-session", "-d", "-x", "200", "-y", "20",
                                                  "%s -I %s %s %s" % (sys.executable, reader,
                                                                      self.out, self.ready)],
                                   capture_output=True, text=True, timeout=10, env=env)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.skipTest("tmux can't start here: %s" % e)
        if start.returncode:
            self.skipTest("tmux can't start here: %s" % start.stderr.strip()[:80])
        self.addCleanup(subprocess.run, self.server + ["kill-server"], capture_output=True)
        self.pane = subprocess.run(self.server + ["display-message", "-p", "#{pane_id}"],
                                   capture_output=True, text=True, env=env).stdout.strip()
        wrap = os.path.join(self.tmp, "bin")
        os.mkdir(wrap)
        with open(os.path.join(wrap, "tmux"), "w") as f:
            f.write('#!/bin/sh\nexec %s -S %s "$@"\n' % (tmux, sock))
        os.chmod(os.path.join(wrap, "tmux"), 0o755)
        self.downloads = os.path.join(self.tmp, "Downloads")
        os.mkdir(self.downloads)
        self.env = {**env, "PATH": wrap + os.pathsep + "/usr/bin:/bin",
                    "HOME": self.tmp, "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "PASTE_INBOX_DIR": os.path.join(self.tmp, "inbox"),
                    "PASTE_INBOX_DOWNLOADS": self.downloads}

    def test_the_path_arrives_as_a_bracketed_paste(self):
        shot = os.path.join(self.downloads, "shot.png")
        with open(shot, "wb") as f:
            f.write(PNG)
        end = time.time() + 10
        while not os.path.exists(self.ready) and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(self.ready), "the reader never started")
        p = subprocess.run([SCRIPT, "paste", self.pane, ""], capture_output=True, timeout=30,
                           env=self.env)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        while not os.path.exists(self.out) and time.time() < end + 10:
            time.sleep(0.05)
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), b"\x1b[200~" + shot.encode() + b"\x1b[201~")


if __name__ == "__main__":
    unittest.main()
