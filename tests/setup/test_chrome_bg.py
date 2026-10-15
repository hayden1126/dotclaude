"""bin/chrome-bg: Windows Chrome behind all windows for headed puppeteer probes (stdlib only).

The real supervisor (chrome-bg.ps1) and Chrome live on the Windows side and the sandbox can't
reach them, so the CLI tests run bin/chrome-bg in a driver process that patches its module-level
seams: `sandboxed` off, `ps_argv` to FAKE_SUP below (the supervisor protocol plus a fake CDP
server), and `wslpath` to a map from C:\\ onto a temp dir. Log fixtures are synthetic lines in the
probe supervisor's format: the probe's real logs carry window titles and the repo is public."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(REPO, "bin", "chrome-bg")


def load():
    loader = importlib.machinery.SourceFileLoader("chrome_bg", CLI)
    spec = importlib.util.spec_from_loader("chrome_bg", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cb = load()


class Framing(unittest.TestCase):
    """The WebSocket client's frames: masked out, 7/16/64-bit lengths, fragments, ping."""

    def test_client_frames_are_masked(self):
        frame = cb.encode_frame(cb.OP_TEXT, b"hello", mask_key=b"\x01\x02\x03\x04")
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 0x80 | 5)
        self.assertEqual(frame[2:6], b"\x01\x02\x03\x04")
        self.assertEqual(frame[6:], bytes(b ^ k for b, k in zip(b"hello", b"\x01\x02\x03\x04\x01")))
        fin, op, payload, used = cb.decode_frame(frame)
        self.assertEqual((fin, op, payload, used), (True, cb.OP_TEXT, b"hello", len(frame)))

    def test_length_encodings(self):
        for n, head in ((125, 2), (126, 4), (65535, 4), (65536, 10)):
            with self.subTest(n=n):
                payload = bytes(range(256)) * (n // 256) + bytes(n % 256)
                frame = cb.encode_frame(cb.OP_BINARY, payload)
                self.assertEqual(len(frame), head + 4 + n)
                self.assertEqual(frame[1] & 0x7F, {2: n, 4: 126, 10: 127}[head])
                self.assertEqual(cb.decode_frame(frame)[2], payload)
                self.assertIsNone(cb.decode_frame(frame[:-1]))
                # A server frame: unmasked.
                server = self.server_frame(cb.OP_TEXT, payload)
                self.assertEqual(cb.decode_frame(server)[2], payload)

    @staticmethod
    def server_frame(op, payload, fin=True):
        n = len(payload)
        head = bytes([(0x80 if fin else 0) | op])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack("!H", n)
        else:
            head += bytes([127]) + struct.pack("!Q", n)
        return head + payload

    def pair(self):
        """A WebSocket on one end of a socketpair, past a scripted handshake."""
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        b.settimeout(5)
        ws = cb.WebSocket.__new__(cb.WebSocket)
        ws.sock, ws.buf, ws.closed = a, b"", False
        return ws, b

    def test_fragments_and_ping(self):
        ws, peer = self.pair()
        msg = json.dumps({"id": 1, "result": {"x": "y" * 300}}).encode()
        peer.sendall(self.server_frame(cb.OP_TEXT, msg[:100], fin=False)
                     + self.server_frame(cb.OP_PING, b"are you there")
                     + self.server_frame(cb.OP_CONT, msg[100:200], fin=False)
                     + self.server_frame(cb.OP_CONT, msg[200:]))
        self.assertEqual(ws.recv(timeout=5), msg.decode())
        pong = peer.recv(100)
        fin, op, payload, _ = cb.decode_frame(pong)
        self.assertEqual((op, payload), (cb.OP_PONG, b"are you there"))
        self.assertTrue(pong[1] & 0x80, "the pong is masked")

    def test_close_frame(self):
        ws, peer = self.pair()
        peer.sendall(self.server_frame(cb.OP_CLOSE, struct.pack("!H", 1000)))
        with self.assertRaises(cb.ConnectionClosed):
            ws.recv(timeout=5)
        self.assertEqual(cb.decode_frame(peer.recv(100))[1], cb.OP_CLOSE)

    def test_read_timeout(self):
        ws, _ = self.pair()
        with self.assertRaises(TimeoutError):
            ws.recv(timeout=0.2)

    def test_handshake_sends_no_origin_and_checks_accept(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        import base64
        import hashlib
        import threading
        seen = {}

        def serve(accept_ok):
            c, _ = srv.accept()
            with c:
                c.settimeout(5)
                data = b""
                while b"\r\n\r\n" not in data:
                    data += c.recv(4096)
                head = data.decode().split("\r\n")
                seen["req"] = head[0]
                seen["headers"] = {ln.split(":")[0].lower() for ln in head[1:] if ":" in ln}
                key = [ln.split(":", 1)[1].strip() for ln in head if ln.lower().startswith("sec-websocket-key")][0]
                acc = base64.b64encode(hashlib.sha1((key + cb.WS_GUID).encode()).digest()).decode()
                c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Accept: {acc if accept_ok else 'x'}\r\n\r\n").encode()
                          + self.server_frame(cb.OP_TEXT, b'{"id":1,"result":{}}'))
                time.sleep(0.3)

        for ok in (True, False):
            t = threading.Thread(target=serve, args=(ok,), daemon=True)
            t.start()
            if ok:
                ws = cb.WebSocket(f"ws://127.0.0.1:{port}/devtools/browser/abc", timeout=5)
                self.assertEqual(ws.recv(timeout=5), '{"id":1,"result":{}}')
                ws.close()
                self.assertEqual(seen["req"], "GET /devtools/browser/abc HTTP/1.1")
                self.assertNotIn("origin", seen["headers"])
            else:
                with self.assertRaises(ConnectionError):
                    cb.WebSocket(f"ws://127.0.0.1:{port}/x", timeout=5)
            t.join(5)


class OffScreen(unittest.TestCase):
    W = 1280

    def test_one_monitor(self):
        self.assertEqual(cb.offscreen_x(0, self.W), -2280)

    def test_monitor_at_negative_x(self):
        x = cb.offscreen_x(-1920, self.W)
        self.assertEqual(x, -4200)
        self.assertLess(x + self.W, -1920)

    def test_monitor_right_of_primary_changes_nothing(self):
        self.assertEqual(cb.offscreen_x(0, self.W), cb.offscreen_x(min(0, 1920), self.W))

    def test_dpi_scaling_only_moves_it_further_left(self):
        # The screen edge is physical; Chrome maps DIPs to physical pixels by a scale >= 1.
        for left in (0, -1920, -3840):
            x = cb.offscreen_x(left, self.W)
            for scale in (1, 1.25, 1.5, 2):
                with self.subTest(left=left, scale=scale):
                    self.assertLess((x + self.W) * scale, min(left, 0))

    def test_clamp(self):
        self.assertEqual(cb.offscreen_x(-40000, self.W), -32767)
        self.assertGreaterEqual(cb.offscreen_x(-31000, self.W), -32767)


class Flags(unittest.TestCase):
    def test_flag_merge(self):
        args = cb.chrome_args(r"C:\T\chrome-bg\0123abcd\profile")
        feats = [a for a in args if a.startswith("--disable-features=")]
        self.assertEqual(len(feats), 1)
        self.assertEqual(set(feats[0].split("=", 1)[1].split(",")),
                         {"Translate", "AcceptCHFrame", "MediaRouter", "OptimizationHints",
                          "ProcessPerSiteUpToMainFrameThreshold", "IsolateSandboxedIframes",
                          "CalculateNativeWinOcclusion"})
        for dropped in ("--disable-popup-blocking", "about:blank", "--disable-dev-shm-usage",
                        "--use-mock-keychain"):
            self.assertNotIn(dropped, args)
        self.assertFalse([a for a in args if a.startswith("--password-store")])
        for kept in ("--enable-automation", "--no-startup-window", "--remote-debugging-port=0",
                     "--enable-features=PdfOopif", "--disable-backgrounding-occluded-windows"):
            self.assertEqual(args.count(kept), 1, kept)
        self.assertEqual(len([a for a in args if "enable-features" in a and "disable" not in a]), 1)
        self.assertEqual(args[-1], r'"--user-data-dir=C:\T\chrome-bg\0123abcd\profile"')

    def test_port_file(self):
        self.assertIsNone(cb.parse_port_file(""))
        self.assertIsNone(cb.parse_port_file("51234"))
        self.assertIsNone(cb.parse_port_file("51234\n"))
        self.assertIsNone(cb.parse_port_file("x\n/devtools/browser/ab-12\n"))
        self.assertIsNone(cb.parse_port_file("70000\n/devtools/browser/ab-12\n"))
        self.assertEqual(cb.parse_port_file("51234\n/devtools/browser/ab-12"), (51234, "/devtools/browser/ab-12"))
        self.assertEqual(cb.parse_port_file("51234\r\n/devtools/browser/ab-12\r\n"), (51234, "/devtools/browser/ab-12"))

    def test_rect_forms(self):
        for v in ({"left": -8, "top": 0, "right": 1912, "bottom": 1040},
                  {"Left": -8, "Top": 0, "Right": 1912, "Bottom": 1040},
                  {"x": -8, "y": 0, "width": 1920, "height": 1040},
                  [-8, 0, 1912, 1040], "-8,0,1912,1040"):
            self.assertEqual(cb.rect(v), (-8, 0, 1912, 1040))
        with self.assertRaises(cb.Fail):
            cb.rect({"nope": 1})


class Trust(unittest.TestCase):
    """What runs sandbox-off can't be moved by PATH or the environment."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def patch(self, name, value):
        old = getattr(cb, name)
        setattr(cb, name, value)
        self.addCleanup(setattr, cb, name, old)

    def test_powershell_outside_mnt_refused(self):
        fake = os.path.join(self.tmp, "c", "Windows", "System32", "WindowsPowerShell", "v1.0")
        os.makedirs(fake)
        open(os.path.join(fake, "powershell.exe"), "w").close()
        self.patch("MNT", self.tmp)
        with self.assertRaises(cb.Fail):
            cb.powershell()

    def test_powershell_pattern(self):
        self.assertTrue(cb.PS_RE.fullmatch("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"))
        self.assertTrue(cb.PS_RE.fullmatch("/mnt/d/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"))
        for bad in ("/tmp/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/../powershell.exe",
                    "/home/x/bin/powershell.exe"):
            self.assertIsNone(cb.PS_RE.fullmatch(bad), bad)

    def test_path_and_env_do_not_move_it(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        planted = os.path.join(bindir, "powershell.exe")
        with open(planted, "w") as f:
            f.write("#!/bin/sh\necho planted\n")
        os.chmod(planted, 0o755)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = bindir + os.pathsep + old
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        try:
            found = cb.powershell()
        except cb.Fail:
            found = None
        self.assertNotEqual(found, planted)
        self.assertEqual(cb.WSLPATH, "/usr/bin/wslpath")

    def test_ps1_missing_refused(self):
        self.patch("REPO", self.tmp)
        with self.assertRaises(cb.Fail):
            cb.ps1()

    def test_sandbox_refusal(self):
        self.patch("sandboxed", lambda proc="/proc": True)
        self.patch("ps_argv", lambda *a: self.fail("reached Windows from the sandbox"))
        for argv in (["ls"], ["check"], ["stop", "--gc"], ["stop", "0123abcd"], ["start"],
                     ["run", "--", "true"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(cb.main(argv), 2)
                self.assertIn("run it with the sandbox off", err.getvalue())

    def test_help_works_in_the_sandbox(self):
        self.patch("sandboxed", lambda proc="/proc": True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
            cb.main(["--help"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("chrome-bg run", out.getvalue())


# The Windows side, faked: chrome-bg.ps1's protocol (PLAN.md "Supervisor protocol") over stdin and
# stdout, and on `launch` a CDP server (HTTP /json/version plus a WebSocket) with a
# DevToolsActivePort in the run dir. --root stands for C:\. It notes what it saw in files under
# --root: launch-<id> (Chrome's args), cdp-<id> (each CDP call), place-<id>, eof-<id>, kill-<id>.
FAKE_SUP = r'''
import base64, hashlib, json, os, re, shutil, socket, struct, sys, threading, time, uuid

args = sys.argv[1:]
root = args[args.index("--root") + 1]
WIN = "C:\\T\\chrome-bg\\"
env = os.environ


def unix(w):
    assert w.startswith("C:\\"), w
    return os.path.join(root, w[3:].replace("\\", "/"))


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def note(name, text=""):
    with open(os.path.join(root, name), "a") as f:
        f.write(text + "\n")


base = unix(WIN)
os.makedirs(base, exist_ok=True)
if "-Scan" in args:
    dirs, procs = [], []
    for name in sorted(os.listdir(base)):
        if os.path.isdir(os.path.join(base, name)):
            dirs.append({"id": name, "age": time.time() - os.path.getmtime(os.path.join(base, name))})
        if os.path.exists(os.path.join(root, "alive-" + name)):
            procs.append({"id": name, "pids": [4242, 4243]})
    out({"ok": True, "root": WIN, "dirs": dirs, "procs": procs})
    sys.exit(0)

rid = args[args.index("-Id") + 1]
run_dir = os.path.join(base, rid)


def cleanup():
    shutil.rmtree(run_dir, ignore_errors=True)
    try:
        os.remove(os.path.join(root, "alive-" + rid))
    except FileNotFoundError:
        pass


if "-Kill" in args:
    note("kill-" + rid)
    cleanup()
    out({"ok": True, "killed": 0})
    sys.exit(0)

t0 = time.monotonic()
logf = open(os.path.join(base, rid + ".log"), "a", buffering=1)


def log(text):
    logf.write("t=%d %s\n" % (int((time.monotonic() - t0) * 1000), text))


log("FOREGROUND tagged=0 idle=900 via=start hwnd=100 pid=10 cls=TestTerminal rect=0,0,1920,1040 "
    "onscreen=1 vis=1 iconic=0 cloaked=0")
guid = str(uuid.uuid4())
bounds = {}
state = {"closed": False, "srv": None, "port": None}


def frame(op, payload, fin=True):
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | op])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack("!H", n)
    else:
        head += bytes([127]) + struct.pack("!Q", n)
    return head + payload


def recvn(c, n):
    data = b""
    while len(data) < n:
        chunk = c.recv(n - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def read_msg(c):
    b0, b1 = recvn(c, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", recvn(c, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", recvn(c, 8))[0]
    if not b1 & 0x80:
        note("unmasked")
        raise EOFError
    key = recvn(c, 4)
    return b0 & 0x0F, bytes(b ^ key[i % 4] for i, b in enumerate(recvn(c, n)))


def dispatch(msg):
    m, p = msg["method"], msg.get("params") or {}
    note("cdp-" + rid, json.dumps(msg))
    if m == "Target.createTarget":
        if p.get("newWindow"):
            left = 0 if env.get("FAKE_CLAMP") else p["left"]
            bounds.update(left=left, top=p["top"], width=p["width"], height=p["height"],
                          windowState="normal")
        return {"result": {"targetId": "T%d" % msg["id"]}}
    if m == "Browser.getWindowForTarget":
        return {"result": {"windowId": 1, "bounds": dict(bounds)}}
    if m == "Browser.setWindowBounds":
        bounds.update(p["bounds"])
        return {"result": {}}
    if m == "Browser.close":
        return {"result": {}}
    if m == "Target.attachToTarget":
        return {"result": {"sessionId": "S1"}}
    if m == "Page.bringToFront":
        return {"result": {}}
    if m == "Runtime.evaluate":
        return {"result": {"result": {"type": "string", "value": env.get("FAKE_RAF", "visible 118")}}}
    return {"error": {"code": -32601, "message": "'%s' wasn't found" % m}}


def close_browser():
    state["closed"] = True
    try:
        os.remove(os.path.join(root, "alive-" + rid))
    except FileNotFoundError:
        pass
    state["srv"].close()


def handle(c):
    try:
        c.settimeout(30)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = c.recv(4096)
            if not chunk:
                return
            data += chunk
        lines = data.split(b"\r\n\r\n")[0].decode().split("\r\n")
        path = lines[0].split()[1]
        headers = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines[1:] if ":" in ln)}
        if path == "/json/version":
            ws = ("0" * 8 + guid[8:]) if env.get("FAKE_WRONG_PATH") else guid
            body = json.dumps({"Browser": "FakeChrome/1.0", "webSocketDebuggerUrl":
                               "ws://127.0.0.1:%d/devtools/browser/%s" % (state["port"], ws)}).encode()
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                      % len(body) + body)
            return
        if path != "/devtools/browser/" + guid or "origin" in headers:
            note("refused-ws", path + " " + json.dumps(headers))
            c.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            return
        acc = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"]
                                             + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        first = True
        while True:
            op, data = read_msg(c)
            if op == 0x8:
                return
            if op == 0xA:
                note("pong-" + rid, data.decode())
                continue
            if op != 0x1:
                continue
            msg = json.loads(data)
            reply = json.dumps({"id": msg["id"], **dispatch(msg)}).encode()
            if first:  # the client must answer a ping and join a fragmented message
                c.sendall(frame(0x9, b"ping") + frame(0x1, reply[:5], fin=False) + frame(0x0, reply[5:]))
                first = False
            else:
                c.sendall(frame(0x1, reply))
            if msg["method"] == "Browser.close":
                close_browser()
                return
    except (EOFError, OSError):
        pass
    finally:
        c.close()


def serve(srv):
    while True:
        try:
            c, _ = srv.accept()
        except OSError:
            return
        threading.Thread(target=handle, args=(c,), daemon=True).start()


def write_port(profile):
    path = os.path.join(profile, "DevToolsActivePort")
    with open(path, "w") as f:  # one line first: the client must wait for both
        f.write("%d\n" % state["port"])
    time.sleep(0.3)
    with open(path, "w") as f:
        f.write("%d\n/devtools/browser/%s" % (state["port"], guid))


for line in sys.stdin:
    msg = json.loads(line)
    op = msg.get("op")
    if op == "hello":
        os.makedirs(run_dir, exist_ok=True)
        vs = int(env.get("FAKE_VS_LEFT", "0"))
        out({"ok": True, "version": 1, "chrome": "C:\\Chrome\\chrome.exe", "runDir": WIN + rid + "\\",
             "virtualScreen": {"x": vs, "y": 0, "w": 1920 - vs, "h": 1080},
             "monitors": [{"rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080},
                           "work": {"left": 0, "top": 0, "right": 1920, "bottom": 1032},
                           "dpi": int(env.get("FAKE_DPI", "96")), "hz": 120, "primary": True}],
             "fg": {"desc": "cls=TestTerminal", "visible": not env.get("FAKE_FG_HIDDEN"), "idleMs": 900},
             "fglock": 200000})
    elif op == "launch":
        note("launch-" + rid, msg["args"])
        srv = state["srv"] = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        state["port"] = srv.getsockname()[1]
        threading.Thread(target=serve, args=(srv,), daemon=True).start()
        profile = unix(re.search(r'"--user-data-dir=([^"]+)"', msg["args"]).group(1))
        os.makedirs(profile, exist_ok=True)
        open(os.path.join(root, "alive-" + rid), "w").close()
        threading.Thread(target=write_port, args=(profile,), daemon=True).start()
        out({"ok": True, "pid": 4242})
    elif op == "place":
        note("place-" + rid, json.dumps(msg))
        log("PLACE [True hwnd=200 pid=4242 cls=Chrome_WidgetWin_1 rect=10,10,1290,910 onscreen=1 vis=1]")
        if env.get("FAKE_PLACE_RESIZE"):
            bounds.update(width=bounds["width"] * 2 // 3, height=bounds["height"] * 2 // 3)
        out({"ok": True, "windows": [{"hwnd": 200, "rect": [10, 10, 1290, 910]}]})
    elif op == "procs":
        out({"ok": True, "procs": [] if state["closed"] else [{"pid": 4242, "type": ""}]})
    elif op == "fg":
        out({"ok": True, "fg": {"desc": "cls=TestTerminal", "visible": True, "idleMs": 900}})
    elif op == "mark":
        log("MARK " + msg["text"])
        out({"ok": True})
    else:
        out({"ok": False, "error": "unknown op %r" % op})

log("EOFKILL left=0")
cleanup()
log("EOFCLEAN dirExists=False")
log("EXIT")
note("eof-" + rid)
'''

# Runs bin/chrome-bg as a module with its seams patched: argv = CLI ROOT ARGS...
DRIVER = r'''
import importlib.machinery, importlib.util, os, sys
cli, root = sys.argv[1], sys.argv[2]
loader = importlib.machinery.SourceFileLoader("chrome_bg", cli)
spec = importlib.util.spec_from_loader("chrome_bg", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
fake = os.path.join(root, "fake_sup.py")
mod.sandboxed = lambda proc="/proc": False
mod.ps_argv = lambda *a: [sys.executable, "-I", fake, "--root", root, *a]


def wslpath(flag, p):
    if flag != "-u" or not p.startswith("C:\\"):
        raise mod.Fail("fake wslpath: %s %s" % (flag, p))
    return os.path.join(root, p[3:].replace("\\", "/"))


mod.wslpath = wslpath
if os.environ.get("DRIVER_AFTER_STOP"):
    mod.AFTER_STOP_S = float(os.environ["DRIVER_AFTER_STOP"])
sys.exit(mod.main(sys.argv[3:]))
'''


class Live(unittest.TestCase):
    """start, stop, run and gc end to end against the fake Windows side."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "c")
        self.base = os.path.join(self.root, "T", "chrome-bg")
        os.makedirs(self.base)
        with open(os.path.join(self.root, "fake_sup.py"), "w") as f:
            f.write(FAKE_SUP)
        self.driver = os.path.join(self.tmp, "driver.py")
        with open(self.driver, "w") as f:
            f.write(DRIVER)
        self.state = os.path.join(self.tmp, "state")
        self.recdir = os.path.join(self.state, "dotclaude", "chrome-bg")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "DRIVER_"))}
        self.env["XDG_STATE_HOME"] = self.state
        self.addCleanup(self.reap)

    def reap(self):
        """SIGKILL any holder a failed test left behind (its fake supervisor then sees EOF)."""
        for rec in self.records():
            if cb.owner_proven(rec) and rec["owner"]["pid"] != os.getpid():
                with contextlib.suppress(OSError):
                    os.kill(rec["owner"]["pid"], signal.SIGKILL)

    def cli(self, *argv, env=None, timeout=60):
        return subprocess.run([sys.executable, "-I", self.driver, CLI, self.root, *argv],
                              env={**self.env, **(env or {})}, capture_output=True, text=True,
                              timeout=timeout)

    def records(self):
        try:
            names = os.listdir(self.recdir)
        except OSError:
            return []
        out = []
        for n in sorted(names):
            if re.fullmatch(r"[0-9a-f]{8}\.json", n):
                with open(os.path.join(self.recdir, n)) as f:
                    out.append(json.load(f))
        return out

    def has(self, name):
        return os.path.exists(os.path.join(self.root, name))

    def notes(self, name):
        with open(os.path.join(self.root, name)) as f:
            return [ln for ln in f.read().split("\n") if ln]

    def cdp_calls(self, rid):
        return [json.loads(ln) for ln in self.notes("cdp-" + rid)]

    def wait_for(self, pred, timeout=20, what="condition"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return
            time.sleep(0.1)
        self.fail(f"timed out waiting for {what}")

    def only_run_id(self):
        ids = sorted(n[len("launch-"):] for n in os.listdir(self.root) if n.startswith("launch-"))
        self.assertEqual(len(ids), 1, ids)
        return ids[0]

    def test_run_passes_url_and_exit_code(self):
        out = os.path.join(self.tmp, "url")
        code = "import os, sys; open(sys.argv[1], 'w').write(os.environ['MY_URL']); sys.exit(7)"
        r = self.cli("run", "--env", "MY_URL", "--", sys.executable, "-c", code, out)
        self.assertEqual(r.returncode, 7, r.stderr)
        rid = self.only_run_id()
        with open(out) as f:
            self.assertRegex(f.read(), r"^http://127\.0\.0\.1:\d+$")
        self.assertTrue(self.has("eof-" + rid), "the supervisor saw stdin EOF")
        self.assertFalse(os.path.exists(os.path.join(self.base, rid)), "run dir deleted")
        self.assertEqual(self.records(), [])
        # Chrome's args: one merged --disable-features and the quoted profile in the run dir.
        launch = self.notes("launch-" + rid)[0]
        self.assertEqual(launch.count("--disable-features="), 1)
        self.assertIn(f'"--user-data-dir=C:\\T\\chrome-bg\\{rid}\\profile"', launch)
        calls = self.cdp_calls(rid)
        create = calls[0]
        self.assertEqual(create["method"], "Target.createTarget")
        self.assertEqual(create["params"], {"url": "about:blank", "newWindow": True,
                                            "background": True, "left": -2280, "top": 10,
                                            "width": 1280, "height": 900})
        self.assertEqual(calls[-1]["method"], "Browser.close")
        self.assertNotIn("Browser.setWindowBounds", [c["method"] for c in calls])
        place = json.loads(self.notes("place-" + rid)[0])
        self.assertEqual((place["x"], place["y"], place["w"], place["h"]), (10, 10, 1280, 900))
        self.assertTrue(self.has("pong-" + rid), "the client answered the server's ping")
        self.assertFalse(self.has("refused-ws") or self.has("unmasked"))

    def test_run_exit_code_of_a_signal(self):
        r = self.cli("run", "--", sys.executable, "-c",
                     "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
        self.assertEqual(r.returncode, 128 + 9, r.stderr)
        self.assertTrue(self.has("eof-" + self.only_run_id()))

    def test_sigterm_to_run(self):
        ready, got = os.path.join(self.tmp, "ready"), os.path.join(self.tmp, "got-term")
        code = ("import os, signal, sys, time\n"
                "def h(s, f):\n"
                "    open(sys.argv[2], 'w').close()\n"
                "    signal.signal(signal.SIGTERM, signal.SIG_DFL)\n"
                "    os.kill(os.getpid(), signal.SIGTERM)\n"
                "signal.signal(signal.SIGTERM, h)\n"
                "open(sys.argv[1], 'w').close()\n"
                "time.sleep(60)\n")
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, "run", "--",
                              sys.executable, "-c", code, ready, got],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.wait_for(lambda: os.path.exists(ready), what="the child to start")
            p.send_signal(signal.SIGTERM)
            _, err = p.communicate(timeout=30)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertEqual(p.returncode, 128 + signal.SIGTERM, err)
        self.assertTrue(os.path.exists(got), "the child got SIGTERM")
        rid = self.only_run_id()
        self.assertTrue(self.has("eof-" + rid), "stop ran and the supervisor saw EOF")
        self.assertEqual(self.cdp_calls(rid)[-1]["method"], "Browser.close")
        self.assertEqual(self.records(), [])

    def test_start_then_stop_by_id_and_by_url(self):
        for how in ("id", "url"):
            with self.subTest(how=how):
                r = self.cli("start", "--json")
                self.assertEqual(r.returncode, 0, r.stderr)
                info = json.loads(r.stdout)
                self.assertEqual(set(info), {"id", "url", "port", "pid"})
                self.assertEqual(info["url"], f"http://127.0.0.1:{info['port']}")
                [rec] = [x for x in self.records() if x["id"] == info["id"]]
                self.assertEqual(rec["kind"], "start")
                self.assertTrue(cb.owner_proven(rec), "the holder is alive")
                self.assertNotEqual(rec["owner"]["pid"], os.getpid())
                self.assertGreater(rec["expires"] - rec["created"], 7100)
                self.assertIn("webSocketDebuggerUrl", cb.json_version(info["port"]))
                r = self.cli("stop", info["id"] if how == "id" else info["url"] + "/")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(cb.owner_dead(rec), "the holder exited")
                self.assertTrue(self.has("eof-" + info["id"]))
                self.assertEqual(self.cdp_calls(info["id"])[-1]["method"], "Browser.close")
                self.assertEqual(self.records(), [])

    def test_start_ttl(self):
        r = self.cli("start", "--ttl", "1s")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r"^http://127\.0\.0\.1:\d+$")
        rid = self.only_run_id()
        self.wait_for(lambda: self.has("eof-" + rid) and not self.records(), what="the TTL stop")

    def test_wrong_port_refused(self):
        r = self.cli("run", "--", sys.executable, "-c", "pass", env={"FAKE_WRONG_PATH": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing port", r.stderr)
        rid = self.only_run_id()
        self.assertFalse(self.has("cdp-" + rid), "no CDP call reached the other Chrome")
        self.assertTrue(self.has("eof-" + rid), "the run was still cleaned up")
        self.assertEqual(self.records(), [])

    def test_dpi_resize_resets_size_without_a_window_state(self):
        r = self.cli("run", "--", sys.executable, "-c", "pass", env={"FAKE_PLACE_RESIZE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        sets = [c for c in self.cdp_calls(self.only_run_id()) if c["method"] == "Browser.setWindowBounds"]
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0]["params"]["bounds"], {"width": 1280, "height": 900})

    def test_negative_screen_and_dpi_and_clamp(self):
        r = self.cli("run", "--size", "1000x700", "--", sys.executable, "-c", "pass",
                     env={"FAKE_VS_LEFT": "-1920", "FAKE_DPI": "144", "FAKE_CLAMP": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = self.only_run_id()
        create = self.cdp_calls(rid)[0]["params"]
        self.assertEqual((create["left"], create["width"], create["height"]), (-3920, 1000, 700))
        place = json.loads(self.notes("place-" + rid)[0])
        self.assertEqual((place["w"], place["h"]), (1500, 1050))
        self.assertIn("clamped onto a monitor", r.stderr)

    # ---- gc and ls ----

    def sleeper(self):
        p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(p.wait, 10)
        self.addCleanup(p.kill)
        return p

    def put_record(self, rid, pid, start, **extra):
        os.makedirs(self.recdir, exist_ok=True)
        rec = {"id": rid, "kind": "start", "owner": {"pid": pid, "start": start}, "cwd": "/x",
               "created": time.time() - 60, "expires": None, "port": None, "wsPath": None,
               "runDir": f"C:\\T\\chrome-bg\\{rid}\\", **extra}
        with open(os.path.join(self.recdir, rid + ".json"), "w") as f:
            json.dump(rec, f)

    def put_dir(self, rid, age):
        d = os.path.join(self.base, rid)
        os.makedirs(os.path.join(d, "profile"), exist_ok=True)
        os.utime(d, (time.time() - age,) * 2)

    def test_gc_stops_runs_whose_owner_is_dead(self):
        live = self.sleeper()
        start = cb.proc_stat(live.pid)[1]
        self.put_record("aaaa0001", live.pid, str(int(start) + 1))  # pid reused by a later process
        self.put_record("aaaa0002", 99999999, "5")                  # no such pid
        self.put_record("aaaa0003", live.pid, start)                # alive: left alone
        for rid in ("aaaa0001", "aaaa0002", "aaaa0003"):
            self.put_dir(rid, 600)
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.has("kill-aaaa0001") and self.has("kill-aaaa0002"), r.stdout)
        self.assertFalse(self.has("kill-aaaa0003"))
        self.assertEqual([x["id"] for x in self.records()], ["aaaa0003"])
        self.assertIsNone(live.poll(), "a reused pid is never signalled")
        self.assertIn("stopped aaaa0001: its owner is gone", r.stdout)

    def test_gc_stops_a_run_past_its_ttl(self):
        owner = self.sleeper()
        self.put_record("bbbb0001", owner.pid, cb.proc_stat(owner.pid)[1], expires=time.time() - 1)
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(owner.wait(10), -signal.SIGTERM, "the holder got SIGTERM")
        self.assertTrue(self.has("kill-bbbb0001"), "it did not clean up, so a one-shot did")
        self.assertEqual(self.records(), [])

    def test_gc_skips_young_unrecorded_dirs(self):
        self.put_dir("cccc0001", 5)
        self.put_dir("cccc0002", 600)
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.has("kill-cccc0001"), "a young dir may be a run still launching")
        self.assertTrue(os.path.isdir(os.path.join(self.base, "cccc0001")))
        self.assertTrue(self.has("kill-cccc0002"))
        self.assertFalse(os.path.exists(os.path.join(self.base, "cccc0002")))

    def test_gc_prunes_old_logs(self):
        os.makedirs(self.recdir)
        old, new = time.time() - 8 * 86400, time.time() - 86400
        paths = {os.path.join(self.base, "dddd0001.log"): old,
                 os.path.join(self.base, "dddd0002.log"): new,
                 os.path.join(self.base, "notes.log"): old,
                 os.path.join(self.recdir, "dddd0003.holder.log"): old,
                 os.path.join(self.recdir, "dddd0004.err"): old}
        for p, t in paths.items():
            open(p, "w").close()
            os.utime(p, (t, t))
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        left = {os.path.basename(p) for p in paths if os.path.exists(p)}
        self.assertEqual(left, {"dddd0002.log", "notes.log"})

    def test_run_and_start_gc_first(self):
        self.put_dir("eeee0001", 600)
        r = self.cli("run", "--", sys.executable, "-c", "pass")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.has("kill-eeee0001"))
        self.assertIn("chrome-bg gc: killed eeee0001", r.stderr)
        self.put_dir("eeee0002", 600)
        r = self.cli("start")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.has("kill-eeee0002"))
        self.assertEqual(self.cli("stop", r.stdout.strip()).returncode, 0)

    def test_ls(self):
        r = self.cli("start", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        info = json.loads(r.stdout)
        self.put_dir("ffff0001", 5)
        r = self.cli("ls")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "PORT", "PIDS", "OWNER", "AGE", "CWD"])
        mine = [ln for ln in lines if ln.startswith(info["id"])][0]
        self.assertIn(str(info["port"]), mine)
        self.assertIn("4242,4243", mine)
        self.assertIn("alive (start)", mine)
        self.assertTrue(mine.rstrip().endswith(os.getcwd()))
        orphan = [ln for ln in lines if ln.startswith("ffff0001")][0]
        self.assertIn("no record", orphan)
        self.assertEqual(self.cli("stop", info["id"]).returncode, 0)

    def test_stop_refuses_a_bare_port(self):
        for target, why in (("9222", "not '9222'"), (":9222", "bare"),
                            ("http://127.0.0.1:9222", "no run serves"), ("0123abcd", "no run 0123abcd")):
            with self.subTest(target=target):
                r = self.cli("stop", target)
                self.assertEqual(r.returncode, 1)
                self.assertIn(why, r.stderr)
        self.assertFalse([n for n in os.listdir(self.root) if n.startswith(("kill-", "eof-"))])


if __name__ == "__main__":
    unittest.main()
