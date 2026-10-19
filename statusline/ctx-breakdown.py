#!/usr/bin/env python3
"""ccstatusline custom-command widget: context breakdown by category.

Reads the Claude Code statusline JSON on stdin. Parses the most recent
/context output stored in the session transcript to get the fixed-overhead
categories (system prompt, tools, skills, memory, MCP...), then computes
Messages live as total_context - overhead. Categories other than Messages
only change when config changes, so one /context run per session keeps the
split honest for the whole session.

Default output is the total chip only (needs preserveColors: true on the
widget so ccstatusline passes the ANSI codes through):
  Ctx 85.4k 43%
The percent is total / window. Flags opt in to more:
  --chips  append per-category breakdown chips after a dim ▏ divider:
           Ctx 85.4k 43% ▏ [Sys 4.2k][Tool 18.1k][Mem 3.1k][Skl 5.9k][Msg 54k]
           (fallback before the first /context run:  Ctx 85k 43% (run /context))
  --conf   render a standalone Conf chip (active config dir) instead
  --no-pct drop the percent from the total chip (tier colors still apply)

The total chip colors by the auto-pass tiers (hooks/autopass_state.py tiers(), on the
watcher's window: the smaller of the model window and autoCompactWindow): green below soft,
yellow from soft, dark red from wrap-up, bold bright red "Ctx!" from hard. A trailing "A"
inside the chip means auto-pass is on for this tab (autopass_state.decide(), cached per
session for CACHE_TTL seconds and while the tab flag's generation holds). On every render
with a session id and a sane context_window_size, the model window is merged into
$XDG_STATE_HOME/dotclaude/ctx/<session>.json as `window` (and `window_at`), since no hook
payload names it; an unchanged value written under WINDOW_FRESH seconds ago is skipped. The
write merges under the session's ctx lock (autopass_state.merge_ctx) and is skipped while the
lock is busy. The cue's cache files (ctx-widget/) are pruned past 7 days, once a day.

setup.sh symlinks this file into ~/.config/ccstatusline/, so its real path finds the repo's
hooks/. When autopass_state can't be imported (a copy, or Windows, which lacks fcntl), the
widget falls back to fixed shares of the window, no cue and no window write.
"""
import sys, json, os, re, signal, tempfile, time

# ccstatusline pipes stdout, where Windows Python defaults to cp1252 and the
# divider glyph below raises UnicodeEncodeError, blanking the whole widget.
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# (label, 256-color bg, 256-color fg) - hues follow /context's own legend
STYLE = {
    'System prompt': ('Sys', 238, 250),
    'System tools': ('Tool', 240, 254),
    'MCP tools': ('MCP', 24, 153),
    'Custom agents': ('Agt', 60, 189),
    'Memory files': ('Mem', 94, 223),
    'Skills': ('Skl', 58, 186),
    'CLAUDE.md': ('Md', 238, 250),
    'Rules': ('Rul', 238, 250),
    'Hooks': ('Hk', 238, 250),
}
MSG_STYLE = ('Msg', 53, 140)
# Categories below this get folded into one dim "Etc" chip to keep the bar short.
MIN_CHIP = 10_000
ETC_STYLE = ('Etc', 236, 245)
CONF_STYLE = (24, 117)
# Total-context chip, by auto-pass band: (256-color bg, fg, attrs, label).
BAND_STYLE = {
    'ok': (22, 114, '', 'Ctx'),
    'soft': (136, 230, '', 'Ctx'),
    'wrap': (88, 210, '', 'Ctx'),
    'hard': (160, 231, '\x1b[1m', 'Ctx!'),
}
# The bands as shares of the window when the tiers are unknown (autopass_state missing, or a
# window too small for tiers).
FALLBACK_SHARE = {'soft': 0.5, 'wrap': 0.66, 'hard': 0.83}
AUTOPASS_CUE = 'A'
CACHE_TTL = 10       # seconds a cached decide() holds
DECIDE_BUDGET = 0.8  # seconds decide() (git, tmux) may take before the cue shows as off
WINDOW_FRESH = 60    # seconds an unchanged `window` write is skipped
LOCK_WAIT = 0.05     # seconds the `window` write waits for the session's ctx lock
SID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')  # hooks/stop_ring.py SID
HOOKS = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'hooks')
RESET = '\x1b[0m'
# Dim divider between the total chip and the category breakdown chips.
GROUP_SEP = '\x1b[38;5;240m ▏ ' + RESET


