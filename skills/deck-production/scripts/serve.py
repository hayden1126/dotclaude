#!/usr/bin/env python3
"""Range-capable static server for the deck iteration loop.

Usage: python3 serve.py <deck-dir> [--port N] [--bind ADDR]

`python3 -m http.server` ignores the Range header, so seeking inside a video
restarts the stream from zero. Linear autoplay (the presentation path) is
unaffected, which is why the gap survives unnoticed until someone scrubs a
timeline. This adds Range support and nothing else.

Always serve over http://, never file://: byte ranges, consistent origins, and
the same URLs the capture tools use.

Stdlib only.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import pathlib
import re
import socketserver
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler plus single-range support (RFC 7233)."""

    def send_head(self):
        if "Range" not in self.headers:
            return super().send_head()

        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            handle = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(handle.fileno()).st_size
        match = RANGE_RE.match(self.headers["Range"])
        if not match:
            handle.close()
            self.send_error(400, "Malformed Range header")
            return None

        start_raw, end_raw = match.groups()
        if start_raw:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
        else:                                   # suffix range: last N bytes
            start = max(0, size - int(end_raw))
            end = size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            handle.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        handle.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._range = (start, end)
        return handle

    def copyfile(self, source, outputfile):
        window = getattr(self, "_range", None)
        if window is None:
            return super().copyfile(source, outputfile)
        remaining = window[1] - window[0] + 1
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._range = None

    def end_headers(self):
        # The iteration loop reloads constantly; a cached fragment is a lie.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "404" in (fmt % args) or "500" in (fmt % args):
            super().log_message(fmt, *args)


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Range-capable static server")
    deckcfg.add_common_args(parser)
    parser.add_argument("--port", type=int, help="override the configured port")
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()

    cfg = deckcfg.load(args.deck, args.config)
    port = args.port or cfg.get("build.serve_port")
    handler = functools.partial(RangeHandler, directory=str(cfg.deck))

    with ReusableServer((args.bind, port), handler) as server:
        print(f"serving {cfg.deck} at http://{args.bind}:{port}/  (Range supported)")
        print(f"  capture mode: http://{args.bind}:{port}/?export")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
