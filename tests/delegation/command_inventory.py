"""The excludedCommands inventory: every command that runs outside the sandbox, why it does, the
calls each entry must cover, and the rules that make the raw primitives ask. test_settings.py
ties settings.json to it in both directions, so neither can change alone.

The rules it encodes:
- A. An excluded command runs outside the sandbox, so what it runs comes from the command text the
  permission gate sees, or from a file the sandbox can't write.
- B. An excluded command takes ids and data, never code. A flag that names a program or a command
  to run asks, and so does one that widens what the call may reach or turns off a guard.
- D. Asks cover raw primitives only, rare enough that each prompt gets read. The calls skills
  tell Claude to make (the wrappers, read-only tmux, `claude -p`) ask nothing.

An ask beats an allow, and a rule can't say "ask on all but X", so the excluded list is the
allowlist of what runs outside and the asks name the raw verbs and flags. A call that matches no
excluded entry runs sandboxed, where tmux reaches no socket and codex no credential, so it fails
closed. A spelling a glob can't anchor (a quoted verb, a global flag before a claude subcommand)
stays with the auto-mode classifier."""
import os
import re
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))

# pattern: the excludedCommands entry. why: what needs the outside. samples: calls it must match.
Excluded = namedtuple("Excluded", "pattern why samples")
# rule: the permissions rule. why: what the call could do. samples: calls only this rule catches.
Rule = namedtuple("Rule", "rule why samples")