def chip(label, value, bg, fg):
    return f'\x1b[48;5;{bg}m\x1b[38;5;{fg}m {label} {value} {RESET}'


def load_aps():
    """hooks/autopass_state, found from this file's real path, or None."""
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    try:
        import autopass_state
    except Exception:
        return None
    return autopass_state


def band(total, tiers):
    for name in ('hard', 'wrap', 'soft'):
        if total >= tiers[name]:
            return name
    return 'ok'


def total_chip(total, pct_window, tiers, show_pct=True, cue=False):
    """tiers: {'soft', 'wrap', 'hard'} in tokens, or None for an uncolored chip."""
    if pct_window and show_pct:
        value = f'{fmt(total)} {total / pct_window * 100:.0f}%'
    else:
        value = fmt(total)
    if cue:
        value += ' ' + AUTOPASS_CUE
    if tiers is None:
        return f'Ctx {value}'
    bg, fg, attrs, label = BAND_STYLE[band(total, tiers)]
    return attrs + chip(label, value, bg, fg)


def chip_tiers(aps, pct_window, transcript_path, model_window):
    """The auto-pass tiers on the watcher's window, else fixed shares of pct_window, else None."""
    if aps is not None:
        try:
            t = aps.tiers(aps.window(transcript_path, model_window))
        except Exception:
            t = None
        if t is not None:
            return t
    if not pct_window:
        return None
    return {k: v * pct_window for k, v in FALLBACK_SHARE.items()}


def write_window(aps, sid, size):
    """Merge the model window into the ctx file, keeping its other fields: always on a change,
    else once per WINDOW_FRESH. It goes through aps.merge_ctx, under the session's lock the
    watcher's tokens write takes too, so neither rolls back the other; with the lock busy past
    LOCK_WAIT the write is skipped and the next render retries."""
    now = time.time()
    try:
        rec = aps.read_ctx(sid)
        at = rec.get('window_at')
        if (rec.get('window') == size and isinstance(at, (int, float))
                and 0 <= now - at < WINDOW_FRESH):
            return
        aps.merge_ctx(sid, {'window': size, 'window_at': now}, wait=LOCK_WAIT)
    except Exception:
        pass


class Slow(BaseException):
    """decide() ran past DECIDE_BUDGET. A BaseException, so no `except Exception` inside
    decide() turns it into a wrong answer; subprocess.run kills its child on the way out."""


def _slow(_sig, _frame):
    raise Slow


def timed_decide(aps, cwd, pane):
    """(on, source), or None when decide() failed or ran past DECIDE_BUDGET."""
    timer = hasattr(signal, 'setitimer')
    if timer:
        old = signal.signal(signal.SIGALRM, _slow)
        signal.setitimer(signal.ITIMER_REAL, DECIDE_BUDGET)
    try:
        got = aps.decide(cwd, pane)
        if timer:
            signal.setitimer(signal.ITIMER_REAL, 0)
        return got
    except (Slow, Exception):
        return None
    finally:  # an alarm landing past the try raises Slow from here: autopass_on catches it
        if timer:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            finally:
                signal.signal(signal.SIGALRM, old)


