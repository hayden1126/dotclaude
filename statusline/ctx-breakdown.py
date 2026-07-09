#!/usr/bin/env python3
"""ccstatusline custom-command widget: context breakdown by category.

Reads the Claude Code statusline JSON on stdin. Parses the most recent
/context output stored in the session transcript to get the fixed-overhead
categories (system prompt, tools, skills, memory, MCP...), then computes
Messages live as total_context - overhead. Categories other than Messages
only change when config changes, so one /context run per session keeps the
split honest for the whole session.

Output: colored background "chips", one per category (needs preserveColors:
true on the widget so ccstatusline passes the ANSI codes through):
  Ctx 85.4k [Sys 4.2k][Tool 18.1k][Mem 3.1k][Skl 5.9k][Msg 54k]
Fallback (no /context run yet):  Ctx 85k (run /context for split)
"""
import sys, json, os, re, tempfile

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
MSG_STYLE = ('Msg', 97, 189)
# Total-context chip: green when comfortable, amber past 50% of the window,
# red past 66% (~400k of a 600k window).
TOTAL_STYLE = [(0.66, 88, 210), (0.50, 130, 215), (0.0, 22, 114)]
RESET = '\x1b[0m'


def chip(label, value, bg, fg):
    return f'\x1b[48;5;{bg}m\x1b[38;5;{fg}m {label} {value} {RESET}'


def total_chip(total, window):
    if not window:
        return f'Ctx {fmt(total)}'
    frac = total / window
    for threshold, bg, fg in TOTAL_STYLE:
        if frac >= threshold:
            return chip('Ctx', fmt(total), bg, fg)
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
    """Return {category: tokens} from the last /context dump in the transcript."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    cache = os.path.join(tempfile.gettempdir(),
                         'ctx-breakdown-' + re.sub(r'\W', '_', path)[-80:] + '.json')
    try:
        with open(cache, encoding='utf-8') as f:
            c = json.load(f)
        if c.get('size') == size:
            return c.get('cats') or None
    except (OSError, ValueError):
        pass

    cats = None
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
            chunk = re.sub(r'\x1b\[[0-9;]*m', '', chunk)
            chunk = chunk.split('Auto-compact window', 1)[0]
            found = {}
            for m in CAT_RE.finditer(chunk):
                name = m.group(1).strip()
                if name not in SKIP:
                    found[name] = to_tokens(m.group(2))
            if len(found) >= 3:
                cats = found
    except OSError:
        return None

    try:
        with open(cache, 'w', encoding='utf-8') as f:
            json.dump({'size': size, 'cats': cats}, f)
    except OSError:
        pass
    return cats


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        print('Ctx ?')
        return
    cw = data.get('context_window') or {}
    total = cw.get('total_input_tokens')
    if total is None:
        u = cw.get('current_usage') or {}
        total = sum(u.get(k) or 0 for k in
                    ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    if not total:
        print('Ctx ?')
        return

    window = cw.get('context_window_size')
    head = total_chip(total, window)

    cats = None
    tp = data.get('transcript_path')
    if tp:
        cats = parse_breakdown(tp)
    if not cats:
        print(f'{head} (run /context for split)')
        return

    overhead = sum(cats.values())
    msgs = max(0, total - overhead)
    chips = []
    for k, v in cats.items():
        if v < 50:
            continue
        label, bg, fg = STYLE.get(k, (k[:3], 238, 250))
        chips.append(chip(label, fmt(v), bg, fg))
    label, bg, fg = MSG_STYLE
    chips.append(chip(label, fmt(msgs), bg, fg))
    print(head + ''.join(chips))


if __name__ == '__main__':
    main()