CREDENTIAL = "needs GitHub's credential, which the sandbox hides"
EXCLUDED = [
    # Only to origin: a push to a local path runs receive-pack, and that repo's hooks, outside
    # the sandbox. A flag-first push asks anyway (the baseline's `git push -*`).
    Excluded("git push", CREDENTIAL, ["git push"]),
    Excluded("git push origin", CREDENTIAL, ["git push origin"]),
    Excluded("git push origin *", CREDENTIAL, ["git push origin feat/x"]),
    Excluded("git push -*", CREDENTIAL, ["git push -u origin feat/x"]),
    Excluded("git fetch", CREDENTIAL, ["git fetch"]),
    Excluded("git fetch *", CREDENTIAL, ["git fetch origin"]),
    Excluded("git pull", CREDENTIAL, ["git pull"]),
    Excluded("git pull *", CREDENTIAL, ["git pull --ff-only"]),
    Excluded("git ls-remote *", CREDENTIAL, ["git ls-remote origin"]),
] + [
    # gh, by the families real use needs (Hayden, 2026-10-13). Any other gh form (gist, release
    # create or download, repo clone, keys, secrets, extensions, auth token) runs sandboxed, where
    # it can't read gh's credential, so it fails closed; Hayden runs those at his terminal.
    Excluded(p, CREDENTIAL, [s])
    for p, s in [
        ("gh pr *", "gh pr view 5"), ("gh run *", "gh run watch 5"),
        ("gh issue *", "gh issue view 5"), ("gh api *", "gh api repos/o/r/pulls"),
        ("gh search *", "gh search prs x"), ("gh repo view", "gh repo view"),
        ("gh repo view *", "gh repo view o/r --json name"), ("gh repo list", "gh repo list"),
        ("gh repo list *", "gh repo list o"), ("gh auth status", "gh auth status"),
        ("gh auth status *", "gh auth status --hostname github.com"),
        ("gh release list", "gh release list"), ("gh release list *", "gh release list -R o/r"),
        ("gh release view", "gh release view"), ("gh release view *", "gh release view v1"),
    ]
] + [
    Excluded("codex-delegate *", "starts codex in its own sandbox and needs codex's credential",
             ["codex-delegate run --model sol --dir /x --brief b.md", "codex-delegate status"]),
    Excluded("delegation-ledger *", "watches agent processes the sandbox can't see",
             ["delegation-ledger wait --pid 1", "delegation-ledger open"]),
    Excluded("lane init", "writes the lanes config in the state dir", ["lane init"]),
    Excluded("lane init *", "writes the lanes config in the state dir", ["lane init --cap 4"]),
    Excluded("lane new *", "fetches, asks gh for PR state, makes a worktree",
             ["lane new chart-fix --claim 42 --goal x"]),
    Excluded("lane adopt *", "registers a worktree in the state dir", ["lane adopt ../x"]),
    Excluded("lane ls", "asks gh for PR state and sees other sessions", ["lane ls"]),
    Excluded("lane ls *", "asks gh for PR state and sees other sessions", ["lane ls --json"]),
    Excluded("lane open *", "opens a tmux window and sees other sessions",
             ["lane open chart-fix", "lane open chart-fix --print"]),
    Excluded("lane done *", "checks the merge with gh, sees and signals the lane's sessions",
             ["lane done chart-fix"]),
    Excluded("pass-respawn", "respawns its tmux pane", ["pass-respawn"]),
    Excluded("pass-respawn *", "respawns its tmux pane", ["pass-respawn -C /x --compact"]),
] + [
    # Read-only tmux, anchored on the verb, in the spellings real use shows. A global flag
    # (-L, -S, -f, -c) or any other verb or alias matches nothing here, so it runs sandboxed,
    # where tmux reaches no socket.
    Excluded(p, "reads the tmux server through its socket, which the sandbox blocks", [s])
    for p, s in [
        ("tmux ls", "tmux ls"), ("tmux ls *", "tmux ls -F x"),
        ("tmux list-sessions", "tmux list-sessions"),
        ("tmux list-sessions *", "tmux list-sessions -F x"),
        ("tmux list-windows *", "tmux list-windows -a"),
        ("tmux list-panes *", "tmux list-panes -a -F '#{pane_id}'"),
        ("tmux list-clients", "tmux list-clients"),
        ("tmux list-clients *", "tmux list-clients -F x"),
        ("tmux list-keys", "tmux list-keys"), ("tmux list-keys *", "tmux list-keys -T root"),
        ("tmux list-commands", "tmux list-commands"),
        ("tmux capture-pane *", "tmux capture-pane -p -t %3"),
        ("tmux display *", "tmux display -p '#{pane_id}'"),
        ("tmux show *", "tmux show -gv @x"),
        ("tmux show-options *", "tmux show-options -g"),
        ("tmux show-environment *", "tmux show-environment -g"),
        ("tmux show-messages", "tmux show-messages"),
        ("tmux show-messages *", "tmux show-messages -J"),
        ("tmux show-hooks *", "tmux show-hooks -g"),
    ]
] + [
    Excluded("claude *", "runs Claude Code, which needs its credential and the user's config",
             ["claude -p --model sonnet", "claude plugin validate skills/autopass"]),
] + [
    # Only read-only codex, as exact forms (no arguments). Raw `codex exec` runs sandboxed and
    # can't reach codex's credential; codex-delegate is the sanctioned path.
    Excluded(p, "reads codex's credential or config, which the sandbox hides", [p])
    for p in ("codex login status", "codex doctor", "codex debug models", "codex features list",
              "codex mcp list", "codex plugin list")
] + [
    Excluded("powershell.exe *", "Windows programs need WSL's interop socket, which the sandbox "
             "blocks", ["powershell.exe -NoProfile -Command Get-Date"]),
    Excluded("cmd.exe *", "Windows programs need WSL's interop socket, which the sandbox blocks",
             ["cmd.exe /c ver"]),
]

