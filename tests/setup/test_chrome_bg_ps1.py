"""chrome-bg.ps1, read statically (powershell.exe can't run in the sandbox). Each Phase 0 rule the
supervisor depends on is a check over its source that returns a list of problems. Rules runs each
check on the real file; CatchesRegressions runs it on a copy with that rule broken, so a check
that stops seeing its regression fails too. Evidence for the rules: the header of chrome-bg.ps1."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PS1 = os.path.join(REPO, "chrome-bg.ps1")

STDOUT_WRITERS = [
    r"\[Console\]::Out\b", r"\bConsole\.Out\b", r"\[Console\]::Write", r"\bConsole\.Write",
    r"\bWrite-Output\b", r"\bWrite-Host\b", r"\bOut-Host\b", r"\bOut-Default\b",
    r"OpenStandardOutput", r"(?<![\w.$-])echo\b", r"(?<![\w.:$-])write\b(?!-)",
]
# Stderr is the same kind of pipe to the owner, and nothing here needs these streams.
OTHER_WRITERS = [
    r"\bWrite-(?:Error|Warning|Information|Verbose|Debug|Progress)\b",
    r"\[Console\]::Error\b", r"\bConsole\.Error\b", r"OpenStandardError",
]
WMI = re.compile(
    r"Management(?:Object|Class|Scope|EventWatcher|Path)|Get-CimInstance|Invoke-CimMethod|"
    r"Get-WmiObject|Win32_\w+|\bWql\w*", re.I)
PARAMS = {"id", "keep", "kill", "scan"}
DROPPED_PARAMS = {"tag", "logfile", "rundir", "windowstyle", "replyonly", "killoneof", "sinkoncreate"}
OPS = {"hello", "launch", "place", "procs", "fg", "mark"}
LOG_KINDS = [
    "VSCREEN", "FGLOCK", "MONITOR", "READY", "FOREGROUND", "TOP", "RANKS", "EV", "SINK-AT-CREATE",
    "KEEP-SINK", "PLACE", "LAUNCHED", "PROC", "PROCS", "MARK", "EOF", "EOFKILL", "EOFCLEAN", "EXIT",
    "UNTAG", "TAG",
]
KEYWORD_BLOCK = re.compile(
    r"\s*(?:if|elseif|else|try|catch|finally|foreach|for|while|do|switch|trap)\b", re.I)
SILENT = re.compile(
    r"(?:if|elseif|else|try|catch|finally|foreach|for|while|do|switch|trap|function|param|exit|return|"
    r"break|continue|throw)\b|\[CmdletBinding\b|\[void\]|Send-Reply\b"
    r"|\$[\w:]+(?:\.\w+|\[[^\]]*\])*\s*[-+*/]?=(?!=)", re.I)
UNTAG = re.compile(r"\btagged\s*\.\s*(?:Remove|Clear)\s*\(|\btagged\s*=\s*new\b")
METHOD = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|internal|static|readonly|unsafe)\s+)+([\w<>\[\], ]+?)\s+"
    r"(\w+)\s*\([^;{)]*\)\s*\{")


def read():
    with open(PS1, encoding="utf-8") as f:
        return f.read()


def blank(pattern, text):
    """Blanks every match with spaces, so offsets stay put."""
    return re.sub(pattern, lambda m: " " * len(m.group()), text)


def close_of(text, i, pair="{}"):
    """Index of the bracket closing the one at text[i]. Brackets inside strings must balance."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == pair[0]:
            depth += 1
        elif text[j] == pair[1]:
            depth -= 1
            if depth == 0:
                return j
    raise AssertionError("unbalanced %s at %d" % (pair, i))


class Parts:
    """The PowerShell and the Add-Type C# of a source, full-line comments blanked."""

    def __init__(self, src):
        m = re.search(r"Add-Type\b[^\n]*?@(['\"])[ \t]*\r?\n(.*?)\r?\n\1@", src, re.S)
        if not m:
            raise AssertionError("no Add-Type here-string")
        self.cs = blank(r"(?m)^[ \t]*//.*$", m.group(2))
        self.ps = blank(r"(?m)^[ \t]*#.*$", src[:m.start(2)] + src[m.end(2):])
        self.methods = {}  # name -> (header start, body start, body end)
        self.returns = {}  # name -> return type
        for h in METHOD.finditer(self.cs):
            open_ = h.end() - 1
            self.methods[h.group(2)] = (h.start(), open_, close_of(self.cs, open_))
            self.returns[h.group(2)] = h.group(1)

    def body(self, name):
        _, start, end = self.methods[name]
        return self.cs[start:end + 1]

    def ps_block(self, opener):
        """(start, end) of the {...} block whose opening line matches `opener`, or None."""
        m = re.search(opener + r"[^{]*\{", self.ps, re.I | re.M)
        return (m.end() - 1, close_of(self.ps, m.end() - 1)) if m else None

    def function(self, name):
        return self.ps_block(r"^[ \t]*function[ \t]+" + re.escape(name) + r"\b")

    def text(self, span):
        return self.ps[span[0]:span[1] + 1] if span else ""

    def param_chunks(self):
        """{name: the attributes and declaration of that script parameter}."""
        m = re.search(r"(?im)^[ \t]*param\s*\(", self.ps)
        block = self.ps[m.end() - 1:close_of(self.ps, m.end() - 1, "()") + 1]
        chunks, prev = {}, 0
        for d in re.finditer(r"\$(\w+)", block):
            chunks[d.group(1).lower()] = block[prev:d.end()]
            prev = d.end()
        return chunks


