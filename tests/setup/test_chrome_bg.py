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
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(REPO, "bin", "chrome-bg")


def load():
    loader = importlib.machinery.SourceFileLoader("chrome_bg", CLI)
    spec = importlib.util.spec_from_loader("chrome_bg", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cb = load()

# The supervisor's replies, as the real chrome-bg.ps1 sent them under PowerShell 5.1 (lane
# chrome-bg, 2026-10-15; the username redacted to `someone`, the shapes verbatim). The fake
# supervisor below answers from these same objects, so it can't drift from the real one.
HELLO = (r'{"ok":true,"version":1,"chrome":"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",'
         r'"runDir":"C:\\Users\\someone\\AppData\\Local\\Temp\\chrome-bg\\5a0ce001",'
         r'"virtualScreen":{"x":0,"y":0,"w":1920,"h":1080},'
         r'"monitors":[{"rect":{"x":0,"y":0,"w":1920,"h":1080},"work":{"x":0,"y":0,"w":1920,"h":1032},'
         r'"dpi":96,"hz":120,"primary":true}],'
         r'"fg":{"hwnd":524472,"pid":43776,"cls":"CASCADIA_HOSTING_WINDOW_CLASS",'
         r'"rect":{"x":-8,"y":-8,"w":1936,"h":1048},"visible":true,"iconic":false,"cloaked":false,'
         r'"tagged":false,"idleMs":973625},"fglock":2147483647}')
FG = (r'{"ok":true,"fg":{"hwnd":524472,"pid":43776,"cls":"CASCADIA_HOSTING_WINDOW_CLASS",'
      r'"rect":{"x":-8,"y":-8,"w":1936,"h":1048},"visible":true,"iconic":false,"cloaked":false,'
      r'"tagged":false,"idleMs":973625}}')
PROCS_EMPTY = r'{"ok":true,"procs":[]}'
PROCS = (r'{"ok":true,"procs":[{"pid":47292,"ppid":1234,"type":"browser"},'
         r'{"pid":47300,"ppid":47292,"type":"renderer"}]}')
LAUNCH = r'{"ok":true,"pid":47292}'
LAUNCH_FAIL_WMI = r'{"ok":false,"error":"Win32_Process Create failed","code":9}'
LAUNCH_FAIL_ARGS = r'{"ok":false,"error":"launch args must hold the run dir (\\chrome-bg\\5a0ce001\\)"}'
PLACE = r'{"ok":true,"windows":[{"hwnd":9569902,"rect":{"x":10,"y":10,"w":1280,"h":900}}]}'
MARK = r'{"ok":true}'
OP_ERROR = r'{"ok":false,"error":"unknown op: bogus"}'
SCAN = (r'{"ok":true,"root":"C:\\Users\\someone\\AppData\\Local\\Temp\\chrome-bg",'
        r'"dirs":[{"id":"5a0ce001","createdUtc":"2026-10-15T03:20:00.0000000Z","ageSec":12}],'
        r'"logs":[{"id":"5a0ce001","ageSec":2}],'
        r'"procs":{"5a0ce001":[{"pid":47292,"ppid":1234,"type":"browser"}]}}')
SCAN_EMPTY = (r'{"ok":true,"root":"C:\\Users\\someone\\AppData\\Local\\Temp\\chrome-bg",'
              r'"dirs":[],"logs":[],"procs":{}}')
KILL = r'{"ok":true,"killed":0,"left":0,"dirExists":false}'
LOG_FG = ("t=15 FOREGROUND tagged=0 idle=973468 via=start hwnd=524472 pid=43776 "
          "cls=CASCADIA_HOSTING_WINDOW_CLASS rect=-8,-8,1928,1040 onscreen=1 vis=1 iconic=0 cloaked=0")
CONTRACT = {name: json.loads(text) for name, text in (
    ("hello", HELLO), ("fg", FG), ("procs_empty", PROCS_EMPTY), ("procs", PROCS),
    ("launch", LAUNCH), ("launch_fail_wmi", LAUNCH_FAIL_WMI), ("launch_fail_args", LAUNCH_FAIL_ARGS),
    ("place", PLACE), ("mark", MARK), ("op_error", OP_ERROR), ("scan", SCAN),
    ("scan_empty", SCAN_EMPTY), ("kill", KILL))}
CONTRACT["log_fg"] = LOG_FG
WINROOT = CONTRACT["scan"]["root"]  # C:\Users\someone\AppData\Local\Temp\chrome-bg


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
        ws.sock, ws.buf, ws.closed, ws.partial = a, b"", False, None
        return ws, b

    def test_fragments_survive_a_timeout(self):
        # CDP.send reads in short slices to poll for stop signals: a slice may end mid-message.
        ws, peer = self.pair()
        peer.sendall(self.server_frame(cb.OP_TEXT, b'{"id":1,', fin=False))
        with self.assertRaises(TimeoutError):
            ws.recv(timeout=0.2)
        peer.sendall(self.server_frame(cb.OP_CONT, b'"result":{}}'))
        self.assertEqual(ws.recv(timeout=5), '{"id":1,"result":{}}')

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

    def test_rect_is_xywh_only(self):
        self.assertEqual(cb.rect({"x": -8, "y": -8, "w": 1936, "h": 1048}, "hello.fg.rect"),
                         (-8, -8, 1936, 1048))
        for v in ({"left": -8, "top": 0, "right": 1912, "bottom": 1040},
                  {"X": -8, "Y": 0, "W": 1920, "H": 1040},
                  {"x": -8, "y": 0, "width": 1920, "height": 1040},
                  {"x": -8, "y": 0, "w": "1920", "h": 1040},
                  {"x": -8, "y": 0, "w": True, "h": 1040},
                  [-8, 0, 1912, 1040], "-8,0,1912,1040"):
            with self.subTest(v=v), self.assertRaises(cb.Fail) as e:
                cb.rect(v, "hello.virtualScreen")
            self.assertIn("hello.virtualScreen", str(e.exception))


TERM = "hwnd=100 pid=10 cls=TestTerminal rect=0,0,1920,1040 onscreen=1 vis=1 iconic=0 cloaked=0"
WIN = "hwnd=200 pid=4242 cls=Chrome_WidgetWin_1 rect=10,10,1290,910 onscreen=1"
CLEAN = [
    f"t=5 FOREGROUND tagged=0 idle=900 via=start {TERM}",
    f"t=6 TOP tagged=0 via=start {TERM}",
    "t=7 MONITOR \\\\.\\DISPLAY1 rect=0,0,1920,1080 work=0,0,1920,1032 primary=1 dpi=96 hz=120",
    "t=10 LAUNCHED pid=4242 via=wmi chrome=C:\\Chrome\\chrome.exe",
    "t=11 TAG pid=4242 created=134052216000000000",
    "t=20 MARK begin page0",
    f"t=30 SINK-AT-CREATE ok=True ev=8000 style=14cf0000 {WIN} vis=0 iconic=0 cloaked=0 title=''",
    f"t=40 PLACE [True {WIN} vis=1 iconic=0 cloaked=0 title='about:blank - Google Chrome']",
    "t=41 RANKS via=ev-LOCATION [200 rank=3/4 aboveOthers=0]",
    "t=50 MARK end page0",
    "t=60 MARK begin newPage-default",
    "t=70 RANKS via=ev-REORDER [200 rank=3/4 aboveOthers=0] [300 rank=4/4 aboveOthers=0]",
    "t=80 MARK end newPage-default",
    "t=90 MARK begin stop",
    "t=95 PROCS count=0",
    "t=99 EOFKILL left=0",
    "t=100 EOFCLEAN dirExists=False",
    "t=101 EXIT",
]


def with_lines(after, *lines):
    """CLEAN with lines inserted after the line starting with `after`."""
    i = next(i for i, ln in enumerate(CLEAN) if ln.startswith(after)) + 1
    return CLEAN[:i] + list(lines) + CLEAN[i:]


def with_action(name, *lines):
    """CLEAN with one more action before stop, its lines between t=1700 and t=1800; stop and
    the lines after it move 2000 ms later."""
    i = CLEAN.index("t=90 MARK begin stop")
    later = [re.sub(r"^t=(\d+)", lambda m: "t=%d" % (int(m.group(1)) + 2000), ln) for ln in CLEAN[i:]]
    return [*CLEAN[:i], f"t=1700 MARK begin {name}", *lines, f"t=1800 MARK end {name}", *later]


# A3's lift (live, 2026-10-15; hwnd and pid made up): the run window rises under the foreground,
# the keeper sinks it 12 ms later, and the poll's RANKS line at the same t shows it back down.
def rises(t):
    return f"t={t} RANKS via=ev-reorder [200 rank=1/3 aboveOthers=1]"


def keeper_sinks(t):
    return f"t={t} KEEP-SINK ok=True via=ev-reorder {WIN} vis=1 iconic=0 cloaked=0 title='about:blank'"


def falls(t):
    return f"t={t} RANKS via=poll [200 rank=2/3 aboveOthers=0]"


A3 = [rises(1712), keeper_sinks(1724), falls(1724)]
BTN = "bringToFront-newPage"


def lift_note(ms, name=BTN):
    return (f"NOTE: {name}: a run window rose above another window, under the foreground, for "
            f"{ms} ms until the keeper sank it")


class Judge(unittest.TestCase):
    """check's verdict from synthetic supervisor logs (the probe's line format)."""

    def run_judge(self, lines, raf="visible 118", hz=120, leftover=None):
        return cb.judge(lines, raf=raf, hz=hz, leftover=leftover)

    def test_pass(self):
        verdict, rows, fails, warns = self.run_judge(CLEAN)
        self.assertEqual((verdict, fails, warns), ("PASS", [], []))
        self.assertEqual([n for n, _ in rows], ["page0", "newPage-default", "stop"])
        self.assertEqual(dict(rows)["page0"]["sunk"], 1)

    def test_fail_on_a_tagged_foreground(self):
        lines = with_lines("t=70 ", f"t=72 FOREGROUND tagged=1 idle=8000 via=ev-foreground {WIN} vis=1 iconic=0 cloaked=0",
                           f"t=78 FOREGROUND tagged=0 idle=8006 via=ev-foreground {TERM}")
        verdict, rows, fails, _ = self.run_judge(lines)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(dict(rows)["newPage-default"]["fg"], 6)
        self.assertIn("took the foreground during newPage-default", fails[0])

    def test_fail_on_top_and_above_time(self):
        lines = with_lines("t=70 ", f"t=71 TOP tagged=1 via=ev-REORDER {WIN} vis=1 iconic=0 cloaked=0",
                           "t=71 RANKS via=ev-REORDER [200 rank=0/4 aboveOthers=1]",
                           f"t=75 TOP tagged=0 via=ev-REORDER {TERM}",
                           "t=76 RANKS via=ev-REORDER [200 rank=3/4 aboveOthers=0]")
        verdict, rows, fails, _ = self.run_judge(lines)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual((dict(rows)["newPage-default"]["top"], dict(rows)["newPage-default"]["above"]), (4, 5))
        self.assertEqual(len(fails), 2)

    def test_open_interval_counts_to_the_end(self):
        lines = with_lines("t=70 ", f"t=71 TOP tagged=1 via=ev-REORDER {WIN} vis=1 iconic=0 cloaked=0")
        verdict, rows, _, _ = self.run_judge(lines)
        self.assertEqual((verdict, dict(rows)["newPage-default"]["top"]), ("FAIL", 101 - 71))

    def test_inconclusive_when_the_first_foreground_is_invisible(self):
        lines = [CLEAN[0].replace("vis=1", "vis=0").replace("cls=TestTerminal", "cls=XamlExplorerHostIslandWindow"), *CLEAN[1:]]
        self.assertEqual(self.run_judge(lines)[0], "INCONCLUSIVE")
        cloaked = [CLEAN[0].replace("cloaked=0", "cloaked=2"), *CLEAN[1:]]
        self.assertEqual(self.run_judge(cloaked)[0], "INCONCLUSIVE")
        fg = cb.parse_fg(CONTRACT["fg"]["fg"], "fg.fg")
        self.assertTrue(cb.fg_visible(fg))
        for key in ("visible", "iconic", "cloaked"):
            flipped = dict(CONTRACT["fg"]["fg"], **{key: not CONTRACT["fg"]["fg"][key]})
            self.assertFalse(cb.fg_visible(cb.parse_fg(flipped, "fg.fg")), key)

    def test_a_fail_lists_every_failure(self):
        steal = f"t=72 FOREGROUND tagged=1 idle=8000 via=ev-foreground {WIN} vis=1 iconic=0 cloaked=0"
        verdict, _, fails, _ = self.run_judge(with_lines("t=70 ", steal), raf="hidden 1")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(any("took the foreground during newPage-default" in f for f in fails), fails)
        self.assertTrue(any("read 'hidden'" in f for f in fails), fails)

    def test_definite_failures_beat_an_invisible_first_foreground(self):
        dead = CLEAN[0].replace("vis=1", "vis=0")
        steal = f"t=72 FOREGROUND tagged=1 idle=8000 via=ev-foreground {WIN} vis=1 iconic=0 cloaked=0"
        top = f"t=71 TOP tagged=1 via=ev-REORDER {WIN} vis=1 iconic=0 cloaked=0"
        stolen = [dead, *with_lines("t=70 ", steal)[1:]]
        self.assertEqual(self.run_judge(stolen)[0], "INCONCLUSIVE", "a steal needs a real foreground")
        for why, lines, kw in (("on top", [dead, *with_lines("t=70 ", top)[1:]], {}),
                               ("hidden", [dead, *CLEAN[1:]], {"raf": "hidden 118"}),
                               ("slow", [dead, *CLEAN[1:]], {"raf": "visible 60"}),
                               ("leftover", [dead, *CLEAN[1:]], {"leftover": "1 chrome.exe"}),
                               ("untracked", [dead, *(ln for ln in CLEAN[1:] if " TAG " not in ln)], {})):
            with self.subTest(why=why):
                self.assertEqual(self.run_judge(lines, **kw)[0], "FAIL")

    def test_unknown_kinds_are_skipped(self):
        lines = with_lines("t=70 ", "t=71 UNTAG pid=47300", "t=72 ERROR keeper: SetWindowPos failed 5",
                           "t=73 SOMETHING-NEW tagged=1 aboveOthers=1")
        verdict, rows, fails, warns = self.run_judge(lines)
        self.assertEqual((verdict, fails, warns), ("PASS", [], []))

    def test_the_browser_must_stay_tracked_until_stop(self):
        # Every tagged=0 reading assumes the supervisor knew the run's windows: LAUNCHED's pid
        # needs a TAG with a real creation time, and no STALE or UNTAG before MARK begin stop.
        tag = "t=11 TAG pid=4242 created=134052216000000000"
        for why, lines, text in (
                ("no TAG", [ln for ln in CLEAN if ln != tag], "pid 4242 was never tagged"),
                ("created=0", [ln.replace("created=134052216000000000", "created=0") for ln in CLEAN],
                 "pid 4242 was never tagged"),
                ("TAG of another pid", [ln.replace("TAG pid=4242", "TAG pid=4243") for ln in CLEAN],
                 "pid 4242 was never tagged"),
                ("STALE", with_lines("t=60 ", "t=65 STALE pid=4242 created=134052216000000000"),
                 "pid 4242 went STALE at t=65"),
                ("UNTAG", with_lines("t=60 ", "t=65 UNTAG pid=4242"), "pid 4242 went UNTAG at t=65"),
                ("no LAUNCHED", [ln for ln in CLEAN if "LAUNCHED" not in ln], "no LAUNCHED pid=N line")):
            with self.subTest(why=why):
                verdict, _, fails, _ = self.run_judge(lines)
                self.assertEqual(verdict, "FAIL")
                self.assertTrue(any(text in f for f in fails), fails)
        for why, lines in (("UNTAG after stop", with_lines("t=95 ", "t=96 UNTAG pid=4242")),
                           ("another pid", with_lines("t=60 ", "t=65 UNTAG pid=4243",
                                                      "t=66 STALE pid=4243 created=1"))):
            with self.subTest(why=why):
                verdict, _, fails, _ = self.run_judge(lines)
                self.assertEqual((verdict, fails), ("PASS", []))

    def test_a_lift_the_keeper_sinks_fast_is_tolerated(self):
        # A3 logs the KEEP-SINK with the closing RANKS line's t, just before that line.
        for why, lines, ms in (("A3", A3, 12),
                               ("sunk mid-lift", [rises(1712), keeper_sinks(1718), falls(1724)], 12),
                               ("at the tolerance", [rises(1712), keeper_sinks(1762), falls(1762)], 50),
                               # KeepSink logs after SetWindowPos returns; a Check nested in that
                               # call may log the fall first, in the same ms.
                               ("nested Check logged the fall first", [*A3[::2], keeper_sinks(1724)], 12),
                               ("KEEP-SINK a ms after the fall", [*A3[::2], keeper_sinks(1725)], 12),
                               ("a refresh-thread line between", [*A3[::2], "t=1726 TAG pid=4243 created=1",
                                                                  keeper_sinks(1727)], 12),
                               ("nested falls before the sink", [*A3[::2], "t=1724 RANKS via=ev-reorder "
                                                                  "[200 rank=3/4 aboveOthers=0]", keeper_sinks(1725)], 12),
                               ("closed by none-onscreen",
                                [rises(1712), keeper_sinks(1720), "t=1724 RANKS via=ev-HIDE none-onscreen"], 12)):
            with self.subTest(why=why):
                verdict, rows, fails, warns = self.run_judge(with_action(BTN, *lines))
                self.assertEqual((verdict, fails, warns), ("PASS", [], [lift_note(ms)]))
                r = dict(rows)[BTN]
                self.assertEqual((r["above"], r["kept"], r["keep"]), (0, ms, 1))

    def test_a_lift_fails_unless_the_keeper_sank_it_in_time(self):
        for why, lines, ms in (
                ("no KEEP-SINK", [rises(1712), falls(1724)], 12),
                ("80 ms", [rises(1712), keeper_sinks(1790), falls(1792)], 80),
                ("51 ms", [rises(1712), keeper_sinks(1763), falls(1763)], 51),
                ("KEEP-SINK logged before it opened", [keeper_sinks(1712), *A3[::2]], 12),
                ("a failed KEEP-SINK", [rises(1712), keeper_sinks(1718).replace("ok=True", "ok=False"),
                                        falls(1724)], 12),
                ("no KEEP-SINK, closed by none-onscreen",
                 [rises(1712), "t=1724 RANKS via=ev-HIDE none-onscreen"], 12)):
            with self.subTest(why=why):
                verdict, rows, fails, warns = self.run_judge(with_action(BTN, *lines))
                self.assertEqual(verdict, "FAIL")
                self.assertEqual(fails, [f"{BTN}: a run window sat above another window for {ms} ms"])
                self.assertEqual((warns, dict(rows)[BTN]["kept"]), ([], 0))

    def test_each_lift_is_judged_on_its_own(self):
        # One tolerated lift per action: a second is a re-raise loop, which KEEP-FIGHT (over 20
        # sinks in 1 s) misses below that rate.
        two = [*A3, rises(1740), keeper_sinks(1752), falls(1752)]
        verdict, rows, fails, warns = self.run_judge(with_action(BTN, *two))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: a run window rose above another window 2 times; one lift "
                                 "per action is tolerated, more is a re-raise loop"])
        self.assertEqual(warns, [lift_note(12), lift_note(12)])
        self.assertEqual((dict(rows)[BTN]["above"], dict(rows)[BTN]["kept"]), (0, 24))
        apart = [*A3, "t=1730 MARK begin other", rises(1740), keeper_sinks(1752), falls(1752)]
        verdict, rows, fails, warns = self.run_judge(with_action(BTN, *apart))
        self.assertEqual((verdict, fails, warns), ("PASS", [], [lift_note(12), lift_note(12, "other")]))
        # A tolerated lift doesn't excuse the others, which still sum per action.
        mixed = [*A3, rises(1740), falls(1748), rises(1760), falls(1765)]
        verdict, rows, fails, warns = self.run_judge(with_action(BTN, *mixed))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: a run window sat above another window for 13 ms"])
        self.assertEqual(warns, [lift_note(12)])

    def test_a_lift_is_charged_to_the_action_it_began_in(self):
        lines = [rises(1712), "t=1715 MARK begin other", falls(1724)]
        verdict, rows, fails, _ = self.run_judge(with_action(BTN, *lines))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: a run window sat above another window for 12 ms"])
        self.assertEqual(dict(rows)["other"]["above"], 0)

    def test_a_same_ms_keep_sink_past_the_next_rise_is_not_this_lifts(self):
        # The fall's look-ahead stops at the next RANKS line: that sink ended the second lift,
        # in the same ms or later.
        lines = [rises(1712), falls(1724), rises(1724), keeper_sinks(1724), falls(1730)]
        verdict, _, fails, warns = self.run_judge(with_action(BTN, *lines))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: a run window sat above another window for 12 ms"])
        self.assertEqual(warns, [lift_note(6)])

    def test_a_tolerated_lift_with_top_or_a_steal_fails(self):
        top = [f"t=1712 TOP tagged=1 via=ev-reorder {WIN} vis=1 iconic=0 cloaked=0", *A3,
               f"t=1724 TOP tagged=0 via=poll {TERM}"]
        verdict, _, fails, warns = self.run_judge(with_action(BTN, *top))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: a run window was on top of the screen for 12 ms"])
        self.assertEqual(warns, [lift_note(12)])
        steal = [*A3[:2], f"t=1724 FOREGROUND tagged=1 idle=8000 via=ev-foreground {WIN} vis=1 "
                 "iconic=0 cloaked=0", A3[2], f"t=1730 FOREGROUND tagged=0 idle=8006 via=ev-foreground {TERM}"]
        verdict, _, fails, warns = self.run_judge(with_action(BTN, *steal))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"a run window took the foreground during {BTN} at t=1724 (idle 8000 ms)"])
        self.assertEqual(warns, [lift_note(12)])

    def test_a_keeper_fight_fails(self):
        fight = [*A3[:2], f"t=1724 KEEP-FIGHT sinks=21 via=ev-reorder {WIN}", A3[2]]
        verdict, rows, fails, warns = self.run_judge(with_action(BTN, *fight))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, [f"{BTN}: the keeper fought a run window (more than 20 sinks in 1 s)"])
        self.assertEqual(dict(rows)[BTN]["fight"], 1)

    def test_an_unclosed_lift_runs_to_the_log_end(self):
        # Opened at t=96 in stop and never closed: 5 ms to the last line, t=101, with no sink.
        verdict, rows, fails, _ = self.run_judge(with_lines("t=95 ", rises(96)))
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(fails, ["stop: a run window sat above another window for 5 ms"])
        self.assertEqual(dict(rows)["stop"]["above"], 5)

    def test_real_first_line_reads_visible(self):
        verdict, _, fails, _ = self.run_judge([LOG_FG, *CLEAN[1:]])
        self.assertEqual((verdict, fails), ("PASS", []))

    def test_warn_on_an_untagged_foreground_after_stop(self):
        lines = with_lines("t=95 ", "t=97 FOREGROUND tagged=0 idle=74531 via=ev-foreground hwnd=300 pid=47 "
                           "cls=#32770 rect=0,0,550,45 onscreen=1 vis=0 iconic=0 cloaked=0")
        verdict, _, fails, warns = self.run_judge(lines)
        self.assertEqual((verdict, fails), ("PASS", []))
        self.assertEqual(len(warns), 1)
        self.assertTrue(warns[0].startswith("WARN: after stop"))
        self.assertIn("cls=#32770", warns[0])
        # A log with no start foreground: the hidden dialog after stop is still only a WARN.
        verdict, _, fails, warns = self.run_judge(lines[1:])
        self.assertEqual((verdict, fails), ("PASS", []))
        self.assertEqual(len(warns), 2)
        self.assertIn("no FOREGROUND line before the first action", warns[1])

    def test_fail_on_page_state_and_leftovers(self):
        self.assertEqual(self.run_judge(CLEAN, raf="hidden 118")[0], "FAIL")
        self.assertEqual(self.run_judge(CLEAN, raf="visible 100")[0], "FAIL")  # under 108 = 90% of 120
        self.assertEqual(self.run_judge(CLEAN, raf="visible 108")[0], "PASS")
        self.assertEqual(self.run_judge(CLEAN, raf=None)[0], "FAIL")
        self.assertEqual(self.run_judge(CLEAN, leftover="2 chrome.exe")[0], "FAIL")

    def test_report_table(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cb.print_report(*self.run_judge(CLEAN), "visible 118")
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0].split(), ["action", "onTop", "aboveOthers", "fg", "sunk", "keep"])
        self.assertEqual(lines[1].split(), ["page0", "0ms", "0ms", "0ms", "1", "0"])
        self.assertEqual(lines[-1], "PASS")