# Calls that must match no excluded entry: they run sandboxed and fail closed (or, for the lane
# subcommands, must stay sandboxed so the command `lane lock` wraps inherits the sandbox).
SANDBOXED = ["tmux -L x ls", "tmux send-keys -t %1 x", "tmux lsp", "tmux display-message -p x",
             "tmux -V", "FOO=1 tmux ls", "codex exec x", "codex --version", "codex mcp add x",
             "codex login", "lane lock gate -- true", "lane whoami", "lane claim 42",
             "git clone x", "git -C . fetch", "git -c k=v fetch", "claude-alt -p x",
             "git push ../r feat", "git push /tmp/r feat", "git push upstream feat",
             "gh gist create f", "gh gist new f", "gh release download v1 -O x",
             "gh repo clone o/r d", "gh auth token", "gh cs cp f r:f", "gh --version",
             "gh extension install o/r", "gh secret set X -f e"]

# --- tmux -----------------------------------------------------------------------------------------

TMUX_VERSION = "tmux 3.7c"
TMUX_SNAPSHOT = os.path.join(HERE, "tmux-3.7c-list-commands.txt")  # `tmux list-commands`, 3.7c
TMUX_READ_ONLY = {"capture-pane", "display-message", "has-session", "list-buffers",
                  "list-clients", "list-commands", "list-keys", "list-panes", "list-sessions",
                  "list-windows", "show-buffer", "show-environment", "show-hooks",
                  "show-messages", "show-options", "show-prompt-history", "show-window-options"}

# tmux's default `command-alias` server option (options-table.c), expanded before the table lookup.
TMUX_DEFAULT_ALIASES = {"split-pane": "split-window", "splitp": "split-window",
                        "server-info": "show-messages", "info": "show-messages",
                        "choose-window": "choose-tree", "choose-session": "choose-tree"}


def tmux_table(text=None):
    """[(name, alias or None)] from `tmux list-commands` output (the snapshot by default)."""
    if text is None:
        with open(TMUX_SNAPSHOT) as f:
            text = f.read()
    return [re.match(r"(\S+)(?: \((\S+)\))?", line).groups() for line in text.splitlines()]


def tmux_spellings(name, table=None):
    """Every verb tmux resolves to this command: its alias, and each prefix of its name from the
    shortest unique one (tmux takes any unambiguous prefix, and an exact alias wins)."""
    table = table or tmux_table()
    names = [n for n, _ in table]
    others = {a for n, a in table if a and n != name}
    short = next(name[:i] for i in range(1, len(name) + 1)
                 if sum(n.startswith(name[:i]) for n in names) == 1 and name[:i] not in others)
    alias = [a for n, a in table if n == name and a]
    return {name[:i] for i in range(len(short), len(name) + 1)} | set(alias)


def tmux_resolve(verb, table=None):
    """The command tmux runs for a verb, or None when it is unknown or ambiguous."""
    table = table or tmux_table()
    hits = [n for n, _ in table if verb in tmux_spellings(n, table)]
    return hits[0] if len(hits) == 1 else None


def tmux_prefix_asks(table=None):
    """The shortest prefixes that cover every spelling of every command that isn't read-only
    without starting any read-only spelling (`tmux n*` covers new-*, next-* and their aliases)."""
    table = table or tmux_table()
    ro = set().union(*(tmux_spellings(n, table) for n, _ in table if n in TMUX_READ_ONLY))
    cover = set()
    for n, _ in table:
        if n in TMUX_READ_ONLY:
            continue
        for s in tmux_spellings(n, table):
            cover.add(next(s[:i] for i in range(1, len(s) + 1)
                           if not any(r.startswith(s[:i]) for r in ro)))
    return sorted(p for p in cover if not any(q != p and p.startswith(q) for q in cover))


