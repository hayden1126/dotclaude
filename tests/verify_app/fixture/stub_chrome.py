"""A fake chrome-headless-shell for the browser setup tests: just enough CDP on fds 3 and 4.

    stub_chrome.py MODE RECORD [chrome flags...]

MODE "hang" never answers. Any other MODE is a CDP method this stub answers with an error. RECORD
gets the profile folder and this process's pid, one per line, so a test can check both are gone."""
import json
import os
import sys
import time

mode, record = sys.argv[1], sys.argv[2]
profile = next(arg.split("=", 1)[1] for arg in sys.argv[3:] if arg.startswith("--user-data-dir="))
with open(record + ".tmp", "w", encoding="utf-8") as f:
    f.write(f"{profile}\n{os.getpid()}\n")
os.replace(record + ".tmp", record)
if mode == "hang":
    time.sleep(60)
    sys.exit()
RESULTS = {"Target.createTarget": {"targetId": "t1"}, "Target.attachToTarget": {"sessionId": "s1"}}
buf = b""
while chunk := os.read(3, 1 << 16):
    buf += chunk
    while b"\0" in buf:
        raw, buf = buf.split(b"\0", 1)
        message = json.loads(raw)
        reply = {"id": message["id"]}
        if message["method"] == mode:
            reply["error"] = {"message": f"the stub refuses {mode}"}
        else:
            reply["result"] = RESULTS.get(message["method"], {})
        if "sessionId" in message:
            reply["sessionId"] = message["sessionId"]
        os.write(4, json.dumps(reply).encode() + b"\0")
        if message["method"] == "Browser.close":
            sys.exit()
