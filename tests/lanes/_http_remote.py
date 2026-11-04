"""A smart-HTTP git remote on 127.0.0.1 that answers only with a credential, for tests of the
store fetches' credential config (the verified stores of `lane new` and `lane sync-main`).

git here speaks https through GnuTLS, which reads no CA file a test can plant, so the remote is
plain http and the lane CLI under test gets http added to its allowed protocols by a patch (see
test_git_tamper.DRIVER's "http" mode). Every request without the Basic credential USER:PASSWORD
gets a 401, so a fetch passes only when a credential helper answered.
"""
import base64
import http.server
import os
import subprocess
import threading

USER, PASSWORD = "lane-test", "s3cret"


def helper_script(log: str) -> str:
    """A credential helper, as a git config value, that answers USER and PASSWORD for `get` and
    appends one line to log each time it runs."""
    return (f"!f() {{ echo ran >> '{log}'; test \"$1\" = get || exit 0; "
            f"echo username={USER}; echo password={PASSWORD}; }}; f")


class Remote:
    """The bare repos under root, served by `git http-backend` at self.url + '/<name>'."""

    def __init__(self, root: str):
        self.root, self.authorized, self.refused = root, 0, 0
        remote = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.backend()

            def do_POST(self):
                self.backend()

            def backend(self):
                want = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
                if self.headers.get("Authorization") != want:
                    remote.refused += 1
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="lanes"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                remote.authorized += 1
                path, _, query = self.path.partition("?")
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                env = {"PATH": os.environ["PATH"], "GIT_PROJECT_ROOT": remote.root,
                       "GIT_HTTP_EXPORT_ALL": "1", "REQUEST_METHOD": self.command,
                       "PATH_INFO": path, "QUERY_STRING": query, "REMOTE_USER": USER,
                       "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                       "CONTENT_LENGTH": str(len(body)), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull}
                if enc := self.headers.get("Content-Encoding"):
                    env["HTTP_CONTENT_ENCODING"] = enc
                if proto := self.headers.get("Git-Protocol"):
                    env["GIT_PROTOCOL"] = proto
                p = subprocess.run(["git", "http-backend"], input=body, env=env,
                                   capture_output=True, timeout=60)
                head, _, out = p.stdout.partition(b"\r\n\r\n")
                if not _:
                    head, _, out = p.stdout.partition(b"\n\n")
                status, headers = 200, []
                for line in head.decode("latin-1").splitlines():
                    name, _, value = line.partition(":")
                    if name.lower() == "status":
                        status = int(value.split()[0])
                    elif name:
                        headers.append((name, value.strip()))
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