TMUX_RULES = [
    Rule("Bash(tmux)", "a bare tmux starts a session", ["tmux"]),
    Rule("Bash(tmux -*)", "a global flag picks another server, config file or shell",
         ["tmux -L x ls", "tmux -Lx"]),
    Rule("Bash(tmux *;*)", "a ; starts a second tmux command after any verb",
         ["tmux display -p x \\; set -g @x 1"]),
    Rule("Bash(tmux *#(*)", "#( is a format's job syntax", ["tmux display -p '#(id)'"]),
    # E: and T: expand a value as a format, so a #( job the value holds would run; any other
    # value-expanding spelling needs a ; between modifiers, which asks above. The globs stop
    # before the colon (a rule ending in :* is the legacy prefix form); no format variable
    # starts with a capital E or T.
    Rule("Bash(tmux *{E*)", "expands a value as a format", ["tmux display -p '#{E:pane_title}'"]),
    Rule("Bash(tmux *{T*)", "expands a value as a format", ["tmux display -p '#{T:pane_title}'"]),
    # Also a false prompt when a target or text after a dash holds a capital I: rare, and safe.
    Rule("Bash(tmux display* -*I*)", "display -I types its input into a pane",
         ["tmux display -I -t %1", "tmux display -pI -t %1"]),
] + [
    Rule(f"Bash(tmux {p}*)", "a tmux command that changes the server, a pane or a client",
         [f"tmux {p}"])
    for p in tmux_prefix_asks()
]

# --- claude ---------------------------------------------------------------------------------------

# Every long flag `claude --help` and `claude agents --help` list, by what it does to the call.
# "ask": it turns off a guard, widens what the session may reach, loads config, code or tools from
# elsewhere, writes a file at a chosen path, or moves the session off this machine.
CLAUDE_FLAG_ASKS = {
    "--dangerously-skip-permissions": "*dangerously-skip-permissions*",
    "--allow-dangerously-skip-permissions": "*dangerously-skip-permissions*",
    "--permission-mode": None,  # only its bypassPermissions and acceptEdits values ask
    "--settings": "*--setting*", "--setting-sources": "*--setting*",
    "--allowedTools": "*--allowedTools*", "--allowed-tools": "*--allowed-tools*",
    "--add-dir": "*--add-dir*", "--agents": "*--agents*", "--mcp-config": "*--mcp-config*",
    "--plugin-dir": "*--plugin-dir*", "--plugin-url": "*--plugin-url*", "--bare": "*--bare*",
    "--safe-mode": "*--safe-mode*", "--debug-file": "*--debug-file*", "--file": "*--file*",
    "--chrome": "*--chrome*", "--cloud": "*--cloud*", "--environment": "*--environment*",
    "--remote-control": "*--remote-control*",
    "--remote-control-session-name-prefix": "*--remote-control*",
    "--teleport": "*--teleport*",
    # Accepted but not in --help (2.1.296): found by a scan of the binary's strings, each
    # checked with `claude -p <flag> X --bogus` (an unknown flag errors before anything runs).
    # A later hidden flag stays with the classifier until it lands here.
    "--permission-prompt-tool": "*--permission-prompt-tool*",
    "--dangerously-load-development-channels": "*--dangerously-load*",
    "--enable-auto-mode": "*--enable-auto-mode*",
    "--inherit-permission-mode": "*--inherit-permission-mode*",
    "--managed-settings": "*--managed-settings*",
    "--forward-home-settings": "*--forward-home-settings*",
    "--project-config-root": "*--project-config-root*",
    "--plugin-dir-no-mcp": "*--plugin-dir*",
    "--system-prompt-file": "*-prompt-file*", "--append-system-prompt-file": "*-prompt-file*",
    "--append-subagent-system-prompt-file": "*-prompt-file*",
    "--channels": "*--channels*", "--rewind-files": "*--rewind-files*",
    "--sdk-url": "*--sdk-url*", "--session-mirror": "*--session-mirror*",
    "--messaging-socket-path": "*--messaging-socket*",
}
CLAUDE_HIDDEN_OK = {
    "--advisor", "--agent-color", "--agent-id", "--agent-name", "--agent-type",
    "--append-subagent-system-prompt", "--attach-serve", "--await-claim", "--await-initialize",
    "--debug-to-stderr", "--deep-link-origin", "--deep-link-repo", "--init", "--init-only",
    "--maintenance", "--max-thinking-tokens", "--max-turns", "--parent-session-id",
    "--plan-mode-instructions", "--prefill", "--proactivity", "--reply-on-resume",
    "--resume-drops-turn", "--resume-session-at", "--task-budget", "--team-name",
    "--teammate-mode", "--thinking", "--thinking-display", "--watch-artifact",
    "--watch-artifact-no-autoreact", "--workload",
}
CLAUDE_FLAG_OK = {
    "--agent", "--all", "--append-system-prompt", "--autocompact", "--ax-screen-reader", "--bg",
    "--background", "--betas", "--brief", "--continue", "--cwd", "--debug", "--desktop",
    "--disable-slash-commands", "--disallowedTools", "--disallowed-tools", "--effort",
    "--exclude-dynamic-system-prompt-sections", "--fallback-model", "--fork-session",
    "--forward-subagent-text", "--from-pr", "--help", "--ide", "--include-hook-events",
    "--include-partial-messages", "--input-format", "--json", "--json-schema", "--max-budget-usd",
    "--model", "--name", "--no-chrome", "--no-session-persistence", "--output-format",
    "--permission-prompts", "--print", "--prompt-suggestions", "--replay-user-messages",
    "--restricted", "--resume", "--session-id", "--strict-mcp-config", "--system-prompt",
    "--system-prompt-snapshot", "--tmux", "--tools", "--verbose", "--version", "--worktree",
    # The options of the "ok" leaf subcommands below.
    "--available", "--data-size", "--label", "--strict", "--text",
}
# Short aliases, by their long flag. None may stand for an ask-class flag: a glob can't anchor
# `-x` safely, so a new one fails the live check until it gets a rule.
CLAUDE_SHORT_FLAGS = {"-c": "--continue", "-d": "--debug", "-h": "--help", "-n": "--name",
                      "-p": "--print", "-r": "--resume", "-v": "--version", "-w": "--worktree"}