class Contract(unittest.TestCase):
    """The real supervisor's replies through the real parsers, and drift failing loudly."""

    def test_hello(self):
        hello = cb.parse_hello(CONTRACT["hello"])
        self.assertEqual(cb.place_args(hello, (1280, 900)), {"x": 10, "y": 10, "w": 1280, "h": 900})
        self.assertEqual(cb.offscreen_x(hello["screen"][0], 1280), -2280)
        self.assertEqual(hello["primary"]["hz"], 120)
        self.assertTrue(cb.holds_tag(hello["runDir"], "5a0ce001"))
        self.assertEqual(cb.win_join(cb.win_parent(hello["runDir"]), "5a0ce001.log"),
                         WINROOT + "\\5a0ce001.log")
        self.assertTrue(cb.fg_visible(hello["fg"]))
        self.assertIn("\\chrome-bg\\5a0ce001\\",
                      " ".join(cb.chrome_args(cb.win_join(hello["runDir"], "profile"))),
                      "launch's args hold the run dir, as the supervisor requires")

    def test_other_ops(self):
        self.assertTrue(cb.fg_visible(cb.parse_fg(CONTRACT["fg"]["fg"], "fg.fg")))
        self.assertEqual(cb.parse_procs(CONTRACT["procs"]), [47292, 47300])
        self.assertEqual(cb.parse_procs(CONTRACT["procs_empty"]), [])
        self.assertEqual(cb.need(CONTRACT["launch"], "pid", "int", "launch"), 47292)
        self.assertEqual(cb.parse_place(CONTRACT["place"]), [(9569902, (10, 10, 1280, 900))])
        self.assertEqual(cb.failure(CONTRACT["launch_fail_wmi"]), "Win32_Process Create failed (code 9)")
        self.assertIn("\\chrome-bg\\5a0ce001\\", cb.failure(CONTRACT["launch_fail_args"]))
        self.assertEqual(cb.failure(CONTRACT["op_error"]), "unknown op: bogus")

    def test_scan_and_kill(self):
        runs, logs, root = cb.parse_scan(CONTRACT["scan"])
        self.assertEqual(runs, {"5a0ce001": {"age": 12.0, "pids": [47292]}})
        self.assertEqual((logs, root), ({"5a0ce001": 2.0}, WINROOT))
        self.assertEqual(cb.parse_scan(CONTRACT["scan_empty"]), ({}, {}, WINROOT))
        self.assertEqual(cb.parse_kill(CONTRACT["kill"]), {"killed": 0, "left": 0, "dirExists": False})
        # -Kill answers ok:false whenever a chrome.exe or the dir is left; that is a failure.
        self.assertIn("Win32_Process Create failed", cb.failure(CONTRACT["launch_fail_wmi"]))

    def test_drift_fails_loudly(self):
        """A renamed or retyped field raises Fail naming the op and the field."""
        cases = []
        for path, new in ((["virtualScreen"], "vscreen"), (["runDir"], "rundir"),
                          (["monitors", 0, "work"], "workArea"), (["monitors", 0, "work", "w"], "width"),
                          (["monitors", 0, "primary"], "Primary"), (["fg", "visible"], "vis")):
            top = json.loads(json.dumps(CONTRACT["hello"]))
            node = top
            for p in path[:-1]:
                node = node[p]
            node[new] = node.pop(path[-1])
            cases.append(("hello", cb.parse_hello, top, repr(path[-1])))
        retyped = json.loads(json.dumps(CONTRACT["hello"]))
        retyped["monitors"][0]["dpi"] = "96"
        cases.append(("hello", cb.parse_hello, retyped, "dpi"))
        for key, new in (("ageSec", "age"), ("id", "ID")):
            top = json.loads(json.dumps(CONTRACT["scan"]))
            top["dirs"][0][new] = top["dirs"][0].pop(key)
            cases.append(("-Scan", cb.parse_scan, top, repr(key)))
        top = json.loads(json.dumps(CONTRACT["scan"]))
        top["dirs"] = {"5a0ce001": 12}
        cases.append(("-Scan", cb.parse_scan, top, "dirs"))
        top = json.loads(json.dumps(CONTRACT["scan"]))
        top["procs"] = [{"id": "5a0ce001", "pids": [47292]}]
        cases.append(("-Scan", cb.parse_scan, top, "procs"))
        top = json.loads(json.dumps(CONTRACT["procs"]))
        top["procs"][0]["pids"] = top["procs"][0].pop("pid")
        cases.append(("procs", cb.parse_procs, top, "'pid'"))
        top = dict(CONTRACT["procs"])
        top["count"] = top.pop("procs")
        cases.append(("procs", cb.parse_procs, top, "'procs'"))
        top = dict(CONTRACT["kill"])
        top["leftover"] = top.pop("left")
        cases.append(("-Kill", cb.parse_kill, top, "'left'"))
        top = json.loads(json.dumps(CONTRACT["place"]))
        top["windows"][0]["rect"] = [10, 10, 1290, 910]
        cases.append(("place", cb.parse_place, top, "rect"))
        for op, parse, reply, field in cases:
            with self.subTest(op=op, field=field), self.assertRaises(cb.Fail) as e:
                parse(reply)
            self.assertIn(f"supervisor {op}", str(e.exception))
            self.assertIn(field, str(e.exception))


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