def autopass_on(aps, sid, cwd, pane):
    """Whether auto-pass is on for this tab. The answer is cached per session in the state dir
    (ctx-widget/<session>.json) for CACHE_TTL seconds, for the same cwd and pane, and only while
    the tab flag's generation is the one read before its decide(), so /autopass shows at once.
    A failed or slow decide() caches as off: a slow git costs one DECIDE_BUDGET per CACHE_TTL."""
    if not isinstance(cwd, str) or not cwd:
        return False
    pane = pane if isinstance(pane, str) and pane else None
    now = time.time()
    try:
        path = os.path.join(aps.state_dir(), 'ctx-widget', sid + '.json')
        gen = aps.flag_generation(pane)
        c = aps.load_json(path)
    except Exception:
        return False
    if (isinstance(c, dict) and isinstance(c.get('on'), bool) and c.get('flag') == gen
            and c.get('cwd') == cwd and c.get('pane') == pane
            and isinstance(c.get('at'), (int, float)) and 0 <= now - c['at'] < CACHE_TTL):
        return c['on']
    try:
        got = timed_decide(aps, cwd, pane)
    except Slow:  # the alarm fired as decide() returned, before the timer was cancelled
        got = None
    on, source = got if got is not None else (False, 'unknown')
    try:
        aps.write_json(path, {'on': on, 'source': source, 'at': now, 'flag': gen,
                              'cwd': cwd, 'pane': pane})
        import stop_ring  # beside autopass_state in hooks/
        stop_ring.prune(os.path.dirname(path), now)  # *.json past 7 days, once a day
    except Exception:
        pass
    return on


SKIP = {'Messages', 'Free space', 'Autocompact buffer'}
CAT_RE = re.compile(r'([A-Z][A-Za-z.]*(?: [a-z][a-z.]+)*):\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)')
MARKER = b'Estimated usage by category'


def to_tokens(s):
    return float(s[:-1]) * 1000 if s.endswith('k') else float(s)


def fmt(n):
    if n >= 99500:
        return f'{n / 1000:.0f}k'
    if n >= 1000:
        return f'{n / 1000:.1f}k'
    return f'{n:.0f}'