def start_process_problems(src):
    p = Parts(src)
    problems = []
    for pat, why in [
        (r"\bStart-Process\b", "Start-Process"),
        (r"(?:^|[;|{(])[ \t]*(?:start|saps)\b(?!-)", "a Start-Process alias"),
        (r"&\s*\$Chrome\b", "a direct call of chrome.exe"),
        (r"\bInvoke-Item\b", "Invoke-Item"),
    ]:
        if re.search(pat, p.ps, re.I | re.M):
            problems.append("launches Chrome through the console chain: " + why)
    if re.search(r"Process\]?(?:::|\.)Start\s*\(|ProcessStartInfo", p.ps + p.cs, re.I):
        problems.append("launches through Process.Start")
    return problems


def launch_problems(src):
    p = Parts(src)
    launch = p.text(p.ps_block(r"^[ \t]*'launch'[ \t]*"))
    if not launch:
        return ["no 'launch' op"]
    problems = []
    calls = [launch[m.start():] for m in re.finditer(r"\bInvoke-CimMethod\b", launch, re.I)]
    # The statement: up to the line end, following backtick continuations.
    calls = [re.match(r"(?:[^\n]*`\r?\n)*[^\n]*", c).group() for c in calls]
    if not any(re.search(r"\bWin32_Process\b", c, re.I) and re.search(r"\bCreate\b", c)
               and re.search(r"\bCommandLine\b", c, re.I) for c in calls):
        problems.append("launch doesn't call Invoke-CimMethod Win32_Process Create with a CommandLine")
    if "AddPid(" not in launch:
        problems.append("launch doesn't tag the new pid (AddPid)")
    return problems


def stdout_problems(src):
    p = Parts(src)
    problems = []
    send = p.function("Send-Reply")
    if not send:
        return ["no Send-Reply function"]
    body = p.text(send)
    if not re.search(r"\[Console\]::Out\b", body, re.I):
        problems.append("Send-Reply doesn't write stdout")
    if not re.search(r"ConvertTo-Json\b(?=[^\n]*-Compress)(?=[^\n]*-Depth)", body, re.I):
        problems.append("Send-Reply doesn't use ConvertTo-Json -Compress -Depth")
    for pat in STDOUT_WRITERS:
        for m in re.finditer(pat, p.ps, re.I):
            if not send[0] <= m.start() <= send[1]:
                problems.append("stdout writer outside Send-Reply: %r" % m.group())
        for m in re.finditer(pat, p.cs, re.I):
            problems.append("stdout writer in the C#: %r" % m.group())
    for pat in OTHER_WRITERS:
        for m in re.finditer(pat, p.ps + p.cs, re.I):
            problems.append("stream writer: %r" % m.group())
    handler = p.text(p.ps_block(r"\$handler\s*=\s*\[Func\[string,\s*bool\]\]\s*"))
    if not handler:
        problems.append("no $handler = [Func[string, bool]] block")
    elif len(re.findall(r"\bSend-Reply\b", handler, re.I)) != 1:
        problems.append("the handler must call Send-Reply exactly once")
    if re.search(r"\bSend-Reply\b", p.text(p.function("Invoke-Op")), re.I):
        problems.append("Invoke-Op sends replies itself")
    return problems


def callback_reach(p):
    """Names of the C# methods reachable from the WinEvent callbacks."""
    return reach(p, re.findall(r"new\s+WinEventProc\s*\(\s*(\w+)\s*\)", p.cs))


def reach(p, roots):
    """Names of the C# methods reachable from the methods named in roots."""
    todo = list(roots)
    seen = set()
    while todo:
        name = todo.pop()
        if name in seen or name not in p.methods:
            continue
        seen.add(name)
        todo.extend(re.findall(r"\b([A-Za-z_]\w*)\s*\(", p.body(name)))
    return seen


