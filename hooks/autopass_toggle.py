"""autopass-toggle: answer `/autopass on|off|status` for the autopass mod.

skills/autopass (a mod: its hooks/register.ts) serves `/autopass` as an immediate slash command
and runs this file with python3 -I through $.process.run, as
`autopass_toggle.py SESSION_ID CWD ARGS`, ARGS being everything typed after the name. It prints
the one reply on stdout; the mod shows it (a transcript notice while a turn runs, the command's
output when idle) under the plugin's name, so a reply never starts with "autopass". The child
inherits the session's environment, so TMUX_PANE names the tab (spike 2, 2.1.296).

- on / off: write the tab flag (autopass_state.set_flag) for TMUX_PANE on its tmux server, and
  drop the watcher's cached decision for this session under its lock (waiting up to 3 s; if
  the lock stays busy, the reply says the change may take up to a minute). Outside tmux nothing
  is written: the toggle is per tab, and `autopass` in pass.toml ($XDG_CONFIG_HOME/dotclaude,
  ~/.config by default; the replies name the one in use) is the global default.
- status, or no word: the context size (ctx/<session>.json), the next tier, on or off, and
  which level set it.
- another word, or more than one: the usage line.
A failure exits non-zero with the error on stderr, and the mod shows it: nothing else answers
the command. Tests: tests/setup/test_context_watch.py. Stdlib only; keep the source ASCII.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402

SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
USAGE = "Usage: /autopass on|off|status (per tmux tab)."
NO_TMUX = ("/autopass {word} is per tmux tab, and this session isn't in one: nothing changed. "
           "The global default is `autopass = true` or `false` in {path}.")
NO_TAB = "/autopass {word}: tmux didn't say which tab this is, so nothing changed."
SOURCES = {"tab": "set in this tab", "lanes": "the lane default", "pass.toml": "from {path}",
           "default": "the default"}
LABELS = {"soft": "soft", "wrap": "wrap-up", "hard": "hard"}
LATE = " The watcher may use the old setting for up to a minute."


def shown_toml() -> str:
    """pass.toml's path as /autopass names it: the one the watcher reads (it follows
    XDG_CONFIG_HOME), with the home directory as ~."""
    path, home = aps.pass_toml_path(), os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


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
        return NO_TMUX.format(word=word, path=shown_toml())
    here = aps.tab(pane)
    if here is None:
        return NO_TAB.format(word=word)
    aps.set_flag(pane, here, word == "on")
    try:
        dropped = drop_cached_mode(sid)
    except OSError:
        dropped = False
    return "%s in this tab: %s%s" % (
        word, "it nudges a handoff at each context tier." if word == "on"
        else "no nudges; one line at the hard tier.", "" if dropped else LATE)


def status(sid, cwd, pane) -> str:
    on, source = aps.decide(cwd, pane)
    head = "%s (%s)." % ("on" if on else "off",
                                  SOURCES[source].format(path=shown_toml()))
    ctx = aps.load_json(aps.ctx_path(sid)) \
        if isinstance(sid, str) and SID.fullmatch(sid) else None
    n = ctx.get("tokens") if isinstance(ctx, dict) and aps.is_int(ctx.get("tokens")) else None
    # `window`: the widget's, refreshed on every render (2b); the config dir comes from
    # CLAUDE_CONFIG_DIR, which the child inherits from the session.
    tiers = aps.tiers(aps.window(None, ctx.get("window") if isinstance(ctx, dict) else None))
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


def answer(args: str, sid, cwd, pane) -> str:
    """The reply to `/autopass ARGS` in session sid."""
    words = args.split()
    if len(words) > 1:
        return USAGE
    word = words[0].lower() if words else "status"
    if word in ("on", "off"):
        return toggle(word, sid, pane)
    if word == "status":
        return status(sid, cwd, pane)
    return USAGE


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: autopass_toggle.py SESSION_ID CWD ARGS\n")
        return 2
    sys.stdout.write(answer(argv[2], argv[0], argv[1], os.environ.get("TMUX_PANE")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