# The Windows side, faked. FAKE_SUP speaks chrome-bg.ps1's protocol (PLAN.md "Supervisor
# protocol") over stdin and stdout and answers only with CONTRACT's replies. On `launch` it starts
# FAKE_CHROME (HTTP /json/version and /json/list plus a CDP WebSocket, and the DevToolsActivePort
# in the run dir) in a process and session of its own, as WMI launches chrome.exe: killing the
# supervisor leaves "Chrome" running. --root stands for C:\. They note what they saw in files
# under --root: launch-<id> (Chrome's args), cdp-<id> (each CDP call), list-<id> (each /json/list
# answer), place-<id>, hello-<id>, eof-<id> (the supervisor saw stdin EOF), kill-<id> (a one-shot
# -Kill ran), session-<id> (the supervisor's pid and session id), alive-<id> (while "Chrome" runs)
# and chrome-<id>.pid. A test scripts /json/list in pages-<id>: one answer per read ("0", "1", or
# "fail" for a 500), the last one kept.
FAKE_COMMON = r'''
import json, os, re, sys, time

args = sys.argv[1:]
root = args[args.index("--root") + 1]
with open(os.path.join(root, "contract.json")) as f:
    C = json.load(f)  # the real supervisor's replies: every reply the fake sends is one of them
TEMPLATE_ID = "5a0ce001"
WIN = C["scan"]["root"] + "\\"
env = os.environ


def unix(w):
    assert w.startswith("C:\\"), w
    return os.path.join(root, w[3:].replace("\\", "/"))


def note(name, text=""):
    with open(os.path.join(root, name), "a") as f:
        f.write(text + "\n")


def rm(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
'''