def callback_wmi_problems(src):
    p = Parts(src)
    reach = callback_reach(p)
    problems = []
    # Guards against a parse that silently finds nothing.
    if not {"OnEvent", "Check", "Desc", "KeepSink", "Log"} <= reach:
        problems.append("callback graph incomplete: %s" % sorted(reach))
    if "Refresh" not in p.methods or not WMI.search(p.body("Refresh")):
        problems.append("Refresh no longer holds the WMI query (this check would see nothing)")
    for name in sorted(reach):
        for m in WMI.finditer(p.body(name)):
            problems.append("WMI in %s, reached from the WinEvent callback: %r" % (name, m.group()))
    return problems


def title_guarded(body, pos):
    """Whether the Title( call at body[pos] sits behind an IsTagged check."""
    tagged = re.compile(r"(?:^|[^!\s])\s*\bIsTagged\s*\(")
    start = max(body.rfind(c, 0, pos) for c in ";{}")
    if tagged.search(body[start + 1:pos]):
        return True
    depth = 0
    for i in range(pos - 1, -1, -1):
        if body[i] == "}":
            depth += 1
        elif body[i] == "{":
            if depth:
                depth -= 1
                continue
            hstart = max(body.rfind(c, 0, i) for c in ";{}")
            if re.search(r"\bif\s*\(\s*IsTagged\s*\(", body[hstart + 1:i]):
                return True
    return False


def title_problems(src):
    p = Parts(src)
    if "Desc" not in p.methods or "Title" not in p.methods:
        return ["no Desc or Title method"]
    problems = []
    desc_head, desc_start, desc_end = p.methods["Desc"]
    desc = p.body("Desc")
    calls = [m.start() for m in re.finditer(r"\bTitle\s*\(", desc)]
    if not calls:
        problems.append("Desc no longer logs run windows' titles")
    for pos in calls:
        if not title_guarded(desc, pos):
            problems.append("Desc writes a title without the IsTagged check")
    title_head = p.methods["Title"][0]
    for m in re.finditer(r"\bTitle\s*\(", p.cs):
        if desc_start <= m.start() <= desc_end or title_head <= m.start() < p.methods["Title"][1]:
            continue
        if not re.match(r"Title\s*\([^()]*\)\s*\.Length\b", p.cs[m.start():]):
            problems.append("a title is used outside Desc for more than its length")
    return problems


def id_param_problems(src):
    p = Parts(src)
    chunks = p.param_chunks()
    problems = []
    if set(chunks) != PARAMS:
        problems.append("params are %s, want %s" % (sorted(chunks), sorted(PARAMS)))
    chunk = chunks.get("id", "")
    m = re.search(r"ValidatePattern\(\s*(['\"])(.*?)\1", chunk, re.S)
    if not m:
        return problems + ["-Id has no ValidatePattern"]
    pattern = m.group(2)
    if "(?-i)" not in pattern and not re.search(r"Options\s*=\s*['\"]?None", chunk):
        problems.append("-Id's ValidatePattern ignores case")
    py = pattern.replace("(?-i)", "").replace(r"\z", r"\Z")
    for good in ["deadbeef", "0123abcd"]:
        if not re.search(py, good):
            problems.append("-Id's pattern refuses %r" % good)
    for bad in ["deadbee", "deadbeef0", "deadbeeg", "dead beef", "..\\..\\x", "", "deadbeef\n"]:
        if re.search(py, bad):
            problems.append("-Id's pattern accepts %r" % bad)
    sets = {name: set(re.findall(r"ParameterSetName\s*=\s*['\"](\w+)['\"]", c))
            for name, c in chunks.items()}
    # A parameter with no set belongs to every set.
    if not sets.get("scan") or not sets.get("id") or sets["scan"] & sets["id"]:
        problems.append("-Scan shares a parameter set with -Id")
    return problems


def dropped_problems(src):
    p = Parts(src)
    problems = []
    back = DROPPED_PARAMS & set(p.param_chunks())
    if back:
        problems.append("dropped params are back: %s" % sorted(back))
    for name in ["replyOnly", "sinkOnCreate", "KillOnEof"]:
        if re.search(r"\b%s\b" % name, p.cs, re.I):
            problems.append("dropped switch is back in the C#: %s" % name)
    for name in ["ShowBottom", "Restore", "FgDesc"]:
        if name in p.methods:
            problems.append("dropped verb method is back: %s" % name)
    verb = re.search(r"(?m)^\s*['\"](LAUNCH\w*|RESTORE|SHOWBOTTOM|PLACE|QUIT|MARK|PROCS|FG)['\"]\s*\{", p.ps)
    if verb:
        problems.append("string verb is back: %s" % verb.group(1))
    invoke = p.text(p.function("Invoke-Op"))
    if not re.search(r"\bswitch\s+-CaseSensitive\b", invoke, re.I):
        problems.append("Invoke-Op's switch isn't case-sensitive, so old upper-case verbs still match")
    ops = set(re.findall(r"(?m)^\s*'(\w+)'\s*\{", invoke))
    if ops != OPS:
        problems.append("ops are %s, want %s" % (sorted(ops), sorted(OPS)))
    return problems