# Leaf options that ask through a rule of their own, anchored on the leaf.
CLAUDE_LEAF_FLAG_ASKS = {"--values-stdin": "Bash(claude plugin* configure *--values-stdin*)"}
# Every subcommand the group helps list ("|" joins an alias), as "ask", "deny" or "ok".
CLAUDE_COMMANDS = {
    (): {"agents": "ok", "attach": "ok", "auth": "group", "auto-mode": "group", "doctor": "ok",
         "gateway": "ask", "import": "ask", "install": "ask", "logs": "ok", "mcp": "group",
         "plugin|plugins": "group", "purge": "ask", "respawn": "ask", "rm": "ask",
         "setup-token": "ask", "stop|kill": "ask", "ultrareview": "deny",
         "update|upgrade": "ask"},
    ("auth",): {"help": "ok", "login": "ask", "logout": "ask", "status": "ok"},
    ("auto-mode",): {"config": "ok", "critique": "ok", "defaults": "ok", "help": "ok",
                     "reset": "ask"},
    ("mcp",): {"add": "ask", "add-from-claude-desktop": "ask", "add-json": "ask", "get": "ok",
               "help": "ok", "list": "ok", "login": "ask", "logout": "ask", "remove": "ask",
               "reset-project-choices": "ask", "serve": "ask"},
    ("plugin",): {"configure": "ok", "details": "ok", "disable": "ask", "enable": "ask",
                  "eval": "ask", "help": "ok", "init|new": "ask", "install|i": "ask",
                  "list": "ok", "marketplace": "ask", "prune|autoremove": "ask", "tag": "ask",
                  "test": "ask", "uninstall|remove": "ask", "update": "ask", "validate": "ok"},
    ("sandbox",): {"help": "ok", "install": "ask", "status": "ok"},  # a hidden group
}

