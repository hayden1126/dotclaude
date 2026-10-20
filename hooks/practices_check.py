"""The practices hook engine; hooks/practices-check.sh runs it on PreToolUse(Edit|Write|MultiEdit|
Bash) and SessionStart. It enforces every installed practices skill at the moment code is written.

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

Skills are found in $CLAUDE_PROJECT_DIR/.claude/skills/*/ (the payload's cwd without it) and in
${CLAUDE_CONFIG_DIR:-~/.claude}/skills/*/, links followed. On a name clash the project copy wins.

Levels:
  L1  an edit that fires a skill's event, when the window (the transcript since the last
      compaction, plus the messages that compaction preserved) shows no load of the skill: a
      Skill call naming it (`name` or `plugin:name`) or a Read of `<skill>/SKILL.md`. Denied once
      per (skill, event) per window. The reason opens with `[practices:L1:<skill>:<event>]`, says
      how to load the skill, and carries the event's lines; one deny names every skill that fired.
  L2  a fired rule, denied once per (file, rule) over the whole transcript, marker
      `[practices:L2:<skill>:<rule>:<path>]`. `practices-allow: <rule>` anywhere in the file
      after the edit suppresses it. L2 doesn't run in a call L1 denies.
  L4  SessionStart(compact): a digest (under DIGEST_MAX characters) naming the practices skills
      loaded since the previous compaction, with their gate lines, plus reloadSkills: true.
Deny-once is stateless: a tool_result in the window that holds the call's own marker lets the
call through. The marker is this engine's own text, never Claude Code's "hook error" wording
around it, which a release may reword. is_error isn't required either: a release that dropped it
must not loop, and a stray marker in some other result costs at most one missed deny.

Compaction boundary (2.1.304, a real /compact): a `type: system`, `subtype: compact_boundary`
row, whose compactMetadata.preservedMessages lists uuids of earlier rows kept in context, then
an isCompactSummary user row. At SessionStart(compact) the new boundary may or may not be on disk
yet: when no assistant row follows the newest boundary it is this compaction's, and the digest
reads back to the one before it; otherwise the digest reads the L1 window.

Subagents: a payload with agent_id carries the parent's transcript_path, so every transcript read
uses <transcript_path minus .jsonl>/subagents/agent-<agent_id>.jsonl, and its sidechain rows.
When the transcript to read is missing, deny-once falls back to a state file keyed by session,
agent, level and id under $XDG_STATE_HOME/dotclaude/practices/denies/.

Per repo, <project>/.claude/practices/config.toml: `enabled = false` turns the engine off there;
`[[disable]]` with `rule` (an event or rule id, or `<skill>:<id>`) and a non-empty `reason` turns
one off; `[auth] helpers = [...]` feeds `{auth_helpers}`. A malformed file falls back to the
defaults (never turning a check off) and is logged.

Failure posture (allow and loud): a BUDGET-second run budget on time.monotonic(); patterns left
when it is spent are skipped and logged. A pattern that throws is skipped and logged; a malformed
events.toml disables that skill only, logged. Any crash allows the call (no output) and is logged
to $XDG_STATE_HOME/dotclaude/practices/errors.log (size-capped). Before each pattern a breadcrumb
(file, level, pattern) is written under the state dir and removed on a normal exit; Claude Code's
timeout kill takes the whole process group, so a killed scan leaves it behind. SessionStart
(startup) runs a self-test, reports leftover breadcrumbs and the errors logged since the last
start, as one systemMessage line (shown to the user only), and prints nothing when all is well.

Not covered in v1: Bash. A Bash call is allowed unchecked, so a file written by a heredoc or
`cat >` escapes L1 and L2 (the commit-time scan, L3s, is the planned backstop).
"""
import hashlib
import json
import mmap
import os
import re
import sys
import time

START = time.monotonic()
try:
    import tomllib
except ImportError:  # python3 < 3.11: reported by the startup health check
    tomllib = None

BUDGET = 2.0  # seconds, well under settings.json's 5 s kill
try:  # tests only: a tiny budget proves the skip path without a slow pattern
    BUDGET = float(os.environ.get("PRACTICES_TEST_BUDGET") or BUDGET)
except ValueError:
    pass
CONTENT_MAX = 256 << 10
FILE_MAX = 1 << 20  # bytes of the current file read to apply an Edit; scans still cap at CONTENT_MAX
LINE_MAX = 4000
PARSE_MAX = 1 << 20  # transcript rows bigger than this are never a load or a deny
LOG_MAX = 64 << 10
DIGEST_MAX = 2000
STALE_CRUMB = 10  # seconds: a live scan ends within the 5 s kill
STATE_DAYS = 7
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")
NOT_ENTRIES = (b'{"type":"api-request', b'{"type":"attachment"', b'{"type":"file-history',
               b'{"type":"queue-operation')
