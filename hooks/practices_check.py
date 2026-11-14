"""The practices hook engine; hooks/practices-check.sh runs it on PreToolUse(Edit|Write|MultiEdit),
PreToolUse(Bash), PostToolUse(Bash) and SessionStart. It enforces every installed practices skill
at the moment code is written, committed, pushed and put up for review.

Each practices skill ships an events.toml beside its SKILL.md:

  skill = "server-code"
  gate = ["<= 6 must-hold lines for the compaction digest"]
  [[event]]                 # L1
  id = "route-handler"
  paths = ["**/app/**/route.{ts,js}", "**/pages/api/**"]
  content = ['''^\\s*["']use server["']''']
  lines = ["3-6 lines for the deny"]
  [[rule]]                  # L2
  id = "SEC-17"
  when = '''regex'''
  unless = '''optional regex'''
  paths = ["optional globs"]
  at = ["edit", "commit"]   # optional: the levels it runs at, both by default
  scope = "line"            # optional: judged line by line (default "file")
  say = "one line"

Globs match the path relative to the project dir (POSIX; the absolute path for a file outside
it): `**` spans folders, `*` and `?` stay within one, `{a,b}` is alternation, and a glob with no
`/` matches the basename. Regexes are Python `re` with re.MULTILINE. Each call has two texts:
  new    what the call writes: Write `content`, Edit `new_string`, every MultiEdit `new_string`;
  after  the file as it will read after the call: Write `content`, or the current file (its
         first FILE_MAX bytes) with the Edit, or each MultiEdit edit in order, applied (the first
         occurrence, every one with `replace_all`). When the file can't be read or an old_string
         isn't in it, after is the new text alone, logged as `fragment-only` (not an engine
         error, so the health line doesn't count it).
An event fires when a glob matches the path or a content regex matches after, so an edit deep in
an existing "use server" file is still that event. A rule fires when `paths` (when given) match,
`when` matches new (only newly written code triggers), and neither `unless` nor an inline
`practices-allow: <id>` is in after (a guard elsewhere in the file counts). Scanned text is capped
at CONTENT_MAX characters and each line at LINE_MAX. The token `{auth_helpers}` inside a regex
expands to an alternation of AUTH_HELPERS plus the repo's `[auth] helpers`, each regex-escaped,
so SEC-01 can name a repo's own auth helper.

Skills are found in ${CLAUDE_CONFIG_DIR:-~/.claude}/skills/*/ and in <project>/.claude/skills/*/,
links followed. An edit, commit, push or PR call runs twice, installed skills first, and stops at the
first pass that speaks (two_passes): a project's patterns can throw or hang, and the call is allowed
when they do, but by then the installed skills have spoken. The project dir, for every level and the
startup health check alike, is CLAUDE_PROJECT_DIR, else the cwd recorded at the session's first
SessionStart, never the call's own cwd (a cd moves it); with neither, an edit is checked against
the user's skills alone with the default config, logged as project-unknown, and the L4 digest
reads the user's skills alone.

Levels:
  L1  an edit that fires a skill's event, when the window (the transcript since the last
      compaction, plus the messages that compaction preserved) shows no load of the skill: a
      Skill call naming it (`name` or `plugin:name`) or a Read of `<skill>/SKILL.md`, either
      with a tool_result (same tool_use_id) that isn't an error. Denied once
      per (skill, event) per window. The reason opens with `[practices:L1:<skill>:<event>]`, says
      how to load the skill, and carries the event's lines; one deny names every skill that fired.
  L2  a fired rule, denied once per (file, rule) over the whole transcript, marker
      `[practices:L2:<skill>:<rule>:<path>]`. `practices-allow: <rule>` anywhere in the file
      after the edit suppresses it. L2 doesn't run in a call L1 denies, nor for a rule whose
      `at` lacks "edit". A `scope = "line"` rule (a key shape) is judged per line of new: `when`,
      `unless` and the allow all on the one line, so an allow covers only its own line.
  L3s, push and L3r: the Bash levels, below.
  L4  SessionStart(compact): a digest (under DIGEST_MAX characters, shared among the skills
      and cut only between lines) naming the practices skills loaded since the previous
      compaction, with their gate lines, plus reloadSkills: true.
Deny-once has two signs, and either lets the call through (an edit level denies only when
one can hold: with an unwritable state dir and an empty or missing transcript, the edit is
allowed, logged as state-error):
  - a tool_result in the window holding the call's own marker. The marker is this engine's own
    text, never Claude Code's "hook error" wording around it, which a release may reword;
    is_error isn't required either, so a stray marker elsewhere costs at most one missed deny;
  - a key in the state file under $XDG_STATE_HOME/dotclaude/practices/denies/ (one file per
    session and agent), written on every deny: L1 keyed by the newest compaction boundary's id
    (or "none") and the skill and event, L2 by the rule and the file. It is the backstop when the
    marker can't be seen: a release that moves the reason out of the tool_result, an agent
    transcript that is empty or missing.

Compaction boundary (2.1.304, a real /compact): a `type: system`, `subtype: compact_boundary`
row, whose compactMetadata.preservedMessages lists uuids of earlier rows kept in context (each
found by its own `"uuid":"<id>"`, searched back from the boundary), then an isCompactSummary
user row. At SessionStart(compact) the new boundary may or may not be on disk
yet: when no assistant row follows the newest boundary it is this compaction's, and the digest
reads back to the one before it; otherwise the digest reads the L1 window.

Subagents: a payload with agent_id carries the parent's transcript_path, so every transcript read
uses <transcript_path minus .jsonl>/subagents/agent-<agent_id>.jsonl, and its sidechain rows.
When that file is missing or empty, the state file alone carries deny-once.

Per repo, <project>/.claude/practices/config.toml: `[auth] helpers = [...]` feeds
`{auth_helpers}`, identifier names only (dotted allowed, like `auth.requireUser`; an empty or
blank name would match any call), others dropped and logged. A malformed file falls back to the
defaults (never turning a check off) and is logged.

Turning the gate off isn't the repo's call, since a session can write its own repo. bin/practices-gate,
run by hand, writes ~/.local/state/dotclaude/practices-off.json: dated entries that turn the engine
off, or one rule off (an event or rule id, or `<skill>:<id>`) with a reason, at and below a dir. Its
home comes from the passwd entry and no environment variable moves it. A repo's own `enabled` and
`[[disable]]` are ignored and logged. A file that is malformed, a link, not a regular file, not the
user's own or writable by others is ignored whole, so the gate stays on, and it is logged. Each
session start names what is off for its project.

A project skill can't replace an installed skill of the same name: every installed rule applies and
the project copy adds only ids the installed skill lacks, in the second pass. Each session start names
the clash and tells the model to compare the two copies and propose what to do.

Failure posture (allow and loud): a BUDGET-second run budget on time.monotonic(); patterns left
when it is spent are skipped and logged, and a transcript read checks it on every row it parses
(once spent, the call is allowed and that is logged). A pattern that throws is skipped and
logged; a malformed events.toml disables that skill only, logged. Any crash allows the call (no
output) and is logged to $XDG_STATE_HOME/dotclaude/practices/errors.log (size-capped). Before
each pattern, each transcript read (level "transcript") and a Bash command's parse (level
"bash", which also checks the budget before each substitution body), a breadcrumb (file, level,
pattern) is written under the state dir and removed on a normal exit; Claude Code's
timeout kill takes the whole process group, so a killed scan leaves it behind. SessionStart
(startup) runs a self-test, reports leftover breadcrumbs and the errors logged since the last
start, as one systemMessage line (shown to the user only), and prints nothing when all is well.

Bash levels. settings.json sends a Bash call here only when its command (the payload's
"command" string, never the tool_response output) holds git with commit or push, gh with pr
ready or pr create, or a package manager with an add verb (PostToolUse: git with commit), so
Python never starts for any other call.
The prefilter is one `LC_ALL=C grep -E`, linear in the payload (a bash `case` glob backtracked
over every "git" in a large output). Every practices entry in settings.json (edit, Bash and
SessionStart) runs the shim only when it exists and then exits 0; a deny is JSON on stdout.
hooks/bash_words.py reads the command as simple commands through chains, wrappers (`sudo -E`,
`env -i`, `time -p`; `env -C` and `sudo -D` move that command's cwd), `cd X &&`, `pushd` and
`popd` (from the payload's cwd; a cd inside `( ... )` ends with it), quotes and heredocs, the body of each
$(...), backtick, <(...) and >(...) (from the cwd where it sits), a `bash -c` script with no
expansion in it, and each git call's -C, --git-dir, --work-tree and GIT_DIR=; an expansion in
one of those skips that call, logged. When what the parser left unread names a commit, push,
pr ready or pr create, word by word, it is logged as git-skipped (one line, no command text),
whatever else the command read: the arguments of any command but a git commit, push or grep, a
gh pr ready or create, and grep or rg (`xargs git push`, `find -exec`, `git submodule foreach`,
a `bash -c` script with an expansion), a heredoc body a shell runs (`bash <<EOF`, `cat <<EOF |
sh`; not `cat > f <<EOF`), and a substitution body or script that won't parse (a shlex error,
nesting past NEST_MAX), while the rest of the command is still read. A command whose top level
won't parse is logged as git-skipped when it names a call, else as the quiet bash-unparsed; so
is one over CMD_MAX characters, which isn't parsed at all (else allowed with no log), so a long
command never runs the parse into the 5 s kill.
Accepted limits beyond those logs: `eval`, an alias, a function or a script file
that runs git with nothing naming it in the command; a command inside an unquoted heredoc's
$(...); a function body's cd, read as if it ran. A file written by a heredoc or `cat >`
escapes L1 and L2, and L3s is its backstop.
A repo is read only inside Bounds: git runs only in (or pointed at) the project dir
(CLAUDE_PROJECT_DIR, else the cwd recorded at the session's first SessionStart, never the call's
own cwd; the Bash levels read config.toml and the project skills from it too, so a cd moves
neither) or the project's own repo, and a repo is scanned only when the realpaths of its git
dir, common dir and every alternates entry sit there too. The project's own repo is the one its
checkout holds, a linked worktree (a lane) only when its git dir's `gitdir` file links back to
the project, so a lane reads its main checkout's .git while `git -C ~/vault`, a planted gitfile
or an alternates entry outside is skipped and logged, with no path or content in the log.
Each level reads commits, never the index or the working tree:
  L3s   PreToolUse on a git commit records each repo's git dir, worktree and HEAD (heads/, keyed
        by session, agent and tool_use_id); PostToolUse for that id scans recorded..HEAD in
        those repos (never a re-parse from its own cwd, which a `cd` in the command moved; no
        record, nothing scanned, logged) and tells the model the findings as additionalContext.
  push  PreToolUse on git push scans what it would send (each refspec's source, else HEAD;
        --all, --branches, --mirror: every local branch) less what any remote has, and denies.
        A delete (--delete, -d, `:ref`) and a dry run (--dry-run, -n) pass, logged as
        push-unscanned; in a short-option cluster -o takes the rest as its value
        (`-onodeploy`). A source that names no commit here (a glob refspec) is logged as
        git-skipped, and the rest are still scanned. One call holding both a commit and a push
        is denied once, told to run them as separate calls (the scan can't see a commit not
        yet made); its resend passes that check, and the push gate still scans the commits
        already made, as for any push.
  L3r   PreToolUse on gh pr ready (not --undo) or a gh pr create without --draft (a -R or
        --repo before the pr subcommand dropped first), judged at a
        head: the branch a `ready` selector or create's --head names (origin/<branch>, else the
        local branch; unknown: logged, allowed), else the checked-out HEAD (a PR number or URL
        says so in the deny, since it may be another branch's PR); each choice is logged. The
        files changed since the merge base with --base, else origin/HEAD, origin/main,
        origin/master (none: logged, allowed), are matched against every skill's L1 events
        (paths, and content on either end of each change, so code a PR takes away counts).
        Denied once per touched skill and head unless
        the transcript (or the parent's, for a subagent) holds an Agent or Task call whose
        prompt has that head's marker, `[practices:review:<sha12>]`, so a review clears only
        the commit it judged; the reason carries each skill's gate lines and the marker in one
        block to paste into a reviewer brief. A marker on a commit the head descends from
        carries over: only a watched file whose PR change differs from the one the nearest
        such commit showed counts (review_delta), the delta coming from git. None left keeps the
        clearance (logged as l3r-reuse); otherwise the block asks for that delta alone and
        suggests a smaller reviewer model. So a clean merge of the base is no delta, and a
        file resolved by hand, or kept over a fix on the base, is. The line-scoped and commit-time rules also run
        over every commit in the range.
A scan runs every rule whose `at` has "commit" (L3r: or `scope = "line"`): `when` on each
commit's added lines (lines its blob has that the parent's doesn't, by count and without a
trailing \\r: a moved line isn't new, nor is a CRLF rewrite) of regular files matching `paths`,
`unless` and practices-allow on the blob the commit leaves. A file added where the same commit
deleted one with the same basename (a rename with edits) is diffed against the deleted blob,
or scanned as all new when that blob is over the size caps (a changed file whose old blob is
over them is skipped, logged).
Merges, pure renames (the same blob), symlinks and binaries are skipped; at most MAX_COMMITS
commits and BYTES_MAX blob bytes, a cut logged as scan-truncated. When the time budget runs
out mid-scan (logged as scan-truncated), the level denies or tells once on what it read,
saying some commits weren't read, and keeps the range's cut key
(`<level>|engine|cut|-|sha1(the git dir and the commits)`), so a resend of the same range
passes unscanned; with nothing read the call is allowed. L3s and push also
run SEC-60, the engine's own rule: a lockfile changed in the range (LOCKFILES, requirements*.txt)
with no audit Bash call (AUDIT) in the transcript or, for a subagent, the parent's.
A finding's key is `<level>|<skill>|<rule>|<path>|sha1(the stripped line)`; a level denies or
tells only the findings whose key is new for this session and agent (the denies/ state file),
so the resend passes and a partial fix re-tells only what is new. An L2 deny also records a
key per line it named (`L2|<skill>|<rule>|<path>|sha1(the stripped line)`); a finding on one
of those lines was accepted at edit time and is skipped, and any other line of that rule in
that file is still told (a transcript marker names no line, so it accepts none). A deny or
tell names a finding by rule, path and line, never the matched text, and so does errors.log.

SEC-64, the engine's other rule, runs first in PreToolUse(Bash) and reads no repo: a Bash call
that adds a named package (ADD_VERBS: npm, pnpm, yarn and bun add and install, pip and uv pip
install, uv, poetry, cargo and bundle add, gem install, composer require; `go get` runs no code
at install) is denied once per manager and package (key `SEC-64|engine|<manager>|<package>`, no
version in it; a call adding several names every unseen one, and the resend passes). The word
after an `--option` this check doesn't list could be that option's value or a package, so it is
never stored or echoed; the call gets one deny that names no package, keyed
`SEC-64|engine|<manager>|?`, beside any named one. Restores
name no package and never fire: a bare install, `npm ci`, `pip install -r`, `uv sync`, a local
path, `pip install -e .`. It doesn't fire when the same simple command turns scripts off
(--ignore-scripts for the npm family, --only-binary :all: for pip and uv pip, --no-build for uv)
or, for the npm family, when an earlier Bash call in the transcript (or, for a subagent, the
parent's) with a result that isn't an error inspected the package. A step of this same call or
a call in its assistant message doesn't count: the model reads that output only after the install
has run the script. Inspecting is a manager's view (`npm view`, `pnpm view`, `yarn info`, `bun
info`) naming `scripts` or with --json and no named fields, with the same version spec as the
install, or tar reading its tarball's package.json: printing the whole tarball or that member, or
extracting it with a later command of the same call printing package/package.json. A Bash call that
redirects stdout, holds `||` or captures the look's output anywhere, or runs in the background,
inspects nothing. Other
managers have no measured inspection, so the deny-once alone applies. The deny names a package
and version spec only when they match a strict pattern and never echoes the rest of the command.
The rule reads the common spellings and is a prompt to
check, not a boundary; what it can't read is logged as install-skipped with no command text. A
key that can't be kept drops the deny.

git runs objects only, through Repo: a system git (SYSTEM_GITS), every GIT_* variable stripped
from the env, no system or global config, GIT_ALLOW_PROTOCOL=none (a partial clone's lazy fetch
would run a transport; 2.43 ignores GIT_NO_LAZY_FETCH), no replace refs, no optional locks,
core.fsmonitor and core.untrackedCache off, and only rev-parse, rev-list, merge-base,
diff-tree --raw -r -z and cat-file --batch, each with the options it lists and no other
(GIT_FLAGS). So no program a repo's config names
runs, and a tracked symlink is read as its target path. The user's safe.directory entries are
forwarded with -c, read as plain text from their global config files (one not theirs alone is
skipped, and named when git refuses the repo). Each call's timeout is what is left of the budget.
"""
import datetime
import hashlib
import json
from bisect import bisect_right
import mmap
import os
import re
import signal
import stat
import sys
import time

START = time.monotonic()
try:
    import tomllib
except ImportError:  # python3 < 3.11: reported by the startup health check
    tomllib = None

BUDGET = 2.0  # seconds, well under settings.json's 5 s kill
try:  # tests only: a tiny budget proves the skip path without a slow pattern. Only with
    # CLAUDE_CONFIG_DIR set, which a project's settings can't pass to a hook, as they can this one.
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        BUDGET = float(os.environ.get("PRACTICES_TEST_BUDGET") or BUDGET)
except ValueError:
    pass
CONTENT_MAX = 256 << 10
FILE_MAX = 1 << 20  # bytes of the current file read to apply an Edit; scans still cap at CONTENT_MAX
LINE_MAX = 4000
# Patterns' \\s* cross lines, so a whitespace run across lines costs each of them n^2 wherever a
# literal comes before it, past any line cap. No pattern needs one this long: past it, such a run
# keeps its line breaks up to this many and the last line's indent. Lines below 33 blank lines or
# more then report a smaller number. A run inside a line stays, under LINE_MAX: finding keys hash
# the raw line, and PATTERN_TIME bounds it.
WS_RUN_MAX = 32
# The time one event or rule may take in a run. Text a repo chooses can still make a pattern slow
# (a long line of one character, repeated); this costs the run that rule, not the 5 s kill, which
# would allow the call with every other rule unread.
PATTERN_TIME = 0.4
WS_RUN = re.compile(r"\s{%d,}" % (WS_RUN_MAX + 1))
LINE_START_WS = re.compile(r"(?<![\\\[])\^(\(\?!)?\\s\*")
PARSE_MAX = 1 << 20  # transcript rows bigger than this are never a load or a deny
LOG_MAX = 64 << 10
DIGEST_MAX = 2000
STALE_CRUMB = 10  # seconds: a live scan ends within the 5 s kill
KEEP_MAX = 500  # preserved uuids looked up per compaction boundary
STATE_DAYS = 7
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")
NOT_ENTRIES = (b'{"type":"api-request', b'{"type":"attachment"', b'{"type":"file-history',
               b'{"type":"queue-operation')
AUTH_HELPERS = ("auth", "getServerSession", "getSession", "currentUser", "getCurrentUser",
                "requireUser", "requireAuth", "verifySession", "getUser", "withAuth")
ID = re.compile(r"[\w.-]+")
OFF_FILE_MAX = 64 * 1024
CONFIG_MAX = 64 * 1024
HELPERS_MAX = 100
HELPER_LEN_MAX = 80
SKILL_NAME_MAX = 64
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")
SKILL_MAX = 1 << 20
PROJECT_SKILLS_MAX = 256 * 1024  # all of a project's events.toml files together
AT = ("edit", "commit")  # a [[rule]]'s `at` when it gives none: checked at both
# An [auth] helpers name: an identifier, dotted allowed (auth.requireUser). An empty or blank
# name would turn `(?:...|)` into a match for any call and silence SEC-01.
HELPER = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")