CLAUDE_RULES = [
    Rule(f"Bash(claude {glob})", "a flag that loosens the call (CLAUDE_FLAG_ASKS)",
         [f"claude -p {flag} x" for flag, g in CLAUDE_FLAG_ASKS.items() if g == glob])
    for glob in dict.fromkeys(g for g in CLAUDE_FLAG_ASKS.values() if g)
] + [
    Rule("Bash(claude *bypassPermissions*)", "a permission mode that skips every check",
         ["claude -p --permission-mode bypassPermissions"]),
    Rule("Bash(claude *acceptEdits*)", "a permission mode that skips edit prompts",
         ["claude -p --permission-mode acceptEdits"]),
    Rule("Bash(claude *permission-mode*auto*)", "lets the classifier approve what -p would deny",
         ["claude -p --permission-mode auto", "claude -p --permission-mode=auto"]),
    Rule("Bash(claude plugin* configure *--values-stdin*)", "saves a plugin's option values",
         ["claude plugin configure x --values-stdin"]),
] + [
    # Anchored on the subcommand, so prompt text can't trip them. `plugin*` covers `plugins`.
    Rule(f"Bash(claude {sub}*)", "changes Claude Code's install, config, auth or sessions",
         [f"claude {sub} x"])
    for sub in ("gateway", "import", "install", "purge", "respawn", "rm", "setup-token", "stop",
                "kill", "update", "upgrade", "auth login", "auth logout", "auto-mode reset",
                "mcp add", "mcp login", "mcp logout", "mcp remove", "mcp reset-project-choices",
                "mcp serve", "sandbox install")
] + [
    # "i " is install's alias; its space keeps it off words that start with i.
    Rule(f"Bash(claude plugin* {sub}*)", "installs, removes or changes plugins",
         [f"claude plugin {sub.strip()} x"])
    for sub in ("disable", "enable", "init", "new", "install", "i ", "marketplace", "prune",
                "autoremove", "tag", "uninstall", "remove", "update")
] + [
    # Like --plugin-dir: the path is in the command text, but the code under it is whatever the
    # sandbox wrote there (Hayden, 2026-10-13).
    Rule("Bash(claude plugin* test*)", "runs a mod's test files from a chosen dir",
         ["claude plugin test skills/autopass"]),
    Rule("Bash(claude plugin* eval*)", "loads a plugin from a chosen path and starts claude runs",
         ["claude plugin eval skills/autopass"]),
]
CLAUDE_DENY = [Rule("Bash(claude *ultrareview*)", "a billed cloud review only Hayden starts",
                    ["claude ultrareview", "claude -p x ultrareview 5"])]

# --- git, gh, the wrappers, Windows ---------------------------------------------------------------

# git takes any unique prefix of a long option (`--upl` is --upload-pack), so each ask names the
# shortest unique prefix of a flag that names the program the remote end runs. A live test derives
# the prefixes from `git <verb> --git-completion-helper-all`.
GIT_PROGRAM_FLAGS = {"push": {"--receive-pack": "--rece", "--exec": "--e"},
                     "fetch": {"--upload-pack": "--upl"}, "pull": {"--upload-pack": "--upl"},
                     "ls-remote": {"--upload-pack": "--u", "--exec": "--exe"}}