def parse_breakdown(path):
    """Return ({category: tokens}, autocompact_window) from the last /context
    dump in the transcript. Either element may be None."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, None
    cache = os.path.join(tempfile.gettempdir(),
                         'ctx-breakdown-' + re.sub(r'\W', '_', path)[-80:] + '.json')
    try:
        with open(cache, encoding='utf-8') as f:
            c = json.load(f)
        if c.get('size') == size:
            return c.get('cats') or None, c.get('acw')
    except (OSError, ValueError, RecursionError):   # json recurses on nesting
        pass

    cats = acw = None
    try:
        with open(path, 'rb') as f:
            data = f.read()
        # Walk marker hits from the end; take the last one that parses.
        pos = len(data)
        while cats is None:
            pos = data.rfind(MARKER, 0, pos)
            if pos < 0:
                break
            # /context lines are ANSI-heavy: a category line can run long
            chunk = data[pos:pos + 8000].decode('utf-8', 'ignore')
            # The command-time transcript entry stores ANSI codes JSON-escaped
            # (a literal backslash-u001b sequence in the raw bytes); the copy
            # attached to the next user message has raw ESC bytes. Handle both.
            chunk = chunk.replace('\\u001b', '\x1b')
            chunk = re.sub(r'\x1b\[[0-9;]*m', '', chunk)
            m = re.search(r'Auto-compact window:\s*([\d.]+k?)', chunk)
            if m:
                acw = to_tokens(m.group(1))
            chunk = chunk.split('Auto-compact window', 1)[0]
            found = {}
            for m in CAT_RE.finditer(chunk):
                name = m.group(1).strip()
                if name not in SKIP:
                    found[name] = to_tokens(m.group(2))
            if len(found) >= 3:
                cats = found
    except OSError:
        return None, None

    try:
        with open(cache, 'w', encoding='utf-8') as f:
            json.dump({'size': size, 'cats': cats, 'acw': acw}, f)
    except OSError:
        pass
    return cats, acw


def config_dir(transcript_path):
    """The active config dir, derived from the transcript path (always
    <config-dir>/projects/<project>/<session>.jsonl) because Claude Code does
    not pass CLAUDE_CONFIG_DIR through to child processes."""
    if transcript_path:
        if os.path.basename(os.path.dirname(os.path.dirname(transcript_path))) == 'projects':
            return os.path.dirname(os.path.dirname(os.path.dirname(transcript_path)))
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')


def autocompact_setting(cfg):
    """autoCompactWindow from the config dir's settings.json, if set."""
    try:
        with open(os.path.join(cfg, 'settings.json'), encoding='utf-8') as f:
            v = json.load(f).get('autoCompactWindow')
        return v if isinstance(v, (int, float)) and v > 0 else None
    except (OSError, ValueError, RecursionError):   # json recurses on nesting
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, RecursionError):   # json recurses on nesting
        data = None
    if not isinstance(data, dict):
        print('Ctx ?')
        return
    tp = data.get('transcript_path')
    tp = tp if isinstance(tp, str) else None
    if '--conf' in sys.argv[1:]:
        # Standalone Conf chip so the layout can place it independently.
        cfg = config_dir(tp)
        print(chip('Conf', os.path.basename(cfg), *CONF_STYLE) if cfg else '')
        return
    cw = data.get('context_window')
    cw = cw if isinstance(cw, dict) else {}
    size = cw.get('context_window_size')
    sid = data.get('session_id')
    sid = sid if isinstance(sid, str) and SID.fullmatch(sid) else None
    aps = load_aps()
    if (aps is not None and sid and aps.is_int(size)
            and aps.WINDOW_RANGE[0] <= size <= aps.WINDOW_RANGE[1]):
        write_window(aps, sid, size)

    # The current context, not a session total: live-checked 2026-10-12 (2.1.296, Opus 5.5), it
    # equals the current_usage sum and the transcript's last main-chain usage sum turn to turn.
    total = cw.get('total_input_tokens')
    if total is None:
        u = cw.get('current_usage')
        u = u if isinstance(u, dict) else {}
        total = sum(v for k in ('input_tokens', 'cache_read_input_tokens',
                                'cache_creation_input_tokens')
                    if isinstance(v := u.get(k), (int, float)))
    if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
        print('Ctx ?')
        return

    cats = acw = None
    if tp:
        cats, acw = parse_breakdown(tp)
    # Percent base: the smallest of the model window, the auto-compact
    # window reported by /context, and the autoCompactWindow setting --
    # compaction fires at the auto-compact point, not the model window.
    cfg = config_dir(tp)
    candidates = [w for w in (size, acw, autocompact_setting(cfg))
                  if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0]
    window = min(candidates) if candidates else None
    tiers = chip_tiers(aps, window, tp, size)
    cue = bool(aps and sid) and autopass_on(aps, sid, data.get('cwd'),
                                            os.environ.get('TMUX_PANE'))
    head = total_chip(total, window, tiers, '--no-pct' not in sys.argv[1:], cue)

    if '--chips' not in sys.argv[1:]:
        print(head)
        return
    if not cats:
        print(f'{head} (run /context for split)')
        return

    overhead = sum(cats.values())
    msgs = max(0, total - overhead)
    chips = []
    etc = 0
    for k, v in cats.items():
        if v < MIN_CHIP:
            etc += v
            continue
        label, bg, fg = STYLE.get(k, (k[:3], 238, 250))
        chips.append(chip(label, fmt(v), bg, fg))
    if etc >= 1000:
        label, bg, fg = ETC_STYLE
        chips.append(chip(label, fmt(etc), bg, fg))
    label, bg, fg = MSG_STYLE
    chips.append(chip(label, fmt(msgs), bg, fg))
    print(head + GROUP_SEP + ''.join(chips))


if __name__ == '__main__':
    main()
