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


if __name__ == "__main__":
    unittest.main()