OTHER_RULES = [
    Rule(f"Bash(git {verb} *{prefix}*)", "names the program the remote end runs",
         [f"git {verb} origin feat {flag}=x", f"git {verb} origin feat {prefix}=x"])
    for verb, flags in GIT_PROGRAM_FLAGS.items() for flag, prefix in flags.items()
] + [
    Rule("Bash(git ls-remote -u*)", "-u is --upload-pack", ["git ls-remote -u x origin"]),
    Rule("Bash(git ls-remote * -u*)", "-u is --upload-pack", ["git ls-remote origin -u x"]),
    Rule("Bash(gh auth status *-t*)", "prints the credential the sandbox hides",
         ["gh auth status -t", "gh auth status --show-token"]),
    Rule("Bash(gh auth status *-at*)", "-at bundles --active and --show-token",
         ["gh auth status -at"]),
    Rule("Bash(gh run download*)", "writes the run's artifacts to a chosen dir",
         ["gh run download 5 -D x"]),
] + [
    # In the excluded families gh still reads a file by path outside the sandbox, where denyRead
    # doesn't bind it, and sends it to GitHub, so each such flag asks (Hayden, 2026-10-13). A
    # bundle like `-dF` slips past a glob; Part 2's guard parses gh's arguments and replaces these
    # asks. A shell redirect needs no rule: it is opened in the sandbox.
    Rule(f"Bash(gh {glob})", "reads a local file and sends it to GitHub", [sample])
    for glob, sample in (
        ("*--body-file*", "gh pr edit 5 --body-file b.md"),
        ("*--input*", "gh api repos/o/r --input body.json"),
        ("* -F*", "gh api repos/o/r -F body=@f"),
        ("*--field*", "gh api repos/o/r --field body=@f"))
] + [
    Rule("Bash(lane init *--setup*)", "names the command each new lane runs",
         ["lane init --setup 'npm ci'"]),
    Rule("Bash(lane init *--root*)", "moves where lanes live", ["lane init --root ~/x-lanes"]),
    Rule("Bash(lane done *--abandon*)", "closes a lane with unmerged work",
         ["lane done chart-fix --abandon"]),
    Rule("Bash(codex-delegate *--network*)", "opens the network to the delegated codex",
         ["codex-delegate run --model sol --dir /x --brief b.md --network"]),
    Rule("Bash(codex-delegate *--no-scope*)", "turns off the memory cap",
         ["codex-delegate run --model sol --dir /x --brief b.md --no-scope"]),
    Rule("Bash(powershell.exe)", "a Windows shell", ["powershell.exe"]),
    Rule("Bash(powershell.exe *)", "a Windows shell", ["powershell.exe -NoProfile -Command x"]),
    Rule("Bash(cmd.exe)", "a Windows shell", ["cmd.exe"]),
    Rule("Bash(cmd.exe *)", "a Windows shell", ["cmd.exe /c ver"]),
]

ASKS = TMUX_RULES + CLAUDE_RULES + OTHER_RULES
DENIES = CLAUDE_DENY

# The hot path (rule D): calls skills and real use make, which must match an excluded entry and
# no ask or deny.
NO_ASK = ["lane ls", "lane ls --json", "lane open chart-fix", "lane open chart-fix --print",
          "lane new chart-fix --claim 42 --goal x", "lane done chart-fix", "lane init --cap 4",
          "lane adopt ../x", "pass-respawn -C /x --compact", "pass-respawn -C /x --print",
          "delegation-ledger wait --pid 1 --max 30", "delegation-ledger canary --quick",
          "codex-delegate run --model sol --dir /x --brief b.md", "tmux ls",
          "tmux list-panes -a -F '#{pane_id} #{pane_current_path}'",
          "tmux capture-pane -p -t %3", "tmux capture-pane -p -t @2 -S -50",
          "tmux display -p '#{pane_id}'", "tmux display -p -t %3 '#{window_id}'",
          "tmux show -gv @x", "tmux show-options -g", "tmux show-environment -g",
          "tmux show-messages", "tmux list-windows -a", "tmux list-keys -T root",
          "tmux list-clients", "claude --version", "claude --help", "claude -p --model sonnet",
          "claude agents --json", "claude plugin validate skills/autopass", "claude plugin list", "claude mcp list",
          "claude mcp get x", "claude sandbox status", "claude auth status",
          "claude --bg --model sonnet", "claude doctor", "claude logs x", "claude attach x",
          "claude -p --no-session-persistence",
          "codex login status", "codex doctor", "gh pr view 5", "gh auth status",
          "gh auth status --hostname github.com", "git push origin feat/x", "git fetch origin",
          "git ls-remote origin", "git pull --ff-only"]

# Skill commands that ask by design, each rare and run by a person's decision.
SKILL_ASKS = {"lane init --root": "moves where lanes live; the lead runs it once per repo",
              "claude stop": "ends a background session that lane done refuses to close"}
