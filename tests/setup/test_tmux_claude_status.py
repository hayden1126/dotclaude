"""tmux/tmux-claude-status: the backstop that clears a dead window's state, fills a cold one, and
maps each background session to the tab showing it (stdlib only).

A background session (claude daemon) has no TMUX_PANE, and its process ancestry reaches whichever
client started the daemon, so the script maps it by directory: the one client pane (a `claude`
pane that no interactive session's ancestry reaches) in the session's cwd. It writes the map to
$XDG_STATE_HOME/dotclaude/tabs for the hooks (hooks/session-pane.sh) and queries `claude agents
--json` only when the panes or the daemon's pty hosts change, or every 60 s while hosts run.

Stubs stand in for tmux, claude, pgrep and delegation-ledger; real `bash -c 'sleep & wait'`
processes give the panes real /proc ancestry."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "tmux-claude-status")

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $1" in
  "tmux list-windows") printf '%s\\n' "$STUB_WINDOWS" ;;
  "tmux list-panes") printf '%s\\n' "$STUB_PANES" ;;
  "claude agents") [ -n "${STUB_HANG:-}" ] && exec sleep 30; printf '%s\\n' "$STUB_AGENTS" ;;
  "pgrep "*) [ -n "$STUB_HOSTS" ] && printf '%s\\n' $STUB_HOSTS ;;
  "delegation-ledger watch") printf '1▶' ;;
esac
exit 0
"""

DNA = "/home/u/code/dna"
SERVER = "4242"