AUTH_HELPERS = ("auth", "getServerSession", "getSession", "currentUser", "getCurrentUser",
                "requireUser", "requireAuth", "verifySession", "getUser", "withAuth")
ID = re.compile(r"[\w.-]+")


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
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {detail}\n")
    except OSError:
        pass


class Budget(Exception):
    pass


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
    if "{auth_helpers}" not in pattern:
        return pattern
    names = sorted(set(AUTH_HELPERS) | set(helpers), key=lambda n: (-len(n), n))
    return pattern.replace("{auth_helpers}", "(?:" + "|".join(map(re.escape, names)) + ")")


def search(pattern, text, helpers=()):
    return re.search(expand(pattern, helpers), text, re.MULTILINE) is not None


def scan_text(content):
    """The content as scanned: CONTENT_MAX characters, each line cut to LINE_MAX."""
    return "\n".join(line[:LINE_MAX] for line in content[:CONTENT_MAX].split("\n"))


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
    if allowed(rule["id"], after_text if after is None else after):
        return False
    if crumb:
        crumb.mark(rel, "L2", rule["id"])
    if not guarded(rule["when"], text, helpers, rule["id"]):
        return False
    return not (rule.get("unless") and guarded(rule["unless"], after_text, helpers, rule["id"]))


def allowed(rule_id, content):
    return re.search(r"practices-allow:[ \t]*" + re.escape(rule_id) + r"(?![\w.-])",
                     content) is not None


class PatternError(Exception):
    pass


def guarded(pattern, text, helpers, owner):
    try:
        return search(pattern, text, helpers)
    except (re.error, RecursionError, TypeError, ValueError) as e:
        raise PatternError(f"{owner}: {type(e).__name__}: {e}") from e


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

def project_dir(event):
    d = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    return os.path.abspath(d)


def config_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def load_skill(folder):
    """(skill dict, None) for a folder's events.toml, or (None, why) when it is malformed."""
    path = os.path.join(folder, "events.toml")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError, RecursionError) as e:  # TOMLDecodeError is a ValueError
        return None, f"{path}: {type(e).__name__}: {e}"
    name = data.get("skill", os.path.basename(folder))
    gate = data.get("gate", [])
    events, rules = data.get("event", []), data.get("rule", [])
    if not isinstance(name, str) or not ID.fullmatch(name) or not _strs(gate) or not (
            isinstance(events, list) and isinstance(rules, list)):
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
                and isinstance(r.get("unless", ""), str) and _strs(r.get("paths", []))):
            return None, f"{path}: bad rule {r.get('id') if isinstance(r, dict) else r!r}"
        ids.append(r["id"])
    if len(ids) != len(set(ids)):
        return None, f"{path}: duplicate ids"
    return {"name": name, "dir": os.path.abspath(folder), "gate": gate, "events": events,
            "rules": rules}, None


def discover(event):
    """{name: skill} from the user's skills, then the project's, which win a clash."""
    skills = {}
    roots = [os.path.join(config_home(), "skills"),
             os.path.join(project_dir(event), ".claude", "skills")]
    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            folder = os.path.join(root, n)
            if not os.path.isfile(os.path.join(folder, "events.toml")):
                continue
            skill, why = load_skill(folder)
            if skill is None:
                log("skill-disabled", why)
            else:
                skills[skill["name"]] = skill
    return skills