FAKE_SUP = FAKE_COMMON + r'''
import shutil, signal, subprocess


def copy(x):
    return json.loads(json.dumps(x))


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


base = unix(WIN)
os.makedirs(base, exist_ok=True)
if "-Scan" in args:
    scan, full = copy(C["scan_empty"]), C["scan"]
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        age = int(time.time() - os.path.getmtime(p))
        if re.fullmatch(r"[0-9a-f]{8}", name) and os.path.isdir(p):
            scan["dirs"].append(dict(full["dirs"][0], id=name, ageSec=age))
            if os.path.exists(os.path.join(root, "alive-" + name)):
                scan["procs"][name] = copy(full["procs"][TEMPLATE_ID])
        m = re.fullmatch(r"([0-9a-f]{8})\.log", name)
        if m:
            scan["logs"].append(dict(full["logs"][0], id=m.group(1), ageSec=age))
    out(scan)
    sys.exit(0)

rid = args[args.index("-Id") + 1]
if not re.fullmatch(r"[0-9a-f]{8}", rid):
    out({"ok": False, "error": "bad -Id"})
    sys.exit(1)
run_dir = os.path.join(base, rid)
alive = os.path.join(root, "alive-" + rid)
pidfile = os.path.join(root, "chrome-%s.pid" % rid)


def cleanup():
    """Kill this run's "Chrome" (by its pid file, as the real one kills by run dir) and delete
    the run dir."""
    try:
        with open(pidfile) as f:
            os.kill(int(f.read()), signal.SIGKILL)
    except (OSError, ValueError):
        pass
    rm(pidfile)
    rm(alive)
    shutil.rmtree(run_dir, ignore_errors=True)


if "-Kill" in args:
    note("killstart-" + rid)
    time.sleep(float(env.get("FAKE_SLOW_KILL", "0")))  # a signal to the caller lands mid-kill
    note("kill-" + rid)
    cleanup()
    out(C["kill"])
    sys.exit(0)

note("session-" + rid, "%d %d" % (os.getpid(), os.getsid(0)))
t0 = time.monotonic()
logf = open(os.path.join(base, rid + ".log"), "a", buffering=1)


def log(text):
    logf.write("t=%d %s\n" % (int((time.monotonic() - t0) * 1000) + 20, text))


logf.write(C["log_fg"] + "\n")  # the real supervisor's first line: t=15 FOREGROUND ... via=start
chrome, procs_failures = None, 0
for line in sys.stdin:
    msg = json.loads(line)
    op = msg.get("op")
    if op == "hello":
        note("hello-" + rid)
        time.sleep(float(env.get("FAKE_SLOW_HELLO", "0")))
        os.makedirs(run_dir, exist_ok=True)
        h = copy(C["hello"])
        h["runDir"] = WIN + rid
        vs = int(env.get("FAKE_VS_LEFT", "0"))
        h["virtualScreen"].update(x=vs, w=1920 - vs)
        h["monitors"][0]["dpi"] = int(env.get("FAKE_DPI", "96"))
        h["fg"]["visible"] = not env.get("FAKE_FG_HIDDEN")
        if env.get("FAKE_RENAME"):  # old=new: drift in a top-level key
            old, new = env["FAKE_RENAME"].split("=")
            h[new] = h.pop(old)
        out(h)
    elif op == "launch" and "\\chrome-bg\\%s\\" % rid not in msg["args"]:
        out(json.loads(json.dumps(C["launch_fail_args"]).replace(TEMPLATE_ID, rid)))
    elif op == "launch" and env.get("FAKE_LAUNCH_FAIL"):
        out(C["launch_fail_wmi"])
    elif op == "launch":
        note("launch-" + rid, msg["args"])
        profile = unix(re.search(r'"--user-data-dir=([^"]+)"', msg["args"]).group(1))
        os.makedirs(profile, exist_ok=True)
        open(alive, "w").close()
        chrome = subprocess.Popen([sys.executable, "-I", os.path.join(root, "fake_chrome.py"),
                                   "--root", root, "--rid", rid, "--profile", profile],
                                  start_new_session=True)
        with open(pidfile, "w") as f:
            f.write(str(chrome.pid))
        log("LAUNCHED pid=%d via=wmi chrome=C:\\Chrome\\chrome.exe" % C["launch"]["pid"])
        log("TAG pid=%d created=134052216000000000" % C["launch"]["pid"])
        out(C["launch"])
    elif op == "place":
        note("place-" + rid, json.dumps(msg))
        log("PLACE [True hwnd=9569902 pid=47292 cls=Chrome_WidgetWin_1 rect=10,10,1290,910 onscreen=1 vis=1]")
        if env.get("FAKE_PLACE_RESIZE"):
            open(os.path.join(root, "resize-" + rid), "w").close()
        out(dict(C["place"], windows=[]) if env.get("FAKE_PLACE_EMPTY") else C["place"])
        if env.get("FAKE_SUP_DIES_AFTER_PLACE"):
            os._exit(0)  # a crashed supervisor: no EOF cleanup, "Chrome" orphaned
    elif op == "procs" and procs_failures < int(env.get("FAKE_PROCS_FAIL", "0")):
        procs_failures += 1  # the op errs (the real error shape), the run goes on
        out(dict(C["op_error"], error="procs: Get-CimInstance failed"))
    elif op == "procs":
        out(C["procs"] if chrome is not None and chrome.poll() is None else C["procs_empty"])
    elif op == "fg":
        out(C["fg"])
    elif op == "mark":
        log("MARK " + msg["text"])
        out(C["mark"])
    else:
        out(dict(C["op_error"], error="unknown op: %s" % op))

note("eof-" + rid)
time.sleep(float(env.get("FAKE_SLOW_EOF", "0")))
code = int(env.get("FAKE_EOF_EXIT", "0"))  # 3: the real one's "cleanup incomplete"
if code == 0:
    log("EOFKILL left=0")
    cleanup()
    log("EOFCLEAN dirExists=False")
log("EXIT")
sys.exit(code)
'''

FAKE_CHROME = FAKE_COMMON + r'''
import base64, hashlib, socket, struct, threading, uuid

rid = args[args.index("--rid") + 1]
profile = args[args.index("--profile") + 1]
guid = str(uuid.uuid4())
bounds = {}
loaded_reads = [0]  # page0's load-check evaluates so far (FAKE_LOADED_AFTER)
pages = [0]  # unless pages-<rid> says otherwise, /json/list holds one page per createTarget
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(8)
port = srv.getsockname()[1]
note("chromepid-" + rid, str(os.getpid()))  # kept after exit, so a test can check it is gone


def exit_chrome():
    if env.get("FAKE_CHROME_IGNORE_CLOSE"):  # a Chrome that won't close: only -Kill or EOF end it
        return
    rm(os.path.join(root, "alive-" + rid))
    rm(os.path.join(root, "chrome-%s.pid" % rid))
    os._exit(0)


def list_answer():
    """The next /json/list answer: pages-<rid>'s first token, which a read consumes unless it is
    the last; else the page count."""
    seq = os.path.join(root, "pages-" + rid)
    try:
        with open(seq) as f:
            tokens = f.read().split()
    except FileNotFoundError:
        return str(pages[0])
    if len(tokens) > 1:
        with open(seq + ".tmp", "w") as f:
            f.write(" ".join(tokens[1:]))
        os.replace(seq + ".tmp", seq)
    return tokens[0]


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
        pages[0] += 1
        if p.get("newWindow"):
            left = 0 if env.get("FAKE_CLAMP") else p["left"]
            bounds.update(left=left, top=p["top"], width=p["width"], height=p["height"],
                          windowState="normal")
        return {"result": {"targetId": "T%d" % msg["id"]}}
    if m == "Browser.getWindowForTarget":
        flag = os.path.join(root, "resize-" + rid)  # the supervisor's place moved it across DPIs
        if os.path.exists(flag):
            rm(flag)
            bounds.update(width=bounds["width"] * 2 // 3, height=bounds["height"] * 2 // 3)
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
    if m == "Page.navigate":
        if env.get("FAKE_NAV_ERROR"):
            return {"result": {"frameId": "F1", "errorText": env["FAKE_NAV_ERROR"]}}
        return {"result": {"frameId": "F1", "loaderId": "L1"}}
    if m == "Runtime.evaluate":
        expr = p.get("expression", "")
        if "location.protocol" in expr:  # page0 loaded check's data: page
            loaded_reads[0] += 1
            value = env.get("FAKE_LOADED", "data: complete")
            if loaded_reads[0] <= int(env.get("FAKE_LOADED_AFTER", "0")):
                value = "about: complete"  # the old about:blank answered first
        elif "window.open" in expr:
            value = env.get("FAKE_POPUP", "true")
        else:
            value = env.get("FAKE_RAF", "visible 118")
        return {"result": {"result": {"type": "string", "value": value}}}
    return {"error": {"code": -32601, "message": "'%s' wasn't found" % m}}


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
                               "ws://127.0.0.1:%d/devtools/browser/%s" % (port, ws)}).encode()
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                      % len(body) + body)
            return
        if path == "/json/list":
            answer = list_answer()
            note("list-" + rid, answer)
            if answer == "fail":
                c.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n")
                return
            # A service worker is no page: only type "page" counts.
            targets = [{"type": "service_worker", "id": "W1"}] + [
                {"type": "page", "id": "T%d" % i} for i in range(int(answer))]
            body = json.dumps(targets).encode()
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
                exit_chrome()  # Chrome exits: its port closes
    except (EOFError, OSError):
        pass
    finally:
        c.close()


path = os.path.join(profile, "DevToolsActivePort")
with open(path, "w") as f:  # one line first: the client must wait for both
    f.write("%d\n" % port)
time.sleep(0.3)
with open(path, "w") as f:
    f.write("%d\n/devtools/browser/%s" % (port, guid))
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
'''