def mapped(*lines, server=SERVER):
    return "".join([f"server {server}\n"] + [line + "\n" for line in lines])


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        local_bin = os.path.join(self.tmp, "home", ".local", "bin")
        os.makedirs(stubs)
        os.makedirs(local_bin)
        # tmux's server PATH lacks ~/.local/bin, where claude and delegation-ledger live: the
        # script must find them there with a bare PATH.
        for path in [os.path.join(stubs, n) for n in ("tmux", "pgrep")] + [
                os.path.join(local_bin, n) for n in ("claude", "delegation-ledger")]:
            with open(path, "w") as f:
                f.write(STUB)
            os.chmod(path, 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state")
        self.run_dir = os.path.join(self.tmp, "run")
        os.mkdir(self.run_dir)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + "/usr/bin:/bin", STUB_LOG=self.log,
                        HOME=os.path.join(self.tmp, "home"), XDG_STATE_HOME=self.state,
                        TMUX_CLAUDE_STATUS_DIR=self.run_dir)
        self.server = SERVER
        self.panes = []     # (pane_id, window_id, pane_pid, command, path)
        self.windows = {}   # window_id -> @claude_state

    # --- fixtures -----------------------------------------------------------------------

    def spawn(self):
        """A pane shell with one child: returns (shell pid, child pid)."""
        p = subprocess.Popen(["bash", "-c", "sleep 60 & wait"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        path = f"/proc/{p.pid}/task/{p.pid}/children"
        deadline = time.time() + 3
        while time.time() < deadline:
            with open(path) as f:
                kids = f.read().split()
            if kids:
                child = int(kids[0])
                self.addCleanup(lambda: subprocess.run(["kill", str(child)],
                                                       stderr=subprocess.DEVNULL))
                return p.pid, child
            time.sleep(0.02)
        self.fail("no child")

    def pane(self, pane_id, window_id, path, state="", command="claude"):
        shell, child = self.spawn()
        self.panes.append((pane_id, window_id, shell, command, path))
        self.windows.setdefault(window_id, state)
        return child

    def run_status(self, agents, hosts="501 502", raw=None, **env):
        self.env["STUB_PANES"] = "\n".join(" ".join(map(str, p)) for p in self.panes)
        self.env["STUB_WINDOWS"] = "\n".join(f"{self.server} {w} {s}"
                                             for w, s in self.windows.items())
        self.env["STUB_AGENTS"] = raw if raw is not None else json.dumps(agents)
        self.env["STUB_HOSTS"] = hosts
        stamp = os.path.join(self.run_dir, f".tmux-claude-status.{os.getuid()}.stamp")
        if os.path.exists(stamp):
            os.remove(stamp)  # past the 3 s rate limit
        if os.path.exists(self.log):
            os.remove(self.log)
        p = subprocess.run(["bash", SCRIPT], capture_output=True, text=True, timeout=15,
                           env={**self.env, **env})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "1▶")  # the delegation token is the script's only output
        return p

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def writes(self):
        return sorted(c for c in self.calls() if c.startswith("tmux set-option"))

    def queried(self):
        return any(c.startswith("claude agents") for c in self.calls())

    def run_file(self, kind):
        return os.path.join(self.run_dir, f".tmux-claude-status.{os.getuid()}.{kind}")

    @staticmethod
    def read(path):
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read()

    def tabs(self):
        return self.read(os.path.join(self.state, "dotclaude", "tabs"))

    @staticmethod
    def session(pid, cwd, kind="interactive", status="busy", sid=None):
        return {"pid": pid, "cwd": cwd, "kind": kind, "status": status,
                "sessionId": sid or f"sid-{pid}"}

    def bg(self, status="busy", sid="bg-1", cwd=DNA, pid=9999):
        return self.session(pid, cwd, kind="background", status=status, sid=sid)

    # --- the directory mapping ------------------------------------------------------------

    def test_one_client_in_the_session_dir_is_mapped_and_filled(self):
        tab = self.pane("%0", "@0", "/home/u/code/other", state="busy")
        self.pane("%2", "@2", DNA)
        self.run_status([self.session(tab, "/home/u/code/other"), self.bg()])
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))
        self.assertEqual(self.writes(), ["tmux set-option -w -t @2 @claude_state busy"])

    def test_a_cwd_with_spaces_maps(self):
        self.pane("%2", "@2", "/home/u/my code/dna")
        self.run_status([self.bg(cwd="/home/u/my code/dna")])
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))

    def test_an_interactive_session_pane_is_never_a_client(self):
        tab = self.pane("%0", "@0", DNA, state="idle")
        self.run_status([self.session(tab, DNA, status="idle"), self.bg()])
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), [])

    def test_only_interactive_rows_are_attributed_by_ancestry(self):
        # A row of another kind may descend from the daemon, so from its first client's pane.
        child = self.pane("%2", "@2", DNA)
        self.run_status([self.session(child, DNA, kind="print", status="busy"), self.bg()])
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))

    def test_two_clients_in_one_dir_map_nothing(self):
        self.pane("%2", "@2", DNA, state="idle")
        self.pane("%3", "@3", DNA, state="idle")
        self.run_status([self.bg()])
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), [])

    def test_two_background_sessions_in_one_dir_map_nothing(self):
        self.pane("%2", "@2", DNA, state="idle")
        self.run_status([self.bg(sid="bg-1", pid=9998), self.bg(sid="bg-2")])
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), [])

    def test_a_stopped_background_session_is_not_mapped(self):
        # A listed session without a pid isn't running.
        self.pane("%2", "@2", DNA, state="idle")
        self.run_status([self.bg(pid=None)])
        self.assertEqual(self.tabs(), mapped())

    def test_a_mapping_survives_a_second_client_appearing(self):
        # A claude just started in the same dir isn't listed yet, so it looks like a client.
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "wait"
        self.pane("%3", "@3", DNA, state="idle")
        self.run_status([self.bg()])
        self.assertTrue(self.queried())
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))
        self.assertEqual(self.writes(), [])

    def test_a_second_background_session_in_the_dir_drops_the_mapping(self):
        # The client may now show either one: map neither, and hand the window back.
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "busy"
        self.run_status([self.bg(), self.bg(sid="bg-2", pid=9998)], hosts="501 503")
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), ["tmux set-option -uw -t @2 @claude_state"])

    def test_a_kept_mapping_is_refilled_after_the_map_went_stale(self):
        # Hooks ignore a map older than 90 s (tmux detached, or queries failing), so the
        # session's window missed its writes meanwhile: the next remap fills it again.
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "busy"
        old = time.time() - 100
        os.utime(os.path.join(self.state, "dotclaude", "tabs"), (old, old))
        os.utime(self.run_file("sig"), (old, old))
        self.run_status([self.bg(status="idle")])
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))
        self.assertEqual(self.writes(), ["tmux set-option -w -t @2 @claude_state idle"])

    def test_a_kept_mapping_is_not_refilled(self):
        # Once mapped, the session's own hooks own the window: the script doesn't overwrite.
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "wait"
        self.run_status([self.bg()], hosts="501 503")  # a host change forces a new query
        self.assertTrue(self.queried())
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))
        self.assertEqual(self.writes(), [])

    def test_a_mapped_pane_moved_to_a_cold_window_gets_the_session_state(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg(status="waiting")])
        pid = self.panes[0][2]
        self.panes = [("%2", "@7", pid, "claude", DNA)]  # break-pane: same pane, new window
        self.windows = {"@7": ""}
        self.run_status([self.bg(status="waiting")])
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @7"))
        self.assertEqual(self.writes(), ["tmux set-option -w -t @7 @claude_state wait"])

    def test_a_vanished_mapping_clears_its_window(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "busy"
        self.run_status([], hosts="502 503")
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), ["tmux set-option -uw -t @2 @claude_state"])

    def test_a_closed_mapped_pane_hands_its_window_back_to_the_split_session(self):
        # The window keeps a claude (an interactive split), so the plain clear skips it: it
        # takes that session's state instead of keeping the background session's glyph.
        tab = self.pane("%6", "@2", "/x", state="")
        self.pane("%2", "@2", DNA)
        agents = [self.session(tab, "/x", status="idle"), self.bg()]
        self.run_status(agents)
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))
        self.windows["@2"] = "busy"
        self.panes = [p for p in self.panes if p[0] != "%2"]
        self.run_status(agents)
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), ["tmux set-option -w -t @2 @claude_state idle"])

    def test_no_pty_host_means_no_query_and_an_empty_map(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "busy"
        self.run_status([], hosts="")
        self.assertFalse(self.queried())
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), ["tmux set-option -uw -t @2 @claude_state"])

    def write_tabs(self, text):
        os.makedirs(os.path.join(self.state, "dotclaude"), exist_ok=True)
        with open(os.path.join(self.state, "dotclaude", "tabs"), "w") as f:
            f.write(text)

    def test_a_map_from_another_tmux_server_is_replaced_not_trusted(self):
        # Ids restart on a new server: the old map's %5/@5 may now be an unrelated tab.
        self.pane("%5", "@5", "/x", state="busy")
        self.write_tabs(mapped("old-sid %5 @5", server="1111"))
        self.run_status([], hosts="501")
        self.assertEqual(self.tabs(), mapped())
        self.assertEqual(self.writes(), [])

    def test_a_map_not_from_this_server_forces_a_remap(self):
        # Same panes and hosts within 60 s, so the sig alone wouldn't requery.
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.windows["@2"] = "busy"
        os.remove(os.path.join(self.state, "dotclaude", "tabs"))
        self.run_status([self.bg()])
        self.assertTrue(self.queried())
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))

    def test_an_empty_tmux_answer_leaves_the_map_alone(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        before = self.tabs()
        self.panes, self.windows = [], {}
        self.run_status([self.bg()], hosts="501 503")
        self.assertEqual(self.tabs(), before)
        self.assertFalse(self.queried())

    # --- the query gate -------------------------------------------------------------------

    def test_an_unchanged_signature_does_not_query_again(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        self.assertTrue(self.queried())
        self.windows["@2"] = "busy"
        self.run_status([self.bg()])
        self.assertFalse(self.queried())

    def test_a_new_pty_host_queries_again(self):
        # A new background session claims a pre-warmed host and the daemon warms a new one.
        self.pane("%2", "@2", DNA, state="idle")
        self.run_status([], hosts="501")
        self.run_status([self.bg()], hosts="501 502")
        self.assertTrue(self.queried())
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))

    def test_a_stale_signature_queries_again(self):
        self.pane("%2", "@2", DNA, state="idle")
        self.run_status([])
        old = time.time() - 61
        os.utime(self.run_file("sig"), (old, old))
        self.run_status([self.bg()])
        self.assertTrue(self.queried())
        self.assertEqual(self.tabs(), mapped("bg-1 %2 @2"))

    def test_the_rate_limit_repeats_the_cached_token(self):
        self.pane("%2", "@2", DNA, state="idle")
        self.run_status([])
        os.remove(self.log)
        p = subprocess.run(["bash", SCRIPT], capture_output=True, text=True, timeout=15,
                           env=self.env)
        self.assertEqual(p.stdout, "1▶")
        self.assertEqual(self.calls(), [])

    def test_a_failed_query_changes_nothing_and_backs_off(self):
        self.pane("%2", "@2", DNA)
        self.run_status([self.bg()])
        before, sig = self.tabs(), self.read(self.run_file("sig"))
        self.windows["@2"] = "busy"
        for raw in ("not json", ""):
            with self.subTest(raw=raw):
                if os.path.exists(self.run_file("fail")):
                    os.remove(self.run_file("fail"))
                self.run_status(None, hosts="501 509", raw=raw)
                self.assertTrue(self.queried())
                self.assertEqual(self.tabs(), before)
                self.assertEqual(self.read(self.run_file("sig")), sig)
                self.assertEqual(self.writes(), [])
                self.run_status([self.bg()], hosts="501 509")
                self.assertFalse(self.queried())  # backing off
        # The backoff stays under the 30 s between the 60 s refresh and the hooks' 90 s limit.
        old = time.time() - 21
        os.utime(self.run_file("fail"), (old, old))
        self.run_status([self.bg()], hosts="501 509")
        self.assertTrue(self.queried())

    def test_a_hung_query_times_out(self):
        self.pane("%2", "@2", DNA)
        start = time.time()
        self.run_status([self.bg()], STUB_HANG="1")
        self.assertLess(time.time() - start, 8)
        self.assertIsNone(self.tabs())

    # --- the cold fill and the clear -------------------------------------------------------

    def test_a_cold_tab_is_filled_from_its_session(self):
        tab = self.pane("%0", "@0", "/x")
        self.run_status([self.session(tab, "/x", status="blocked")], hosts="")
        self.assertEqual(self.writes(), ["tmux set-option -w -t @0 @claude_state wait"])

    def test_a_background_session_never_fills_by_ancestry(self):
        # The daemon descends from the first client that needed it, so a background session's
        # ancestry reaches that client's pane even though another tab shows it.
        first_client = self.pane("%0", "@0", "/x")
        self.run_status([self.bg(pid=first_client)], hosts="")
        self.assertNotIn("tmux set-option -w -t @0 @claude_state busy", self.writes())

    def test_an_unattributed_claude_window_is_filled_idle_once(self):
        # Otherwise every run would re-query for a window nothing can fill.
        self.pane("%2", "@2", "/nowhere")
        self.run_status([], hosts="")
        self.assertEqual(self.writes(), ["tmux set-option -w -t @2 @claude_state idle"])

    def test_a_window_without_claude_is_cleared(self):
        self.pane("%4", "@4", "/x", state="busy", command="zsh")
        self.run_status([], hosts="")
        self.assertEqual(self.writes(), ["tmux set-option -uw -t @4 @claude_state"])
        self.assertFalse(self.queried())


if __name__ == "__main__":
    unittest.main()