def setwindowpos_problems(src):
    p = Parts(src)
    problems = []
    calls = [m for m in re.finditer(r"\bSetWindowPos\s*\(", p.cs)
             if "extern" not in p.cs[p.cs.rfind("\n", 0, m.start()):m.start()]]
    if len(calls) < 3:
        problems.append("expected SetWindowPos in KeepSink, OnEvent and Place, found %d" % len(calls))
    for m in calls:
        args = p.cs[m.end() - 1:close_of(p.cs, m.end() - 1, "()") + 1]
        if "HWND_BOTTOM" not in args or "SWP_NOACTIVATE" not in args:
            problems.append("SetWindowPos without HWND_BOTTOM and SWP_NOACTIVATE: %s" % args)
    on_event = p.body("OnEvent") if "OnEvent" in p.methods else ""
    if not ("0x8000" in on_event and "SetWindowPos(" in on_event and "SINK-AT-CREATE" in on_event):
        problems.append("OnEvent no longer sinks new run frames at EVENT_OBJECT_CREATE")
    if not re.search(r"::Start\([^)\n]*\$Keep\b", p.ps, re.I):
        problems.append("-Keep doesn't reach the supervisor's Start")
    check = p.body("Check") if "Check" in p.methods else ""
    if not re.search(r"\bkeeper\b", check) or "KeepSink(" not in check:
        problems.append("Check lost the keeper")
    return problems


def untag_problems(src):
    """Run pids leave the set once refresh passes stop confirming them (Windows reuses pids), and
    only the refresh thread removes them: the hook thread keeps a lock-plus-lookup."""
    p = Parts(src)
    if "Refresh" not in p.methods:
        return ["no Refresh method"]
    problems = []
    refresh = p.body("Refresh")
    m = re.search(r"new\s+Thread\s*\(\s*delegate\s*\(\s*\)\s*\{", refresh)
    thread = refresh[m.end() - 1:close_of(refresh, m.end() - 1) + 1] if m else ""
    if not re.search(r"\btagged\s*\.\s*Remove\s*\(", thread):
        problems.append("the refresh thread never untags a pid")
    for name in p.methods:
        if name != "Refresh" and UNTAG.search(p.body(name)):
            problems.append("%s removes run pids; only the refresh thread may" % name)
    grace = re.search(r"\bconst\s+long\s+UntagMs\s*=\s*(\d+)", p.cs)
    if not grace or not 1000 <= int(grace.group(1)) <= 5000:
        problems.append("the untag grace must be 1-5 s, so a launch pid outlives a pass that missed it")
    elif "UntagMs" not in thread:
        problems.append("the refresh thread doesn't apply the untag grace")
    return problems


def spans(text, opener):
    """(start, end) of every {...} block whose opening matches opener."""
    return [(m.end() - 1, close_of(text, m.end() - 1)) for m in re.finditer(opener + r"\s*\{", text, re.I)]


def inside(pos, blocks):
    return any(a <= pos <= b for a, b in blocks)


def handler_text(p):
    return p.text(p.ps_block(r"\$handler\s*=\s*\[Func\[string,\s*bool\]\]\s*"))


def eof_problems(src):
    """EOF cleans up through Close-Run, and ends the loop whatever the handler returns or throws."""
    p = Parts(src)
    problems = []
    handler = handler_text(p)
    m = re.search(r"\bEofLine\b[^{]*\{", handler)
    branch = handler[m.end() - 1:close_of(handler, m.end() - 1) + 1] if m else ""
    if not re.search(r"\bClose-Run\b", branch, re.I):
        problems.append("the handler's EofLine branch doesn't call Close-Run")
    loop = p.body("Loop") if "Loop" in p.methods else ""
    if not re.search(r"try\s*\{[^{}]*\bhandle\s*\([^{}]*\}\s*catch\b", loop):
        problems.append("Loop doesn't catch a throwing handler")
    if not re.search(r"if\s*\((?=[^{;]*\bEofLine\b)[^{;]*\)\s*\{?\s*done\s*=\s*true", loop):
        problems.append("Loop doesn't end on EofLine whatever the handler returns")
    return problems