def state_dir():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "dotclaude", "practices")


def log(kind, detail):
    """One line in errors.log; kind is what the startup health line counts."""
    try:
        d = state_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "errors.log")
        try:
            if os.path.getsize(path) > LOG_MAX:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a", encoding="utf-8", errors="backslashreplace") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {detail}\n")
    except OSError:
        pass


class Budget(Exception):
    pass


def check_budget(what="transcript read"):
    if time.monotonic() - START > BUDGET:
        raise Budget(what)


class Crumb:
    """The scan breadcrumb: rewritten before each pattern, removed on a normal exit."""

    def __init__(self):
        self.fd = self.path = None

    def mark(self, file, level, pattern):
        if time.monotonic() - START > BUDGET:
            raise Budget(f"{level} {pattern}")
        data = json.dumps({"file": file, "level": level, "pattern": pattern}).encode()
        try:
            if self.fd is None:
                os.makedirs(state_dir(), exist_ok=True)
                self.path = os.path.join(state_dir(), f"breadcrumb-{os.getpid()}")
                self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.ftruncate(self.fd, 0)
            os.pwrite(self.fd, data, 0)
        except OSError:
            pass

    def clear(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
                os.unlink(self.path)
            except OSError:
                pass
            self.fd = None


CRUMB = Crumb()


# ---------------------------------------------------------------- globs and patterns

def _glob_body(g):
    out, i = [], 0
    while i < len(g):
        if g.startswith("**", i):
            if g.startswith("**/", i):
                out.append(r"(?:.*/)?")
                i += 3
            else:
                out.append(".*")
                i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        elif g[i] == "{" and (close := _brace_end(g, i)) != -1:
            out.append("(?:" + "|".join(_glob_body(a) for a in _split_alts(g[i + 1:close])) + ")")
            i = close + 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return "".join(out)


def _brace_end(g, i):
    depth = 0
    for j in range(i, len(g)):
        depth += {"{": 1, "}": -1}.get(g[j], 0)
        if depth == 0:
            return j
    return -1


def _split_alts(s):
    alts, depth, cur = [], 0, ""
    for c in s:
        if c == "," and depth == 0:
            alts.append(cur)
            cur = ""
            continue
        depth += {"{": 1, "}": -1}.get(c, 0)
        cur += c
    return alts + [cur]


def glob_regex(glob):
    """A regex (for fullmatch) for one glob; a glob with no / matches the basename."""
    glob = glob.removeprefix("./")
    return ("" if "/" in glob else r"(?:.*/)?") + _glob_body(glob)


def path_matches(globs, rel):
    return any(re.fullmatch(glob_regex(g), rel) for g in globs)


def expand(pattern, helpers):
    # With re.M, \\s after ^ runs across the blank lines below, from each one, which adds up over
    # many short runs. Anything those \\s* found past a newline, ^ finds on its own line, so
    # staying on the line finds the same.
    pattern = LINE_START_WS.sub(lambda m: "^" + (m.group(1) or "") + r"[^\S\n]*", pattern)
    if "{auth_helpers}" not in pattern:
        return pattern
    names = sorted(set(AUTH_HELPERS) | {h for h in helpers if HELPER.fullmatch(h)},
                   key=lambda n: (-len(n), n))
    return pattern.replace("{auth_helpers}", "(?:" + "|".join(map(re.escape, names)) + ")")


def search(pattern, text, helpers=()):
    return re.search(expand(pattern, helpers), text, re.MULTILINE) is not None


def _cut_run(m):
    run = m.group()
    if "\n" not in run:
        return run
    return "\n" * min(run.count("\n"), WS_RUN_MAX) + run[run.rindex("\n") + 1:]


def squeeze(text):
    return WS_RUN.sub(_cut_run, text)


def scan_text(content):
    """The content as scanned: CONTENT_MAX characters, each line cut to LINE_MAX, each whitespace
    run across lines to WS_RUN_MAX line breaks."""
    return squeeze("\n".join(line[:LINE_MAX] for line in content[:CONTENT_MAX].split("\n")))


def event_fires(event, rel, text, helpers=(), crumb=None):
    """Whether an [[event]] fires for the file at rel with the scanned text."""
    if path_matches(event.get("paths", ()), rel):
        return True
    for pattern in event.get("content", ()):
        if crumb:
            crumb.mark(rel, "L1", f"{event['id']} content")
        if guarded(pattern, text, helpers, event["id"]):
            return True
    return False


def rule_fires(rule, rel, text, helpers=(), crumb=None, after_text=None, after=None):
    """Whether a [[rule]] fires: paths (when given) match, `when` matches the new text, and
    neither `unless` (in the scanned file after the edit) nor `practices-allow: <id>` (anywhere
    in it) matches. Without after_text and after, the new text is the whole file (a Write)."""
    after_text = text if after_text is None else after_text
    if rule.get("paths") and not path_matches(rule["paths"], rel):
        return False
    if rule.get("scope") == "line":
        if crumb:
            crumb.mark(rel, "L2", rule["id"])
        return bool(line_hits(rule, enumerate(text.split("\n"), 1), helpers))
    if allowed(rule["id"], after_text if after is None else after):
        return False
    if crumb:
        crumb.mark(rel, "L2", rule["id"])
    if not guarded(rule["when"], text, helpers, rule["id"]):
        return False
    return not excused(rule, after_text, helpers)


def line_hits(rule, lines, helpers=()):
    """[(number, line)] that a `scope = "line"` rule flags: `when` matches the line, and neither
    `unless` nor `practices-allow: <id>` is on that same line."""
    out = []
    for n, line in lines:
        if not guarded(rule["when"], line, helpers, rule["id"]) or allowed(rule["id"], line):
            continue
        if excused(rule, line, helpers):
            continue
        out.append((n, line))
    return out


def file_hits(rule, lines, blob, helpers=()):
    """[(number, line)] that a whole-file rule flags in a commit: `when` matches the added lines
    (each flagged line is the one a match starts on), and neither `unless` nor
    `practices-allow: <id>` is anywhere in the file as the commit leaves it (blob). `when` runs
    first, on the added lines alone: the blob checks cost a pass over the whole file each, so
    they run only for a file `when` flags (a file with no `when` match gives [] either way)."""
    hits = when_lines(rule, lines, helpers)
    if not hits:
        return []
    if allowed(rule["id"], blob) or excused(rule, scan_text(blob), helpers):
        return []
    return hits


def when_lines(rule, lines, helpers=()):
    """[(number, line)] of the lines that a match of a rule's `when`, over the lines joined,
    starts on."""
    lines, blanks, kept = list(lines), 0, []
    for n, line in lines:  # the numbers stay with the lines, so blank ones can go from the join
        blank = not line.strip()
        blanks = blanks + 1 if blank else 0
        if blanks <= WS_RUN_MAX:
            kept.append((n, line, "" if blank else line))
    lines = [item[:2] for item in kept]
    text = "\n".join(item[2] for item in kept)
    starts, pos = [], 0
    for item in kept:
        starts.append(pos)
        pos += len(item[2]) + 1
    try:
        found = {bisect_right(starts, m.start()) - 1
                 for m in re.finditer(expand(rule["when"], helpers), text, re.MULTILINE)}
    except (re.error, RecursionError, TypeError, ValueError, OverflowError) as e:
        raise PatternError(f"{rule['id']}: {type(e).__name__}: {e}") from e
    return [lines[k] for k in sorted(found)]


def allowed(rule_id, content):
    return re.search(r"practices-allow:[ \t]*" + re.escape(rule_id) + r"(?![\w.-])",
                     content) is not None


class PatternError(Exception):
    pass


class SlowPattern(PatternError):
    pass


def on_the_clock(call):
    """call() under a repeating alarm at PATTERN_TIME: Python's re engine runs signal handlers as
    it matches. Unclocked where there is no alarm or this isn't the main thread."""
    def ring(_signum, _frame):
        raise SlowPattern(f"ran past {PATTERN_TIME}s on this text")

    try:
        signal.signal(signal.SIGALRM, ring)
        signal.setitimer(signal.ITIMER_REAL, PATTERN_TIME, PATTERN_TIME)
    except (AttributeError, ValueError):
        return call()
    try:
        return call()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def guarded(pattern, text, helpers, owner):
    try:
        return search(pattern, text, helpers)
    except (re.error, RecursionError, TypeError, ValueError, OverflowError) as e:
        raise PatternError(f"{owner}: {type(e).__name__}: {e}") from e


def excused(rule, text, helpers):
    """Whether a rule's `unless` matches. One that runs out of time excuses nothing, so slow text
    can't stand in for the guard the rule asks for."""
    try:
        return bool(rule.get("unless")) and guarded(rule["unless"], text, helpers, rule["id"])
    except SlowPattern as e:
        log("pattern-skipped", f"{rule['id']}'s unless: {e}; the rule still fires")
        return False


def lint_regex(pattern):
    """Why a regex is backtracking-prone, or None: an unbounded repeat nested inside another
    unbounded repeat ((a+)+, (a*)*, (.*)+), or an alternation under an unbounded repeat with two
    identical branches ((a|a)*). Rewrite such a pattern with bounded repeats or a lookahead."""
    try:
        import re._parser as parser  # noqa: PLC0415 (3.11+)
        import re._constants as const  # noqa: PLC0415
    except ImportError:
        import sre_parse as parser  # noqa: PLC0415
        import sre_constants as const  # noqa: PLC0415
    try:
        tree = parser.parse(expand(pattern, ()))
    except re.error as e:
        return f"doesn't compile: {e}"
    repeats = {const.MAX_REPEAT, const.MIN_REPEAT}
    repeats |= {getattr(const, "POSSESSIVE_REPEAT")} if hasattr(const, "POSSESSIVE_REPEAT") else set()

    def children(op, av):
        if op in repeats:
            return [av[2]]
        if op is const.SUBPATTERN:
            return [av[3]]
        if op is const.BRANCH:
            return list(av[1])
        if op in (const.ASSERT, const.ASSERT_NOT):
            return [av[1]]
        if op is const.GROUPREF_EXISTS:
            return [x for x in av[1:] if x is not None]
        if getattr(const, "ATOMIC_GROUP", None) is op:
            return [av]
        return []

    def walk(sub, under):
        for op, av in sub:
            unbounded = op in repeats and av[1] == const.MAXREPEAT
            if unbounded and under:
                return f"nested unbounded repeat in {pattern!r}"
            if op is const.BRANCH and under:
                seen = [str(list(b)) for b in av[1]]
                if len(seen) != len(set(seen)):
                    return f"repeated identical alternatives in {pattern!r}"
            for child in children(op, av):
                if why := walk(child, under or unbounded):
                    return why
        return None

    return walk(tree, False)


# ---------------------------------------------------------------- skills and config

def config_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _at_ok(at):
    """A rule's `at`: a non-empty list of "edit" and "commit", each at most once."""
    return _strs(at) and bool(at) and set(at) <= set(AT) and len(at) == len(set(at))


def read_toml(path, cap):
    """The TOML at path. A repo chooses these files, so one that would block (a FIFO), never end (a
    link to /dev/zero) or take the run's budget to parse raises ValueError instead."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            raise ValueError(f"not a regular file of at most {cap} bytes")
        return tomllib.loads(f.read(cap + 1).decode("utf-8"))


def load_skill(folder):
    """(skill dict, None) for a folder's events.toml, or (None, why) when it is malformed."""
    path = os.path.join(folder, "events.toml")
    try:
        data = read_toml(path, SKILL_MAX)
    except (OSError, ValueError, RecursionError) as e:  # TOMLDecodeError is a ValueError
        return None, f"{path}: {type(e).__name__}: {e}"
    name = data.get("skill", os.path.basename(folder))
    gate = data.get("gate", [])
    events, rules = data.get("event", []), data.get("rule", [])
    if not isinstance(name, str) or not ID.fullmatch(name) or len(name) > SKILL_NAME_MAX \
            or not _strs(gate) or not (isinstance(events, list) and isinstance(rules, list)):
        return None, f"{path}: bad skill, gate, event or rule"
    ids = []
    for ev in events:
        if not (isinstance(ev, dict) and isinstance(ev.get("id"), str) and ID.fullmatch(ev["id"])
                and _strs(ev.get("paths", [])) and _strs(ev.get("content", []))
                and _strs(ev.get("lines", []))):
            return None, f"{path}: bad event {ev.get('id') if isinstance(ev, dict) else ev!r}"
        ids.append(ev["id"])
    for r in rules:
        if not (isinstance(r, dict) and isinstance(r.get("id"), str) and ID.fullmatch(r["id"])
                and isinstance(r.get("when"), str) and isinstance(r.get("say"), str)
                and isinstance(r.get("unless", ""), str) and _strs(r.get("paths", []))
                and _at_ok(r.get("at", list(AT))) and r.get("scope", "file") in ("file", "line")):
            return None, f"{path}: bad rule {r.get('id') if isinstance(r, dict) else r!r}"
        ids.append(r["id"])
    if len(ids) != len(set(ids)):
        return None, f"{path}: duplicate ids"
    return {"name": name, "dir": os.path.abspath(folder), "gate": gate, "events": events,
            "rules": rules}, None


def add_copy(installed, copy):
    """A project copy of an installed skill, for a view of both (the session-start note, the
    digest): its events and rules with new ids are added, so it can't take anything away. Its gate
    lines stay out: they print under the installed skill's SKILL.md as what that skill requires."""
    ids = {x["id"] for x in installed["events"] + installed["rules"]}
    installed["events"] += [e for e in copy["events"] if e["id"] not in ids]
    installed["rules"] += [r for r in copy["rules"] if r["id"] not in ids]
    installed.setdefault("copies", []).append(copy["dir"])


def _load_root(root, quiet, cap=None):
    """[skill] from each folder under root that has an events.toml. A project's folders share cap
    bytes. Whatever a folder holds, a fault here costs only that skill."""
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        folder = os.path.join(root, n)
        path = os.path.join(folder, "events.toml")
        try:
            if not os.path.isfile(path):
                continue
            if cap is not None:
                cap -= os.path.getsize(path)
            skill, why = (None, f"{folder}: over {PROJECT_SKILLS_MAX} bytes of project skills") \
                if cap is not None and cap < 0 else load_skill(folder)
        except Exception as e:  # noqa: BLE001 (a repo chooses these files)
            skill, why = None, f"{folder}: {type(e).__name__}: {e}"
        if skill is not None:
            out.append(skill)
        elif not quiet:
            log("skill-disabled", why)
    return out


# Which skills this pass sees: "all" for a view of both, "installed" or "project" for a level's two
# passes (two_passes).
SCOPE = {"now": "all"}


def discover(project, quiet=False):
    """{name: skill} in the current SCOPE (a project's none when project is None). In "all", a
    project skill of an installed skill's name adds to it and never replaces it (add_copy). In
    "project", such a copy holds only the ids the installed skill lacks. quiet logs no malformed
    skill, for a second look in one run."""
    scope = SCOPE["now"]
    installed = {sk["name"]: sk for sk in _load_root(os.path.join(config_home(), "skills"), quiet)}
    if scope == "installed" or not project:
        return {} if scope == "project" else installed
    copies = _load_root(os.path.join(project, ".claude", "skills"), quiet, PROJECT_SKILLS_MAX)
    skills = {} if scope == "project" else installed
    for copy in copies:
        name = copy["name"]
        if scope == "all" and name in installed:
            add_copy(installed[name], copy)
            continue
        if name in installed:
            ids = {x["id"] for x in installed[name]["events"] + installed[name]["rules"]}
            copy["events"] = [e for e in copy["events"] if e["id"] not in ids]
            copy["rules"] = [r for r in copy["rules"] if r["id"] not in ids]
        skills[name] = copy
    return skills


def passwd_home():
    """The home in the passwd entry: the off file must not move with $HOME or $XDG_STATE_HOME,
    which a project's settings can set for a hook. bin/practices-gate does the same."""
    try:
        import pwd  # noqa: PLC0415 (Unix only)
    except ImportError:
        return os.path.expanduser("~")
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:  # a uid with no entry: no off file can be trusted, so the gate stays on
        return None


def off_file():
    home = passwd_home()
    return home and os.path.join(home, ".local", "state", "dotclaude", "practices-off.json")


def _off_entry_ok(e):
    if not isinstance(e, dict) or not isinstance(e.get("dir"), str):
        return False
    d, until = e["dir"], e.get("until")
    home = passwd_home()
    if (not os.path.isabs(d) or os.path.normpath(d) != d or under(home, d)  # never home or above
            or home == d or home.startswith(d.rstrip(os.sep) + os.sep)):  # home's link too
        return False
    try:
        # Exactly YYYY-MM-DD: fromisoformat also reads 2026-W45-4, which as a string sorts after
        # every date and so would never lapse.
        if datetime.date.fromisoformat(until).isoformat() != until:
            return False
    except (TypeError, ValueError):
        return False
    if "rule" in e:
        return (isinstance(e["rule"], str) and bool(e["rule"]) and isinstance(e.get("reason"), str)
                and bool(e["reason"].strip()))
    return True


def off_entries(project):
    """The entries in force at the project: (entries, whether the file is bad). Any fault ignores
    the whole file, so the gate stays on."""
    if not project:
        return [], False
    path = off_file()
    if not path:
        log("off-file-bad", "this uid has no passwd entry")
        return [], True
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return [], False
    except OSError as e:
        log("off-file-bad", f"{path}: {type(e).__name__}")
        return [], True
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or st.st_size > OFF_FILE_MAX):
            log("off-file-bad", f"{path}: not a private regular file of this user's")
            return [], True
        data = json.loads(os.read(fd, OFF_FILE_MAX + 1))
    except (OSError, ValueError, RecursionError) as e:
        log("off-file-bad", f"{path}: {type(e).__name__}")
        return [], True
    finally:
        os.close(fd)
    entries = data.get("entries") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(entries, list) or not all(_off_entry_ok(e) for e in entries):
        log("off-file-bad", f"{path}: not the format bin/practices-gate writes")
        return [], True
    real = os.path.realpath(project)
    today = datetime.date.today().isoformat()  # local, as the command's --until is
    return [e for e in entries if under(real, e["dir"]) and e["until"] >= today], False


def load_config(project):
    """{"enabled", "disable" (a set of ids and skill:ids), "helpers"}: the first two from the off
    file, the helpers from the project's config.toml; defaults on any fault, or when project is
    None."""
    default = {"enabled": True, "disable": set(), "helpers": ()}
    if not project:
        return default
    entries, _ = off_entries(project)
    off = {"enabled": not any("rule" not in e for e in entries),
           "disable": {e["rule"] for e in entries if "rule" in e}, "helpers": ()}
    path = os.path.join(project, ".claude", "practices", "config.toml")
    try:
        data = read_toml(path, CONFIG_MAX)
    except FileNotFoundError:
        return off
    except (OSError, ValueError, RecursionError) as e:
        log("config-malformed", f"{path}: {type(e).__name__}: {e}")
        return off
    if "enabled" in data or "disable" in data:
        log("config-ignored", f"{path}: a repo can't turn the gate off; run `practices-gate` by hand")
    auth = data.get("auth", {})
    helpers = auth.get("helpers", []) if isinstance(auth, dict) else None
    if not _strs(helpers):
        log("config-malformed", f"{path}: bad auth.helpers")
        return off
    bad = [h for h in helpers if not HELPER.fullmatch(h)]
    if bad:
        log("config-malformed", f"{path}: auth.helpers dropped {bad!r}: not identifier names")
    good = [h for h in helpers if HELPER.fullmatch(h) and len(h) <= HELPER_LEN_MAX]
    if len(good) > HELPERS_MAX:  # these reach installed rules' patterns, in the first pass
        log("config-malformed", f"{path}: auth.helpers kept the first {HELPERS_MAX}")
    return {**off, "helpers": tuple(good[:HELPERS_MAX])}