def load_config(event):
    """{"enabled", "disable" (a set of ids and skill:ids), "helpers"}; defaults on any fault."""
    default = {"enabled": True, "disable": set(), "helpers": ()}
    path = os.path.join(project_dir(event), ".claude", "practices", "config.toml")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError, RecursionError) as e:
        log("config-malformed", f"{path}: {type(e).__name__}: {e}")
        return default
    enabled = data.get("enabled", True)
    disable = data.get("disable", [])
    auth = data.get("auth", {})
    helpers = auth.get("helpers", []) if isinstance(auth, dict) else None
    if not isinstance(enabled, bool) or not isinstance(disable, list) or not _strs(helpers):
        log("config-malformed", f"{path}: bad enabled, disable or auth.helpers")
        return default
    off = set()
    for d in disable:
        if (isinstance(d, dict) and isinstance(d.get("rule"), str) and d["rule"]
                and isinstance(d.get("reason"), str) and d["reason"].strip()):
            off.add(d["rule"])
        else:
            log("config-malformed", f"{path}: a [[disable]] without rule and reason is ignored")
    return {"enabled": enabled, "disable": off, "helpers": tuple(helpers)}


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
        hi = len(self.m) if hi is None else hi
        pos = lo
        while pos < hi and (i := self.m.find(needle, pos, hi)) != -1:
            s, e = self.line_at(i)
            d = self.parse(s, e)
            if d is not None:
                yield s, d
            pos = e + 1

    def boundaries(self):
        """(row start, row end, preserved uuids) per compact boundary, newest first."""
        end = len(self.m)
        while end > 0 and (i := self.m.rfind(b'"compact_boundary"', 0, end)) != -1:
            s, e = self.line_at(i)
            d = self.parse(s, e)
            if d and d.get("type") == "system" and d.get("subtype") == "compact_boundary":
                yield s, e, preserved(d)
            end = s

    def assistant_after(self, pos):
        return any(d.get("type") == "assistant" for _, d in self.hits(b'"assistant"', pos))


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
    """The skill a tool_use block loads (its bare name), or None."""
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if b.get("name") == "Skill" and isinstance(inp.get("skill"), str):
        return inp["skill"].rsplit(":", 1)[-1].strip() or None
    fp = inp.get("file_path")
    if b.get("name") == "Read" and isinstance(fp, str) and fp.replace("\\", "/").endswith(
            "/SKILL.md"):
        parent = fp.replace("\\", "/").rsplit("/", 2)
        return parent[-2] if len(parent) >= 2 and parent[-2] else None
    return None


class Window:
    """The rows from lo to hi, plus earlier rows whose uuid is in keep."""

    def __init__(self, t, lo, hi, keep):
        self.t, self.lo, self.hi, self.keep = t, lo, hi, keep

    def rows(self, needle):
        for s, d in self.t.hits(needle, 0 if self.keep else self.lo, self.hi):
            if s >= self.lo or d.get("uuid") in self.keep:
                yield d

    def loads(self):
        names = set()
        for needle in (b'"Skill"', b"SKILL.md"):
            for d in self.rows(needle):
                if d.get("type") == "assistant":
                    names |= {n for b in blocks(d) if b.get("type") == "tool_use"
                              if (n := loaded_name(b))}
        return names

    def results(self, needle):
        return [text for d in self.rows(needle) if d.get("type") == "user"
                for text in result_texts(d)]


def l1_window(t):
    b = next(t.boundaries(), None)
    return Window(t, b[1], None, b[2]) if b else Window(t, 0, None, frozenset())


def compact_window(t):
    """The rows before this compaction and after the one before it."""
    bounds = t.boundaries()
    last = next(bounds, None)
    if last is None or t.assistant_after(last[1]):
        return l1_window(t)
    prev = next(bounds, None)
    return Window(t, prev[1], last[0], prev[2]) if prev else Window(t, 0, last[0], frozenset())


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
    try:
        with open(_state_file(event), encoding="utf-8") as f:
            keys = json.load(f).get("keys", [])
        return set(k for k in keys if isinstance(k, str))
    except (OSError, ValueError, AttributeError, RecursionError):
        return set()


def state_add(event, keys):
    path = _state_file(event)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"keys": sorted(state_keys(event) | set(keys))}, f)
        os.replace(tmp, path)
    except OSError as e:
        log("state-error", f"{path}: {e}")


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


def run_patterns(items, fn):
    """[item for item in items if fn(item)], each inside its own guard; a throwing pattern is
    logged and skipped, and once the budget is spent the rest are skipped and logged."""
    out = []
    for n, item in enumerate(items):
        try:
            if fn(item):
                out.append(item)
        except PatternError as e:
            log("pattern-skipped", str(e))
        except Budget:
            left = ", ".join(f"{s['name']}:{x['id']}" for s, x in items[n:])
            log("budget-spent", f"after {BUDGET}s, skipped {left}")
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


def l2_reason(pending, rel):
    return "\n\n".join(
        f"[practices:L2:{skill['name']}:{rule['id']}:{rel}] {rule['say']}\nFix it and resend, "
        f"or, when this is a false positive, add a comment `practices-allow: {rule['id']} "
        f"<reason>` to the code; this check won't stop this file for {rule['id']} again."
        for skill, rule in pending)