def exit_code_problems(src):
    """Exit 0 only after a complete EOF cleanup; 3 otherwise, so bin/chrome-bg runs -Kill."""
    p = Parts(src)
    problems = []
    functions = spans(p.ps, r"(?m)^[ \t]*function[ \t]+[\w-]+[^{\n]*")
    oneshots = spans(p.ps, r"(?m)^[ \t]*if\s*\(\s*\$(?:Scan|Kill)\s*\)")
    start = [m for m in re.finditer(r"\$ExitCode\s*=\s*3\b", p.ps) if not inside(m.start(), functions)]
    if not start:
        problems.append("no top-level $ExitCode = 3 before the loop")
    for m in re.finditer(r"(?im)\bexit\b(?=[ \t]*(?:\d|\$|;|\}|$))", p.ps):
        if not (re.match(r"exit\s+\$ExitCode\b", p.ps[m.start():], re.I) or inside(m.start(), oneshots)):
            problems.append("an exit outside -Scan and -Kill skips the exit code: %r"
                            % p.ps[m.start():m.start() + 12])
    if not re.search(r"\bexit\s+\$ExitCode\b", p.ps, re.I):
        problems.append("the script doesn't exit with $ExitCode")
    close = p.function("Close-Run")
    for m in re.finditer(r"\$(?:script:)?ExitCode\s*=\s*0\b", p.ps):
        head = p.ps[max(p.ps.rfind(c, 0, p.ps.rfind("{", 0, m.start())) for c in ";{}\n") + 1:m.start()]
        guarded = re.search(r"if\s*\((?=[^{]*\.left\s+-eq\s+0)(?=[^{]*-not\s+\$)", head, re.I)
        if not (close and inside(m.start(), [close]) and guarded):
            problems.append("exit code 0 set outside Close-Run's left-0, dir-gone check")
    return problems


def reply_after_eof_problems(src):
    """No reply once stdin has closed: the owner is gone (probe C2)."""
    p = Parts(src)
    problems = []
    send = p.text(p.function("Send-Reply"))
    flag = re.search(r"\bStdinClosed\b", send)
    write = re.search(r"\[Console\]::Out\b", send, re.I)
    if not flag or not write or flag.start() > write.start():
        problems.append("Send-Reply doesn't check StdinClosed before writing")
    reader = p.body("ReadStdin") if "ReadStdin" in p.methods else ""
    if not re.search(r"\bStdinClosed\s*=\s*true\s*;[^}]*\bPush\s*\(\s*EofLine\b", reader):
        problems.append("the stdin reader doesn't set StdinClosed before queuing EofLine")
    return problems


def tag_match_problems(src):
    """Kills and process lists go by the run's tag, never by every chrome.exe."""
    p = Parts(src)
    problems = []
    if not re.search(r"CommandLine[^\n]*\$Tag\b", p.text(p.function("Get-TaggedProcs")), re.I):
        problems.append("Get-TaggedProcs doesn't match CommandLine on $Tag")
    stop = p.text(p.function("Stop-RunProcs"))
    direct = re.search(r"Get-CimInstance|Get-WmiObject|Get-Process\b", stop, re.I)
    if direct or not re.search(r"\bGet-TaggedProcs\b", stop, re.I):
        problems.append("Stop-RunProcs must pick processes through Get-TaggedProcs only")
    return problems


def cleanup_problems(src):
    """A failing query can't stop the cleanup: each kill round catches its own error, the run dir
    is deleted even after a failed kill, and EOFKILL carries the error."""
    p = Parts(src)
    problems = []
    stop = p.text(p.function("Stop-RunProcs"))
    tries = spans(stop, r"\btry")
    for m in re.finditer(r"\bGet-TaggedProcs\b", stop, re.I):
        if not inside(m.start(), tries):
            problems.append("a Get-TaggedProcs call in Stop-RunProcs is outside a try")
    close = p.text(p.function("Close-Run"))
    tries = spans(close, r"\btry")
    kill = re.search(r"\bStop-RunProcs\b", close, re.I)
    rm = re.search(r"\bRemove-RunDir\b", close, re.I)
    if not kill or not rm:
        problems.append("Close-Run doesn't both kill and delete")
    elif not inside(kill.start(), tries) or any(inside(kill.start(), [t]) and inside(rm.start(), [t])
                                                for t in tries):
        problems.append("Close-Run's delete doesn't run independently of a failed kill")
    if not re.search(r"EOFKILL", close) or "error=" not in close:
        problems.append("EOFKILL doesn't carry the kill's error")
    return problems


