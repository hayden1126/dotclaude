#!/usr/bin/env python3
"""ccstatusline custom-command widget: a 1-2 sentence session summary.

Renders a plain-language "what is this session doing, and where does it stand"
line under the metrics row, so a developer juggling several Claude terminals can
re-orient after switching back to one. The text is produced out-of-band by the
Stop hook (hooks/session-summary.sh -> Haiku) and cached per session; this widget
only reads that cache. Before the first summary lands (or if generation is off or
failed) it falls back to Claude Code's own ai-title from the transcript, so a
fresh session still shows something.

The summary can run to two visual rows. ccstatusline renders one widget per line,
so this script is wired twice -- `--row 1` on line 2, `--row 2` on line 3 -- and
each call prints only its slice (row 2 prints nothing when the text fits on one
line). Needs preserveColors: true so the dim ANSI passes through.

Fail-open: any error or missing data -> print nothing (never a traceback, never
a stray error string in the status line).
"""
import sys, os, json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- tunables -------------------------------------------------------------
MARKER        = "▸ "     # leading glyph on row 1 (row 2 indents under it)
DIM           = "\x1b[38;5;245m"
RESET         = "\x1b[0m"
MAX_ROWS      = 2
DEFAULT_WIDTH = 100      # used when COLUMNS is not in the environment
# ---------------------------------------------------------------------------


def fail():
    sys.exit(0)  # exit 0, nothing on stdout


def arg_row():
    a = sys.argv[1:]
    if "--row" in a:
        try:
            return max(1, int(a[a.index("--row") + 1]))
        except (ValueError, IndexError):
            return 1
    return 1


def config_dir(transcript_path):
    """<config-dir> from the transcript path (<cfg>/projects/<proj>/<sess>.jsonl).
    CLAUDE_CONFIG_DIR is not passed through to widget subprocesses, so derive it
    the same way ctx-breakdown.py does, keeping the cache path in agreement with
    the writer (the Stop hook)."""
    if transcript_path:
        d = os.path.dirname(transcript_path)
        if os.path.basename(os.path.dirname(d)) == "projects":
            return os.path.dirname(os.path.dirname(d))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def read_cached_summary(cfg, session_id):
    if not session_id:
        return ""
    path = os.path.join(cfg, "session-summaries", session_id + ".txt")
    try:
        with open(path, encoding="utf-8") as f:
            return " ".join(f.read().split())
    except OSError:
        return ""


def scan_ai_title(transcript, cwd, chunk=262144):
    """Freshest ai-title from the transcript tail: the zero-cost fallback shown
    before the Haiku summary lands (same tail-scan as session-title.sh)."""
    if not transcript:
        return ""
    path = transcript
    if not os.path.isabs(path):
        path = os.path.join(cwd or "", path)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > chunk:
                f.seek(size - chunk)
            blob = f.read()
    except OSError:
        return ""
    for line in reversed(blob.decode("utf-8", "ignore").splitlines()):
        if '"ai-title"' in line:
            try:
                o = json.loads(line)
                if o.get("type") == "ai-title" and o.get("aiTitle"):
                    return " ".join(str(o["aiTitle"]).split())
            except Exception:
                pass
    return ""


def wrap(text, width, max_rows):
    """Greedy word-wrap into at most max_rows lines; ellipsize the last if the
    text does not fit."""
    words = text.split()
    rows, cur = [], ""
    for i, w in enumerate(words):
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            rows.append(cur)
            cur = w
            if len(rows) == max_rows:
                cur = ""  # no room for another row; remaining words are dropped
                break
    if cur and len(rows) < max_rows:
        rows.append(cur)
    consumed = sum(len(r.split()) for r in rows)
    if consumed < len(words) and rows:
        last = rows[-1]
        if len(last) + 1 > width:
            last = last[:max(0, width - 1)].rstrip()
        rows[-1] = last + "…"
    return rows


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        fail()
    session_id = data.get("session_id")
    transcript = data.get("transcript_path")
    cwd = data.get("cwd") or ""
    cfg = config_dir(transcript)

    summary = read_cached_summary(cfg, session_id) or scan_ai_title(transcript, cwd)
    if not summary:
        fail()

    try:
        width = int(os.environ.get("COLUMNS") or DEFAULT_WIDTH)
    except ValueError:
        width = DEFAULT_WIDTH
    # leave a small margin, and reserve room for the 2-col marker/indent
    text_width = max(16, width - 2 - len(MARKER))

    rows = wrap(summary, text_width, MAX_ROWS)
    row = arg_row()
    if row > len(rows):
        fail()  # this line stays empty
    text = rows[row - 1]
    if row == 1:
        sys.stdout.write(DIM + MARKER + text + RESET)
    else:
        sys.stdout.write(DIM + (" " * len(MARKER)) + text + RESET)


if __name__ == "__main__":
    main()