def is_off(cfg, skill, item_id):
    return item_id in cfg["disable"] or f"{skill['name']}:{item_id}" in cfg["disable"]


# ---------------------------------------------------------------- transcripts

class Transcript:
    """A mapped transcript; rows are parsed only where a needle hits."""

    def __init__(self, m, sidechain_ok):
        self.m, self.sidechain_ok = m, sidechain_ok

    def line_at(self, i):
        s = self.m.rfind(b"\n", 0, i) + 1
        e = self.m.find(b"\n", i)
        return s, len(self.m) if e == -1 else e

    def parse(self, s, e):
        if e - s > PARSE_MAX or self.m[s:s + 32].startswith(NOT_ENTRIES):
            return None
        try:
            d = json.loads(self.m[s:e])
        except (ValueError, RecursionError):  # json recurses on nesting
            return None
        if not isinstance(d, dict) or (d.get("isSidechain") and not self.sidechain_ok):
            return None
        return d

    def hits(self, needle, lo=0, hi=None):
        """(start, end, row) for each parseable row in [lo, hi) holding needle, in order."""
        hi = len(self.m) if hi is None else hi
        pos = lo
        while pos < hi and (i := self.m.find(needle, pos, hi)) != -1:
            check_budget()
            s, e = self.line_at(i)
            d = self.parse(s, e)
            if d is not None:
                yield s, e, d
            pos = e + 1

    def boundaries(self):
        """(row start, row end, preserved uuids, id) per compact boundary, newest first; the id
        is the row's uuid, or its offset when it has none."""
        end = len(self.m)
        while end > 0 and (i := self.m.rfind(b'"compact_boundary"', 0, end)) != -1:
            check_budget()
            s, e = self.line_at(i)
            d = self.parse(s, e)
            if d and d.get("type") == "system" and d.get("subtype") == "compact_boundary":
                uid = d.get("uuid")
                yield s, e, preserved(d), uid if isinstance(uid, str) and uid else f"@{s}"
            end = s

    def rows_by_uuid(self, uuids, before):
        """[(start, end)] of the rows before offset `before` with these uuids: each found by its
        own `"uuid":"<id>"` (the compact JSON Claude Code writes), searched back from `before`,
        so a preserved segment costs no rescan of the transcript."""
        spans = set()
        for u in sorted(uuids)[:KEEP_MAX]:
            check_budget()
            i = self.m.rfind(b'"uuid":' + json.dumps(u).encode(), 0, before)
            if i != -1:
                spans.add(self.line_at(i))
        return sorted(spans)

    def succeeded(self, tool_id, start):
        """Whether the tool call with this id has a result after offset start that isn't an
        error."""
        if not isinstance(tool_id, str) or not tool_id:
            return False
        for _, _, d in self.hits(json.dumps(tool_id).encode(), start):
            if d.get("type") != "user":
                continue
            for b in blocks(d):
                if b.get("type") == "tool_result" and b.get("tool_use_id") == tool_id:
                    return not b.get("is_error")
        return False

    def call_name(self, tool_id, before):
        """The tool name of the call with this id before offset before, or None if not found."""
        if not isinstance(tool_id, str) or not tool_id:
            return None
        needle = json.dumps(tool_id).encode()
        i = self.m.rfind(needle, 0, before)
        while i != -1:  # backward: the call sits just before its result
            check_budget()
            s, e = self.line_at(i)
            d = self.parse(s, e)
            if d is not None and d.get("type") == "assistant":
                for b in blocks(d):
                    if b.get("type") == "tool_use" and b.get("id") == tool_id:
                        return b.get("name")
            i = self.m.rfind(needle, 0, s)
        return None

    def assistant_after(self, pos):
        return any(d.get("type") == "assistant" for _, _, d in self.hits(b'"assistant"', pos))


def preserved(boundary):
    meta = boundary.get("compactMetadata")
    pm = meta.get("preservedMessages") if isinstance(meta, dict) else None
    if not isinstance(pm, dict):
        return frozenset()
    return frozenset(u for k in ("uuids", "allUuids") for u in (pm.get(k) or [])
                     if isinstance(u, str))


def blocks(d):
    msg = d.get("message")
    c = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def result_texts(d):
    for b in blocks(d):
        if b.get("type") != "tool_result":
            continue
        c = b.get("content")
        if isinstance(c, list):
            yield "\n".join(x.get("text") or "" for x in c if isinstance(x, dict))
        elif isinstance(c, str):
            yield c


def loaded_name(b):
    """What a tool_use block loads: a Skill call's bare name, or the realpath of the dir whose
    SKILL.md a Read took, since a Read names one copy and a repo can hold its own of any name.
    None otherwise."""
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if b.get("name") == "Skill" and isinstance(inp.get("skill"), str):
        return inp["skill"].rsplit(":", 1)[-1].strip() or None
    fp = inp.get("file_path")
    if b.get("name") == "Read" and isinstance(fp, str) and fp.replace("\\", "/").endswith(
            "/SKILL.md"):
        try:
            return os.path.dirname(os.path.realpath(os.path.expanduser(fp.replace("\\", "/"))))
        except ValueError:  # a NUL or a lone surrogate: no file by that name was read
            return None
    return None


def is_loaded(skill, loads):
    return (skill["name"] in loads or os.path.basename(skill["dir"]) in loads
            or os.path.realpath(skill["dir"]) in loads)


class Window:
    """The rows from lo to hi, plus the preserved rows (keep: uuids of rows before lo)."""

    def __init__(self, t, lo, hi, keep=frozenset()):
        self.t, self.lo, self.hi = t, lo, hi
        self.kept = t.rows_by_uuid(keep, lo) if keep else []

    def rows(self, needle):
        for s, e in self.kept:
            if self.t.m.find(needle, s, e) != -1 and (d := self.t.parse(s, e)) is not None:
                yield s, e, d
        yield from self.t.hits(needle, self.lo, self.hi)

    def loads(self):
        """The skills a Skill call or a Read of their SKILL.md loaded, each with a result that
        isn't an error (a mistyped path or an unknown skill loads nothing)."""
        names = set()
        for needle in (b'"Skill"', b"SKILL.md"):
            for _, e, d in self.rows(needle):
                if d.get("type") != "assistant":
                    continue
                for b in blocks(d):
                    n = loaded_name(b) if b.get("type") == "tool_use" else None
                    if n and n not in names and self.t.succeeded(b.get("id"), e):
                        names.add(n)
        return names

    def denies(self, needle):
        """The text of each errored result of an edit tool's call that holds needle: a hook's deny
        reads that way, and a file the model read, or a Bash call that failed printing it, doesn't.
        A call whose row isn't found (a compaction dropped it) counts."""
        out = []
        for s, _, d in self.rows(needle):
            if d.get("type") != "user":
                continue
            for b in blocks(d):
                if b.get("type") == "tool_result" and b.get("is_error"):
                    if self.t.call_name(b.get("tool_use_id"), s) in (None, *EDIT_TOOLS):
                        out += list(result_texts({"message": {"content": [b]}}))
        return out


def l1_window(t):
    """(the window since the last compaction, that boundary's id or "none")."""
    b = next(t.boundaries(), None)
    return (Window(t, b[1], None, b[2]), b[3]) if b else (Window(t, 0, None), "none")


def compact_window(t):
    """The rows before this compaction and after the one before it."""
    bounds = t.boundaries()
    last = next(bounds, None)
    if last is None or t.assistant_after(last[1]):
        return l1_window(t)[0]
    prev = next(bounds, None)
    return Window(t, prev[1], last[0], prev[2]) if prev else Window(t, 0, last[0])


def transcript_of(event):
    path = event.get("transcript_path")
    agent = event.get("agent_id")
    if not isinstance(path, str) or not path:
        return None
    if not agent:
        return path
    if not path.endswith(".jsonl"):
        return None
    return os.path.join(path[:-len(".jsonl")], "subagents", f"agent-{agent}.jsonl")


def open_transcript(event):
    """(mmap or None, file) for the call's own transcript; (None, None) when it is missing."""
    path = transcript_of(event)
    try:
        f = open(path, "rb")
    except (OSError, TypeError):
        return None, None
    try:
        if os.fstat(f.fileno()).st_size == 0:
            return b"", f
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ), f
    except (OSError, ValueError):
        f.close()
        return None, None


# ---------------------------------------------------------------- deny-once state fallback

def _state_file(event):
    key = f"{event.get('session_id')}|{event.get('agent_id') or 'main'}"
    return os.path.join(state_dir(), "denies", hashlib.sha256(key.encode()).hexdigest()[:32]
                        + ".json")


def state_keys(event):
    """The deny keys recorded for this session and agent. A missing file is empty; so is a
    malformed one (logged), and deny-once still holds through the transcript markers."""
    path = _state_file(event)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return set()
    except (OSError, ValueError, RecursionError) as e:
        log("state-error", f"{path}: unreadable ({type(e).__name__}), read as empty")
        return set()
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        log("state-error", f"{path}: not {{\"keys\": [strings]}}, read as empty")
        return set()
    return set(keys)


def state_add(event, keys):
    """Record deny keys; whether the write held (a failure is logged). The Bash levels deny
    only after it holds: they have no transcript marker to fall back on, so a deny whose key
    can't be kept would stop the resend too, forever."""
    path = _state_file(event)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"keys": sorted(state_keys(event) | set(keys))}, f)
        os.replace(tmp, path)
        return True
    except OSError as e:
        log("state-error", f"{path}: {e}")
        return False


# ---------------------------------------------------------------- git, objects only

SYSTEM_GITS = ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git")
# Every subcommand the engine runs, with the options it may pass (one ending in = takes its
# value attached). None of them reads the index or the working tree, or runs a program a config
# names: no patch (diff drivers, textconv), no --filters or --textconv, no status (fsmonitor,
# untracked cache). After --end-of-options, where a subcommand's set allows it, every word is a
# name, never an option (rev() passes a name that may start with -).
GIT_FLAGS = {"rev-parse": {"--absolute-git-dir", "--git-common-dir", "--show-toplevel",
                           "--verify", "--quiet", "--abbrev-ref", "--end-of-options"},
             "rev-list": {"--no-merges", "--parents", "--max-count=", "--not", "--branches",
                          "--remotes"},
             "merge-base": set(),
             "diff-tree": {"--raw", "-r", "-z", "--no-renames", "--root", "--no-commit-id"},
             "cat-file": {"--batch", "--batch-check"}}
GIT_MARGIN = 0.05  # seconds of the budget kept for the work after a git call
GIT_TIMEOUT_MAX = 10.0  # seconds, for a budget patched huge in tests
GITCONFIG_MAX = 1 << 20


class GitError(Exception):
    """A git call the engine skips: no git, not a repo, a refused ownership check."""


def git_env():
    """The environment for every git call: no GIT_* variable from the hook's own env (a GIT_DIR
    there names another repo), no system or global config, no transport (a partial clone's lazy
    fetch would run one; 2.43 ignores GIT_NO_LAZY_FETCH), no replace refs, no optional locks."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL="none",
               GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0",
               GIT_TERMINAL_PROMPT="0", GIT_ATTR_NOSYSTEM="1")
    if os.environ.get("PRACTICES_TEST_DIFFERENT_OWNER"):  # tests only: stricter, never looser
        env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
    return env


def safe_directories():
    """(the user's safe.directory values, why none could be read or None), read as plain text
    from their real global config files, which GIT_CONFIG_GLOBAL hides from git. A file that
    isn't a regular file owned by the user, or that others can write, is skipped."""
    home = os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    values, why = [], []
    for path in (os.path.join(home, ".gitconfig"), os.path.join(xdg, "git", "config")):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue
        except OSError as e:
            why.append(f"{path}: {type(e).__name__}")
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022 \
                or st.st_size > GITCONFIG_MAX:
            why.append(f"{path}: not a regular file of the user's that only they can write")
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read(GITCONFIG_MAX)
        except OSError as e:
            why.append(f"{path}: {type(e).__name__}")
            continue
        section = None
        for line in text.splitlines():
            line = line.strip()
            if m := re.match(r"\[\s*([A-Za-z0-9.-]+)\s*(?:\"[^\"]*\")?\s*\]", line):
                section = m.group(1).lower()
                line = line[m.end():].strip()
            if section == "safe" and (m := re.match(r"(?i)directory\s*=\s*(.*)$", line)):
                v = m.group(1).strip()
                v = v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else re.split(r"\s[#;]", v)[0]
                if v:
                    values.append(v)
    return values, ("; ".join(why) or None)


class Repo:
    """One repository, read through git's object store only. Every call runs a system git with
    git_env(), core.fsmonitor and core.untrackedCache off, the user's safe.directory entries,
    and a timeout from what is left of the budget."""

    def __init__(self, cwd, git_dir=None, work_tree=None):
        self.git = next((g for g in SYSTEM_GITS if os.path.isfile(g)), None)
        if not self.git:
            raise GitError("no system git")
        self.cwd, self.env = cwd, git_env()
        self.safe, self.safe_why = safe_directories()
        self.base = [self.git, "--no-pager", "-c", "core.fsmonitor=false",
                     "-c", "core.untrackedCache=false",
                     *(x for d in self.safe for x in ("-c", f"safe.directory={d}"))]
        if git_dir:
            self.base.append(f"--git-dir={git_dir}")
        if work_tree:
            self.base.append(f"--work-tree={work_tree}")
        out = self.run("rev-parse", "--absolute-git-dir", "--git-common-dir").decode(
            "utf-8", "surrogateescape").split("\n")
        self.git_dir = out[0].strip()
        # A relative common dir is relative to the cwd git ran in.
        self.common_dir = os.path.normpath(os.path.join(cwd, out[1].strip())) \
            if len(out) > 1 and out[1].strip() else self.git_dir
        try:
            self.top = self.run("rev-parse", "--show-toplevel").decode(
                "utf-8", "surrogateescape").strip() or None
        except GitError:
            self.top = None  # a bare repo
        self.base = [x for x in self.base if not x.startswith(("--git-dir=", "--work-tree="))]
        self.base.append(f"--git-dir={self.git_dir}")

    def run(self, sub, *args, stdin=None, ok=(0,)):
        """git's stdout as bytes; GitError on a refused call or a failure, Budget when the
        budget runs out first."""
        allowed = GIT_FLAGS.get(sub)
        opts = args[:args.index("--end-of-options")] if allowed and "--end-of-options" in \
            allowed and "--end-of-options" in args else args
        if allowed is None or any(a.startswith("-") and a not in allowed and not (
                "=" in a and a.split("=", 1)[0] + "=" in allowed) for a in opts):
            raise GitError(f"refused: git {sub} {' '.join(args)}")
        if sub == "diff-tree" and not {"--raw", "-r", "-z"} <= set(args):
            raise GitError("refused: diff-tree without --raw -r -z")
        left = BUDGET - (time.monotonic() - START) - GIT_MARGIN
        if left <= 0:
            raise Budget(f"git {sub}")
        import subprocess  # noqa: PLC0415 (only the Bash levels pay for it)
        try:
            p = subprocess.run([*self.base, sub, *args], cwd=self.cwd, env=self.env, input=stdin,
                               capture_output=True, timeout=min(left, GIT_TIMEOUT_MAX))
        except subprocess.TimeoutExpired as e:
            raise Budget(f"git {sub}") from e
        except OSError as e:
            raise GitError(f"git {sub}: {type(e).__name__}") from e
        if p.returncode not in ok:
            err = p.stderr.decode("utf-8", "replace")
            if p.returncode == 128 and ("dubious ownership" in err or "safe.directory" in err):
                raise GitError("ownership check refused the repo" + (
                    f" (safe.directory not forwarded: {self.safe_why})" if self.safe_why else ""))
            raise GitError(f"git {sub} exited {p.returncode}")
        return p.stdout

    def rev(self, name):
        """The commit name resolves to, or None."""
        out = self.run("rev-parse", "--verify", "--quiet", "--end-of-options", f"{name}^{{commit}}",
                       ok=(0, 1))
        return out.decode().strip() or None

    def commits(self, *spec, cap):
        """[(commit, parent or None)] for rev-list spec, newest first, merges left out, at most
        cap; and whether more were left out."""
        out = self.run("rev-list", "--no-merges", "--parents", f"--max-count={cap + 1}", *spec)
        rows = [line.split() for line in out.decode().splitlines() if line.strip()]
        pairs = [(r[0], r[1] if len(r) > 1 else None) for r in rows]
        return pairs[:cap], len(pairs) > cap

    def changes(self, old, new):
        """[(status, old mode, new mode, old oid, new oid, path)] from old (a tree-ish, or None
        for a commit against its parent or the empty tree) to new, renames off."""
        args = ["--raw", "-r", "-z", "--no-renames", "--no-commit-id"]
        args += [old, new] if old else ["--root", new]
        parts = self.run("diff-tree", *args).split(b"\0")
        out, i = [], 0
        while i + 1 < len(parts):
            meta = parts[i].decode("ascii", "replace")
            if not meta.startswith(":"):
                i += 1
                continue
            omode, nmode, ooid, noid, status = meta[1:].split()[:5]
            out.append((status[:1], omode, nmode, ooid, noid,
                        parts[i + 1].decode("utf-8", "surrogateescape")))
            i += 2
        return out

    def blobs(self, oids, each_max, total_max):
        """({oid: bytes}, [oids left out for size]) for the blobs, each at most each_max bytes
        and all together at most total_max."""
        oids = list(dict.fromkeys(o for o in oids if o and set(o) != {"0"}))
        if not oids:
            return {}, []
        check = self.run("cat-file", "--batch-check", stdin="\n".join(oids).encode() + b"\n")
        keep, skipped, total = [], [], 0
        for line in check.decode().splitlines():
            f = line.split()
            if len(f) == 3 and f[1] == "blob" and int(f[2]) <= each_max \
                    and total + int(f[2]) <= total_max:
                keep.append(f[0])
                total += int(f[2])
            elif f:
                skipped.append(f[0])
        if not keep:
            return {}, skipped
        data = self.run("cat-file", "--batch", stdin="\n".join(keep).encode() + b"\n")
        out, pos = {}, 0
        while pos < len(data):
            nl = data.index(b"\n", pos)
            head = data[pos:nl].decode().split()
            if len(head) != 3:
                break
            size = int(head[2])
            out[head[0]] = data[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
        return out, skipped


# ---------------------------------------------------------------- PreToolUse

def edits_of(tool, inp):
    """[(old_string, new_string, replace_all)] for an Edit or MultiEdit, in order."""
    raw = [inp] if tool == "Edit" else [e for e in inp.get("edits") or [] if isinstance(e, dict)]
    return [(e.get("old_string") if isinstance(e.get("old_string"), str) else "",
             e.get("new_string") if isinstance(e.get("new_string"), str) else "",
             e.get("replace_all") is True) for e in raw]


def apply_edits(current, edits):
    """The content after the edits, applied in order as Claude Code applies them (the first
    occurrence, or every one with replace_all; an empty old_string only creates an empty
    file), or None when an edit can't apply."""
    for old, new, every in edits:
        if old == "":
            if current:
                return None
            current = new
        elif old not in current:
            return None
        else:
            current = current.replace(old, new, -1 if every else 1)
    return current


def post_edit(tool, inp, path):
    """(fragment, after): the text the call writes, and the file as it will read after the
    call. Write's are both its content. For an Edit or MultiEdit, after is the current file
    (its first FILE_MAX bytes) with the edits applied; when the file can't be read or an edit
    doesn't apply, after falls back to the fragment and that is logged."""
    if tool == "Write":
        content = inp.get("content") if isinstance(inp.get("content"), str) else ""
        return content, content
    edits = edits_of(tool, inp)
    fragment = "\n".join(new for _, new, _ in edits)
    try:
        with open(path, "rb") as f:
            current = f.read(FILE_MAX).decode("utf-8", "replace")
    except FileNotFoundError:
        current = None
    except OSError as e:
        log("fragment-only", f"{path}: unreadable ({type(e).__name__}), so only the new text "
            "was checked")
        return fragment, fragment
    after = apply_edits("" if current is None else current, edits)
    if after is None:
        why = "missing" if current is None else "an old_string isn't in it"
        log("fragment-only", f"{path}: {why}, so only the new text was checked")
        return fragment, fragment
    return fragment, after


def edit_of(event):
    """(absolute path, fragment, after) for an Edit, Write or MultiEdit, else None."""
    inp = event.get("tool_input")
    tool = event.get("tool_name")
    if tool not in EDIT_TOOLS or not isinstance(inp, dict):
        return None
    fp = inp.get("file_path")
    if not isinstance(fp, str) or not fp:
        return None
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    path = os.path.abspath(os.path.join(cwd, fp))
    return (path, *post_edit(tool, inp, path))


def relative(path, project):
    rel = os.path.relpath(path, project)
    if rel.startswith(".."):
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(project))
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def run_patterns(items, fn, cut=False):
    """[item for item in items if fn(item)], each inside its own guard; a throwing pattern is
    logged and skipped, and once the budget is spent the rest are skipped and logged (with
    cut, the Budget then goes on up, so a scan knows it was cut short)."""
    out = []
    for n, item in enumerate(items):
        try:
            if on_the_clock(lambda item=item: fn(item)):
                out.append(item)
        except SlowPattern as e:
            log("pattern-skipped", f"{item[0]['name']}:{item[1]['id']}: {e}")
        except PatternError as e:
            log("pattern-skipped", str(e))
        except Budget:
            left = ", ".join(f"{s['name']}:{x['id']}" for s, x in items[n:])
            log("budget-spent", f"after {BUDGET}s, skipped {left}")
            if cut:
                raise
            break
    return out


def l1_reason(pending, rel, subagent):
    parts = []
    for skill, evs in pending:
        skill_md = os.path.join(skill["dir"], "SKILL.md")
        how = (f"Read {skill_md}" if subagent else
               f"call the Skill tool with \"{skill['name']}\", or Read {skill_md}")
        markers = "".join(f"[practices:L1:{skill['name']}:{ev['id']}]" for ev in evs)
        names = ", ".join(ev["id"] for ev in evs) + (" events" if len(evs) > 1 else " event")
        lines = "".join(f"\n- {line}" for ev in evs for line in ev.get("lines", []))
        parts.append(f"{markers} This edit to {rel} is a {names} of the {skill['name']} "
                     f"skill, and that skill isn't loaded in this context. "
                     f"Load it first ({how}), then resend this edit; this check won't stop it "
                     f"again." + (f"\nThe skill's lines for this event:{lines}" if lines else ""))
    return "\n\n".join(parts)


def l2_lines(rule, text, helpers):
    """The lines of the new text an L2 deny names: the ones a line rule flags, or the ones a
    file rule's `when` match starts on. A later commit, push or PR skips a finding only on these
    lines, so one accepted deny never hides another line of the same rule in the same file."""
    lines = enumerate(text.split("\n"), 1)
    hits = line_hits(rule, lines, helpers) if rule.get("scope") == "line" else \
        when_lines(rule, lines, helpers)
    return [line for _, line in hits]


def l2_reason(pending, rel):
    return "\n\n".join(
        f"[practices:L2:{skill['name']}:{rule['id']}:{rel}] {rule['say']}\nFix it and resend, "
        f"or, when this is a false positive, add a comment `practices-allow: {rule['id']} "
        f"<reason>` to the code; this check won't stop this file for {rule['id']} again."
        for skill, rule in pending)


def pre_tool_use(event):
    if event.get("tool_name") == "Bash":
        return bash_pre(event)
    edit = edit_of(event)
    if edit is None:
        return None
    project = bash_project(event)  # as the Bash levels read it: never a cwd a cd moved
    if project is None:
        log("project-unknown", "edit: no project dir (CLAUDE_PROJECT_DIR unset and no cwd "
            "recorded at session start), so only the user's skills were checked")
    cfg = load_config(project)
    if not cfg["enabled"]:
        return None
    skills = discover(project)
    if not skills:
        return None
    path, fragment, after = edit
    rel = relative(path, project) if project else path
    text, after_text = scan_text(fragment), scan_text(after)
    helpers = cfg["helpers"]
    events = [(s, ev) for s in skills.values() for ev in s["events"] if not is_off(cfg, s, ev["id"])]
    rules = [(s, r) for s in skills.values() for r in s["rules"]
             if "edit" in r.get("at", AT) and not is_off(cfg, s, r["id"])]
    fired = run_patterns(events, lambda x: event_fires(x[1], rel, after_text, helpers, CRUMB))

    m, f = open_transcript(event)
    reason, keys = None, []
    try:
        t = Transcript(m, bool(event.get("agent_id"))) if m is not None else None
        seen = state_keys(event)
        if fired:
            CRUMB.mark(rel, "transcript", "L1 loads and denies")
            win, bid = l1_window(t) if t is not None else (None, "none")
            loads = win.loads() if win else set()
            denied = win.denies(b"[practices:L1:") if win else []
            pending = {}
            for s, ev in fired:
                if is_loaded(s, loads):
                    continue
                marker = f"[practices:L1:{s['name']}:{ev['id']}]"
                key = f"L1|{bid}|{s['name']}|{ev['id']}"
                if key in seen or any(marker in x for x in denied):
                    continue
                pending.setdefault(s["name"], (s, []))[1].append(ev)
                keys.append(key)
            if pending:
                reason = l1_reason(list(pending.values()), rel, bool(event.get("agent_id")))
        if reason is None and rules:
            hit = run_patterns(rules, lambda x: rule_fires(x[1], rel, text, helpers, CRUMB,
                                                           after_text, after))
            denied = []
            if hit and t is not None:
                CRUMB.mark(rel, "transcript", "L2 denies")
                denied = Window(t, 0, None).denies(b"[practices:L2:")
            pending = []
            for s, r in hit:
                marker = f"[practices:L2:{s['name']}:{r['id']}:{rel}]"
                key = f"L2|{s['name']}|{r['id']}|{rel}"
                if key in seen or any(marker in x for x in denied):
                    continue
                pending.append((s, r))
                keys.append(key)
                try:
                    lines = on_the_clock(lambda r=r: l2_lines(r, text, helpers))
                except SlowPattern as e:  # the rule's key alone: a later scan then rereads the file
                    log("pattern-skipped", f"{s['name']}:{r['id']}: {e}")
                    lines = []
                keys += [f"{key}|{_sha1(line.strip())}" for line in lines]
            if pending:
                reason = l2_reason(pending, rel)
        # A deny needs a way for its resend through: the state key, or a transcript that will
        # hold the marker. With neither (an unwritable state dir and an empty or missing
        # transcript), every resend would be denied too, so the edit is allowed, logged.
        if reason and not state_add(event, keys) and not m:
            log("state-error", f"{rel}: the deny couldn't be kept and the transcript is empty "
                "or missing, so the edit was allowed")
            reason = None
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the {e} for {rel}; the edit was allowed")
        return None
    finally:
        if isinstance(m, mmap.mmap):
            m.close()
        if f:
            f.close()
    if not reason:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


# ---------------------------------------------------------------- Bash: L3s, push, L3r

MAX_COMMITS = 50   # commits scanned per call, newest first
BYTES_MAX = 4 << 20  # blob bytes read per call
LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
             "Pipfile.lock", "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum"}