# Runs bin/chrome-bg as a module with its seams patched: argv = CLI ROOT ARGS... The supervisor
# goes through /bin/sh first, which logs the signals it inherited blocked (SigBlk) and ignored
# (SigIgn) to ROOT/sigign.log before exec: a Python process ignores SIGPIPE whatever it
# inherited, so only a shell can tell.
DRIVER = r'''
import importlib.machinery, importlib.util, os, sys
cli, root = sys.argv[1], sys.argv[2]
loader = importlib.machinery.SourceFileLoader("chrome_bg", cli)
spec = importlib.util.spec_from_loader("chrome_bg", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
fake = os.path.join(root, "fake_sup.py")
mod.sandboxed = lambda proc="/proc": False
mod.ps_argv = lambda *a: ["/bin/sh", "-c",
                          'echo "$$ $(grep -E "^Sig(Ign|Blk):" /proc/self/status | tr -d "\t" | tr "\n" " ")" >> "$0"; exec "$@"',
                          os.path.join(root, "sigign.log"), sys.executable, "-I", fake, "--root", root, *a]


def wslpath(flag, p):
    if flag != "-u" or not p.startswith("C:\\"):
        raise mod.Fail("fake wslpath: %s %s" % (flag, p))
    return os.path.join(root, p[3:].replace("\\", "/"))


mod.wslpath = wslpath
mod.PROCS_POLL_S = 0.2
if os.environ.get("DRIVER_FAST"):
    mod.AFTER_STOP_S = mod.SETTLE_S = mod.RESINK_S = 0.05
    mod.LOADED_WAIT_S = 0.5
if os.environ.get("DRIVER_STOP_WAIT"):
    mod.STOP_WAIT_S = float(os.environ["DRIVER_STOP_WAIT"])
if os.environ.get("DRIVER_PAGES_GONE"):
    mod.PAGES_GONE_S = float(os.environ["DRIVER_PAGES_GONE"])
if "DRIVER_TTY_FG" in os.environ:  # stands in for /dev/tty's foreground process group check
    mod.in_tty_foreground = lambda: os.environ["DRIVER_TTY_FG"] == "1"
sys.exit(mod.main(sys.argv[3:]))
'''