def top_statements(ps):
    """The script's own statements: splits at newlines and ';' and opens keyword blocks (if, try,
    catch...) whose bodies run at top level; functions, hashtables and script blocks stay whole."""
    out, cur, paren, i = [], [], 0, 0
    while i < len(ps):
        ch = ps[i]
        if ch in "'\"":
            j = i + 1
            while j < len(ps) and ps[j] != ch:
                j += 2 if ch == '"' and ps[j] == "`" else 1
            cur.append(ps[i:j + 1])
            i = j + 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == "{" and not (paren == 0 and KEYWORD_BLOCK.match("".join(cur))):
            j = close_of(ps, i)
            cur.append(ps[i:j + 1])
            i = j + 1
            continue
        if paren == 0 and ch in "\n;{}":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return [s for s in out if s]


def top_output_problems(src):
    """No top-level statement emits pipeline output, which would reach stdout: each one assigns,
    casts to [void], pipes to Out-Null, is a keyword or Send-Reply, or calls a void C# method."""
    p = Parts(src)
    statements = top_statements(p.ps)
    problems = []
    if not any(s.startswith("Add-Type") for s in statements):
        problems.append("top-level parse found no Add-Type")
    for s in statements:
        if SILENT.match(s) or re.search(r"\|\s*Out-Null\s*$", s, re.I):
            continue
        if re.match(r"Add-Type\b", s, re.I) and not re.search(r"-PassThru\b", s, re.I):
            continue
        call = re.match(r"\[\w+\]::(\w+)\s*\(", s)
        if call and p.returns.get(call.group(1)) == "void":
            continue
        problems.append("top-level statement may emit output: %r" % s[:60])
    return problems


def created_problems(src):
    """A run pid is its process: IsTagged compares the creation time recorded when tagging, AddPid
    and Refresh record it, and every process handle is closed in a finally."""
    p = Parts(src)
    problems = []
    readers = {n for n in p.methods if "GetProcessTimes(" in p.body(n)}
    if not readers:
        return ["nothing reads a process creation time"]
    for name in ("IsTagged", "AddPid", "Refresh"):
        if name not in p.methods or not reach(p, [name]) & readers:
            problems.append("%s doesn't read the process creation time" % name)
    calls = r"\b(?:%s)\s*\(" % "|".join(sorted(readers))
    is_tagged = p.body("IsTagged") if "IsTagged" in p.methods else ""
    if not any(re.search(calls, s) and re.search(r"[!=]=", s) for s in is_tagged.split(";")):
        problems.append("IsTagged doesn't compare the creation time")
    for name in p.methods:
        body = p.body(name)
        if "OpenProcess(" in body and not re.search(r"finally\s*\{[^}]*\bCloseHandle\s*\(", body):
            problems.append("%s opens a process without closing it in a finally" % name)
    return problems


def log_kind_problems(src):
    p = Parts(src)
    return ["no log line of kind %s" % kind for kind in LOG_KINDS
            if not re.search(r"Log\(\s*[\"']%s(?![\w-])" % re.escape(kind), p.ps + p.cs)]


class Rules(unittest.TestCase):
    def setUp(self):
        self.src = read()

    def test_ascii_only(self):
        # Windows PowerShell 5.1 reads a file without a BOM in the ANSI code page.
        self.assertTrue(self.src.isascii())

    def test_launches_only_through_wmi(self):
        self.assertEqual(start_process_problems(self.src), [])
        self.assertEqual(launch_problems(self.src), [])

    def test_stdout_only_through_send_reply(self):
        self.assertEqual(stdout_problems(self.src), [])

    def test_no_wmi_reachable_from_the_winevent_callback(self):
        self.assertEqual(callback_wmi_problems(self.src), [])

    def test_titles_only_for_run_windows(self):
        self.assertEqual(title_problems(self.src), [])

    def test_id_is_validated_and_scan_takes_none(self):
        self.assertEqual(id_param_problems(self.src), [])

    def test_prototype_params_and_verbs_are_gone(self):
        self.assertEqual(dropped_problems(self.src), [])

    def test_every_move_is_to_the_bottom_unactivated(self):
        self.assertEqual(setwindowpos_problems(self.src), [])

    def test_log_kinds_for_the_judge(self):
        self.assertEqual(log_kind_problems(self.src), [])

    def test_only_the_refresh_thread_untags_pids(self):
        self.assertEqual(untag_problems(self.src), [])

    def test_eof_cleans_up_and_ends_the_loop(self):
        self.assertEqual(eof_problems(self.src), [])

    def test_exit_code_reports_the_cleanup(self):
        self.assertEqual(exit_code_problems(self.src), [])

    def test_no_reply_after_stdin_closes(self):
        self.assertEqual(reply_after_eof_problems(self.src), [])

    def test_processes_match_the_run_tag(self):
        self.assertEqual(tag_match_problems(self.src), [])

    def test_cleanup_survives_a_failing_query(self):
        self.assertEqual(cleanup_problems(self.src), [])

    def test_no_top_level_output(self):
        self.assertEqual(top_output_problems(self.src), [])

    def test_run_pids_carry_their_creation_time(self):
        self.assertEqual(created_problems(self.src), [])