LOCK_GLOB = re.compile(r"requirements[^/]*\.txt")
# An audit counts whatever its exit code. uv audit is uv's own (0.11); poetry audit is the
# poetry-audit-plugin; uvx pip-audit and uv run pip-audit match pip-audit.
AUDIT = re.compile(r"(?:^|[\s;&|(!`])(?:(?:npm|pnpm|yarn)\s+(?:npm\s+)?audit|pip-audit|cargo\s+audit"
                   r"|bundle\s+audit|bundler-audit|composer\s+audit|govulncheck|uv\s+audit"
                   r"|poetry\s+audit)(?![\w-])")
SEC60 = {"id": "SEC-60", "say": (
    "A dependency lockfile changed and no audit ran in this session. Run the ecosystem's audit "
    "(npm audit, pnpm audit, yarn npm audit, pip-audit or uv audit, cargo audit, bundle audit, "
    "composer audit, govulncheck), fix or note what it reports, and say so in your reply.")}
ENGINE = {"name": "engine", "dir": None, "gate": []}
HEADS = ("git", "gh")


def _sha1(text):
    return hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest()


def is_lockfile(path):
    base = path.rsplit("/", 1)[-1]
    return base in LOCKFILES or bool(LOCK_GLOB.fullmatch(base))


def _eol(line):
    """A line as added_lines compares it: a trailing \\r dropped, so LF to CRLF adds nothing."""
    return line[:-1] if line.endswith("\r") else line


def added_lines(old, new):
    """[(number, line)] of the lines in new that old doesn't have (as many times as new adds
    them), compared without a trailing \\r: a moved line isn't new code, and neither is a line
    whose ending changed. Linear, unlike a real diff."""
    have = {}
    for line in old.split("\n") if old else ():
        have[_eol(line)] = have.get(_eol(line), 0) + 1
    out = []
    for n, line in enumerate(new.split("\n"), 1):
        if have.get(_eol(line), 0):
            have[_eol(line)] -= 1
        else:
            out.append((n, line[:LINE_MAX]))
    return out


def text_of(data):
    """A blob as text, or None for a binary one."""
    if data is None or b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", "replace")[:CONTENT_MAX]


class Finding:
    def __init__(self, level, skill, rule, path, line_no, line, commit):
        self.skill, self.rule, self.path, self.line_no, self.commit = \
            skill, rule, path, line_no, commit
        self.line_hash = _sha1(line.strip())
        self.key = f"{level}|{skill['name']}|{rule['id']}|{path}|{self.line_hash}"


def command_of(event):
    inp = event.get("tool_input")
    cmd = inp.get("command") if isinstance(inp, dict) else None
    return cmd if isinstance(cmd, str) and cmd.strip() else None


# Characters of a Bash command the reader parses. shlex builds a long word in quadratic time and
# a `bash -c` script is parsed once per level it is nested, so a 1 MB command nested 8 deep took
# 9 to 11 s, past the 5 s kill. At this cap the worst shape measured (`bash -c` nested 8 deep)
# parses in about 0.5 s. A longer command isn't parsed: logged as git-skipped when it names a
# call, else allowed quietly.
CMD_MAX = 64 << 10

_BASH_WORDS = []


def load_bash_words():
    """hooks/bash_words.py beside this file, loaded by its path and compiled from its source.
    The hooks dir never joins sys.path (a planted shlex.py there would run outside the sandbox
    when bash_words imports shlex), and no cached .pyc is read."""
    if not _BASH_WORDS:
        import importlib.util  # noqa: PLC0415 (only the Bash levels need it)
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bash_words.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location(
            "bash_words", path))
        exec(compile(source, path, "exec"), mod.__dict__)  # noqa: S102 (our own module)
        _BASH_WORDS.append(mod)
    return _BASH_WORDS[0]


# The prefilter's words, matched as words in order (git, then commit or push; gh, then pr, then
# ready or create), each chain one forward search per word, so linear in the text.
NAMED = ((re.compile(r"(?<![\w.-])git(?![\w-])"), re.compile(r"(?<![\w-])(?:commit|push)(?![\w-])")),
         (re.compile(r"(?<![\w.-])gh(?![\w-])"), re.compile(r"(?<![\w-])pr(?![\w-])"),
          re.compile(r"(?<![\w-])(?:ready|create)(?![\w-])")))


def names_a_call(text):
    """Whether text names git commit or push, or gh pr ready or create, word by word in order."""
    for chain in NAMED:
        pos = 0
        for rx in chain:
            m = rx.search(text, pos)
            if not m:
                break
            pos = m.end()
        else:
            return True
    return False


def bash_calls(event):
    """(git calls as (subcommand, args, where), gh calls as (args, cwd), whether what the
    parser left unread names one) in the Bash command. Unread: the arguments of every command
    but a git commit, push or grep, a gh pr ready or create, and grep or rg (`xargs git push`,
    `find -exec`, `git submodule foreach`), a heredoc body a shell runs, and a substitution
    body that won't parse. Expansions in a git location, and an unparsable command, are
    skipped and logged."""
    bash_words = load_bash_words()
    cmd = command_of(event)
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    gits, ghs, rest = [], [], []
    if not cmd:
        return gits, ghs, False
    if len(cmd) > CMD_MAX:  # parsing it could outlast the budget, or the kill
        if names_a_call(cmd):
            log("git-skipped", f"the command names git commit or push, or gh pr ready or "
                f"create, but is over {CMD_MAX} characters, too long to parse in time, so it "
                "wasn't checked")
        return gits, ghs, False
    try:
        CRUMB.mark("(the command)", "bash", "parse")  # a parse the kill ends leaves a trace
        calls = bash_words.calls(cmd, set(HEADS), cwd, rest,
                                 check=lambda: check_budget("command parse"))
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the {e}; the call was allowed unchecked")
        return [], [], False
    except ValueError as e:
        if names_a_call(cmd):  # a check that failed open, so it counts
            log("git-skipped", f"the command names git commit or push, or gh pr ready or "
                f"create, but couldn't be parsed ({type(e).__name__}), so it wasn't checked")
        else:
            log("bash-unparsed", f"{type(e).__name__}: the command was allowed unchecked")
        return gits, ghs, False
    for name, args, prefix, c in calls:
        if name == "gh":
            ghs.append((args, c))
            if without_repo(args)[:2] not in (["pr", "ready"], ["pr", "create"]):
                rest.append(" ".join(args))  # what a PR call says is its own; others aren't read
            continue
        try:
            g = bash_words.git_call(args, prefix, c)
        except bash_words.Unreadable as e:
            log("git-skipped", f"{e}: an expansion in a git location, so this call wasn't checked")
            continue
        if g:
            gits.append(g)
        if not g or g[0] not in ("commit", "push", "grep"):  # `git submodule foreach git push`
            rest.append(" ".join(args))
    return gits, ghs, any(names_a_call(t) for t in rest)


# Where the Bash levels may read. They run outside the sandbox on a command the model wrote, and
# what they print (paths, line numbers, rule hits) is an oracle for any repo they scan, so a repo
# the command names (`git -C ~/vault`, `--git-dir=`, a planted gitfile, an alternates entry) is
# read only when it is the project's.

ALTERNATES_DEPTH = 5  # git follows nested alternates this deep


def _sessions_file(event):
    key = str(event.get("session_id"))
    return os.path.join(state_dir(), "sessions", hashlib.sha256(key.encode()).hexdigest()[:32]
                        + ".json")


def record_session_cwd(event):
    """At SessionStart: the session's cwd, kept from its first start (a later start may come
    after a cd), as the project dir when CLAUDE_PROJECT_DIR is unset."""
    cwd = event.get("cwd")
    path = _sessions_file(event)
    if not isinstance(cwd, str) or not cwd or os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f"{path}.{os.getpid()}", "w", encoding="utf-8") as f:
            json.dump({"cwd": os.path.abspath(cwd)}, f)
        os.replace(f"{path}.{os.getpid()}", path)
    except OSError as e:
        log("state-error", f"{path}: {e}")


def bash_project(event):
    """The project dir for every level and the health check (config, project skills, the paths L2
    keys and the Bash levels match them by): CLAUDE_PROJECT_DIR, else the cwd recorded at the
    session's start, never the call's own cwd (a cd moves it); None when neither is known."""
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.environ["CLAUDE_PROJECT_DIR"]
    try:
        with open(_sessions_file(event), encoding="utf-8") as f:
            cwd = json.load(f).get("cwd")
    except (OSError, ValueError, RecursionError, AttributeError):
        return None
    return cwd if isinstance(cwd, str) and cwd else None


