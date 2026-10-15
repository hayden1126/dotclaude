"""tmux/paste-inbox and laptop/: the image inbox behind Alt+V (stdlib only).

`receive` and `paste` run as subprocesses against a stub tmux that logs each call as a JSON line
(and keeps what load-buffer reads), with PATH narrowed to the stubs and /usr/bin:/bin so no real
powershell.exe or tmux is reached. Real tmux servers on private sockets check that the paste arrives
bracketed (RealTmux) and that Alt+V, pressed on a client attached through a pty, runs it
(RealBinding); remote-paste.ps1 runs in Windows PowerShell against ends that fail fast
(LaptopPowerShell). The Bash sandbox blocks tmux's socket and WSL interop, so those skip there:
run them sandbox-off once per change."""
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import pty
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "paste-inbox")
CONF = os.path.join(REPO, "tmux", "claude.conf")
CHEATSHEET = os.path.join(REPO, "tmux", "cheatsheet.txt")
LAPTOP = os.path.join(REPO, "laptop")

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

STUB_PS = """#!%s -I
import base64, json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["powershell.exe"] + sys.argv[1:]) + "\\n")
profile = os.environ.get("STUB_PROFILE", "C:\\\\Users\\\\tester")
out = os.environ.get("STUB_PS_OUT") or base64.b64encode(profile.encode()).decode()
sys.stdout.write(out + "\\r\\n")
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
        for name, text in (("tmux", STUB_TMUX), ("powershell.exe", STUB_PS),
                           ("wslpath", STUB_WSLPATH)):
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

    def receive(self, data, device="laptop", size=None, check=False, **env):
        size = len(data) if size is None else size
        return self.run_script(["receive", *(["--check"] if check else []), device, str(size)],
                               data, **env)

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
                     b"BM" + b"\x00" * 40, PNG[:7], b"\xef\xbb\xbf" + PNG):
            with self.subTest(head=data[:8]):
                p = self.receive(data, size=max(len(data), 1))
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, b"")
                self.assertNotEqual(p.stderr, b"")
                self.assertEqual(self.files(), [])

    def test_an_image_over_the_cap_is_refused_and_leaves_nothing(self):
        for data, size in ((PNG + b"\x00" * (CAP + 1 - len(PNG)), None), (PNG, CAP + 1)):
            with self.subTest(size=size):
                p = self.receive(data, size=size)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn(b"50 MB", p.stderr)
                self.assertEqual(self.files(), [])

    def test_an_image_at_the_cap_is_kept(self):
        p = self.receive(PNG + b"\x00" * (CAP - len(PNG)))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(os.path.getsize(p.stdout.decode().strip()), CAP)

    def test_a_size_other_than_the_one_given_is_refused_and_leaves_nothing(self):
        for size in (len(PNG) + 1, len(PNG) - 1):
            with self.subTest(size=size):
                p = self.receive(PNG, size=size)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn(b"expected %d" % size, p.stderr)
                self.assertEqual(self.files(), [])

    def test_check_validates_and_keeps_nothing(self):
        p = self.receive(PNG, "selftest", check=True)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        path = p.stdout.decode().strip()
        self.assertEqual(os.path.dirname(path), self.inbox)
        self.assertEqual(NAME.match(os.path.basename(path))["device"], "selftest")
        self.assertEqual(self.files(), [])
        p = self.receive(b"hello", "selftest", check=True)
        self.assertNotEqual(p.returncode, 0)
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
        self.assertEqual(tmux[-2:], [["load-buffer", "-b", "claude-paste-5", "-"],
                                     ["paste-buffer", "-p", "-d", "-b", "claude-paste-5",
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
        self.put(self.downloads, "camera.jpg", age=-3600, data=JPEG)   # a clock an hour ahead
        self.put(self.downloads, "placeholder.png", age=1, data=b"")
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
        self.assertLess(cancel, tmux.index(["load-buffer", "-b", "claude-paste-5", "-"]))

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

    def test_a_slightly_future_mtime_still_counts(self):
        shot = self.put(self.downloads, "a.png", age=-30)
        self.paste()
        self.assertEqual(self.pasted(), shot)

    def test_a_non_ascii_path_pastes_intact(self):
        shot = self.put(self.downloads, "\u00e9cran.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), shot)

    def test_an_unwritable_state_dir_still_pastes(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        state = os.path.join(self.tmp, "state")
        with open(state, "w") as f:
            f.write("a file where the state dir would be")
        shot = self.put(os.path.join(self.tmp, "winhome", "Downloads"), "a.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), shot)

    def test_downloads_is_found_through_windows_once_then_cached(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        shot = self.put(os.path.join(self.tmp, "winhome", "Downloads"), "a.png", age=5)
        self.paste()
        self.assertEqual(self.pasted(), shot)
        self.assertEqual([c[0] for c in self.calls() if c[0] != "tmux"],
                         ["powershell.exe", "wslpath"])
        self.assertEqual(self.calls()[0][1:4], ["-NoProfile", "-NonInteractive", "-Command"])
        self.assertIn("GetFolderPath('UserProfile')", self.calls()[0][4])
        self.assertEqual(self.calls()[1][1:], ["-u", "C:\\Users\\tester"])
        os.remove(self.log)
        os.remove(self.buffer)
        os.remove(os.path.join(self.stubs, "powershell.exe"))
        self.paste()
        self.assertEqual(self.pasted(), shot)
        self.assertEqual([c[0] for c in self.calls() if c[0] != "tmux"], [])

    def test_a_non_ascii_windows_profile_is_found(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        shot = self.put(os.path.join(self.tmp, "winhome", "Downloads"), "a.png", age=5)
        self.paste(STUB_PROFILE="C:\\Users\\Zo\u00eb")
        self.assertEqual(self.pasted(), shot)
        self.assertEqual(self.calls()[1][1:], ["-u", "C:\\Users\\Zo\u00eb"])

    def test_garbage_from_windows_falls_back_to_the_inbox(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        upload = self.put(self.inbox, "20261015T000000Z-laptop-aaaaaa.png", age=5)
        for out in ("not base64 at all!", "w4k=", "QzpcVXNlcnNc8A=="):   # junk, "é", bad UTF-8
            with self.subTest(out=out):
                if os.path.exists(self.buffer):
                    os.remove(self.buffer)
                self.paste(STUB_PS_OUT=out)
                self.assertEqual(self.pasted(), upload)

    def test_without_windows_the_inbox_alone_is_used(self):
        del self.env["PASTE_INBOX_DOWNLOADS"]
        os.remove(os.path.join(self.stubs, "powershell.exe"))
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


def load():
    """tmux/paste-inbox as a module, for the paths a subprocess can't reach."""
    loader = importlib.machinery.SourceFileLoader("paste_inbox", SCRIPT)
    spec = importlib.util.spec_from_loader("paste_inbox", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class InProcess(unittest.TestCase):
    def setUp(self):
        self.pi = load()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        patch = unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp,
                                                      "PASTE_INBOX_DIR": self.tmp + "/inbox"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_crash_in_paste_is_logged_shown_and_exits_zero(self):
        said = []
        boom = unittest.mock.patch.object(self.pi, "newest_image", side_effect=RuntimeError("boom"))
        record = unittest.mock.patch.object(self.pi, "tmux",
                                            side_effect=lambda *a, **k: said.append(a) or "")
        with boom, record:
            self.assertEqual(self.pi.main(["paste-inbox", "paste", "%5", "/dev/pts/9"]), 0)
        log = os.path.join(self.tmp, "dotclaude", "paste-inbox", "error.log")
        with open(log) as f:
            self.assertIn("RuntimeError: boom", f.read())
        self.assertEqual(said, [("display-message", "-c", "/dev/pts/9", "-d", "5000",
                                 "paste-inbox failed; see %s" % log)])

    def test_an_upload_that_stalls_is_refused_and_leaves_nothing(self):
        r, w = os.pipe()
        self.addCleanup(os.close, w)
        stdin = io.TextIOWrapper(open(r, "rb"))
        self.addCleanup(stdin.close)
        os.write(w, PNG)                      # a start, then nothing and no EOF
        err = io.StringIO()
        with unittest.mock.patch.object(self.pi, "STALL", 1), \
                unittest.mock.patch.object(sys, "stdin", stdin), \
                unittest.mock.patch.object(sys, "stderr", err):
            start = time.monotonic()
            self.assertEqual(self.pi.receive("laptop", 10 * len(PNG), False), 1)
        self.assertLess(time.monotonic() - start, 5)
        self.assertIn("stalled", err.getvalue())
        self.assertFalse(os.path.exists(self.tmp + "/inbox"))


class Cli(Inbox):
    def test_the_cli_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_help_and_bad_usage(self):
        p = self.run_script(["--help"])
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"paste-inbox receive", p.stdout)
        self.assertIn(b"paste-inbox paste", p.stdout)
        for args in ([], ["receive"], ["receive", "laptop"], ["receive", "laptop", "0"],
                     ["receive", "laptop", "12x"], ["receive", "--check", "laptop"],
                     ["paste", "%5"], ["bogus"]):
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


