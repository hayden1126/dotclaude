"""A tiny stdlib web app for the verify harness tests. FIXTURE_MODE plants one break."""
import http.server
import os
import signal
import subprocess
import sys
import time

MODE = os.environ.get("FIXTURE_MODE", "normal")
PORT = int(os.environ["FIXTURE_PORT"])
STATE = os.environ["FIXTURE_DIR"]
OUTSIDE = os.environ["FIXTURE_OUTSIDE"]
SLEEPER = "import signal, time\nsignal.signal(15, %s)\ntime.sleep(45)\n"
UNDUMPABLE = "import ctypes\nctypes.CDLL(None).prctl(4, 0)  # PR_SET_DUMPABLE: environ and cwd unreadable\n"
HOME = b"""<!doctype html><title>fixture home</title><h1>fixture home</h1>
<button id="go" onclick="document.getElementById('result').textContent = 'clicked'">Go</button>
<p id="result">idle</p>
<button id="pay" onclick="fetch('/paid', {method: 'POST'}).then(() => {
  document.getElementById('paid').textContent = 'paid'})">Pay</button>
<p id="paid">unpaid</p>
<form method="post" action="/export"><button id="save">Save</button></form>
<button onclick="document.getElementById('result').textContent = 'by text'">  Export
</button>
<button onclick="document.getElementById('result').textContent = 'wrong'">Export all</button>
<a href="#" role="button">Copy</a><button>Copy</button>
<button hidden onclick="document.getElementById('result').textContent = 'hidden'">Secret</button>
"""
# Smooth scrolling animates scrollIntoView, so a rect read straight after it is the old spot.
SMOOTH = b"""<!doctype html><title>smooth</title><style>html{scroll-behavior:smooth}</style>
<p id="result">idle</p><div style="height:4000px">spacer</div>
<button id="far" onclick="document.getElementById('result').textContent = 'far'">Far</button>
<div style="height:4000px">spacer</div>
<button onclick="document.getElementById('result').textContent = 'far text'">Far text</button>
"""


def spawn(handler: str = "signal.SIG_DFL",
    cwd: str | None = None,
    new_session: bool = False,
    keep: tuple = (),
    undumpable: bool = False,
) -> None:
    """Start a sleeper the harness must deal with, and leave its pid for the test."""
    code = (UNDUMPABLE if undumpable else "") + SLEEPER % handler
    child = subprocess.Popen([sys.executable, "-c", code], cwd=cwd, pass_fds=keep,
                             start_new_session=new_session, stdin=subprocess.DEVNULL)
    path = os.path.join(STATE, "child.pid")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(str(child.pid))
    os.replace(path + ".tmp", path)
    time.sleep(0.2)  # let it reach its own signal call before anyone signals it


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        print(self.requestline, flush=True)

    def reply(self, status: int, body: bytes, headers: tuple = ()):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def note(self):
        with open(os.path.join(STATE, "requests.log"), "a", encoding="utf-8") as f:
            f.write(f"{self.command} {self.path}\n")

    def do_GET(self):
        self.note()
        if self.path == "/":
            self.reply(500 if MODE == "bad_doctor" else 200, HOME, (("Content-Type", "text/html"),))
        elif self.path == "/smooth":
            self.reply(200, SMOOTH, (("Content-Type", "text/html"),))
        elif self.path == "/health":
            self.reply(200, b"ok")
        elif self.path == "/moved":
            self.reply(302, b"", (("Location", "/elsewhere"),))
        elif self.path == "/file.bin":
            self.reply(200, b"file bytes", (("Content-Disposition", 'attachment; filename="file.bin"'),))
        elif self.path == "/crash":
            os._exit(7)
        else:
            self.reply(404, b"not here")

    def do_POST(self):
        self.note()
        if self.path == "/export":
            self.reply(200, b"exported bytes", (("Content-Type", "application/octet-stream"),
                                                ("Content-Disposition", 'attachment; filename="out.bin"')))
        else:
            self.reply(200, b"ok")


def main():
    print("fixture starting", MODE, flush=True)
    with open(os.path.join(STATE, "cwd"), "w", encoding="utf-8") as f:
        f.write(os.getcwd())
    if MODE == "boot_crash":
        sys.exit(3)
    if MODE == "never_ready":
        time.sleep(45)
        return
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    if MODE == "grandchild":
        spawn()
    elif MODE == "setsid":
        spawn(new_session=True)
    elif MODE == "ignore_term":
        spawn(handler="signal.SIG_IGN")
    elif MODE == "undumpable":
        spawn(handler="signal.SIG_IGN", undumpable=True)
    elif MODE == "outside":
        spawn(cwd=OUTSIDE, new_session=True)
    elif MODE == "outside_port":
        spawn(cwd=OUTSIDE, new_session=True, keep=(server.socket.fileno(),))
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    server.serve_forever()


if __name__ == "__main__":
    main()