def under(path, root):
    """Whether path's realpath is root (a realpath) or inside it."""
    p = os.path.realpath(path)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def read_plain(path, cap):
    """Up to cap bytes of a regular file; OSError for anything else, so a FIFO can't block."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        return os.read(fd, cap)
    finally:
        os.close(fd)


def alternates(objects, depth=0):
    """The realpath of each object dir that objects/info/alternates names, then of the ones
    each of those names (lazily, so a caller stops before reading past an outside one); None
    for an entry this can't read (a quoted path), or past git's depth."""
    try:
        text = read_plain(os.path.join(objects, "info", "alternates"), GITCONFIG_MAX).decode(
            "utf-8", "surrogateescape")
    except FileNotFoundError:
        return
    except OSError:
        yield None
        return
    for line in text.split("\n"):  # as git reads it: no stripping, # starts a comment
        if not line or line.startswith("#"):
            continue
        if line.startswith('"') or "\0" in line or depth >= ALTERNATES_DEPTH:
            yield None
            continue
        d = os.path.realpath(os.path.join(objects, line))  # an absolute line stays itself
        yield d
        yield from alternates(d, depth + 1)


class Bounds:
    """Where the Bash levels may read: anything under the project dir, and the project's own
    repo (its git dir, common dir and main worktree, so a lane reads its main checkout's .git).
    The project's repo counts as its own only when its checkout holds the project dir and, for
    a linked worktree, its git dir's `gitdir` file links back to that checkout: a gitfile the
    model planted at the project's top can't claim another repo."""

    def __init__(self, project):
        self.project = os.path.realpath(project)
        self.own = self.main = None
        try:
            r = Repo(self.project)
        except GitError:
            return  # the project isn't in a repo, or git refused it
        gd, cd = os.path.realpath(r.git_dir), os.path.realpath(r.common_dir)
        main = os.path.dirname(cd) if os.path.basename(cd) == ".git" else cd
        if gd == cd:  # a main checkout: the project is in its worktree
            ok = under(self.project, main)
        else:  # a linked worktree, like a lane
            back = None
            try:
                back = read_plain(os.path.join(gd, "gitdir"), 4096).decode(
                    "utf-8", "surrogateescape").strip()
            except OSError:
                pass
            if back and "\0" in back:
                back = None
            top = os.path.realpath(r.top) if r.top else None
            ok = bool(back and top and under(gd, cd) and under(self.project, top)
                      and os.path.realpath(os.path.join(gd, back))
                      == os.path.realpath(os.path.join(top, ".git")))
        if ok:
            self.own, self.main = cd, main

    def allows(self, path):
        """Whether git may run in, or be pointed at, path."""
        return any(under(path, root) for root in (self.project, self.main, self.own) if root)

    def outside(self, repo):
        """What of the repo lies outside these bounds ("git dir", "common dir" or "alternates
        entry", as the log says "the repo's <what> is outside"), or None when all of it is
        inside."""
        gd, cd = os.path.realpath(repo.git_dir), os.path.realpath(repo.common_dir)
        if not (self.own and cd == self.own and under(gd, self.own)):
            if not under(gd, self.project):
                return "git dir"
            if not under(cd, self.project):
                return "common dir"
        for d in alternates(os.path.join(cd, "objects")):
            if d is None or not self.allows(d):
                return "alternates entry"
        return None


def bounds_of(project):
    """The Bounds for the Bash levels' project (bash_project), or None (logged by open_repo)
    when no project dir is known."""
    return Bounds(project) if project else None


def open_repo(where, level, bounds):
    """A Repo for a git call's location, or None (logged) when it can't be read: a cd this
    check can't follow, no project dir known, or a repo outside the project (logged without
    its paths or contents)."""
    if where["cwd"] is None:
        log("git-skipped", f"{level}: a cd this check can't follow, so the call wasn't checked")
        return None
    if bounds is None:
        log("git-skipped", f"{level}: no project dir (CLAUDE_PROJECT_DIR unset and no cwd "
            "recorded at session start), so the call wasn't checked")
        return None
    if not all(bounds.allows(where[k]) for k in ("cwd", "git_dir", "work_tree") if where[k]):
        log("git-skipped", f"{level}: the call names a location outside the project, so it "
            "wasn't checked")
        return None
    try:
        repo = Repo(where["cwd"], where["git_dir"], where["work_tree"])
    except GitError as e:
        if "ownership" in str(e):
            log("git-skipped", f"{level}: {where['cwd']}: {e}")
        return None
    why = bounds.outside(repo)
    if why:
        log("git-skipped", f"{level}: the repo's {why} is outside the project, so the call "
            "wasn't checked")
        return None
    return repo


class Transcripts:
    """The call's own transcript and, for a subagent, the parent's (the payload's
    transcript_path), each mapped; closed on exit."""

    def __init__(self, event):
        self.own, self.parent, self._open = None, None, []
        m, f = open_transcript(event)
        if m is not None:
            self._open.append((m, f))
            self.own = Transcript(m, bool(event.get("agent_id")))
        if event.get("agent_id") and isinstance(event.get("transcript_path"), str):
            try:
                pf = open(event["transcript_path"], "rb")
                pm = (mmap.mmap(pf.fileno(), 0, access=mmap.ACCESS_READ)
                      if os.fstat(pf.fileno()).st_size else b"")
                self._open.append((pm, pf))
                self.parent = Transcript(pm, False)
            except (OSError, ValueError):
                pass

    def all(self):
        return [t for t in (self.own, self.parent) if t is not None]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for m, f in self._open:
            if isinstance(m, mmap.mmap):
                m.close()
            f.close()


def tool_uses(t, needle, names):
    """The input of each assistant tool_use named in names in rows holding needle."""
    for _, _, d in t.hits(needle):
        if d.get("type") != "assistant":
            continue
        for b in blocks(d):
            if b.get("type") == "tool_use" and b.get("name") in names \
                    and isinstance(b.get("input"), dict):
                yield b["input"]


def audited(ts):
    return any(isinstance(inp.get("command"), str) and AUDIT.search(inp["command"])
               for t in ts.all() for needle in (b"audit", b"govulncheck")
               for inp in tool_uses(t, needle, ("Bash",)))


def accepted_at_l2(event):
    """The deny keys of this agent and, for a subagent, the parent's: among them, one per line
    each L2 deny named (`L2|skill|rule|path|sha1(the stripped line)`), accepted at edit time.
    A transcript marker names no line, so it accepts none."""
    keys = set(state_keys(event))
    if event.get("agent_id"):
        keys |= state_keys({**event, "agent_id": None})
    return keys


def commit_rules(skills, cfg, line_only=False):
    return [(s, r) for s in skills.values() for r in s["rules"] if not is_off(cfg, s, r["id"])
            and ("commit" in r.get("at", AT) or (line_only and r.get("scope") == "line"))]


def scan(repo, spec, rules, level, ctx, lockfiles=True):
    """([Finding], cut) for what the commits of rev-list spec add (merges left out, the newest
    MAX_COMMITS, BYTES_MAX of blobs), skipping pure renames and anything but regular files.
    With lockfiles, a changed lockfile with no audit in the transcripts is a SEC-60 finding.
    cut is None when the scan read all it meant to. When the time budget ran out mid-scan
    (logged as scan-truncated), the findings are those read before it and cut is the range's
    cut key, `<level>|engine|cut|-|sha1(git dir and commits)`: a level that denies on them
    keeps it, and a resend of the same range then passes unscanned (logged), rather than
    getting further and being denied again. The key is shared by a level's two passes, so that
    resend passes as the deny said, in both."""
    found, key = [], f"{level}|engine|cut|-|unread"
    try:
        commits, more = repo.commits(*spec, cap=MAX_COMMITS)
        key = f"{level}|engine|cut|-|" + _sha1("\n".join([repo.git_dir, *(c for c, _ in commits)]))
        if key in ctx["seen"]:
            ctx["cut"] = key  # the calls the cut left unchecked pass too (unchecked_key)
            log("scan-truncated", f"{level}: resent after a scan the time budget cut short, so "
                "it passed unscanned")
            return [], None
        _scan(repo, commits, more, rules, level, ctx, lockfiles, found)
    except Budget as e:
        log("scan-truncated", f"{level}: the time budget ran out in the {e}, so what came after "
            "it wasn't scanned")
        ctx["cut"] = key
        return found, key
    return found, None


def unchecked_key(ctx, level, n):
    """The key of the command's call number n (pushes first, then PR calls), which a cut scan
    earlier in the same command left unchecked: tied to that scan's cut key and the command, so
    only a resend of the same command whose cut scan read the same commits passes it."""
    return f"{level}|engine|cut|-|" + _sha1(f"{ctx['cut']}\n{n}\n{ctx['command']}")


def resent_unchecked(ctx, level, n):
    """Whether call n is one a cut scan left unchecked on this command's earlier run, whose
    deny said the resend passes: once this run met that scan's cut key, it passes, logged."""
    if ctx.get("cut") and unchecked_key(ctx, level, n) in ctx["seen"]:
        log("scan-truncated", f"{level}: resent after a scan the time budget cut short left "
            "this call unchecked, so it passed unscanned")
        return True
    return False


def _scan(repo, commits, more, rules, level, ctx, lockfiles, found):
    """scan's body: appends each Finding to found as it is read, so a cut keeps them."""
    if more:
        log("scan-truncated", f"{level}: only the newest {MAX_COMMITS} commits were scanned")
    files = []
    for commit, _ in commits:
        CRUMB.mark(commit[:12], level, "diff-tree")
        changes = repo.changes(None, commit)
        gone = {c[3] for c in changes if c[0] == "D"}
        moved = {c[4] for c in changes if c[0] == "A" and c[4] in gone}
        # A rename with edits shows as a delete and an add: the add is diffed against a
        # regular file this commit deleted with the same basename, so only what it truly
        # adds counts. (diff-tree -M would pair them by content, but its content reads aren't
        # shown to stay objects-only, as GIT_FLAGS requires, so it isn't allowed.)
        deleted = {}
        for status, omode, _, ooid, _, path in changes:
            if status == "D" and omode in ("100644", "100755") and ooid not in moved:
                deleted.setdefault(path.rsplit("/", 1)[-1], []).append(ooid)
        for status, _, nmode, ooid, noid, path in changes:
            if status not in ("A", "M", "T") or nmode not in ("100644", "100755"):
                continue
            if status == "A" and noid in gone:
                continue  # a pure rename: the same blob under a new name
            old, paired = (ooid if status != "A" else None), False
            if status == "A" and deleted.get(path.rsplit("/", 1)[-1]):
                old, paired = deleted[path.rsplit("/", 1)[-1]].pop(0), True
            files.append((commit, path, old, noid, paired))
    locks = [(c, p, n) for c, p, _, n, _ in files if lockfiles and is_lockfile(p)]
    if locks and not is_off(ctx["cfg"], ENGINE, "SEC-60") and not ctx["audited"]():
        for commit, path, noid in locks:
            found.append(Finding(level, ENGINE, SEC60, path, 0, noid, commit))
    wanted = []
    for f in files:
        check_budget("changed-file list")
        if any(not r.get("paths") or path_matches(r["paths"], f[1]) for _, r in rules):
            wanted.append(f)
    blobs, skipped = repo.blobs([x for _, _, o, n, _ in wanted for x in (n, o)], FILE_MAX,
                                BYTES_MAX)
    if skipped:
        log("scan-truncated", f"{level}: {len(skipped)} blobs over the size caps were not read")
    cut = 0
    for commit, path, ooid, noid, paired in wanted:
        new = text_of(blobs.get(noid))
        if new is None:
            continue
        if ooid and ooid not in blobs and paired:
            ooid = None  # a guess at a rename: unread, the file is scanned as all new
        elif ooid and ooid not in blobs:
            cut += 1  # unread, the old blob would make every line of the file read as added
            continue
        old = text_of(blobs[ooid]) if ooid else ""
        added = added_lines(old or "", new)
        if not added:
            continue
        mine = [(s, r) for s, r in rules if not r.get("paths") or path_matches(r["paths"], path)]

        def hits(item, path=path, added=added, new=new):
            s, r = item
            CRUMB.mark(path, level, r["id"])
            got = (line_hits(r, added, ctx["helpers"]) if r.get("scope") == "line"
                   else file_hits(r, added, new, ctx["helpers"]))
            found.extend(Finding(level, s, r, path, n, line, commit) for n, line in got)
            return False

        run_patterns(mine, hits, cut=True)
    if cut:
        log("scan-truncated", f"{level}: {cut} changed files were not scanned: their old blob "
            "was over the size caps, so what they add can't be told")


def fresh(findings, event, repo, project):
    """The findings whose key is new for this session and agent, less those on a line L2
    already denied for that file and rule (its path relative to project, the Bash levels'
    project dir, as L2 keyed it); one per key."""
    seen = state_keys(event)
    l2_keys = accepted_at_l2(event)
    out, keys = [], set()
    for f in findings:
        if f.key in seen or f.key in keys:
            continue
        if f.skill is not ENGINE:
            rel = relative(os.path.join(repo.top or repo.cwd, f.path), project)
            if f"L2|{f.skill['name']}|{f.rule['id']}|{rel}|{f.line_hash}" in l2_keys:
                continue
        keys.add(f.key)
        out.append(f)
    return out


def findings_text(findings, shown=12):
    """The findings by rule: id, skill, the places (path:line, never the matched text), and
    what the rule says."""
    by = {}
    for f in findings:
        by.setdefault((f.skill["name"], f.rule["id"]), (f, []))[1].append(
            f"{f.path}:{f.line_no}" if f.line_no else f.path)
    parts = []
    for (skill, rid), (f, places) in by.items():
        places = list(dict.fromkeys(places))
        more = f", and {len(places) - shown} more" if len(places) > shown else ""
        owner = "the practices engine" if f.skill is ENGINE else skill
        parts.append(f"- {rid} ({owner}) at {', '.join(places[:shown])}{more}: {f.rule['say']}")
    return "\n".join(parts)


def context(event, cfg, ts, project):
    cache = {}

    def was_audited():
        if "a" not in cache:
            CRUMB.mark("(transcript)", "transcript", "audit calls")
            cache["a"] = audited(ts)
        return cache["a"]

    return {"cfg": cfg, "helpers": cfg["helpers"], "audited": was_audited,
            "seen": state_keys(event), "project": project, "command": command_of(event),
            "cut": None, "cut_at": None}


CUT_NOTE = ("The time budget ran out before this check read every commit, so some weren't "
            "checked; these are the findings it read.")
LEFT_NOTE = ("The pushes and PR calls after that point in this command weren't checked either; "
             "resending it unchanged passes them too.")


# L3s: the PreToolUse half records HEAD, the PostToolUse half scans what the commit added.

def _heads_file(event):
    key = f"{event.get('session_id')}|{event.get('agent_id') or 'main'}|{event.get('tool_use_id')}"
    return os.path.join(state_dir(), "heads", hashlib.sha256(key.encode()).hexdigest()[:32]
                        + ".json")


def record_heads(event, commits, bounds):
    """Before a commit call: {git dir: HEAD or None (unborn)} and {git dir: its worktree} for
    each repo it commits in, read where the command's cds and options lead from the call's
    cwd. PostToolUse scans these repos: its own cwd may have moved (`cd sub && git commit`)."""
    heads, tops = {}, {}
    for _, _, where in commits:
        repo = open_repo(where, "L3s", bounds)
        if repo is not None:
            CRUMB.mark(repo.git_dir, "L3s", "record HEAD")
            heads[repo.git_dir] = repo.rev("HEAD")
            tops[repo.git_dir] = repo.top
    path = _heads_file(event)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(f"{path}.{os.getpid()}", "w", encoding="utf-8") as f:
            json.dump({"heads": heads, "tops": tops}, f)
        os.replace(f"{path}.{os.getpid()}", path)
    except OSError as e:
        log("state-error", f"{path}: {e}")


def recorded_heads(event):
    """(heads, tops) that record_heads wrote for this tool_use_id (deleted once read), or None.
    A record without tops (written before they were) reads as tops unknown. The file goes at the
    first read, so a level's second pass gets the same answer."""
    if SCOPE["now"] == "all":
        return _read_heads(event)
    if "record" not in HEADS_READ:
        HEADS_READ["record"] = _read_heads(event)
    return HEADS_READ["record"]


HEADS_READ = {}


def _read_heads(event):
    path = _heads_file(event)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        os.unlink(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as e:
        log("state-error", f"{path}: unreadable ({type(e).__name__}), read as no record")
        return None
    heads = data.get("heads") if isinstance(data, dict) else None
    tops = data.get("tops", {}) if isinstance(data, dict) else None
    if not isinstance(heads, dict) or not isinstance(tops, dict) or not all(
            isinstance(k, str) and (v is None or isinstance(v, str))
            for d in (heads, tops) for k, v in d.items()):
        log("state-error", f"{path}: not a heads record, read as no record")
        return None
    return heads, tops


def post_tool_use(event):
    """L3s: after a commit call, tell the model once per new key what the commits added that a
    rule flags (additionalContext, which reaches the model with the tool result). The repos
    are the ones PreToolUse recorded for this tool_use_id, never a re-parse of the command
    from this event's cwd, which the command's own cd may have moved; with no record nothing
    is scanned, logged."""
    if event.get("tool_name") != "Bash":
        return None
    gits, _, _ = bash_calls(event)
    if not any(g[0] == "commit" for g in gits):
        return None
    project = bash_project(event)
    cfg = load_config(project)
    if not cfg["enabled"]:
        return None
    record = recorded_heads(event)
    if record is None:
        log("git-skipped", "L3s: no repo was recorded before this commit call, so it wasn't "
            "checked")
        return None
    heads, tops = record
    skills = discover(project)
    rules = commit_rules(skills, cfg)
    found, repos, cuts = [], {}, []
    with Transcripts(event) as ts:
        ctx = context(event, cfg, ts, project)
        try:
            bounds = bounds_of(project) if heads else None
            for git_dir, before in heads.items():
                top = tops.get(git_dir)
                where = {"cwd": top or os.path.dirname(git_dir), "git_dir": git_dir,
                         "work_tree": top}
                repo = open_repo(where, "L3s", bounds)  # bounds again: the call ran since
                if repo is None or repo.git_dir in repos:
                    continue
                repos[repo.git_dir] = repo
                head = repo.rev("HEAD")
                if head is None or before == head:
                    continue  # unborn still, or nothing committed
                spec = [head, "--not", before] if before else [head]
                got, cut = scan(repo, spec, rules, "L3s", ctx)
                found += [(f, repo) for f in got]
                if cut:
                    cuts.append(cut)
                    break  # the budget is spent: tell what was read
        except Budget as e:
            log("budget-spent", f"after {BUDGET}s, in the L3s {e}; the repos left went "
                "unchecked")
        except GitError as e:
            log("git-skipped", f"L3s: {e}")
            return None
    new = []
    for repo in repos.values():
        new += fresh([f for f, r in found if r is repo], event, repo, project)
    if not new:
        return None
    state_add(event, [f.key for f in new] + cuts)
    text = ("[practices:L3s] This commit added code that a practices rule flags. Fix it and "
            "amend the commit, or, when one is a false positive, add `practices-allow: <id> "
            "<reason>` to the code (on the flagged line itself for a line-scoped rule) and "
            "amend. Each finding is told once.\n" + (CUT_NOTE + "\n" if cuts else "")
            + findings_text(new))
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}


# The push gate: what a git push would send, scanned before it goes.

PUSH_ARG_OPTS = {"--repo", "--receive-pack", "--exec", "--push-option"}


def push_sources(args):
    """(the source refs a git push sends, why it is skipped or None). No refspec sends HEAD;
    --all, --branches and --mirror send every local branch ("--branches"); a delete
    (--delete, -d, `:ref`) and a dry run (--dry-run, -n) send nothing. In a short-option
    cluster, -o takes the rest of the word as its value (`-onodeploy`), or the next word."""
    srcs, positional, every, i = [], [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a in ("--delete", "--dry-run"):
            return [], "a delete or a dry run"
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            letters = a[1:]
            k = letters.find("o")
            if set(letters if k < 0 else letters[:k]) & {"d", "n"}:
                return [], "a delete or a dry run"
            i += 2 if k == len(letters) - 1 else 1
            continue
        if a in ("--all", "--branches", "--mirror"):
            every = True
        elif a in PUSH_ARG_OPTS:
            i += 1
        elif not a.startswith("-"):
            positional.append(a)
        i += 1
    for spec in positional[1:]:
        spec = spec.lstrip("+")
        src = spec.split(":", 1)[0]
        if src:
            srcs.append(src)
    if every:
        srcs.append("--branches")
    elif not positional[1:]:
        srcs.append("HEAD")
    return srcs, None


def push_gate(event, pushes, skills, cfg, ts, ctx, bounds):
    """(new findings, the cut keys of a scan the budget cut short) for the commits the pushes
    would send that no remote has. Once the budget is spent the pushes left go unchecked,
    logged, and the findings read so far still count."""
    rules = commit_rules(skills, cfg)
    out, cuts = [], []
    try:
        for n, (_, args, where) in enumerate(pushes):
            if resent_unchecked(ctx, "push", n):
                continue
            srcs, skip = push_sources(args)
            if skip:
                log("push-unscanned", f"push: {skip} sends no commits, so it wasn't scanned")
                continue
            if not srcs:  # every refspec is a delete (`:old`)
                log("push-unscanned", "push: a delete refspec sends no commits, so it wasn't "
                    "scanned")
                continue
            if any("$" in s or "%SUBST%" in s for s in srcs):
                log("git-skipped", "push: an expansion in a refspec, so this push wasn't checked")
                continue
            repo = open_repo(where, "push", bounds)
            if repo is None:
                continue
            tips = ["--branches"] if "--branches" in srcs else []
            named = [(s, repo.rev(s)) for s in srcs if s != "--branches"]
            tips += [oid for _, oid in named if oid]
            if any(oid is None for _, oid in named):
                log("git-skipped", "push: a source names no commit here (a glob refspec, say), "
                    "so what it sends wasn't checked")
            if not tips:
                continue
            found, cut = scan(repo, [*tips, "--not", "--remotes"], rules, "push", ctx)
            out += fresh(found, event, repo, ctx["project"])
            if cut:
                cuts.append(cut)
                ctx["cut_at"] = n
                break
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the push {e}; the pushes left went unchecked")
    return out, cuts


def push_reason(findings, cut=False):
    return ("[practices:push] The commits this push would send add code that a practices rule "
            "flags. Fix it in a new commit (or amend one that isn't pushed yet) and push again, "
            "or, when one is a false positive, add `practices-allow: <id> <reason>` to the code "
            "(on the flagged line itself for a line-scoped rule). Resending this push unchanged "
            "passes this check.\n" + (CUT_NOTE + "\n" if cut else "") + findings_text(findings))


# L3r: a PR marked ready (or opened as one) waits for a reviewer briefed with the gate lines.

def without_repo(args):
    """gh's args less -R/--repo and its value wherever it sits before the pr subcommand
    (`gh -R o/r pr ready`, `gh pr --repo o/r ready`); after it, pr_ready reads it itself."""
    out, i, words = [], 0, 0
    while i < len(args):
        a = args[i]
        if words < 2:  # `pr`, then its subcommand
            if a in ("-R", "--repo"):
                i += 2
                continue
            if a.startswith("--repo=") or (a.startswith("-R") and len(a) > 2):
                i += 1
                continue
            words += not a.startswith("-")
        out.append(a)
        i += 1
    return out


def pr_ready(args):
    """None unless args are `gh pr ready` (not --undo) or a `gh pr create` that isn't a draft;
    else {"base": the --base, "branch": the branch a `ready` selector or create's --head names
    (an `owner:` prefix dropped), "pr": a `ready` selector that is a PR number or URL}, each
    None when not given. A -R/--repo before the subcommand is dropped first."""
    args = without_repo(args)
    if len(args) < 2 or args[0] != "pr" or args[1] not in ("ready", "create"):
        return None
    rest, out = args[2:], {"base": None, "branch": None, "pr": None}
    if args[1] == "ready":
        if "--undo" in rest:
            return None
        k, selector = 0, None
        while k < len(rest):
            if rest[k] in ("-R", "--repo"):
                k += 2
                continue
            if not rest[k].startswith("-") and selector is None:
                selector = rest[k]
            k += 1
        if selector and (re.fullmatch(r"#?\d+", selector) or re.match(r"https?://", selector)):
            out["pr"] = selector
        elif selector:
            out["branch"] = selector
        return out
    for k, a in enumerate(rest):
        nxt = rest[k + 1] if k + 1 < len(rest) else None
        if a in ("--draft", "-d", "--draft=true"):
            return None
        for key, short, long_ in (("base", "-B", "--base"), ("branch", "-H", "--head")):
            if a in (short, long_) and nxt is not None:
                out[key] = nxt
            elif a.startswith(long_ + "="):
                out[key] = a.split("=", 1)[1]
            elif a.startswith(short) and len(a) > 2:
                out[key] = a[2:]
    if out["branch"] and ":" in out["branch"]:
        out["branch"] = out["branch"].split(":", 1)[1]  # --head owner:branch, a fork's
    return out


REVIEW_NEEDLE = b"[practices:review:"
REVIEW_MARK = re.compile(r"\[practices:review:([0-9a-f]{12})\]")
REVIEW_MARKS_MAX = 4  # up to three git calls each, from a 2 s budget; an older mark only asks more
REGULAR = ("100644", "100755")
NO_FILE = "000000"  # the mode diff-tree gives a side a file is missing from


def review_marker(head):
    """The marker a reviewer's brief carries for the commit it judges."""
    return f"[practices:review:{head[:12]}]"


def review_marks(ts):
    """The sha12 of each review marker in an Agent or Task prompt in the transcripts."""
    return [m for t in ts.all() for inp in tool_uses(t, REVIEW_NEEDLE, ("Agent", "Task"))
            if isinstance(inp.get("prompt"), str) for m in REVIEW_MARK.findall(inp["prompt"])]


def last_review(repo, marks, head):
    """The nearest of the marked commits that head descends from, or None. A commit the head
    doesn't descend from (a rebased head, a forged marker) clears nothing, and a mark that names
    no commit here is skipped. Only the newest REVIEW_MARKS_MAX distinct marks are tried, each at
    a cost of git calls from the budget."""
    best = None
    for mark in list(dict.fromkeys(reversed(marks)))[:REVIEW_MARKS_MAX]:
        oid = repo.rev(mark)
        if oid and is_ancestor(repo, oid, head) and (best is None or is_ancestor(repo, best, oid)):
            best = oid
    return best


def is_ancestor(repo, old, new):
    return repo.run("merge-base", old, new, ok=(0, 1)).decode().strip() == old


def pr_head(repo, pr):
    """(the commit a PR call is judged at, its branch name, a note for the deny or None), or
    None (logged) when the named branch isn't known here. A branch (a `ready` selector,
    create's --head) is judged at origin/<branch>, else the local branch; anything else at the
    checked-out HEAD, and a PR number or URL says so in the deny, since it may be another
    branch's PR."""
    if pr["branch"]:
        b = pr["branch"]
        head = None if "$" in b or "%" in b else (
            repo.rev(f"refs/remotes/origin/{b}") or repo.rev(f"refs/heads/{b}"))
        if head is None:
            log("git-skipped", "L3r: the PR's branch is neither an origin/<branch> nor a local "
                "branch here, so the PR went unchecked")
            return None
        log("l3r-target", f"L3r: judged the named branch at {head[:12]}")
        return head, b, None
    head = repo.rev("HEAD")
    if head is None:
        return None, None, None
    branch = repo.run("rev-parse", "--abbrev-ref", "HEAD").decode(
        "utf-8", "surrogateescape").strip() or "HEAD"
    if not pr["pr"]:
        return head, branch, None
    log("l3r-target", f"L3r: a PR named by number or URL, judged against {branch} at "
        f"{head[:12]}")
    return head, branch, (f"[practices:L3r] This PR was judged against {branch} at "
                          f"{head[:12]}; run this from the PR's checkout if it is another "
                          "branch.")


def l3r(event, ghs, skills, cfg, ts, ctx, bounds, first=0):
    """(review blocks, their keys, new rule findings, notes, the cut keys of a scan the budget
    cut short) for the PR calls, numbered from first among the command's calls. Once the
    budget is spent the PR calls left go unchecked, logged, and what was found so far still
    counts."""
    out = ([], [], [], [], [])
    try:
        _l3r(event, ghs, skills, cfg, ts, ctx, bounds, first, *out)
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the L3r {e}; the PR calls left went "
            "unchecked")
    return out


def _l3r(event, ghs, skills, cfg, ts, ctx, bounds, first, blocks_, keys, found, notes, cuts):
    """l3r's body: appends to its lists as it goes, so a spent budget keeps what was found."""
    for n, (args, cwd) in enumerate(ghs, first):
        if resent_unchecked(ctx, "L3r", n):
            continue
        pr = pr_ready(args)
        if pr is None:
            continue
        repo = open_repo({"cwd": cwd, "git_dir": None, "work_tree": None}, "L3r", bounds)
        if repo is None:
            continue
        target = pr_head(repo, pr)
        if target is None:
            continue
        head, branch, note = target
        base_name = pr["base"]
        names = ([f"refs/remotes/origin/{base_name}", base_name] if base_name else
                 ["refs/remotes/origin/HEAD", "refs/remotes/origin/main",
                  "refs/remotes/origin/master"])
        base = next((oid for n in names if "$" not in n and (oid := repo.rev(n))), None)
        if head is None or base is None:
            log("git-skipped", f"L3r: no base branch found ({', '.join(names)}), so the PR "
                "went unchecked")
            continue
        mb = repo.run("merge-base", base, head, ok=(0, 1)).decode().strip()
        if not mb:
            log("git-skipped", "L3r: the branch shares no history with its base, unchecked")
            continue
        diff = repo.changes(mb, head)
        events = [(s, ev) for s in skills.values() for ev in s["events"]
                  if not is_off(cfg, s, ev["id"])]
        touched = watched(repo, versions(diff), events, cfg)
        told = (len(blocks_), len(found))
        touched, prior = carried_over(ts, touched, repo, diff, head, mb, base, events, cfg)
        if prior and not touched:
            log("l3r-reuse", f"L3r: {head[:12]} keeps the review of {prior[:12]}: "
                "nothing a skill watches changed since")
        new = [(s, paths) for s, paths in touched.values()
               if (k := f"L3r|{s['name']}|review|-|{_sha1(head)}") not in state_keys(event)
               and k not in keys]
        if new:
            keys += [f"L3r|{s['name']}|review|-|{_sha1(head)}" for s, _ in new]
            blocks_.append(review_block(new, mb, head, branch, prior=prior))
        rules = commit_rules(skills, cfg, line_only=True)
        got, cut = scan(repo, [head, "--not", mb], rules, "L3r", ctx, lockfiles=False)
        found += fresh(got, event, repo, ctx["project"])
        if note and (len(blocks_), len(found)) != told:
            notes.append(note)
        if cut:
            cuts.append(cut)
            ctx["cut_at"] = n
            return


def versions(rows):
    """Each version of a file the diff rows show, as (path, blob), so a skill sees the code a
    change adds and the code it takes away. A link or gitlink has no text, so its blob is None
    and only its path is read. New ends come first: the blob cap then drops old ones."""
    def side(mode, oid):
        return oid if mode in REGULAR else None
    return ([(c[5], side(c[2], c[4])) for c in rows if c[2] != NO_FILE]
            + [(c[5], side(c[1], c[3])) for c in rows if c[1] != NO_FILE])


def watched(repo, files, events, cfg):
    """{skill name: (skill, its paths)} among files, a list of (path, blob), that fire an event."""
    blobs, _ = repo.blobs([oid for _, oid in files], FILE_MAX, BYTES_MAX)
    hits = {}
    for path, oid in files:
        if time.monotonic() - START > BUDGET:  # keep what the files read so far have told
            log("budget-spent", f"after {BUDGET}s, L3r stopped reading the changed files")
            break
        text = scan_text(text_of(blobs.get(oid)) or "")
        for s, _ in run_patterns(events, lambda x: event_fires(x[1], path, text,
                                                              cfg["helpers"], CRUMB)):
            hits.setdefault(s["name"], (s, []))[1].append(path)
    return hits


def carried_over(ts, touched, repo, diff, head, mb, base, events, cfg):
    """(what still needs a review, the commit last reviewed or None). A budget spent on the way
    keeps touched whole, so what the head pass found still reaches the deny."""
    try:
        marks = review_marks(ts)
        if head[:12] in marks:
            return {}, None
        prior = last_review(repo, marks, head)
        return (review_delta(repo, touched, diff, prior, mb, base, events, cfg), prior) \
            if prior else (touched, None)
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the L3r {e}; asking for a whole review")
        return touched, None


def review_delta(repo, touched, diff, prior, mb, base, events, cfg):
    """What a review of prior didn't see, in watched()'s form. A PR's change to a file is its pair
    of ends: the blob on the base and the blob on the branch. That pair is compared at the two
    commits, prior against the base it held and the head (diff) against mb, so any file whose
    pair differs is new work: edited since, kept over a fix on the base, dropped back to the
    base's blob, deleted, moved, made a link or retargeted. A file a clean merge took from the
    base has no pair at either. Touched files in that list stay as read, so a size cap on this
    second read can't quiet one. Every file in it is then read at each version() of both pairs,
    so one that's gone since the review counts, and so does a skill that fires only on what the
    review saw; past the caps, only its path is read. Prior sharing no history with the base
    shows nothing, so touched stands.
    Known limits: a marker names no base, so `gh pr create --base <older>` widens the diff with
    what the review never saw, and a merge of history the local base ref doesn't hold yet (an
    unfetched or other remote's main) reads as the branch's own. A budget that ends during this
    second read loses only versions the head pass never read, so the head's own watched code
    still counts. The gate denies once and the resend passes, so each costs a prompt, not a
    boundary."""
    held = repo.run("merge-base", prior, base, ok=(0, 1)).decode().strip()
    if not held:
        return touched
    was = {c[5]: c for c in repo.changes(held, prior)}
    now = {c[5]: c for c in diff}
    new = {p for p in was.keys() | now.keys()
           if (was[p][1:5] if p in was else None) != (now[p][1:5] if p in now else None)}
    out = {name: (s, kept) for name, (s, paths) in touched.items()
           if (kept := [p for p in paths if p in new])}
    rows = [c for p in sorted(new) for c in (now.get(p), was.get(p)) if c]
    for name, (s, paths) in watched(repo, versions(rows), events, cfg).items():
        out.setdefault(name, (s, []))[1].extend(paths)
    return out


def review_block(touched, mb, head, branch, shown=8, prior=None):
    """The deny's text. With prior, the commit last reviewed, it asks for the delta alone, naming
    every file: the marker clears them all, so none may hide behind "and N more"."""
    if prior:
        shown = None
    check = ("Read its SKILL.md, check every must-hold line against the changed code, and report "
             "each one that doesn't hold, with file and line. Try to disprove each finding before "
             "you report it, and when one rests on a deployment fact you can't see, report it as "
             "needs validation instead of guessing.")
    first = (f"Review only what changed in {branch} since its last review at {prior[:12]}: the "
             f"files listed below, comparing each at that commit, on the base ({mb[:12]}) and at "
             f"the head ({head[:12]}), against each practices skill below. {check}" if prior else
             f"Review the changes of {branch} ({mb[:12]}..{head[:12]}) against each practices "
             f"skill below. {check}")
    parts = [f"{review_marker(head)} {first}"]
    for s, paths in touched:
        paths = list(dict.fromkeys(paths))
        more = f", and {len(paths) - shown} more" if shown and len(paths) > shown else ""
        parts.append(f"{s['name']} ({os.path.join(s['dir'], 'SKILL.md')}), for "
                     f"{', '.join(paths[:shown])}{more}:" + "".join(
                         f"\n- {line}" for line in s["gate"]))
    lead = ("[practices:L3r] This PR changed code that practices skills own since its last "
            "review. Start a reviewer (the Agent tool) with the block below in its prompt; a "
            "smaller model such as Sonnet is enough for a delta. Fix what it reports, then "
            "resend; this check won't stop the resend." if prior else
            "[practices:L3r] This PR changes code that practices skills own, and no reviewer "
            "agent has checked it against them in this session. Start a reviewer (the Agent "
            "tool) with the block below in its prompt, fix what it reports, then resend; this "
            "check won't stop the resend.")
    return lead + "\n\n" + "\n\n".join(parts)


# ---------------------------------------------------------------- SEC-64, the install check

SEC64 = {"id": "SEC-64", "say": (
    "Read a package's install scripts before its first install, or install with scripts off.")}
SEC64_SHARE = 0.5  # of BUDGET, counted from the start of the run; the git levels keep the rest
NPM_FAMILY = {"npm", "pnpm", "yarn", "bun"}
PY_MANAGERS = {"pip", "uv", "poetry"}
# Each manager's words that add a package named after them. npm's are its documented aliases.
ADD_VERBS = {
    "npm": {"add", "install", "i", "in", "ins", "inst", "insta", "instal", "isnt", "isnta",
            "isntal", "isntall", "install-test", "it"},
    "pnpm": {"add", "install", "i"}, "yarn": {"add", "install", "i"},
    "bun": {"add", "a", "install", "i"}, "pip": {"install"}, "uv": {"add"}, "poetry": {"add"},
    "cargo": {"add"}, "bundle": {"add"}, "gem": {"install", "i"},
    "composer": {"require", "r", "req", "requ", "requi", "requir"}}
# The common options that take the next word, so it isn't read as a package.
_NODE_VALUES = {"--prefix", "--registry", "--tag", "--cache", "--userconfig", "--globalconfig",
                "--workspace", "--omit", "--include", "--loglevel", "--save-prefix", "--otp",
                "--before", "--install-strategy", "--pack-destination", "--cwd", "--dir",
                "--filter", "--filter-prod", "--store-dir", "--modules-folder", "--cache-folder",
                "--cache-dir", "--reporter", "--network-timeout", "--config", "--proxy",
                "--https-proxy", "--cpu", "--os", "--libc", "--allow-git", "--min-release-age",
                "--global-dir", "--virtual-store-dir", "--backend", "--ca", "--cafile",
                "--linker", "--concurrent-scripts", "--network-concurrency",
                "--minimum-release-age", "--mode", "--location", "--maxsockets"}
# The common boolean long options (any other `--no-...` is one too). The word after any other
# `--option` without `=` may be its value, a token included, so split_args reports it as
# ambiguous and it is never read as a package.
NODE_FLAGS = {"--save", "--save-dev", "--save-prod", "--save-optional", "--save-peer",
              "--save-exact", "--save-bundle", "--save-text-lockfile",
              "--save-workspace-protocol", "--workspace", "--global", "--force", "--dry-run",
              "--ignore-scripts",
              "--foreground-scripts", "--legacy-peer-deps", "--legacy-bundling", "--global-style",
              "--strict-peer-deps", "--prefer-dedupe", "--package-lock", "--package-lock-only",
              "--workspaces", "--include-workspace-root", "--workspace-root", "--install-links",
              "--audit", "--fund", "--bin-links", "--silent", "--quiet", "--verbose", "--json",
              "--offline", "--prefer-offline", "--prefer-online", "--yes", "--dev",
              "--peer", "--optional", "--exact", "--tilde", "--production", "--frozen-lockfile",
              "--pure-lockfile", "--lockfile-only", "--recursive", "--aggregate-output",
              "--stream", "--use-stderr", "--fail-if-no-match", "--yarn", "--analyze",
              "--only-missing", "--trust", "--ignore-engines", "--ignore-optional",
              "--ignore-platform", "--ignore-workspace-root-check", "--non-interactive", "--flat",
              "--har", "--interactive", "--cached", "--prefer-dev", "--help", "--version",
              "--unsafe-perm", "--engine-strict", "--shamefully-hoist"}
_PIP_FLAGS = {"--upgrade", "--user", "--force-reinstall", "--ignore-installed", "--pre", "--quiet",
              "--verbose", "--no-input", "--dry-run", "--require-hashes",
              "--break-system-packages", "--isolated", "--compile", "--prefer-binary",
              "--ignore-requires-python", "--use-pep517", "--check-build-dependencies", "--debug",
              "--require-virtualenv", "--disable-pip-version-check", "--help", "--version"}
FLAGS = {
    "npm": NODE_FLAGS, "pnpm": NODE_FLAGS, "yarn": NODE_FLAGS, "bun": NODE_FLAGS,
    "pip": _PIP_FLAGS,
    "uv": _PIP_FLAGS | {"--dev", "--raw", "--frozen", "--locked", "--lfs", "--active", "--workspace",
                        "--reinstall", "--compile-bytecode", "--refresh", "--offline",
                        "--all-extras", "--system", "--exact", "--strict", "--managed-python",
                        "--system-certs"},
    "poetry": {"--dev", "--dry-run", "--lock", "--allow-prereleases", "--editable", "--quiet",
               "--verbose", "--ansi", "--help", "--version"},
    "cargo": {"--dev", "--build", "--optional", "--dry-run", "--locked", "--offline", "--frozen",
              "--default-features", "--public", "--ignore-rust-version", "--quiet", "--verbose",
              "--help"},
    "bundle": {"--skip-install", "--strict", "--optimistic", "--quiet"},
    "gem": {"--user-install", "--conservative", "--force", "--prerelease", "--development",
            "--development-all", "--minimal-deps", "--ignore-dependencies", "--local", "--remote",
            "--both", "--quiet", "--silent", "--verbose", "--help"},
    "composer": {"--dev", "--no-update", "--no-install", "--with-all-dependencies", "-W",
                 "--with-dependencies", "--prefer-dist", "--prefer-source", "--sort-packages",
                 "--update-with-dependencies", "--dry-run", "--quiet", "--verbose", "--ansi",
                 "--help", "--version"}}
_PIP_VALUES = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-t", "--target",
               "--prefix", "--root", "--src", "-i", "--index-url", "--extra-index-url", "-f",
               "--find-links", "--platform", "--python-version", "--implementation", "--abi",
               "--no-binary", "--only-binary", "--trusted-host", "--proxy", "--cert",
               "--client-cert", "--timeout", "--retries", "--log", "--cache-dir", "--progress-bar",
               "--upgrade-strategy", "--report", "--config-settings", "--python", "-p",
               "--use-feature", "--use-deprecated", "--exists-action", "--root-user-action",
               "--global-option", "--keyring-provider"}