def pre_tool_use(event):
    edit = edit_of(event)
    if edit is None:  # Bash and anything else: allowed unchecked in v1
        return None
    cfg = load_config(event)
    if not cfg["enabled"]:
        return None
    skills = discover(event)
    if not skills:
        return None
    path, fragment, after = edit
    rel = relative(path, project_dir(event))
    text, after_text = scan_text(fragment), scan_text(after)
    helpers = cfg["helpers"]
    events = [(s, ev) for s in skills.values() for ev in s["events"] if not is_off(cfg, s, ev["id"])]
    rules = [(s, r) for s in skills.values() for r in s["rules"] if not is_off(cfg, s, r["id"])]
    fired = run_patterns(events, lambda x: event_fires(x[1], rel, after_text, helpers, CRUMB))

    m, f = open_transcript(event)
    try:
        t = Transcript(m, bool(event.get("agent_id"))) if m is not None else None
        seen = state_keys(event) if t is None else None
        reason, keys = None, []
        if fired:
            win = l1_window(t) if t is not None and len(m) else None
            loads = win.loads() if win else set()
            denied = win.results(b"[practices:L1:") if win else []
            pending = {}
            for s, ev in fired:
                if s["name"] in loads or os.path.basename(s["dir"]) in loads:
                    continue
                marker = f"[practices:L1:{s['name']}:{ev['id']}]"
                if (seen is not None and marker in seen) or any(marker in x for x in denied):
                    continue
                pending.setdefault(s["name"], (s, []))[1].append(ev)
                keys.append(marker)
            if pending:
                reason = l1_reason(list(pending.values()), rel, bool(event.get("agent_id")))
        if reason is None and rules:
            hit = run_patterns(rules, lambda x: rule_fires(x[1], rel, text, helpers, CRUMB,
                                                           after_text, after))
            denied = (Window(t, 0, None, frozenset()).results(b"[practices:L2:")
                      if t is not None and len(m) else [])
            pending = []
            for s, r in hit:
                marker = f"[practices:L2:{s['name']}:{r['id']}:{rel}]"
                if (seen is not None and marker in seen) or any(marker in x for x in denied):
                    continue
                pending.append((s, r))
                keys.append(marker)
            if pending:
                reason = l2_reason(pending, rel)
        if reason and seen is not None:
            state_add(event, keys)
    finally:
        if isinstance(m, mmap.mmap):
            m.close()
        if f:
            f.close()
    if not reason:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


# ---------------------------------------------------------------- SessionStart

def digest(names, skills):
    head = ("Practices skills loaded before this compaction: " + ", ".join(names) + ".")
    out = head
    for n in names:
        s = skills[n]
        block = (f"\n{n} ({os.path.join(s['dir'], 'SKILL.md')}), its must-hold lines:"
                 + "".join(f"\n- {line}" for line in s["gate"]))
        if len(out) + len(block) >= DIGEST_MAX:
            room = DIGEST_MAX - len(out) - 2
            out += block[:max(room, 0)] + ("…" if room > 0 else "")
            break
        out += block
    return out[:DIGEST_MAX - 1]


def compact(event):
    if not load_config(event)["enabled"]:
        return None
    skills = discover(event)
    if not skills:
        return None
    out = {"hookEventName": "SessionStart", "reloadSkills": True}
    m, f = open_transcript(event)
    try:
        if m:
            t = Transcript(m, bool(event.get("agent_id")))
            loads = compact_window(t).loads()
            names = sorted(n for n, s in skills.items()
                           if n in loads or os.path.basename(s["dir"]) in loads)
            if names:
                out["additionalContext"] = digest(names, skills)
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
        discover(event)  # logs a malformed events.toml, counted below
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
    if not problems:
        return None
    return {"systemMessage": "practices hooks: " + "; ".join(problems)}


LABELS = {"skill-disabled": ("skill disabled", "skills disabled"),
          "pattern-skipped": ("pattern skipped", "patterns skipped"),
          "budget-spent": ("time budget spent", "time budgets spent"),
          "config-malformed": ("malformed config", "malformed configs"),
          "state-error": ("state error", "state errors"), "crash": ("crash", "crashes")}
QUIET = {"fragment-only"}  # logged for debugging, never an engine error


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


def main():
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise TypeError("the event isn't an object")
    if tomllib is None and event.get("source") != "startup":
        raise ImportError("tomllib missing (python3 < 3.11)")
    name = event.get("hook_event_name")
    if name == "SessionStart" or (name is None and "source" in event):
        source = event.get("source")
        out = health(event) if source == "startup" else compact(event) if source == "compact" \
            else None
    else:
        out = pre_tool_use(event)
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001  allow and loud: the next startup reports it
        log("crash", f"{type(e).__name__}: {e}")
    finally:
        CRUMB.clear()