class Laptop(unittest.TestCase):
    """laptop/: the Windows side. No AutoHotkey here, so the .ahk gets static checks; the .ps1
    files parse in Windows PowerShell where WSL interop works (the Bash sandbox blocks it, so
    that test skips there)."""

    def read(self, name):
        with open(os.path.join(LAPTOP, name), encoding="utf-8") as f:
            return f.read()

    def test_the_title_pattern_matches_only_a_remote_tmux_view(self):
        installer = re.search(r"\[string\]\$TitlePattern = '([^']*)'",
                              self.read("install-remote-paste.ps1"))[1]
        ahk = re.search(r'"remote-paste", "title", "([^"]*)"\)', self.read("remote-paste.ahk"))[1]
        self.assertEqual(ahk, installer)
        for title in ("view-2313 · ✳ Claude Code", "view-17890 · zsh"):
            self.assertRegex(title, installer)
        for title in ("main · Claude Code", "~ : zsh", "Ubuntu", "preview-1 · x", "view-x · y"):
            self.assertNotRegex(title, installer)

    def test_the_pieces_name_each_other(self):
        self.assertIn('Send(code = 3 ? "^v" : "!v")', self.read("remote-paste.ahk"))  # M-v
        self.assertIn("remote-paste.ps1", self.read("remote-paste.ahk"))
        ps1 = self.read("remote-paste.ps1")
        self.assertIn("'--exec', '.local/bin/paste-inbox'\n$wsl += $receive + @($device, "
                      "$bytes.Length)", ps1)
        self.assertIn("if ($SelfTest) { $receive += '--check' }", ps1)
        with open(os.path.join(REPO, "setup-tmux.sh")) as f:
            self.assertIn('"$HOME/.local/bin/paste-inbox"', f.read())

    def test_a_pc_without_the_helper_is_named_plainly(self):
        # wsl.exe 2.x's line for a missing --exec target, captured on the PC
        line = ("<3>WSL (90981 - Relay) ERROR: CreateProcessCommon:735: "
                "execvpe(.local/bin/paste-inbox) failed: No such file or directory")
        pattern = re.search(r"\$stderr -match '([^']+)'", self.read("remote-paste.ps1"))[1]
        self.assertRegex(line, pattern)
        self.assertNotRegex(line.replace("paste-inbox", "other"), pattern)

    def test_no_host_or_account_name_ships(self):
        for name in sorted(os.listdir(LAPTOP)):
            with self.subTest(name=name):
                self.assertNotRegex(self.read(name), r"(?i)ts\.net|tail[0-9a-f]{6}|hayde|haypc")

    def test_the_powershell_scripts_parse(self):
        ps = shutil.which("powershell.exe") \
            or "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
        if not os.path.exists(ps):
            self.skipTest("no Windows PowerShell here")
        check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                 "$env:RP_PS1, [ref]$null, [ref]$e); 'errors=' + $e.Count; $e | ForEach-Object "
                 "{ $_.Extent.StartLineNumber.ToString() + ': ' + $_.Message }")
        for name in ("remote-paste.ps1", "install-remote-paste.ps1"):
            with self.subTest(name=name):
                env = {**os.environ, "RP_PS1": os.path.join(LAPTOP, name), "WSLENV": "RP_PS1/p"}
                p = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", check],
                                   capture_output=True, text=True, timeout=60, env=env)
                if "UtilConnectUnix" in p.stderr or "UtilConnectUnix" in p.stdout:
                    self.skipTest("the Bash sandbox blocks WSL interop; run outside it")
                self.assertEqual(p.stdout.replace("\r", "").strip(), "errors=0", p.stderr)