VALUE_OPTS = {
    "npm": _NODE_VALUES | {"-w", "-C"},
    "pnpm": (_NODE_VALUES - {"--workspace"}) | {"-C", "-F"},  # pnpm's -w and --workspace take none
    "yarn": _NODE_VALUES,
    "bun": _NODE_VALUES | {"-c"},
    "pip": _PIP_VALUES,
    "uv": _PIP_VALUES | {"--project", "--directory", "--package", "--group", "--optional",
                         "--index", "--default-index", "--branch", "--tag", "--rev", "-C",
                         "--extra", "--exclude-newer", "--exclude-newer-package", "--script",
                         "--requirements", "--constraints", "--overrides", "--excludes",
                         "-m", "--marker", "-b", "--build-constraints", "--bounds",
                         "--index-strategy", "-P", "--upgrade-package", "--upgrade-group",
                         "--resolution", "--prerelease", "--fork-strategy",
                         "--reinstall-package", "--refresh-package", "--link-mode",
                         "--config-setting", "--config-settings-package", "--config-file",
                         "--color", "--allow-insecure-host", "--python-platform",
                         "--torch-backend", "--no-build-package", "--no-binary-package",
                         "--no-sources-package", "--no-install-package",
                         "--no-build-isolation-package"},
    "poetry": {"-C", "--directory", "-P", "--project", "-G", "--group", "-E", "--extras",
               "--source", "--python", "--platform", "--markers"},
    "cargo": {"-F", "--features", "--rename", "--path", "--git", "--branch", "--tag", "--rev",
              "--registry", "--manifest-path", "-p", "--package", "--target", "--config",
              "--lockfile-path", "--color", "-Z"},
    "bundle": {"-v", "--version", "-g", "--group", "-s", "--source", "-r", "--require", "--path",
               "--git", "--github", "--branch", "--ref", "--glob"},
    "gem": {"-v", "--version", "-i", "--install-dir", "-n", "--bindir", "-s", "--source", "-p",
            "--http-proxy", "--platform", "--document", "--build-root"},
    "composer": {"-d", "--working-dir", "--with"}}