class Live(unittest.TestCase):
    """start, stop, run and gc end to end against the fake Windows side."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "c")
        self.base = os.path.join(self.root, *WINROOT[3:].split("\\"))
        os.makedirs(self.base)
        with open(os.path.join(self.root, "fake_sup.py"), "w") as f:
            f.write(FAKE_SUP)
        with open(os.path.join(self.root, "fake_chrome.py"), "w") as f:
            f.write(FAKE_CHROME)
        with open(os.path.join(self.root, "contract.json"), "w") as f:
            json.dump(CONTRACT, f)
        self.driver = os.path.join(self.tmp, "driver.py")
        with open(self.driver, "w") as f:
            f.write(DRIVER)
        self.state = os.path.join(self.tmp, "state")
        self.recdir = os.path.join(self.state, "dotclaude", "chrome-bg")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "DRIVER_"))}
        self.env["XDG_STATE_HOME"] = self.state
        self.addCleanup(self.reap)

    def reap(self):
        """SIGKILL what a failed test left behind: holders (their fake supervisors then see EOF)
        and orphaned fake Chromes."""
        home = os.path.join(self.tmp, "home", ".local", "state", "dotclaude", "chrome-bg")
        for rec in self.records() + self.records(home):
            if cb.owner_proven(rec) and rec["owner"]["pid"] != os.getpid():
                with contextlib.suppress(OSError):
                    os.kill(rec["owner"]["pid"], signal.SIGKILL)
        for name in os.listdir(self.root):
            if re.fullmatch(r"chrome-[0-9a-f]{8}\.pid", name):
                with contextlib.suppress(OSError, ValueError), open(os.path.join(self.root, name)) as f:
                    os.kill(int(f.read()), signal.SIGKILL)

    def cli(self, *argv, env=None, timeout=60, cwd=None):
        return subprocess.run([sys.executable, "-I", self.driver, CLI, self.root, *argv],
                              env={**self.env, **(env or {})}, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)

    def popen(self, *argv, env=None):
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, *argv],
                             env={**self.env, **(env or {})}, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)

        def end():
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=10)
        self.addCleanup(end)
        return p

    def owner(self, rid=None, *, ignore_term=False, mine=True):
        """A stand-in owner process: a python whose argv names bin/chrome-bg, with a child whose
        argv holds `-Id <rid>` standing for that run's supervisor (it exits with its parent), so
        it passes owner_proven for rid. mine=False gives a plain `sleep`. (Popen, start time)."""
        if mine:
            code = ("import signal, subprocess, sys, time\n"
                    + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
                    + "subprocess.Popen([sys.executable, '-c', 'import os, time\\np = os.getppid()\\n"
                    "while os.getppid() == p: time.sleep(0.1)', '-Id', sys.argv[3]])\n"
                    "open(sys.argv[1], 'w').close()\ntime.sleep(60)\n")
            ready = os.path.join(self.tmp, f"owner-{time.monotonic_ns()}")
            p = subprocess.Popen([sys.executable, "-c", code, ready, CLI, rid])
            self.wait_for(lambda: os.path.exists(ready), what="the owner to start")
        else:
            p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(p.wait, 10)
        self.addCleanup(p.kill)
        return p, cb.proc_stat(p.pid)[1]

    def started(self, prefix):
        """The run ids the fake noted under prefix (hello-, launch-, eof-, kill-)."""
        return sorted(n[len(prefix):] for n in os.listdir(self.root) if n.startswith(prefix))

    def records(self, recdir=None):
        recdir = recdir or self.recdir
        try:
            names = os.listdir(recdir)
        except OSError:
            return []
        out = []
        for n in sorted(names):
            if re.fullmatch(r"[0-9a-f]{8}\.json", n):
                with open(os.path.join(recdir, n)) as f:
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
        self.assertIn(f'"--user-data-dir={WINROOT}\\{rid}\\profile"', launch)
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

    def child_with_handlers(self):
        """A CMD that notes SIGINT and SIGTERM in files, then dies of the signal."""
        ready = os.path.join(self.tmp, "ready")
        code = ("import os, signal, sys, time\n"
                "def h(s, f):\n"
                "    open(os.path.join(sys.argv[2], 'got-%d' % s), 'w').close()\n"
                "    signal.signal(s, signal.SIG_DFL)\n"
                "    os.kill(os.getpid(), s)\n"
                "signal.signal(signal.SIGTERM, h)\n"
                "signal.signal(signal.SIGINT, h)\n"
                "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
                "time.sleep(60)\n")
        return ready, [sys.executable, "-c", code, ready, self.tmp]

    def got(self, sig):
        return os.path.exists(os.path.join(self.tmp, f"got-{int(sig)}"))

    def run_and_signal(self, tty_fg, *sigs):
        ready, cmd = self.child_with_handlers()
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, "run", "--", *cmd],
                             env={**self.env, "DRIVER_TTY_FG": tty_fg}, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        try:
            self.wait_for(lambda: os.path.exists(ready), what="the child to start")
            for sig in sigs:
                p.send_signal(sig)
                time.sleep(0.5)
            _, err = p.communicate(timeout=30)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        return p.returncode, err

    def test_sigint_forwarded_without_a_terminal(self):
        rc, err = self.run_and_signal("0", signal.SIGINT)
        self.assertEqual(rc, 128 + signal.SIGINT, err)
        self.assertTrue(self.got(signal.SIGINT), "no terminal sent it to CMD, so run did")
        self.assertTrue(self.has("eof-" + self.only_run_id()))

    def test_sigint_not_forwarded_from_the_terminal(self):
        # In the terminal's foreground group, CMD got the ctrl-c itself: run must not repeat it.
        rc, err = self.run_and_signal("1", signal.SIGINT, signal.SIGTERM)
        self.assertEqual(rc, 128 + signal.SIGTERM, err)
        self.assertFalse(self.got(signal.SIGINT), "run delivered SIGINT a second time")
        self.assertTrue(self.got(signal.SIGTERM), "SIGTERM still forwards")
        self.assertTrue(self.has("eof-" + self.only_run_id()))

    def test_renamed_key_fails_loudly_and_cleans_up(self):
        r = self.cli("run", "--", sys.executable, "-c", "pass",
                     env={"FAKE_RENAME": "virtualScreen=vscreen"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("supervisor hello has no 'virtualScreen'", r.stderr)
        self.assertFalse([n for n in os.listdir(self.root) if n.startswith("launch-")],
                         "Chrome never launched on a reply it could not read")
        self.assertTrue([n for n in os.listdir(self.root) if n.startswith("eof-")])
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
               "runDir": f"{WINROOT}\\{rid}", **extra}
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
        owner, start = self.owner("bbbb0001")
        self.put_record("bbbb0001", owner.pid, start, expires=time.time() - 1)
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(owner.wait(10), -signal.SIGTERM, "the holder got SIGTERM")
        self.assertTrue(self.has("kill-bbbb0001"), "it did not clean up, so a one-shot did")
        self.assertEqual(self.records(), [])

    def test_forged_record_owner_is_never_signalled(self):
        owner, start = self.owner(mine=False)  # alive, right start time, but not a chrome-bg
        self.put_record("bbbb0002", owner.pid, start)
        r = self.cli("stop", "bbbb0002")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not provably this run's chrome-bg, so it was not signalled", r.stdout)
        time.sleep(0.3)
        self.assertIsNone(owner.poll(), "no SIGTERM to a pid that is not chrome-bg")
        self.assertTrue(self.has("kill-bbbb0002"))

    def test_forged_record_naming_another_runs_owner(self):
        r = self.cli("start", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        a = json.loads(r.stdout)
        [arec] = self.records()
        # X names A's live holder (a chrome-bg, right start time) but A's supervisor is not X's.
        self.put_record("cafe0001", arec["owner"]["pid"], arec["owner"]["start"],
                        expires=time.time() - 1)
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not provably this run's chrome-bg, so it was not signalled", r.stdout)
        self.assertTrue(self.has("kill-cafe0001"))
        self.assertFalse(self.has("eof-" + a["id"]), "run A was not torn down")
        self.assertTrue(cb.owner_proven(arec), "A's holder still runs")
        self.assertEqual([x["id"] for x in self.records()], [a["id"]])
        r = self.cli("stop", a["id"])
        self.assertIn("stopped by its owner", r.stdout)

    def put_raw(self, rid, rec):
        os.makedirs(self.recdir, exist_ok=True)
        with open(os.path.join(self.recdir, rid + ".json"), "w") as f:
            json.dump(rec, f)

    def test_malformed_records_cannot_stop_gc(self):
        base = {"kind": "start", "cwd": "/x", "created": time.time() - 60,
                "expires": time.time() - 1}
        self.put_raw("dddd0101", dict(base, id="dddd0101"))                          # no owner
        self.put_raw("dddd0102", dict(base, id="dddd0102", owner={"pid": "123", "start": "1"}))
        self.put_raw("dddd0103", dict(base, id="dddd0103", owner=[]))
        self.put_raw("dddd0104", dict(base, id="dddd0104", owner={"start": "1"}))   # no pid
        r = self.cli("run", "--", sys.executable, "-c", "pass")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        for rid in ("dddd0101", "dddd0102", "dddd0103", "dddd0104"):
            self.assertIn(f"{rid}.json: not a run record", r.stderr)
        self.assertEqual(self.cli("stop", "--gc").returncode, 0)
        r = self.cli("stop", "dddd0101")
        self.assertEqual(r.returncode, 1)
        self.assertIn("its record is malformed (it has no owner object)", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_children_start_with_the_stop_signals_unblocked(self):
        out = os.path.join(self.tmp, "status")
        code = "import sys; open(sys.argv[1], 'w').write(open('/proc/self/status').read())"
        r = self.cli("run", "--", sys.executable, "-c", code, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        held = sum(1 << (s - 1) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP))
        with open(out) as f:
            blk = int(re.search(r"SigBlk:\s*([0-9a-f]+)", f.read()).group(1), 16)
        self.assertEqual(blk & held, 0, "CMD")
        pid = self.notes("session-" + self.only_run_id())[0].split()[0]
        [line] = [ln for ln in self.notes("sigign.log") if ln.split()[0] == pid]
        self.assertEqual(int(re.search(r"SigBlk:([0-9a-f]+)", line).group(1), 16) & held, 0,
                         "the supervisor")

    def test_holder_rides_out_failed_procs_polls(self):
        r = self.cli("start", "--json", env={"FAKE_PROCS_FAIL": "2"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        log = os.path.join(self.recdir, rid + ".holder.log")

        def failures():
            with open(log) as f:
                return f.read().count("poll failed")
        self.wait_for(lambda: failures() == 2, what="2 failed polls")
        time.sleep(0.6)  # more polls, now answered
        [rec] = self.records()
        self.assertTrue(cb.owner_proven(rec), "two failed polls don't end a live run")
        self.assertFalse(self.has("eof-" + rid))
        self.assertIn("stopped by its owner", self.cli("stop", rid).stdout)

    def test_holder_ends_after_three_failed_polls(self):
        r = self.cli("start", "--json", env={"FAKE_PROCS_FAIL": "99"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        self.wait_for(lambda: self.has("eof-" + rid) and not self.records(), what="the end")
        with open(os.path.join(self.recdir, rid + ".holder.log")) as f:
            log = f.read()
        self.assertEqual(log.count("poll failed ("), 3)
        self.assertIn("polls failed 3 times in a row", log)

    def test_check_stops_cleanly_on_sigterm_and_sighup(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                for n in os.listdir(self.root):
                    if n.startswith(("launch-", "eof-", "kill-")):
                        os.remove(os.path.join(self.root, n))
                p = self.popen("check")
                self.wait_for(lambda: self.started("launch-"), what="Chrome's launch")
                time.sleep(0.5)
                p.send_signal(sig)
                _, err = p.communicate(timeout=40)
                self.assertEqual(p.returncode, 128 + sig, err)
                [rid] = self.started("launch-")
                self.assertTrue(self.has("eof-" + rid), "finish ran")
                self.assertFalse(self.has("alive-" + rid))
                self.assertEqual(self.records(), [])

    def test_holder_cleanup_survives_more_signals(self):
        # A stop signal while the holder starts, then another while it cleans up after it.
        p = self.popen("start", env={"FAKE_SLOW_HELLO": "2"})
        self.wait_for(lambda: self.started("hello-") and self.records(), what="the holder")
        [rec] = self.records()
        holder = rec["owner"]["pid"]
        os.kill(holder, signal.SIGTERM)
        time.sleep(0.3)
        os.kill(holder, signal.SIGTERM)
        _, err = p.communicate(timeout=40)
        self.assertEqual(p.returncode, 1)
        self.assertIn("start stopped by signal 15", err)
        [rid] = self.started("hello-")
        self.assertTrue(self.has("eof-" + rid))
        self.assertEqual(self.records(), [])
        # A second SIGTERM while the holder's finish waits on its supervisor.
        r = self.cli("start", "--json", env={"FAKE_SLOW_EOF": "1.5"})
        rid = json.loads(r.stdout)["id"]
        [rec] = self.records()
        stop = self.popen("stop", rid)
        self.wait_for(lambda: self.has("eof-" + rid), what="the holder's finish")
        os.kill(rec["owner"]["pid"], signal.SIGTERM)
        out, err = stop.communicate(timeout=40)
        self.assertEqual(stop.returncode, 0, err)
        self.assertIn("stopped by its owner", out)
        self.assertFalse(self.has("kill-" + rid), "the holder finished its own cleanup")
        self.assertEqual(self.records(), [])
        self.assertEqual(self.records(), [])

    def test_stop_times_out_on_an_owner_that_stays(self):
        owner, start = self.owner("bbbb0003", ignore_term=True)
        self.put_record("bbbb0003", owner.pid, start)
        r = self.cli("stop", "bbbb0003", env={"DRIVER_STOP_WAIT": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("was still there after 1s", r.stdout)
        self.assertIsNone(owner.poll())
        self.assertTrue(self.has("kill-bbbb0003"), "the run was killed by its dir instead")
        self.assertEqual(self.records(), [])

    def test_gc_survives_a_non_http_listener(self):
        import threading
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        srv.settimeout(0.2)
        self.addCleanup(srv.close)
        stop = []
        self.addCleanup(stop.append, True)

        def serve():
            while not stop:
                try:
                    c, _ = srv.accept()
                except OSError:
                    continue
                with c:
                    c.sendall(b"not http at all\r\n\r\n")
        threading.Thread(target=serve, daemon=True).start()
        owner, start = self.owner("bbbb0004")
        self.put_record("bbbb0004", owner.pid, start, expires=time.time() - 1)
        self.put_dir("bbbb0004", 600)
        with open(os.path.join(self.base, "bbbb0004", "profile", "DevToolsActivePort"), "w") as f:
            f.write("%d\n/devtools/browser/abc" % srv.getsockname()[1])
        self.put_record("bbbb0005", 99999999, "5")
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(self.has("kill-bbbb0004") and self.has("kill-bbbb0005"), r.stdout)
        self.assertEqual(owner.wait(10), -signal.SIGTERM)
        self.assertEqual(self.records(), [])

    def test_bad_records_are_ignored_and_reported(self):
        os.makedirs(self.recdir)
        with open(os.path.join(self.recdir, "aaaa0009.json"), "w") as f:
            json.dump({"id": "bbbb0009", "owner": {"pid": os.getpid(), "start": "1"}}, f)
        with open(os.path.join(self.recdir, "notarun.json"), "w") as f:
            json.dump({"id": "notarun"}, f)
        r = self.cli("ls")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("aaaa0009.json: not a run record", r.stderr)
        self.assertIn("notarun.json: not a run record", r.stderr)
        self.assertEqual(self.cli("stop", "--gc").returncode, 0)
        self.assertFalse(self.started("kill-"))

    def test_run_sigkilled_then_gc(self):
        ready, cmd = self.child_with_handlers()
        p = self.popen("run", "--", *cmd)
        self.wait_for(lambda: os.path.exists(ready) and os.path.getsize(ready),
                      what="the child to start")
        rid = self.only_run_id()
        p.kill()
        with open(ready) as f:  # CMD holds the driver's pipes; end it too
            os.kill(int(f.read()), signal.SIGKILL)
        p.communicate(timeout=10)
        self.wait_for(lambda: self.has("eof-" + rid), what="the supervisor to see EOF")
        self.assertEqual([x["id"] for x in self.records()], [rid], "the record outlives its owner")
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.has("kill-" + rid))
        self.assertEqual(self.records(), [])

    def test_holder_sigkilled_then_gc(self):
        r = self.cli("start", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        [rec] = self.records()
        os.kill(rec["owner"]["pid"], signal.SIGKILL)
        self.wait_for(lambda: self.has("eof-" + rid), what="the supervisor to see EOF")
        self.wait_for(lambda: cb.owner_dead(rec), what="the holder to die")
        r = self.cli("stop", "--gc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.has("kill-" + rid))
        self.assertEqual(self.records(), [])

    def test_supervisor_ending_badly_gets_a_one_shot_kill(self):
        for env, why in (({"FAKE_SUP_DIES_AFTER_PLACE": "1"}, "had already exited"),
                         ({"FAKE_EOF_EXIT": "3"}, "exited 3")):
            with self.subTest(why=why):
                for n in os.listdir(self.root):
                    if n.startswith(("launch-", "kill-", "eof-", "alive-", "chromepid-")):
                        os.remove(os.path.join(self.root, n))
                # This "Chrome" ignores Browser.close: only the one-shot -Kill can end it.
                r = self.cli("run", "--", sys.executable, "-c", "import time; time.sleep(0.3)",
                             env={**env, "FAKE_CHROME_IGNORE_CLOSE": "1"})
                self.assertEqual(r.returncode, 0, r.stderr)
                rid = self.only_run_id()
                self.assertIn(f"the supervisor of {rid} {why}; killed the run by its dir", r.stderr)
                self.assertTrue(self.has("kill-" + rid))
                chrome = int(self.notes("chromepid-" + rid)[0])
                st = cb.proc_stat(chrome)
                self.assertTrue(st is None or st[0] == "Z", "-Kill reaped the orphaned Chrome")
                self.assertFalse(self.has("alive-" + rid))
                self.assertEqual(self.records(), [])

    def test_a_group_signal_cannot_cut_the_one_shot_kill_short(self):
        # run in a session of its own, so killpg reaches it as a terminal's ctrl-c would reach
        # its foreground group. The SIGINT lands while finish's -Kill one-shot runs.
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, "run", "--",
                              sys.executable, "-c", "pass"],
                             env={**self.env, "FAKE_EOF_EXIT": "3", "FAKE_SLOW_KILL": "2"},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            self.wait_for(lambda: self.started("killstart-"), what="the one-shot -Kill")
            os.killpg(p.pid, signal.SIGINT)
            _, err = p.communicate(timeout=40)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        # The SIGINT stays pending through cleanup, then ends run: 130 or killed by SIGINT.
        self.assertIn(p.returncode, (128 + signal.SIGINT, -signal.SIGINT), err)
        rid = self.only_run_id()
        self.assertTrue(self.has("kill-" + rid), "the -Kill ran to the end")
        self.assertIn(f"the supervisor of {rid} exited 3; killed the run by its dir", err)
        self.assertFalse(self.has("alive-" + rid))
        self.assertEqual(self.records(), [])

    def test_a_closed_stderr_cannot_skip_the_cleanup(self):
        # Nothing finish prints may raise past the kill and the record's removal.
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, "run", "--",
                              sys.executable, "-c", "import time; time.sleep(0.5)"],
                             env={**self.env, "FAKE_EOF_EXIT": "3"},
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        p.stderr.close()  # every write to stderr now fails with EPIPE
        try:
            p.wait(timeout=40)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        rid = self.only_run_id()
        self.assertTrue(self.has("kill-" + rid))
        self.assertFalse(self.has("alive-" + rid))
        self.assertEqual(self.records(), [])

    def test_an_inherited_ignored_sighup_stays_ignored(self):
        # As under nohup: SIGHUP neither stops run nor reaches CMD.
        out = os.path.join(self.tmp, "status")
        code = "import sys; open(sys.argv[1], 'w').write(open('/proc/self/status').read())"
        p = subprocess.Popen(["/bin/sh", "-c", 'trap "" HUP; exec "$@"', "sh",
                              sys.executable, "-I", self.driver, CLI, self.root, "run", "--",
                              sys.executable, "-c", code, out],
                             env={**self.env, "FAKE_SLOW_HELLO": "2"},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.wait_for(lambda: self.started("hello-"), what="hello")
            p.send_signal(signal.SIGHUP)
            _, err = p.communicate(timeout=40)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertEqual(p.returncode, 0, err)
        rid = self.only_run_id()
        with open(out) as f:
            ign = int(re.search(r"SigIgn:\s*([0-9a-f]+)", f.read()).group(1), 16)
        self.assertTrue(ign >> (signal.SIGHUP - 1) & 1, "CMD inherits SIGHUP ignored")
        self.assertTrue(self.has("eof-" + rid))
        self.assertEqual(self.records(), [])

    def test_the_holder_keeps_sigterm_when_start_inherits_it_ignored(self):
        # SIGTERM is the holder's stop channel: an ignore chrome-bg inherited must not reach it.
        def under_ignored_term(*argv, env=None):
            return subprocess.Popen(["/bin/sh", "-c", 'trap "" TERM; exec "$@"', "sh",
                                     sys.executable, "-I", self.driver, CLI, self.root, *argv],
                                    env={**self.env, **(env or {})}, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
        # Its Chrome ignores Browser.close, so only stop's SIGTERM can end the holder.
        p = under_ignored_term("start", "--json", env={"FAKE_CHROME_IGNORE_CLOSE": "1"})
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, err)
        rid = json.loads(out)["id"]
        r = self.cli("stop", rid, env={"DRIVER_STOP_WAIT": "5"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("stopped by its owner", r.stdout)
        with open(os.path.join(self.recdir, rid + ".holder.log")) as f:
            self.assertIn("signal 15", f.read())
        self.assertFalse(self.has("kill-" + rid), "the holder ended the run itself")
        self.assertEqual(self.records(), [])
        # An interrupted start stops its holder with SIGTERM too (SIGINT here, as SIGTERM is
        # ignored by the start process itself).
        p = under_ignored_term("start", env={"FAKE_SLOW_HELLO": "2"})
        try:
            self.wait_for(lambda: len(self.started("hello-")) == 2 and len(self.records()) == 1,
                          what="the second holder")
            p.send_signal(signal.SIGINT)
            _, err = p.communicate(timeout=40)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertEqual(p.returncode, 128 + signal.SIGINT, err)
        [rid2] = [i for i in self.started("hello-") if i != rid]
        self.assertIn(f"start interrupted by signal 2; run {rid2} was stopped", err)
        with open(os.path.join(self.recdir, rid2 + ".holder.log")) as f:
            self.assertIn("signal 15", f.read())
        self.assertTrue(self.has("eof-" + rid2))
        self.assertEqual(self.started("launch-"), [rid], "the second run never launched")
        self.assertEqual(self.records(), [])

    def test_post_ready_sigterm_to_the_holder(self):
        # stop's SIGTERM reaches a ready holder whose Chrome ignores Browser.close: the holder
        # still ends the run itself, through its supervisor's EOF cleanup, with no -Kill.
        r = self.cli("start", "--json", env={"FAKE_CHROME_IGNORE_CLOSE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        chrome = int(self.notes("chromepid-" + rid)[0])
        r = self.cli("stop", rid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("stopped by its owner", r.stdout)
        with open(os.path.join(self.recdir, rid + ".holder.log")) as f:
            self.assertIn("signal 15", f.read())
        self.assertTrue(self.has("eof-" + rid))
        self.assertFalse(self.has("kill-" + rid), "the holder's own cleanup ended Chrome")
        st = cb.proc_stat(chrome)
        self.assertTrue(st is None or st[0] == "Z", "Chrome is gone")
        self.assertEqual(self.records(), [])

    def test_group_sigterm_to_run(self):
        # The whole process group (run and CMD) gets SIGTERM; the supervisor, in a session of
        # its own, gets only the EOF of a normal cleanup.
        ready, cmd = self.child_with_handlers()
        p = subprocess.Popen([sys.executable, "-I", self.driver, CLI, self.root, "run", "--", *cmd],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        try:
            self.wait_for(lambda: os.path.exists(ready), what="the child to start")
            os.killpg(p.pid, signal.SIGTERM)
            _, err = p.communicate(timeout=40)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertIn(p.returncode, (128 + signal.SIGTERM, -signal.SIGTERM), err)
        self.assertTrue(self.got(signal.SIGTERM), "CMD got SIGTERM")
        rid = self.only_run_id()
        self.assertTrue(self.has("eof-" + rid), "the supervisor saw EOF")
        self.assertFalse(self.has("kill-" + rid), "it cleaned up without a -Kill")
        self.assertEqual(self.cdp_calls(rid)[-1]["method"], "Browser.close")
        self.assertEqual(self.records(), [])

    def test_no_window_to_place_fails_the_start(self):
        marker = os.path.join(self.tmp, "ran")
        for argv in (["run", "--", sys.executable, "-c", "import sys; open(sys.argv[1], 'w').close()",
                      marker], ["start"]):
            with self.subTest(cmd=argv[0]):
                for n in os.listdir(self.root):
                    if n.startswith(("launch-", "eof-", "alive-")):
                        os.remove(os.path.join(self.root, n))
                r = self.cli(*argv, env={"FAKE_PLACE_EMPTY": "1"})
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("no run window to place", r.stderr)
                rid = self.only_run_id()
                self.assertTrue(self.has("eof-" + rid), "the supervisor was ended")
                self.assertFalse(self.has("alive-" + rid), "Chrome was closed")
                self.assertFalse(os.path.exists(marker), "CMD never ran")
                self.assertEqual(self.records(), [])

    def test_supervisor_ignores_sigpipe_in_a_session_of_its_own(self):
        r = self.cli("run", "--", sys.executable, "-c", "pass")
        self.assertEqual(r.returncode, 0, r.stderr)
        pid, sid = map(int, self.notes("session-" + self.only_run_id())[0].split())
        self.assertEqual(pid, sid, "start_new_session: the supervisor leads its own session")
        [line] = [ln for ln in self.notes("sigign.log") if ln.split()[0] == str(pid)]
        mask = int(re.search(r"SigIgn:([0-9a-f]+)", line).group(1), 16)
        self.assertTrue(mask >> (signal.SIGPIPE - 1) & 1, "restore_signals=False: SIGPIPE ignored")

    def test_start_failing_in_the_holder(self):
        r = self.cli("start", env={"FAKE_LAUNCH_FAIL": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Win32_Process Create failed (code 9)", r.stderr)
        [rid] = self.started("hello-")
        self.assertTrue(self.has("eof-" + rid), "the holder ended its supervisor")
        self.assertEqual(self.records(), [])

    def test_signal_before_the_child_exists(self):
        for argv in (["run", "--", sys.executable, "-c", "pass"], ["start"]):
            with self.subTest(cmd=argv[0]):
                for n in os.listdir(self.root):
                    if n.startswith(("hello-", "eof-")):
                        os.remove(os.path.join(self.root, n))
                p = self.popen(*argv, env={"FAKE_SLOW_HELLO": "2"})
                self.wait_for(lambda: self.started("hello-"), what="hello")
                p.send_signal(signal.SIGTERM)
                time.sleep(0.3)
                p.send_signal(signal.SIGTERM)  # held while cleanup runs, so it can't cut it short
                _, err = p.communicate(timeout=40)
                # Exit 143, or (the second one still pending once cleanup is done) killed by
                # SIGTERM, which a shell reports as 143 too.
                self.assertIn(p.returncode, (128 + signal.SIGTERM, -signal.SIGTERM), err)
                [rid] = self.started("hello-")
                self.assertTrue(self.has("eof-" + rid), "the supervisor was ended")
                self.assertFalse(self.started("launch-"), "Chrome never launched")
                self.assertEqual(self.records(), [])

    def test_holder_ends_when_chrome_is_gone(self):
        r = self.cli("start", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        info = json.loads(r.stdout)
        path = urlparse(cb.json_version(info["port"])["webSocketDebuggerUrl"]).path
        cdp = cb.CDP(cb.browser_ws(info["port"], path))
        with contextlib.suppress(OSError):
            cdp.send("Browser.close", timeout=5)  # what a fixture's browser.close() sends
        cdp.close()
        self.wait_for(lambda: self.has("eof-" + info["id"]) and not self.records(),
                      what="the holder to see Chrome gone and stop")

    def start_scripted(self, gone_s, answers):
        """A `start` run whose /json/list answers follow `answers`, with PAGES_GONE_S = gone_s:
        (run id, holder log path, when the script went in)."""
        r = self.cli("start", "--json", env={"DRIVER_PAGES_GONE": str(gone_s)})
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        seq = os.path.join(self.root, "pages-" + rid)
        with open(seq + ".tmp", "w") as f:
            f.write(" ".join(answers))
        os.replace(seq + ".tmp", seq)
        return rid, os.path.join(self.recdir, rid + ".holder.log"), time.monotonic()

    def lists(self, rid):
        return self.notes("list-" + rid) if self.has("list-" + rid) else []

    def assert_lives_through(self, rid, log, answers):
        """Every scripted answer read and two more polls, and the run still up."""
        self.wait_for(lambda: len(self.lists(rid)) >= len(answers) + 2 or self.has("eof-" + rid),
                      what="the scripted reads")
        self.assertFalse(self.has("eof-" + rid), "the holder ended the run")
        [rec] = self.records()
        self.assertTrue(cb.owner_proven(rec), "the holder still holds the run")
        with open(log) as f:
            self.assertNotIn("its last page closed", f.read())
        self.assertIn("stopped by its owner", self.cli("stop", rid).stdout)

    def test_holder_ends_when_its_last_page_closes(self):
        # You closed the window: Chrome runs on windowless (--no-startup-window), its /json/list
        # holds no page (a service worker is no page), and procs still lists it.
        rid, log, t0 = self.start_scripted(1, ["0"])
        self.wait_for(lambda: self.has("eof-" + rid) and not self.records(),
                      what="the holder to see no page and stop")
        self.assertGreaterEqual(time.monotonic() - t0, 1, "it waits PAGES_GONE_S first")
        self.assertGreaterEqual(len(self.lists(rid)), 2)
        self.assertFalse(self.has("alive-" + rid))
        with open(log) as f:
            text = f.read()
        self.assertIn("its last page closed", text)
        self.assertIn("stopped", text)

    def test_a_page_back_within_pages_gone_s_keeps_the_run(self):
        # Each spell of no page is under PAGES_GONE_S (5 polls at 0.2 s against 2 s), all three
        # together are over it: a page back must restart the clock.
        answers = ["0"] * 6 + ["1"] + ["0"] * 6 + ["1"] + ["0"] * 6 + ["1"]
        rid, log, _ = self.start_scripted(2, answers)
        self.assert_lives_through(rid, log, answers)

    def test_a_failed_page_read_never_counts_as_zero_pages(self):
        # As above, with failed reads between the spells: a failure is no page count, so it
        # neither counts toward PAGES_GONE_S nor lets the spells join.
        answers = ["0"] * 6 + ["fail"] + ["0"] * 6 + ["fail"] + ["0"] * 6 + ["1"]
        rid, log, _ = self.start_scripted(2, answers)
        self.assert_lives_through(rid, log, answers)
        with open(log) as f:
            text = f.read()
        self.assertIn("poll failed (1 in a row)", text)
        self.assertIn("/json/list answered 500", text)

    def test_holder_ends_after_three_failed_page_reads(self):
        rid, log, _ = self.start_scripted(60, ["fail"])
        self.wait_for(lambda: self.has("eof-" + rid) and not self.records(), what="the end")
        with open(log) as f:
            text = f.read()
        self.assertEqual(text.count("/json/list answered 500"), 3)
        self.assertIn("polls failed 3 times in a row", text)

    def test_stop_by_url_checks_the_runs_own_port_file(self):
        r = self.cli("start", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        a = json.loads(r.stdout)
        # A forged record claiming A's port: its run's port file names another browser path.
        forger, start = self.owner(mine=False)
        self.put_record("ffff0001", forger.pid, start, port=a["port"])
        self.put_dir("ffff0001", 5)
        with open(os.path.join(self.base, "ffff0001", "profile", "DevToolsActivePort"), "w") as f:
            f.write("%d\n/devtools/browser/forged" % a["port"])
        r = self.cli("stop", a["url"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"stopped {a['id']}", r.stdout)
        self.assertEqual([x["id"] for x in self.records()], ["ffff0001"])
        self.assertIsNone(forger.poll())
        # B's own port file no longer matches what its port serves: no record for that URL.
        r = self.cli("start", "--json")
        b = json.loads(r.stdout)
        with open(os.path.join(self.base, b["id"], "profile", "DevToolsActivePort"), "w") as f:
            f.write("%d\n/devtools/browser/other" % b["port"])
        r = self.cli("stop", b["url"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no run serves", r.stderr)
        self.assertEqual(self.cli("stop", b["id"]).returncode, 0)

    def test_relative_xdg_state_home_is_ignored(self):
        home = os.path.join(self.tmp, "home")
        env = {"XDG_STATE_HOME": "rel/state", "HOME": home}
        r = self.cli("start", "--json", env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = json.loads(r.stdout)["id"]
        recdir = os.path.join(home, ".local", "state", "dotclaude", "chrome-bg")
        self.assertTrue(os.path.exists(os.path.join(recdir, rid + ".json")),
                        "the holder wrote its record under ~/.local/state")
        ls = self.cli("ls", env=env, cwd=self.root)
        self.assertIn(rid, ls.stdout, "the start parent and the holder read the same dir")
        r = self.cli("stop", rid, env=env, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("stopped by its owner", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(recdir, rid + ".json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "rel")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "rel")))

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
        self.assertIn("  47292  ", mine)
        self.assertIn("alive (start)", mine)
        self.assertTrue(mine.rstrip().endswith(os.getcwd()))
        orphan = [ln for ln in lines if ln.startswith("ffff0001")][0]
        self.assertIn("no record", orphan)
        self.assertEqual(self.cli("stop", info["id"]).returncode, 0)

    # ---- check against the fake ----

    def check(self, **env):
        return self.cli("check", env={"DRIVER_FAST": "1", **env}, timeout=90)

    def test_check_passes_a_clean_run(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "PASS")
        for action in ("page0", "newPage-default", "bringToFront", BTN, "setWindowBounds-maximized",
                       "setWindowBounds-normal", "window.open", "raf-covered", "stop"):
            self.assertRegex(r.stdout, rf"(?m)^{re.escape(action)}\s+0ms\s+0ms\s+0ms")
        rid = self.only_run_id()
        calls = [c["method"] for c in self.cdp_calls(rid)]
        self.assertEqual(calls[-1], "Browser.close")
        # bringToFront-newPage is the first action (page0 still its window's only tab), page0's
        # bringToFront then a new page; the plain bringToFront follows every new page, so page0
        # is the active tab when raf-covered reads it.
        with open(os.path.join(self.base, rid + ".log")) as f:
            marks = [ln.split(" ", 1)[1] for ln in f.read().splitlines() if " MARK begin " in ln]
        self.assertEqual(marks[:2], ["MARK begin page0", f"MARK begin {BTN}"])
        self.assertLess(marks.index(f"MARK begin {BTN}"), marks.index("MARK begin bringToFront"))
        # page0 loads a page of its own first: on about:blank the pair lifted nothing live.
        i = calls.index("Page.bringToFront")
        self.assertEqual(calls[i - 2:i + 2], ["Page.navigate", "Runtime.evaluate",
                                              "Page.bringToFront", "Target.createTarget"])
        nav, loaded, front, new_page = self.cdp_calls(rid)[i - 2:i + 2]
        self.assertTrue(nav["params"]["url"].startswith("data:text/html,"), nav)
        self.assertEqual(loaded["params"]["expression"], cb.LOADED_JS, "waits for page0's data: page")
        for c in (nav, loaded, front):
            self.assertEqual(c.get("sessionId"), "S1", "on page0's session")
        self.assertEqual(new_page["params"], {"url": "about:blank"})
        last_front = len(calls) - 1 - calls[::-1].index("Page.bringToFront")
        self.assertNotIn("Target.createTarget", calls[last_front:], "a new page after the last bringToFront")
        evals = [c for c in self.cdp_calls(rid) if c["method"] == "Runtime.evaluate"]
        opens = [c for c in evals if "window.open" in c["params"]["expression"]]
        self.assertEqual(len(opens), 1)
        self.assertTrue(opens[0]["params"]["userGesture"], "window.open carries a user gesture")
        self.assertEqual({c.get("sessionId") for c in evals}, {"S1"})
        self.assertIn({"windowState": "maximized"},
                      [c["params"].get("bounds") for c in self.cdp_calls(rid)])
        self.assertTrue(self.has("eof-" + rid))
        self.assertEqual(self.records(), [])

    def test_check_fails_an_action_it_could_not_take(self):
        r = self.check(FAKE_NAV_ERROR="net::ERR_ABORTED")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "FAIL")
        self.assertRegex(r.stdout, rf"(?m)^FAIL: {re.escape(BTN)}: the action could not be taken "
                                   r"\(.*ERR_ABORTED.*\), so it went untested$")
        self.assertEqual(self.records(), [])

    def test_check_polls_until_page0_reports_its_data_page(self):
        # Page.navigate answers at the browser's commit: the old about:blank may answer first.
        r = self.check(FAKE_LOADED_AFTER="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "PASS")
        calls = [c["method"] for c in self.cdp_calls(self.only_run_id())]
        nav, front = calls.index("Page.navigate"), calls.index("Page.bringToFront")
        self.assertEqual(calls[nav + 1:front], ["Runtime.evaluate"] * 3)

    def test_check_fails_when_page0_never_loads_or_no_popup_opens(self):
        for env, text in (({"FAKE_LOADED": "about: complete"},
                           rf"{re.escape(BTN)}: the action could not be taken \(page0 never loaded "
                           r".*; it read 'about: complete'\)"),
                          ({"FAKE_POPUP": "false"},
                           r"window\.open: the action could not be taken \(window\.open returned "
                           r"'false', so no popup opened\)")):
            with self.subTest(env=env):
                r = self.check(**env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertRegex(r.stdout, rf"(?m)^FAIL: {text}, so it went untested$")
                self.assertEqual(self.records(), [])

    def test_check_inconclusive_without_a_visible_foreground(self):
        r = self.check(FAKE_FG_HIDDEN="1")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("INCONCLUSIVE", r.stdout)
        self.assertFalse([n for n in os.listdir(self.root) if n.startswith("launch-")],
                         "Chrome never launched")

    def test_check_fails_a_hidden_page(self):
        r = self.check(FAKE_RAF="hidden 3")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL: page0 read 'hidden'", r.stdout)

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