def mutate(src, pattern, repl, flags=0):
    out, n = re.subn(pattern, repl, src, count=1, flags=flags)
    if not n:
        raise AssertionError("mutation anchor not found: %s" % pattern)
    return out


def in_method(src, name, pattern, repl):
    """Applies a substitution inside one C# method's body."""
    p = Parts(src)
    here = re.search(r"Add-Type\b[^\n]*?@(['\"])[ \t]*\r?\n", src, re.S).end()
    _, start, end = p.methods[name]
    body = src[here + start:here + end + 1]
    return src[:here + start] + mutate(body, pattern, repl) + src[here + end + 1:]


class CatchesRegressions(unittest.TestCase):
    def setUp(self):
        self.src = read()

    def assertCaught(self, check, src):
        self.assertNotEqual(check(src), [])

    def test_start_process_launch(self):
        bad = mutate(self.src, r"\$r = Invoke-CimMethod[^\n]*",
                     "$r = Start-Process -FilePath $Chrome -ArgumentList $a -PassThru")
        self.assertCaught(start_process_problems, bad)
        self.assertCaught(launch_problems, bad)

    def test_launch_without_tagging(self):
        self.assertCaught(launch_problems, mutate(self.src, r"\[ChromeBgSup\]::AddPid\([^\n]*", "$null"))

    def test_stray_stdout_in_an_op(self):
        self.assertCaught(stdout_problems, mutate(self.src, r"('fg'\s*\{)", r"\1 Write-Output 'stray';"))
        self.assertCaught(stdout_problems, mutate(self.src, r"('mark'\s*\{)", r"\1 echo 'stray';"))

    def test_stdout_from_the_csharp(self):
        self.assertCaught(stdout_problems, in_method(self.src, "Log", r"\{", "{ Console.Out.WriteLine(s);"))

    def test_stderr_writer(self):
        self.assertCaught(stdout_problems, mutate(self.src, r"('fg'\s*\{)", r"\1 Write-Warning 'x';"))

    def test_second_reply_in_the_handler(self):
        bad = mutate(self.src, r"(\n[ \t]*Send-Reply \$reply)(\s*\n[ \t]*return \$true)", r"\1\1\2")
        self.assertCaught(stdout_problems, bad)

    def test_wmi_two_calls_below_the_callback(self):
        wmi = 'using (var q = new ManagementObjectSearcher("SELECT ProcessId FROM Win32_Process")) { }'
        self.assertCaught(callback_wmi_problems, in_method(self.src, "Desc", r"\{", "{ " + wmi))

    def test_unguarded_title(self):
        guard = r"if\s*\(\s*IsTagged\s*\([^()]*\)\s*\)\s*"
        self.assertCaught(title_problems, in_method(self.src, "Desc", guard, ""))

    def test_negated_guard(self):
        self.assertCaught(title_problems, in_method(self.src, "Desc", r"if\s*\(\s*IsTagged", "if (!IsTagged"))

    def test_title_logged_elsewhere(self):
        leak = '{ Log("KEEP-SINK title=" + Title(h));'
        self.assertCaught(title_problems, in_method(self.src, "KeepSink", r"\{", leak))

    def test_guard_helper(self):
        def guarded(code):
            return title_guarded(code, code.index("Title("))
        self.assertTrue(guarded("if (IsTagged(p)) { s += Title(h); }"))
        self.assertTrue(guarded("s += IsTagged(p) ? Title(h) : \"\";"))
        self.assertFalse(guarded("if (IsTagged(p)) { } else { s += Title(h); }"))
        self.assertFalse(guarded("if (! IsTagged(p)) s += Title(h);"))
        self.assertFalse(guarded("x = 1; s += Title(h);"))

    def test_id_without_validation(self):
        self.assertCaught(id_param_problems, mutate(self.src, r"\[ValidatePattern\([^\n]*\)\]", ""))

    def test_id_pattern_ignoring_case(self):
        self.assertCaught(id_param_problems, mutate(self.src, r"(ValidatePattern\([^\n]*?)\(\?-i\)", r"\1"))

    def test_id_pattern_with_dollar(self):
        self.assertCaught(id_param_problems, mutate(self.src, r"\{8\}\\z", "{8}$"))

    def test_scan_taking_an_id(self):
        bad = mutate(self.src, r"ParameterSetName\s*=\s*'Scan'", "ParameterSetName = 'Run'")
        self.assertCaught(id_param_problems, bad)

    def test_dropped_param_back(self):
        bad = mutate(self.src, r"(?m)^(param\s*\()", r"\1[string]$Tag = '',", re.I)
        self.assertCaught(dropped_problems, bad)

    def test_old_verb_back(self):
        bad = mutate(self.src, r"(\n[ \t]*default\s*\{)", r"\n    'QUIT' { return $null }\1")
        self.assertCaught(dropped_problems, bad)

    def test_dropped_switch_back(self):
        bad = mutate(self.src, r"(public static class \w+\s*\{)", r"\1 public static bool replyOnly;")
        self.assertCaught(dropped_problems, bad)

    def test_activating_place(self):
        self.assertCaught(setwindowpos_problems, in_method(self.src, "Place", r"SWP_NOACTIVATE", "0"))

    def test_pids_never_untagged(self):
        bad = in_method(self.src, "Refresh", r"tagged\.Remove\(", "tagged.ContainsKey(")
        self.assertCaught(untag_problems, bad)

    def test_untag_on_the_hook_thread(self):
        bad = in_method(self.src, "Check", r"\{", "{ lock (tagged) { tagged.Clear(); }")
        self.assertCaught(untag_problems, bad)

    def test_no_untag_grace(self):
        self.assertCaught(untag_problems, mutate(self.src, r"(UntagMs\s*=\s*)\d+", r"\g<1>0"))

    def test_eof_without_close_run(self):
        self.assertCaught(eof_problems, mutate(self.src, r"Close-Run;\s*", ""))

    def test_loop_trusting_the_handler(self):
        self.assertCaught(eof_problems, in_method(self.src, "Loop", r"\bc\s*==\s*EofLine\b", "false"))
        bad = in_method(self.src, "Loop", r"try\s*\{\s*(more = handle\(c\);)\s*\}\s*catch[^}]*\}", r"\1")
        self.assertCaught(eof_problems, bad)

    def test_exit_code_starting_at_0(self):
        self.assertCaught(exit_code_problems, mutate(self.src, r"(\$ExitCode\s*=\s*)3\b", r"\g<1>0"))

    def test_early_exit_0(self):
        bad = mutate(self.src, r"(\n\[ChromeBgSup\]::Log\(\"EXIT)", r"\nexit 0\1")
        self.assertCaught(exit_code_problems, bad)

    def test_unguarded_exit_code_0(self):
        bad = mutate(self.src, r"if\s*\([^)]*\)\s*\{\s*(\$script:ExitCode\s*=\s*0)\s*\}", r"\1")
        self.assertCaught(exit_code_problems, bad)

    def test_reply_after_eof(self):
        self.assertCaught(reply_after_eof_problems, mutate(self.src, r"\n[^\n]*::StdinClosed\)[^\n]*", ""))
        bad = in_method(self.src, "ReadStdin", r"StdinClosed = true;", "")
        self.assertCaught(reply_after_eof_problems, bad)

    def test_kill_by_name_not_tag(self):
        bad = mutate(self.src, r"(CommandLine\.IndexOf\()\$Tag", r"\1'chrome'")
        self.assertCaught(tag_match_problems, bad)
        every = "@(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\")"
        bad = mutate(self.src, r"@\(Get-TaggedProcs\)", every)
        self.assertCaught(tag_match_problems, bad)

    def test_unguarded_final_count(self):
        guarded = r"\$left = -1\s*\n\s*try \{ \$left = (@\(Get-TaggedProcs\)\.Count) \} catch \{[^}]*\}"
        bad = mutate(self.src, guarded, r"$left = \1")
        self.assertCaught(cleanup_problems, bad)

    def test_delete_tied_to_the_kill(self):
        joint = "try { $k = Stop-RunProcs; $exists = Remove-RunDir }"
        bad = mutate(self.src, r"try \{ \$k = Stop-RunProcs \}", joint)
        self.assertCaught(cleanup_problems, bad)

    def test_top_level_output(self):
        self.assertCaught(top_output_problems, mutate(self.src, r"\[void\]\((New-Item[^\n]*)\)", r"\1"))
        bad = mutate(self.src, r"(\n\[ChromeBgSup\]::ReadStdin\(\))", r"\n[ChromeBgSup]::FgLock()\1")
        self.assertCaught(top_output_problems, bad)

    def test_lookup_only_is_tagged(self):
        bad = in_method(self.src, "IsTagged", r"return[^;]*CreationTime[^;]*;", "return true;")
        self.assertCaught(created_problems, bad)

    def test_leaked_process_handle(self):
        self.assertCaught(created_problems, in_method(self.src, "CreationTime", r"finally\s*\{[^}]*\}", ""))

    def test_missing_log_kind(self):
        self.assertCaught(log_kind_problems, mutate(self.src, r"EOFCLEAN dirExists", "CLEANED dirExists"))


if __name__ == "__main__":
    unittest.main()