# The words that come before a manager's add verb, so an unlisted option doesn't take them.
BEFORE_VERB = {"yarn": {"global", "workspace"}, "composer": {"global"}, "uv": {"pip"}}
SOURCE_OPTS = {"-e", "--editable", "--git", "--github"}  # their value can be a remote source
PIP_HEAD = re.compile(r"pip\d*(?:\.\d+)?")  # pip3, pip3.12
INTERPRETER = re.compile(r"python\d*(?:\.\d+)?")  # `python3.12 -m pip install x`
LAUNCHERS = {"xargs", "find", "fd", "parallel", "ssh", "watch", "eval", "setsid", "flock", "dash",
             "ksh", "corepack", "mise", "asdf", "volta"} | {"bash", "sh", "zsh"}
RUNNERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye", "bundle"} | NPM_FAMILY
RUN_WORDS = {"run", "exec", "x", "dlx"}
# Named so a wrapper's `sudo -E pip3.12 ...` isn't taken for the wrapper's own argument.
INSTALL_HEADS = (set(ADD_VERBS) | set(HEADS) | LAUNCHERS | {"pip3", "python", "python3"}
                 | {f"{name}3.{minor}" for name in ("pip", "python") for minor in range(7, 20)})
MANAGER_NAMED = re.compile(r"(?<![\w.-])(?:npm|pnpm|yarn|bun|pip3?|uv|poetry|cargo|bundle|gem"
                           r"|composer)(?![\w-])")
ADD_NAMED = re.compile(r"(?<![\w-])(?:add|install|i|req|requ|requi|requir|require)(?![\w-])")
LOCAL_PREFIX = (".", "/", "~", "file:", "link:", "workspace:", "portal:")  # `.[dev]` too
ARCHIVE_SUFFIX = (".tgz", ".tar", ".tar.gz", ".tar.bz2", ".zip", ".whl", ".gem", ".crate")
_NAME = r"[A-Za-z0-9][\w.-]{0,213}"
NPM_PACKAGE = re.compile(rf"((?:@[a-z0-9][\w.-]{{0,213}}/)?{_NAME})(?:@([^/:\s]*))?", re.ASCII)
COMPOSER_PACKAGE = re.compile(rf"({_NAME}/{_NAME})(?::\S*)?", re.ASCII)
OTHER_PACKAGE = re.compile(  # requests[socks]>=2, serde@1, rails:7.0, x (>=1,<2)
    rf"({_NAME})(?:\[[^\]]*\])?(?:@[^/:\s]*|:[^/\s]*|\s*[=<>!~;(^].*)?", re.ASCII | re.DOTALL)
SPEC_SHOWN = re.compile(r"[\w.^~+-]{1,64}", re.ASCII)  # a version spec the deny may repeat
VIEW_VERBS = {"npm": {"view", "info", "show", "v"}, "pnpm": {"view", "info", "show", "v"},
              "yarn": {"info"}, "bun": {"info"}}
# The tar options whose effect on what it prints is known; any other means it counts as no read.
# f takes the archive and C a value that isn't a member; the rest take none or `=value`.
TAR_SHORT = set("xOzjJZvfCopm")
TAR_LONG = {"--extract": "x", "--get": "x", "--to-stdout": "O", "--file": "f", "--directory": "C",
            "--strip-components": "C", "--gzip": "z", "--gunzip": "z", "--ungzip": "z",
            "--bzip2": "j", "--xz": "J", "--verbose": "v", "--wildcards": "v",
            "--no-same-owner": "o", "--no-same-permissions": "v"}
# What prints a package.json named as its argument, unlike echo, ls or test. A filter prints only
# what it's asked for, so one must also name the scripts (or be jq's whole-file `.`).
FILE_READERS = {"cat", "head", "tail", "less", "more", "bat"}
FILE_FILTERS = {"jq", "grep", "egrep", "rg", "sed", "awk", "node", "python", "python3"}
# The redirections that leave stdout in the call's result: `2>`, `2>>`, `2>&1`, `>&2`, and `>(` is
# a process substitution. Any other `>` sends it away.
KEPT_OUTPUT = re.compile(r"(?:(?<!\w)\d+)?>&\d+(?!\w)|(?<!\w)(?:[02-9]|\d\d+)>>?\|?|>\(")
CAPTURED = re.compile(r"`|\$\(\s*(?:npm|pnpm|yarn|bun|tar)\b")  # `$(mktemp -d)` is fine
STDERR_AWAY = re.compile(r"(?<!\w)2>>?\s*[^&\s].*>&2|>&2.*(?<!\w)2>>?\s*[^&\s]")  # takes stdout too
UNNAMED = "?"  # the state key's package for a call with an ambiguous word: it names none


class EveryHead(frozenset):
    """The heads for calls(): every command comes back with its name, so what is left in rest is
    only what the reader couldn't read, and read_installs judges each command by its name. The
    elements are the names a wrapper's option word mustn't swallow."""

    def __contains__(self, name):
        return True


def names_an_install(text):
    """Whether text names a package manager and, after it, an add verb, word by word."""
    m = MANAGER_NAMED.search(text)
    return bool(m and ADD_NAMED.search(text, m.end()))


def split_args(args, value_opts, flags=None, verbs=()):
    """(positional words, option words, whether a word is ambiguous) of a manager's arguments. An
    option in value_opts takes the next word and `--flag true|false` its boolean, both folded to
    `<option>=<value>`. With flags, the word after any other `--option` without `=` could be its
    value or a package: it is dropped and reported as ambiguous, unless it is one of verbs and no
    positional word came before it. Every word after `--` is positional."""
    words, opts, ambiguous, i = [], [], False, 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            words.extend(args[i:])
            break
        if not a.startswith("-") or a == "-":
            words.append(a)
        elif i < len(args) and (a in value_opts
                                or (a.startswith("--") and args[i] in ("true", "false"))):
            opts.append(f"{a}={args[i]}")
            i += 1
        else:
            opts.append(a)
            if (flags is not None and i < len(args) and a.startswith("--") and "=" not in a
                    and a not in flags and not a.startswith("--no-")
                    and not args[i].startswith("-") and (words or args[i] not in verbs)):
                ambiguous = True
                i += 1
    return words, opts, ambiguous


def install_of(head, args):
    """(manager, the words after the add verb, option words, whether a word is ambiguous) when
    this simple command is a manager's add verb, else None."""
    if INTERPRETER.fullmatch(head):
        at = args.index("-m") if "-m" in args else len(args)
        if not PIP_HEAD.fullmatch("".join(args[at + 1:at + 2])):
            return None
        head, args = "pip", args[at + 2:]
    manager = "pip" if PIP_HEAD.fullmatch(head) else head
    if manager not in ADD_VERBS:
        return None
    if manager == "gem" and "--" in args:  # what follows goes to the gem's build, not to gem
        args = args[:args.index("--")]
    words, opts, ambiguous = split_args(args, VALUE_OPTS[manager], FLAGS[manager],
                                        ADD_VERBS[manager] | BEFORE_VERB.get(manager, set()))
    if manager in ("yarn", "composer") and words[:1] == ["global"]:
        words = words[1:]
    elif manager == "yarn" and words[:1] == ["workspace"]:  # `yarn workspace web add x`
        words = words[2:]
    if manager == "uv" and words[:2] == ["pip", "install"]:
        return manager, words[2:], opts, ambiguous
    if not words or words[0] not in ADD_VERBS[manager]:
        return None
    return manager, words[1:], opts, ambiguous


def scripts_off(manager, opts):
    """Whether these options stop the install running a package's code. npm reads the last one."""
    if manager in NPM_FAMILY:
        off = manager == "yarn" and "--mode=skip-build" in opts  # later Yarn's spelling
        for o in opts:
            if o in ("--ignore-scripts", "--ignore-scripts=true"):
                off = True
            elif o in ("--ignore-scripts=false", "--no-ignore-scripts"):
                off = False
        return off
    if manager in ("pip", "uv"):  # --no-binary takes a package back out of --only-binary
        return ("--only-binary=:all:" in opts or (manager == "uv" and "--no-build" in opts)) \
            and not any(o.startswith("--no-binary") for o in opts)
    return False


def source_in_options(opts):
    """Whether an option's value names a remote source: `-e git+https://...`, `--git <url>`."""
    for o in opts:
        name, eq, value = o.partition("=")
        if eq and name in SOURCE_OPTS and (name in ("--git", "--github") or "://" in value
                                           or value.startswith("git+")):
            return True
    return False


def npm_word(word):
    """The registry package an npm-family word names: `x@npm:real@1` installs real@1."""
    return word.split("@npm:", 1)[1] if "@npm:" in word else word


def npm_spec(word):
    """The version spec in an npm-family word, None for none or `latest`: `x` means the latest."""
    m = NPM_PACKAGE.fullmatch(npm_word(word))
    spec = m.group(2) if m else None
    return None if spec in (None, "", "latest") else spec


def package_of(manager, word):
    """(package name, version stripped; whether the word is readable). A local path or file is
    (None, True), never an add from a registry; a word no pattern fits is (None, False)."""
    if word.startswith(LOCAL_PREFIX) or ("://" not in word and (
            word.endswith(ARCHIVE_SUFFIX) or (manager in PY_MANAGERS and "/" in word))):
        return None, True
    if manager in NPM_FAMILY:
        m = NPM_PACKAGE.fullmatch(npm_word(word))
    elif manager == "composer":
        if not re.search(r"[/$%]", word):
            return None, True  # the version word of `composer require vendor/pkg ^1.0`
        m = COMPOSER_PACKAGE.fullmatch(word)
    else:
        m = OTHER_PACKAGE.fullmatch(word)
    return (m.group(1), True) if m else (None, False)


def flat_name(pkg):
    """The name in the tarball npm pack writes: @scope/name packs to scope-name-<version>.tgz."""
    return pkg[1:].replace("/", "-") if pkg.startswith("@") else pkg


def tarball_version(word, pkg):
    """The version in word when it names pkg's tarball, else None."""
    m = re.fullmatch(re.escape(flat_name(pkg)) + r"-([\d*][\w.*+-]*)\.(?:tgz|tar\.gz)",
                     word.rsplit("/", 1)[-1], re.ASCII)
    return m.group(1) if m else None


def tar_parts(args):
    """(mode letters, archives, member words) of a tar's arguments, or None for an option whose
    effect on what it prints isn't known here."""
    modes, archives, members, taking = set(), [], [], []
    for n, a in enumerate(args):
        if taking:
            if taking.pop(0) == "f":
                archives.append(a)
        elif a.startswith("--"):
            name, eq, value = a.partition("=")
            if name not in TAR_LONG:
                return None
            modes.add(TAR_LONG[name])
            if TAR_LONG[name] in "fC" and not eq:
                taking.append(TAR_LONG[name])
            elif TAR_LONG[name] == "f":
                archives.append(value)
        elif (a.startswith("-") and a != "-") or n == 0:  # `-xOzf file`, or the old `xOzf file`
            letters = a.lstrip("-")
            for m, c in enumerate(letters):
                if c not in TAR_SHORT:
                    return None
                modes.add(c)
                if c in "fC" and a.startswith("-") and letters[m + 1:]:  # `-fname` holds its value
                    if c == "f":
                        archives.append(letters[m + 1:])
                    break
                if c in "fC":
                    taking.append(c)
        else:
            members.append(a)
    return modes, archives, members


def is_manifest(word):
    """Whether a tar member word names a package.json."""
    return word.rsplit("/", 1)[-1] == "package.json"


def reads_unpacked(head, words):
    """Whether this command prints the package.json a tarball unpacks to, package/package.json:
    a bare one, or another folder's, is the repo's own."""
    if not any(w == "package/package.json" or w.endswith("/package/package.json") for w in words):
        return False
    return head in FILE_READERS or (head in FILE_FILTERS and any(
        "script" in w or (head == "jq" and w == ".") for w in words))


def tar_reads(args, pkg, spec, read_after):
    """Whether this tar's output can show pkg's scripts: it prints the whole tarball or a member
    naming package.json, or extracts those with read_after, a later command of the call printing
    a package.json. A tarball's version, unlike a view's spec, is what `npm pack x` resolved `x`
    to, so it differs only from another pinned spec, and a pinned install needs the version
    spelled out."""
    parts = tar_parts(args)
    if parts is None or "x" not in parts[0]:
        return False
    modes, archives, members = parts
    if members and not any(is_manifest(m) for m in members):
        return False
    return ("O" in modes or read_after) and any(
        v and (spec is None or v == spec)
        for v in (tarball_version(a, pkg) for a in archives))


def inspects(head, args, pkg, spec, read_after=False):
    """Whether this simple command shows pkg's install scripts, for the spec being installed:
    a manager's view naming scripts, or with --json and no named fields (named fields print only
    those; a bare view shows no scripts), or tar reading its tarball. A view's spec must equal
    the install's, None meaning unversioned or latest."""
    if head == "tar":
        return tar_reads(args, pkg, spec, read_after)
    if head not in VIEW_VERBS:
        return False
    words, opts, _ = split_args(args, VALUE_OPTS[head])
    if len(words) < 2 or words[0] not in VIEW_VERBS[head]:
        return False
    if package_of(head, words[1])[0] != pkg or npm_spec(words[1]) != spec:
        return False
    fields = words[2:]
    if fields:
        return "scripts" in fields  # `scripts.test` shows one script, not what runs at install
    return "--json" in opts or "--json=true" in opts


def hides_output(command):
    """Whether this Bash command redirects stdout, holds `||`, or captures a manager's or tar's
    output, anywhere: blunt, since a false answer costs one deny and a true one can hide the only
    output the model would read."""
    return ("||" in command or ">" in KEPT_OUTPUT.sub(" ", command)
            or bool(CAPTURED.search(command) or STDERR_AWAY.search(command)))


def command_inspects(command, pkg, spec):
    """Whether a Bash command from the transcript holds an inspection of pkg."""
    if len(command) > CMD_MAX or hides_output(command):
        return False
    try:
        calls = load_bash_words().calls(command, EveryHead(INSTALL_HEADS | {"tar"}), None,
                                        check=lambda: check_budget("command parse"))
    except ValueError:
        return False
    return any(
        inspects(head, args, pkg, spec, any(
            reads_unpacked(later, words) for later, words, _, _ in calls[n + 1:]))
        for n, (head, args, _, _) in enumerate(calls))


def bash_rows(t, needle):
    """(command, tool id, row end) of each assistant Bash call in the rows holding needle, less
    a background call, whose output the result doesn't hold."""
    for _, end, d in t.hits(needle):
        if d.get("type") != "assistant":
            continue
        for b in blocks(d):
            inp = b.get("input")
            command = inp.get("command") if isinstance(inp, dict) else None
            if b.get("type") == "tool_use" and b.get("name") == "Bash" \
                    and isinstance(command, str) and not inp.get("run_in_background"):
                yield command, b.get("id"), end


def tool_ids(d):
    return {b.get("id") for b in blocks(d) if b.get("type") == "tool_use"}


def same_message(t, tool_id):
    """The ids of the tool calls in the assistant message holding tool_id. Claude Code writes one
    row per block, each with the message's id, before the calls run."""
    ids = set()
    if not isinstance(tool_id, str) or not tool_id:
        return ids
    for _, _, d in t.hits(json.dumps(tool_id).encode()):
        if d.get("type") != "assistant" or tool_id not in tool_ids(d):
            continue
        ids |= tool_ids(d)
        msg_id = d["message"].get("id")
        if isinstance(msg_id, str) and msg_id:
            ids |= {i for _, _, m in t.hits(json.dumps(msg_id).encode())
                    if m.get("type") == "assistant" and isinstance(m.get("message"), dict)
                    and m["message"].get("id") == msg_id for i in tool_ids(m)}
    return ids


def inspected_earlier(event, wanted):
    """Those of wanted, (package, spec) pairs, that a Bash call with a result that isn't an error
    inspected, in this transcript or, for a subagent, the parent's. A call in the install's own
    assistant message doesn't count: the model hasn't read its result. A tarball's name holds
    only the flat name."""
    CRUMB.mark("(the transcript)", "transcript", "SEC-64")
    read = set()
    with Transcripts(event) as ts:
        for t in ts.all():
            siblings = same_message(t, event.get("tool_use_id"))
            read |= {(pkg, spec) for pkg, spec in wanted if any(
                tool_id not in siblings and command_inspects(command, pkg, spec)
                and t.succeeded(tool_id, end)
                for needle in {pkg, flat_name(pkg)}
                for command, tool_id, end in bash_rows(t, needle.encode()))}
    return read


def launches(head, args):
    """Whether this command runs what its arguments name, as `echo`'s or `sed`'s text doesn't."""
    if head in LAUNCHERS:
        return True
    if head in RUNNERS:
        return next((a for a in args if not a.startswith("-")), None) in RUN_WORDS
    return head in HEADS and "foreach" in args


def read_installs(event):
    """([(manager, package, version spec)] this call would add with scripts on, in order, each
    spec of a package kept; whether part of it couldn't be read; the managers with a word that
    may be a package or an option's value)."""
    cmd = command_of(event)
    if not cmd or not MANAGER_NAMED.search(cmd):
        return [], False, []
    if len(cmd) > CMD_MAX:
        return [], names_an_install(cmd), []
    rest, found, unread, ambiguous = [], [], False, []
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    CRUMB.mark("(the command)", "bash", "SEC-64")
    try:
        calls = load_bash_words().calls(cmd, EveryHead(INSTALL_HEADS), cwd, rest,
                                        check=lambda: check_budget("command parse"))
    except ValueError:
        return [], names_an_install(cmd), []
    for head, args, _, _ in calls:
        add = install_of(head, args) if head else None
        if add is None:
            if head and launches(head, args):
                rest.append(" ".join(args))
            continue
        manager, words, opts, unsure = add
        if scripts_off(manager, opts):
            continue
        unread = unread or source_in_options(opts)
        if unsure and manager not in ambiguous:
            ambiguous.append(manager)
        for word in words:
            pkg, readable = package_of(manager, word)
            unread = unread or not readable
            item = (manager, pkg, npm_spec(word) if manager in NPM_FAMILY else None)
            if pkg and item not in found:
                found.append(item)
    return found, unread or any(names_an_install(t) for t in rest), ambiguous