class LaptopPowerShell(unittest.TestCase):
    """remote-paste.ps1 run for real in Windows PowerShell, from a temp folder with its own ini,
    against ends that fail fast here: no key reaches the PC from itself, so the happy path is
    the installer's self-test on the laptop. Needs WSL interop, which the Bash sandbox blocks,
    so these skip there."""

    def setUp(self):
        self.ps = shutil.which("powershell.exe") \
            or "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
        if not os.path.exists(self.ps):
            self.skipTest("no Windows PowerShell here")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copy(os.path.join(LAPTOP, "remote-paste.ps1"), self.tmp)

    def self_test(self, **ini):
        values = {"target": "nobody@127.0.0.1", "port": "1", "distro": "Ubuntu",
                  "laptopDistro": "", **ini}
        with open(os.path.join(self.tmp, "remote-paste.ini"), "w") as f:
            f.write("[remote-paste]\n" + "".join("%s=%s\n" % kv for kv in values.items()))
        win = subprocess.run(["wslpath", "-w", os.path.join(self.tmp, "remote-paste.ps1")],
                             capture_output=True, text=True).stdout.strip()
        command = ("& '%s' -SelfTest; $c = $LASTEXITCODE; Remove-Item -LiteralPath "
                   "(Join-Path $env:TEMP 'remote-paste.err') -ErrorAction SilentlyContinue; "
                   "exit $c" % win)
        p = subprocess.run([self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                            "Bypass", "-Command", command], capture_output=True, timeout=90)
        err = p.stderr.decode("utf-8", "replace")
        if "UtilConnectUnix" in err or "UtilConnectUnix" in p.stdout.decode("utf-8", "replace"):
            self.skipTest("the Bash sandbox blocks WSL interop; run outside it")
        return p.returncode, err

    def test_an_unreachable_pc_fails_fast_with_ssh_s_reason(self):
        start = time.monotonic()
        code, err = self.self_test()     # 127.0.0.1:1 refuses or times out (ConnectTimeout 5)
        self.assertEqual(code, 1, err)
        self.assertIn("remote-paste: ssh: connect to host 127.0.0.1 port 1", err)
        self.assertLess(time.monotonic() - start, 30)

    def test_wsl_s_own_error_arrives_readable(self):
        code, err = self.self_test(laptopDistro="NoSuchDistro")
        self.assertEqual(code, 1, err)
        self.assertNotIn("\x00", err)
        self.assertRegex(err, r"remote-paste: \S")
        self.assertIn("There is no distribution with the supplied name", err)

    def test_a_bad_target_is_refused_before_any_connection(self):
        code, err = self.self_test(target="a b@c")
        self.assertEqual(code, 1, err)
        self.assertIn("bad target", err)


