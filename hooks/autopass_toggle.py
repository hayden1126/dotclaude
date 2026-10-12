"""autopass-toggle: answer `/autopass on|off|status` without a model turn.

hooks/autopass-toggle.sh runs this file with python3 -I on UserPromptSubmit, passing the event
on stdin. Spike A1: a defined command (skills/autopass/SKILL.md) reaches the hook as the raw
text, and `decision: block` with a `reason` shows the reason and runs no model turn. Only a
prompt that is, after a strip, `/autopass` with at most one word after it is answered; anything
else (injected notices included) passes through untouched, as does a subagent's (agent_id).

- on / off: write the tab flag (autopass_state.set_flag) for TMUX_PANE on its tmux server, and
  drop the watcher's cached decision for this session. Outside tmux nothing is written: the
  toggle is per tab, and `autopass` in ~/.config/dotclaude/pass.toml is the global default.
- status, or no word: the context size (ctx/<session>.json), the next tier, on or off, and
  which level set it.
- anything else: the usage line.
Tests: tests/setup/test_context_watch.py. Stdlib only; keep the source ASCII. Fails open.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402

COMMAND = re.compile(r"/autopass(?:\s+(\S+))?\s*")
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
USAGE = "Usage: /autopass on|off|status (per tmux tab)."
NO_TMUX = ("/autopass {word} is per tmux tab, and this session isn't in one: nothing changed. "
           "The global default is `autopass = true` or `false` in "
           "~/.config/dotclaude/pass.toml.")
NO_TAB = "/autopass {word}: tmux didn't say which tab this is, so nothing changed."
SOURCES = {"tab": "set in this tab", "lanes": "the lane default", "pass.toml":
           "from ~/.config/dotclaude/pass.toml", "default": "the default"}
LABELS = {"soft": "soft", "wrap": "wrap-up", "hard": "hard"}


def drop_cached_mode(sid) -> None:
    if not (isinstance(sid, str) and SID.fullmatch(sid)):
        return
    path = aps.watch_path(sid)
    with aps.watch_lock() as locked:
        rec = aps.load_json(path) if locked else None
        if isinstance(rec, dict) and "mode" in rec:
            del rec["mode"]
            aps.write_json(path, rec)


def toggle(word: str, sid, pane) -> str:
    if not (isinstance(pane, str) and aps.PANE.fullmatch(pane)):
        return NO_TMUX.format(word=word)
    here = aps.tab(pane)
    if here is None:
        return NO_TAB.format(word=word)
    aps.set_flag(pane, here, word == "on")
    try:
        drop_cached_mode(sid)
    except OSError:
        pass
    return "autopass %s in this tab: %s" % (
        word, "it nudges a handoff at each context tier." if word == "on"
        else "no nudges; one line at the hard tier.")


def status(sid, cwd, pane) -> str:
    on, source = aps.decide(cwd, pane)
    head = "autopass %s (%s)." % ("on" if on else "off", SOURCES[source])
    ctx = aps.load_json(aps.ctx_path(sid)) \
        if isinstance(sid, str) and SID.fullmatch(sid) else None
    n = ctx.get("tokens") if isinstance(ctx, dict) and aps.is_int(ctx.get("tokens")) else None
    tiers = aps.tiers()
    if tiers is None:
        return head + " No tiers: autoCompactWindow is too small for them."
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
    word = (m.group(1) or "status").lower()
    if word in ("on", "off"):
        return toggle(word, d.get("session_id"), pane)
    if word == "status":
        return status(d.get("session_id"), d.get("cwd"), pane)
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