def install_key(manager, pkg, _spec=None):
    """The state key: per manager and package name, never per version."""
    if manager in PY_MANAGERS:  # PEP 503: Foo_Bar and foo-bar are one package
        pkg = re.sub(r"[-_.]+", "-", pkg).lower()
    return f"SEC-64|engine|{manager}|{pkg}"


def install_reason(found, unnamed=False):
    """The deny for these (manager, package, spec) triples: rule, package, spec and check, no
    other command text. With unnamed, one line for a word that may be a package, naming none."""
    lines = [f"[practices:SEC-64] {SEC64['say']}"]
    for manager, pkg, spec in found:
        if manager in NPM_FAMILY:
            shown = f"{pkg}@{spec}" if spec and SPEC_SHOWN.fullmatch(spec) else pkg
            off = ("`--ignore-scripts`" if manager != "yarn" else
                   "scripts off (`--ignore-scripts` on Yarn 1; on later versions see "
                   "`yarn add --help`)")
            lines.append(f"- {pkg}: run `npm view {shown} scripts` and read what it prints, or "
                         f"install it with {off}.")
        elif manager == "pip":
            lines.append(f"- {pkg}: install it with `--only-binary :all:` (a wheel runs no code "
                         "at install), or read its build code first.")
        elif manager == "uv":
            lines.append(f"- {pkg}: install it with `--no-build` (a wheel runs no code at "
                         "install), or read its build code first.")
        else:
            lines.append(f"- {pkg}: read what it runs at install or build ({manager}).")
    if unnamed:
        lines.append("This install may add a package: a word after an option this check doesn't "
                     "know could be a package or that option's value, so it isn't repeated here. "
                     "Read that package's install scripts first, or install with scripts off "
                     "where this manager has a way.")
    if any(manager in NPM_FAMILY for manager, _, _ in found):
        lines.append("`npm view` shows only this package's own scripts. A dependency's install "
                     "scripts can run too, and only turning scripts off covers them.")
    lines.append("Load the `dependencies` skill when it is listed. Resending this call passes "
                 "this check. In your reply, say what the script does and whether you read it "
                 "before or after it ran.")
    return "\n".join(lines)


def install_check(event):
    """SEC-64: the deny for this call, or None. A fault allows the call and logs it, and the git
    levels still run, with their share of the budget."""
    global BUDGET
    whole, BUDGET = BUDGET, BUDGET * SEC64_SHARE
    try:
        found, unread, ambiguous = read_installs(event)
        if not (found or unread or ambiguous):
            return None
        cfg = load_config(bash_project(event))
        if not cfg["enabled"] or is_off(cfg, ENGINE, SEC64["id"]):
            return None
        if unread:
            log("install-skipped", "the command adds a package in a form this check can't read, "
                "so that part wasn't checked")
        seen = state_keys(event)
        found = [k for k in found if install_key(*k) not in seen]
        unnamed = [install_key(m, UNNAMED) for m in ambiguous
                   if install_key(m, UNNAMED) not in seen]
        wanted = list(dict.fromkeys(k[1:] for k in found if k[0] in NPM_FAMILY))
        read = inspected_earlier(event, wanted) if wanted else set()
        new = [k for k in found if not (k[0] in NPM_FAMILY and k[1:] in read)]
        keys = [install_key(*k) for k in new] + unnamed
        if not keys or not state_add(event, keys):
            return None
        return deny(install_reason(new, bool(unnamed)))
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in SEC-64's {e}; the call was allowed")
    except Exception as e:  # noqa: BLE001  never at the cost of the push and PR checks
        log("crash", f"SEC-64: {type(e).__name__}: {e}")
    finally:
        BUDGET = whole
    return None


def bash_pre(event):
    """PreToolUse(Bash): deny a first package install once per package (SEC-64), deny a call
    that both commits and pushes once, record HEAD before a commit (L3s), deny a push once per
    new finding in what it would send, and deny a PR's `ready` once until a reviewer ran with the
    gate lines of the skills it touches (L3r)."""
    out = install_check(event)
    if out:
        return out
    gits, ghs, named = bash_calls(event)
    commits = [g for g in gits if g[0] == "commit"]
    pushes = [g for g in gits if g[0] == "push"]
    ghs = [g for g in ghs if pr_ready(g[0]) is not None]
    if not (commits or pushes or ghs or named):
        return None
    project = bash_project(event)  # never the call's cwd, which an earlier cd moved
    cfg = load_config(project)
    if not cfg["enabled"]:
        return None
    if named:  # the backstop for a launcher this parser can't read, beside any call it read
        log("git-skipped", "the command names git commit or push, or gh pr ready or create, "
            "in a form this check can't read (a launcher such as xargs, find -exec or a "
            "script), so that part wasn't checked")
    if not (commits or pushes or ghs):
        return None
    if commits and pushes:
        key = f"push|engine|chain|-|{_sha1(command_of(event))}"
        if key not in state_keys(event) and state_add(event, [key]):
            return deny(
                "[practices:push] This one Bash call both commits and pushes, so the push check "
                "can't see what the commit adds. Run the commit and the push as separate Bash "
                "calls. Resending this call unchanged passes this check, but the push check "
                "still scans the commits already made that no remote has, and stops the resend "
                "once for any finding in them; what the new commit adds is only told after it "
                "is made.")
    reasons, keys, cut_keys = [], [], []
    try:
        bounds = bounds_of(project)
        if commits:
            record_heads(event, commits, bounds)
        if pushes or ghs:
            skills = discover(project)
            with Transcripts(event) as ts:
                ctx = context(event, cfg, ts, project)
                new, cuts = (push_gate(event, pushes, skills, cfg, ts, ctx, bounds) if pushes
                             else ([], []))
                cut_keys += cuts
                if new:
                    reasons.append(push_reason(new, bool(cuts)))
                    keys += [f.key for f in new]
                if ghs and ctx["cut_at"] is None:  # after a cut the budget is spent
                    review, review_keys, found, notes, cuts = l3r(event, ghs, skills, cfg, ts,
                                                                  ctx, bounds, len(pushes))
                    cut_keys += cuts
                    reasons += review
                    keys += review_keys
                    found = [f for f in found if f.key not in keys]
                    if found:
                        reasons.append(
                            "[practices:L3r] This PR's commits add code that a practices rule "
                            "flags. Fix it in a new commit and push, or, when one is a false "
                            "positive, add `practices-allow: <id> <reason>` to the code. Resending "
                            "passes this check.\n" + (CUT_NOTE + "\n" if cuts else "")
                            + findings_text(found))
                        keys += [f.key for f in found]
                    reasons += notes
                # The calls after a cut go unchecked; each gets a key tied to the cut, so the
                # resend of this command over the same commits passes them, as the deny says.
                if ctx["cut_at"] is not None:
                    levels = ["push"] * len(pushes) + ["L3r"] * len(ghs)
                    left = [unchecked_key(ctx, lv, n) for n, lv in enumerate(levels)
                            if n > ctx["cut_at"]]
                    if left:
                        log("scan-truncated", f"{len(left)} later calls in this command went "
                            "unchecked after the cut; a resend passes them unscanned")
                        cut_keys += left
                        if reasons:
                            reasons.append(LEFT_NOTE)
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the Bash check's {e}; the call was allowed")
        return None
    except GitError as e:
        log("git-skipped", f"Bash check: {e}")
        return None
    # A cut scan's key rides on any deny of this call, so its resend passes that range unscanned.
    if not reasons or not state_add(event, keys + cut_keys):  # an unkept key: allow, logged
        return None
    return deny("\n\n".join(reasons))


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


# ---------------------------------------------------------------- SessionStart

def digest(names, skills):
    """The L4 digest, under DIGEST_MAX characters: a head naming the skills, then each one's
    SKILL.md path and gate lines. The room after the head is shared among the skills (one that
    needs less than its share passes the rest on), so a long gate never crowds out the next
    skill, and a skill's lines are cut only between lines, with a note of how many it left
    out."""
    head = "Practices skills loaded before this compaction: " + ", ".join(names) + "."
    blocks = [(f"\n{n} ({os.path.join(skills[n]['dir'], 'SKILL.md')}), its must-hold lines:",
               [f"\n- {line}" for line in skills[n]["gate"]]) for n in names]
    need = [len(title) + sum(map(len, lines)) for title, lines in blocks]
    room, share, left = DIGEST_MAX - 1 - len(head), {}, list(range(len(blocks)))
    while left:  # each skill's share: what it needs, or an even split of what is left
        fair = max(room, 0) // len(left)
        fits = [k for k in left if need[k] <= fair]
        if not fits:
            share.update((k, fair) for k in left)
            break
        for k in fits:
            share[k], room = need[k], room - need[k]
        left = [k for k in left if k not in fits]
    out = head
    for k, (title, lines) in enumerate(blocks):
        if need[k] <= share[k]:
            out += title + "".join(lines)
            continue
        kept, used = [], len(title)
        for line in lines:
            note = f"\n- ({len(lines) - len(kept) - 1} more in its SKILL.md)"
            if used + len(line) + len(note) > share[k]:
                break
            kept.append(line)
            used += len(line)
        note = f"\n- ({len(lines) - len(kept)} more in its SKILL.md)"
        if used + len(note) <= share[k]:
            out += title + "".join(kept) + note
    return out[:DIGEST_MAX - 1]  # only a head naming dozens of skills reaches this cap


def compact(event):
    project = bash_project(event)  # as every level reads it: never a cwd a cd moved
    if not load_config(project)["enabled"]:
        return None
    skills = discover(project)
    if not skills:
        return None
    out = {"hookEventName": "SessionStart", "reloadSkills": True}
    m, f = open_transcript(event)
    try:
        if m:
            CRUMB.mark("(compaction digest)", "transcript", "L4 loads")
            t = Transcript(m, bool(event.get("agent_id")))
            loads = compact_window(t).loads()
            names = sorted(n for n, s in skills.items() if is_loaded(s, loads))
            if names:
                out["additionalContext"] = digest(names, skills)
    except Budget as e:
        log("budget-spent", f"after {BUDGET}s, in the {e} for the compaction digest; "
            "it was left out")
    finally:
        if isinstance(m, mmap.mmap):
            m.close()
        if f:
            f.close()
    return {"hookSpecificOutput": out}


SELF_TEST = (
    ({"id": "e", "paths": ["**/app/**/route.{ts,js}"], "content": [r"^\s*['\"]use server['\"]"]},
     "event", [("app/api/x/route.ts", "", True), ("src/app/route.js", "", True),
               ("app/route.tsx", "", False), ("lib/a.ts", "'use server'\nx", True),
               ("lib/a.ts", "x = 'use server'", False)]),
    ({"id": "r", "when": r"\bquery\(`[^`]*\$\{", "unless": "safe", "paths": ["*.ts"]},
     "rule", [("a/b.ts", "query(`x ${y}`)", True), ("a/b.js", "query(`x ${y}`)", False),
              ("a/b.ts", "query(`x ${y}`) // safe", False),
              ("a/b.ts", "query(`x ${y}`) // practices-allow: r ok", False)]),
)


def self_test():
    """None, or what the built-in matcher fixture got wrong."""
    if tomllib is None:
        return "python3 lacks tomllib (needs 3.11+)"
    for item, kind, cases in SELF_TEST:
        for rel, content, want in cases:
            fn = event_fires if kind == "event" else rule_fires
            got = fn(item, rel, scan_text(content))
            if got != want:
                return f"self-test: {kind} on {rel!r} gave {got}"
    return None


def health(event):
    problems = []
    d = state_dir()
    try:
        broken = self_test()
    except Exception as e:  # noqa: BLE001 (any failure here is the report)
        broken = f"self-test crashed: {type(e).__name__}: {e}"
    if broken:
        problems.append(f"down ({broken}); edits are not checked")
    else:
        discover(bash_project(event))  # logs a malformed events.toml, counted below
    now = time.time()  # wall clock: compared with file mtimes
    try:
        crumbs = sorted(n for n in os.listdir(d) if n.startswith("breadcrumb-"))
    except OSError:
        crumbs = []
    for n in crumbs:
        p = os.path.join(d, n)
        try:
            if now - os.path.getmtime(p) < STALE_CRUMB:
                continue
            with open(p, encoding="utf-8") as fh:
                c = json.load(fh)
            problems.append(f"a check was killed mid-scan ({c.get('level')} {c.get('pattern')} "
                            f"on {c.get('file')})")
        except (OSError, ValueError, AttributeError):
            problems.append("a check was killed mid-scan")
        try:
            os.unlink(p)
        except OSError:
            pass
    counts = new_errors(d)
    if counts:
        problems.append(", ".join(f"{n} {LABELS.get(k, (k, k))[n != 1]}"
                                  for k, n in sorted(counts.items()))
                        + f" since the last start (see {os.path.join(d, 'errors.log')})")
    prune(os.path.join(d, "denies"), now)
    prune(os.path.join(d, "heads"), now)
    prune(os.path.join(d, "sessions"), now)
    if not problems:
        return None
    return {"systemMessage": "practices hooks: " + "; ".join(problems)}


LABELS = {"skill-disabled": ("skill disabled", "skills disabled"),
          "pattern-skipped": ("pattern skipped", "patterns skipped"),
          "budget-spent": ("time budget spent", "time budgets spent"),
          "config-malformed": ("malformed config", "malformed configs"),
          "config-ignored": ("repo off setting ignored", "repo off settings ignored"),
          "off-file-bad": ("unusable off file", "unusable off file reads"),
          "state-error": ("state error", "state errors"), "crash": ("crash", "crashes"),
          "git-skipped": ("git call skipped", "git calls skipped"),
          "install-skipped": ("package install skipped", "package installs skipped"),
          "scan-truncated": ("scan cut short", "scans cut short"),
          "project-unknown": ("edit without a project dir", "edits without a project dir")}
# For debugging, never an engine error: a deliberate choice (a delete push sends nothing to
# scan), not a check that failed open.
QUIET = {"fragment-only", "bash-unparsed", "l3r-target", "l3r-reuse", "push-unscanned"}


def new_errors(d):
    """{kind: distinct lines} in errors.log since the last startup check, which it then marks.
    Lines differing only in their stamp count once (a malformed skill logs on every call)."""
    path, mark = os.path.join(d, "errors.log"), os.path.join(d, "health.json")
    try:
        with open(mark, encoding="utf-8") as fh:
            seen = json.load(fh)
        seen = seen if isinstance(seen, dict) else {}
    except (OSError, ValueError, RecursionError):
        seen = {}
    found = {}
    try:
        st = os.stat(path)
        start = seen.get("size", 0) if seen.get("ino") == st.st_ino else 0
        start = start if isinstance(start, int) and 0 <= start <= st.st_size else 0
        with open(path, "rb") as fh:
            fh.seek(max(start, st.st_size - LOG_MAX))
            for line in fh.read().decode("utf-8", "replace").splitlines():
                parts = line.split(" ", 3)
                if len(parts) >= 3 and parts[2] not in QUIET:
                    found.setdefault(parts[2], set()).add(parts[3] if len(parts) > 3 else "")
        os.makedirs(d, exist_ok=True)
        with open(mark, "w", encoding="utf-8") as fh:
            json.dump({"ino": st.st_ino, "size": st.st_size}, fh)
    except OSError:
        pass
    return {k: len(v) for k, v in found.items()}


def prune(folder, now):
    try:
        for n in os.listdir(folder):
            p = os.path.join(folder, n)
            if now - os.path.getmtime(p) > STATE_DAYS * 86400:
                os.unlink(p)
    except OSError:
        pass


def start_notes(event):
    """(lines for the user, text for the model) about this project at any session start: what the
    off file turns off here, and each project copy of an installed skill. Paths reach the model
    only when printable, since a folder name is the project's to choose."""
    project = bash_project(event)
    if not project:
        return [], None
    lines = []
    entries, bad = off_entries(project)
    if bad:
        lines.append("the off file can't be used, so the gate stays on here")
    for e in entries:
        what = f"rule {e['rule']} is off ({e['reason']})" if "rule" in e else "the gate is off"
        lines.append(f"{what} in {e['dir']} until {e['until']} (practices-gate)".replace(
            "the gate is off in", "off in"))
    helpers = load_config(project)["helpers"]
    if helpers:
        lines.append("this project names its own auth checks, which quiet SEC-01: "
                     + ", ".join(helpers[:10]) + (" and more" if len(helpers) > 10 else ""))
    context = []
    for name, skill in sorted(discover(project, quiet=True).items()):
        for copy in skill.get("copies", []):
            lines.append(f"this project has its own copy of the skill {name}; both run")
            shown = copy if copy.isprintable() else "(a folder under the project's .claude/skills)"
            context.append(
                f"This project has its own copy of the installed practices skill {name}: {shown}, "
                f"beside {skill['dir']}. Both run: every installed rule applies, and the copy only "
                "adds rules with new ids. Read both, tell the user how they differ, and propose "
                "what to do: keep both, rename the copy, move a rule into the installed skill, or "
                "delete the copy. Change nothing until the user decides.")
    return lines, "\n".join(context) or None


def with_notes(out, event):
    """out (a session start's output, or None) with start_notes added. A crash here is logged and
    keeps out, which may carry reloadSkills."""
    try:
        lines, context = start_notes(event)
    except Exception as e:  # noqa: BLE001
        log("crash", f"start_notes: {type(e).__name__}: {e}")
        return out
    if not lines and not context:
        return out
    out = dict(out or {})
    if lines:
        note = "practices hooks: " + "; ".join(lines)
        out["systemMessage"] = f"{out['systemMessage']}; {'; '.join(lines)}" \
            if out.get("systemMessage") else note
    if context:
        spec = out.setdefault("hookSpecificOutput", {"hookEventName": "SessionStart"})
        spec["additionalContext"] = (spec["additionalContext"] + "\n" + context
                                     if spec.get("additionalContext") else context)
    return out


def two_passes(level, event):
    """The installed skills' verdict first, then the project's. A repo chooses a project skill's
    patterns and globs, so one can throw or run into the 5 s kill, and either allows the call. By
    then the installed skills have already had their say, so a project skill can only add to them:
    when the first pass speaks, the second doesn't run, and its findings wait for a later call."""
    global START  # noqa: PLW0603
    project = bash_project(event)
    try:
        SCOPE["now"] = "installed"
        ran = bool(discover(project, quiet=True))
        if ran:
            out = level(event)
            if out:
                return out
        SCOPE["now"] = "project"
        if discover(project, quiet=True):
            if ran:
                START = time.monotonic()  # its own budget: the kill now costs only this pass
            return level(event)
        SCOPE["now"] = "installed"
        return None if ran else level(event)   # no skills at all: the levels that need none
    finally:  # both belong to this call alone
        SCOPE["now"] = "all"
        HEADS_READ.clear()


def main():
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise TypeError("the event isn't an object")
    if tomllib is None and event.get("source") != "startup":
        raise ImportError("tomllib missing (python3 < 3.11)")
    name = event.get("hook_event_name")
    if name == "SessionStart" or (name is None and "source" in event):
        record_session_cwd(event)
        source = event.get("source")
        out = health(event) if source == "startup" else compact(event) if source == "compact" \
            else None
        out = with_notes(out, event)
    else:
        out = two_passes(post_tool_use if name == "PostToolUse" else pre_tool_use, event)
    if out:
        print(json.dumps(out))


def run():
    try:
        main()
    except Exception as e:  # noqa: BLE001  allow and loud: the next startup reports it
        log("crash", f"{type(e).__name__}: {e}")
    finally:
        CRUMB.clear()


if __name__ == "__main__":
    run()