class RealTmux(unittest.TestCase):
    """The paste on a real tmux server: a pane that turned bracketed paste on (mode 2004) gets
    the path between ESC[200~ and ESC[201~, which is what makes Claude Code attach it. tmux
    can't start inside the Bash sandbox, where these skip: run them sandbox-off once per change
    (`python3 -m unittest tests.setup.test_paste_inbox.RealTmux
    tests.setup.test_paste_inbox.RealBinding`)."""

    READER = r"""
import os, select, sys, time, tty
out, ready = sys.argv[1], sys.argv[2]
tty.setraw(0)
os.write(1, b"\x1b[?2004h")
open(ready, "w").close()
got, end, last = b"", time.time() + 60, None
while time.time() < end and b"\x1b[201~" not in got:
    if select.select([0], [], [], 0.1)[0]:
        got, last = got + os.read(0, 4096), time.time()
    elif last and time.time() - last > 0.5:
        break
with open(out, "wb") as f:
    f.write(got)
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        tmux = shutil.which("tmux")
        if not tmux:
            self.skipTest("tmux not installed")
        self.sock = os.path.join(self.tmp, "sock")
        self.server = [tmux, "-S", self.sock, "-f", "/dev/null"]
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        self.downloads = os.path.join(self.tmp, "Downloads")
        os.mkdir(self.downloads)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "PASTE_INBOX"))}
        self.env = {**env, "PATH": os.path.dirname(tmux) + os.pathsep + "/usr/bin:/bin",
                    "HOME": self.home, "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "PASTE_INBOX_DIR": os.path.join(self.tmp, "inbox"),
                    "PASTE_INBOX_DOWNLOADS": self.downloads, "TERM": "xterm-256color"}
        reader = os.path.join(self.tmp, "reader.py")
        with open(reader, "w") as f:
            f.write(self.READER)
        self.out, self.ready = os.path.join(self.tmp, "out"), os.path.join(self.tmp, "ready")
        try:
            start = subprocess.run(self.server + ["new-session", "-d", "-s", "t", "-x", "100",
                                                  "-y", "20", "%s -I %s %s %s" % (
                                                      sys.executable, reader, self.out,
                                                      self.ready)],
                                   capture_output=True, text=True, timeout=10, env=self.env)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.skipTest("tmux can't start here: %s" % e)
        if start.returncode:
            self.skipTest("tmux can't start here: %s" % start.stderr.strip()[:80])
        self.addCleanup(subprocess.run, self.server + ["kill-server"], capture_output=True)
        self.pane, pid = self.ask("#{pane_id} #{pid}").split()
        self.tmux_env = {**self.env, "TMUX": "%s,%s,0" % (self.sock, pid)}
        end = time.time() + 10
        while not os.path.exists(self.ready) and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(self.ready), "the reader never started")

    def ask(self, fmt):
        return subprocess.run(self.server + ["display-message", "-p", fmt], capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def shot(self):
        path = os.path.join(self.downloads, "shot.png")
        with open(path, "wb") as f:
            f.write(PNG)
        return path

    def received(self):
        end = time.time() + 60
        while not os.path.exists(self.out) and time.time() < end:
            time.sleep(0.05)
        with open(self.out, "rb") as f:
            return f.read()

    def test_the_path_arrives_as_a_bracketed_paste(self):
        shot = self.shot()
        p = subprocess.run([SCRIPT, "paste", self.pane, ""], capture_output=True, timeout=30,
                           env=self.tmux_env)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertEqual(self.received(), b"\x1b[200~" + shot.encode() + b"\x1b[201~")


class RealBinding(RealTmux):
    """Alt+V itself: tmux/claude.conf sourced into the server, a client attached through a pty,
    and `send-keys -K` pressing M-v on that client, so if-shell, run-shell's format expansion
    and the fallback all run as tmux runs them. Skips in the Bash sandbox, like RealTmux."""

    def setUp(self):
        super().setUp()
        p = subprocess.run(self.server + ["source-file", CONF], capture_output=True, text=True,
                           env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 100, 0, 0))
        client = subprocess.Popen(self.server + ["attach", "-t", "t"], stdin=slave,
                                  stdout=slave, stderr=slave, env=self.env,
                                  start_new_session=True)
        os.close(slave)
        self.addCleanup(os.close, master)
        self.addCleanup(client.wait, 10)
        self.addCleanup(client.terminate)
        drain = threading.Thread(target=self.drain, args=(master,), daemon=True)
        drain.start()
        end = time.time() + 10
        self.client = ""
        while not self.client and time.time() < end:
            self.client = subprocess.run(self.server + ["list-clients", "-F", "#{client_name}"],
                                         capture_output=True, text=True,
                                         env=self.env).stdout.strip()
            time.sleep(0.05)
        self.assertTrue(self.client, "the client never attached")

    @staticmethod
    def drain(fd):
        """Read the client's screen so its pty never fills."""
        try:
            while os.read(fd, 65536):
                pass
        except OSError:
            pass

    def press_alt_v(self):
        p = subprocess.run(self.server + ["send-keys", "-K", "-c", self.client, "M-v"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_alt_v_pastes_the_newest_image_into_the_pane(self):
        os.symlink(SCRIPT, os.path.join(self.home, ".local", "bin", "paste-inbox"))
        shot = self.shot()
        self.press_alt_v()
        self.assertEqual(self.received(), b"\x1b[200~" + shot.encode() + b"\x1b[201~")

    def test_without_the_script_alt_v_reaches_the_pane(self):
        self.shot()
        self.press_alt_v()
        self.assertEqual(self.received(), b"\x1bv")


if __name__ == "__main__":
    unittest.main()
