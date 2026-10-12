"""autopass-toggle: answer `/autopass on|off|status` without a model turn.

hooks/autopass-toggle.sh runs this file with python3 -I on UserPromptSubmit, passing the event
on stdin. Spike A1: a defined command (skills/autopass/SKILL.md) reaches the hook as the raw
text, and `decision: block` with a `reason` shows the reason and runs no model turn. Every
prompt that starts, after a strip, with `/autopass` and then a space or nothing is answered
(so a stray word gets the usage line, not the skill body's "not installed"); anything else
(injected notices included) passes through untouched, as does a subagent's (agent_id).

- on / off: write the tab flag (autopass_state.set_flag) for TMUX_PANE on its tmux server, and
  drop the watcher's cached decision for this session under its lock (waiting up to 3 s; if
  the lock stays busy, the reply says the change may take up to a minute). Outside tmux nothing is written: the
  toggle is per tab, and `autopass` in ~/.config/dotclaude/pass.toml is the global default.
- status, or no word: the context size (ctx/<session>.json), the next tier, on or off, and
  which level set it.
- another word, or more than one: the usage line.
Tests: tests/setup/test_context_watch.py. Stdlib only; keep the source ASCII. Fails open.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402

COMMAND = re.compile(r"/autopass(?:\s+(.*))?", re.S)
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
USAGE = "Usage: /autopass on|off|status (per tmux tab)."
NO_TMUX = ("/autopass {word} is per tmux tab, and this session isn't in one: nothing changed. "
           "The global default is `autopass = true` or `false` in "
           "~/.config/dotclaude/pass.toml.")
NO_TAB = "/autopass {word}: tmux didn't say which tab this is, so nothing changed."
SOURCES = {"tab": "set in this tab", "lanes": "the lane default", "pass.toml":
           "from ~/.config/dotclaude/pass.toml", "default": "the default"}
LABELS = {"soft": "soft", "wrap": "wrap-up", "hard": "hard"}


LATE = " The watcher may use the old setting for up to a minute."


def drop_cached_mode(sid) -> bool:
    """Drop the watcher's cached decision for session sid; False when its lock stayed busy."""
    if not (isinstance(sid, str) and SID.fullmatch(sid)):
        return True
    path = aps.watch_path(sid)
    with aps.watch_lock(sid, wait=3.0) as locked:
        if not locked:
            return False
        rec = aps.load_json(path)
        if isinstance(rec, dict) and "mode" in rec:
            del rec["mode"]
            aps.write_json(path, rec)
    return True


def toggle(word: str, sid, pane) -> str:
    if not (isinstance(pane, str) and aps.PANE.fullmatch(pane)):
        return NO_TMUX.format(word=word)
    here = aps.tab(pane)
    if here is None:
        return NO_TAB.format(word=word)
    aps.set_flag(pane, here, word == "on")
    try:
        dropped = drop_cached_mode(sid)
    except OSError:
        dropped = False
    return "autopass %s in this tab: %s%s" % (
        word, "it nudges a handoff at each context tier." if word == "on"
        else "no nudges; one line at the hard tier.", "" if dropped else LATE)


def status(sid, cwd, pane, transcript_path=None) -> str:
    on, source = aps.decide(cwd, pane)
    head = "autopass %s (%s)." % ("on" if on else "off", SOURCES[source])
    ctx = aps.load_json(aps.ctx_path(sid)) \
        if isinstance(sid, str) and SID.fullmatch(sid) else None
    n = ctx.get("tokens") if isinstance(ctx, dict) and aps.is_int(ctx.get("tokens")) else None
    tiers = aps.tiers(aps.window(transcript_path,
                                 ctx.get("window") if isinstance(ctx, dict) else None))
    if tiers is None:
        return head + " No tiers: the context window is too small for them."
    where = "Context %s" % (aps.kilo(n) if n is not None else "unknown yet")
    nxt = [t for t in aps.TIER_NAMES if n is None or n < tiers[t]]
    if nxt:
        tail = "next tier: %s at %s" % (LABELS[nxt[0]], aps.kilo(tiers[nxt[0]]))
    else:
        tail = "past the hard tier (%s)" % aps.kilo(tiers["hard"])
    return "%s %s, %s; auto-compact near %s." % (head, where, tail,
                                                aps.kilo(tiers["compact_at"]))


def answer(d: dict, pane):
    """The block reason for prompt event d, or None to let it through."""
    if d.get("agent_id") or not isinstance(d.get("prompt"), str):
        return None
    m = COMMAND.fullmatch(d["prompt"].strip())
    if not m:
        return None
    words = (m.group(1) or "").split()
    if len(words) > 1:
        return USAGE
    word = words[0].lower() if words else "status"
    if word in ("on", "off"):
        return toggle(word, d.get("session_id"), pane)
    if word == "status":
        return status(d.get("session_id"), d.get("cwd"), pane, d.get("transcript_path"))
    return USAGE


def main() -> None:
    try:
        d = json.load(sys.stdin.buffer)
        reason = answer(d, os.environ.get("TMUX_PANE")) if isinstance(d, dict) else None
    except Exception:
        return
    if reason:
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
