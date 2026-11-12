#!/usr/bin/python3 -I
"""Build the watch list, practice/videos.html, from practice/videos.json, from the hub root.

  videos.py [--root DIR]

The watch list ranks explainer videos per idea of the course, best first, with a "read the notes"
row where no video is good. The page is the notes chassis: the skill's templates/notes-chassis.html
with its placeholders filled, the Review toggle's blocks replaced by a By idea / By lecture toggle,
one accent rule per topic from assemble.py's accents(), and templates/videos-addon.html's CSS and
script added (the rows, chips, legend and the view switch). So the page has the notes page's rail
with scroll-spy, themes, fixed theme icon, full screen and keys (CHASSIS.md C1 to C4); MathJax
loads as on the notes page (no math is expected). The figure panel's code (C5) is present and idle.

The data, practice/videos.json (UTF-8 JSON; text is escaped, so markup shows as text):

  top     exam (label, e.g. "Midterm 1"); course (optional short label for the rail and title);
          notes_url (the published notes page's https URL, no #); lectures (optional:
          {lecture key: title} naming the by-lecture view's groups; when given, every segment's
          lecture must be in it); topics (ordered list, at least one).
  topic   key (slug: a-z, 0-9, hyphens; unique); name; section (the notes section label, "§8");
          intro (list of short bullet strings: what it is, how it differs from its neighbour
          topic, how its rows build); ideas (ordered list, at least one).
  idea    idea (title); notes (list of notes ids it maps to, at least one: sec-N, sec-N-slug,
          ex-N-slug or fig-N-slug, linked to notes_url#id); picks (ordered list, best first).
  pick    kind: video | segment (a stretch of a full lecture) | yours (a link the student
          supplied, ranked on the same rules) | notes (read the notes: no good video).
          Every pick: thread (one line: what it picks up from the previous row, what it sets up
          for the next), differs (list of "differs from your notes" lines, notation and symbols
          first; [] renders "Matches your notes"), tested (one line: how it's tested, what to
          write), also (optional {lead, items}: "+ also" points folded in from cut overlapping
          videos).
          A video, segment or yours pick: title, channel, video_id (11 of A-Z a-z 0-9 _ -),
          start and end (optional whole seconds; a segment needs start), length (optional text),
          visuals (optional short text), why (string or list of strings), flags (optional list
          of short chips, "quiet audio"); a segment also lecture (a lecture key: its by-lecture
          group) and chapter (optional text).
          A notes pick: title (optional, default "Read the notes"), explain (optional concise
          box: a list of {label, text}, labels from Rule, Why, Steps, Example, Trap, Answer form,
          in that order, each at most once), and none of the video fields.

The page: a legend under the title explains the chips; each topic is a section.note (its own
accent) opening with its intro box; each idea an h3 with a line of links into the notes; each
pick a numbered row: the title linked to https://www.youtube.com/watch?v=<id>&t=<start>s (links
only: the artifact host blocks embedded players; target=_blank rel=noopener), the time range
(m:ss, h:mm:ss past an hour), length, a kind chip (your pick, lecture, no good video; none for a
plain video), visuals, why, flags as chips, then the thread, differs, tested and also lines; a
notes row's explain renders as CHASSIS.md C6's concise box. The by-lecture view, when any
segment exists, lists each lecture's segments across topics in timestamp order, the gaps before
and between them marked "Skipped" (a gap after a segment with no end can't be known and isn't
shown), each row linking back to its idea; the view is remembered per viewer in localStorage.
A footer counts the picks and topics.

Checks (exit 1, every problem listed as `<file>: <path.to.field>: <message>`, nothing written):
the shape above (a missing or mistyped field, an unknown kind or explain label, explain labels
out of order or repeated, a field on a kind that doesn't take it); a segment without start; end
not after start; a video_id not of YouTube's form; a notes id not of the notes page's id form,
or, when the notes page is built here at _build/notes.html, an id it doesn't have; the same
video and start twice anywhere on the page (the same stretch twice: fold the second into the
first row's also); two picks of one video in one idea whose ranges overlap or sit within
ADJACENT seconds of each other (merge them; no start is 0, no end is the video's end); the
segments of one lecture key on different videos. Exit 2 on bad usage (no data file, data that
isn't UTF-8). Stdlib only.
"""
import argparse
import html
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHASSIS = os.path.join(HERE, "..", "templates", "notes-chassis.html")
ADDON = os.path.join(HERE, "..", "templates", "videos-addon.html")
DATA = os.path.join("practice", "videos.json")
OUT = os.path.join("practice", "videos.html")
NOTES = os.path.join("_build", "notes.html")

KINDS = {"video": "", "segment": "lecture", "yours": "your pick", "notes": "no good video"}
LABELS = ["Rule", "Why", "Steps", "Example", "Trap", "Answer form"]
VIDEO_FIELDS = ("channel", "video_id", "start", "end", "length", "visuals", "why", "flags",
                "lecture", "chapter")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
NOTES_ID = re.compile(r"^(sec-[1-9][0-9]*(-[a-z0-9]+)*|(ex|fig)-[1-9][0-9]*(-[a-z0-9]+)+)$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SECTION = re.compile(r"^§[1-9][0-9]*$")
NOTES_URL = re.compile(r"^https://[^\s#\"'<>]+$")
# Two stretches of one video this close are one stretch to a student: merge them. A judgement,
# not a measured threshold.
ADJACENT = 10
TOGGLE = re.compile(r"<!-- REVIEW TOGGLE -->(.*?)<!-- /REVIEW TOGGLE -->", re.S)
PAGEHEAD = re.compile(r'<header class="pagehead">.*?</header>', re.S)


def load_assemble():
    """assemble.py, for accents(): the topics take the notes page's section hues."""
    spec = importlib.util.spec_from_file_location("exam_prep_assemble", os.path.join(HERE, "assemble.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Problems:
    def __init__(self, name):
        self.name, self.lines = name, []

    def add(self, path, msg):
        self.lines.append(f"{self.name}: {path}: {msg}")


def text(obj, key, path, bad, required=True):
    """obj[key] as a non-empty string, or None (with a problem when required or mistyped)."""
    if key not in obj:
        if required:
            bad.add(f"{path}.{key}", "missing")
        return None
    v = obj[key]
    if not isinstance(v, str) or not v.strip():
        bad.add(f"{path}.{key}", "want a non-empty string")
        return None
    return v.strip()


def texts(obj, key, path, bad, required=True, empty_ok=False):
    """obj[key] as a list of non-empty strings, or None."""
    if key not in obj:
        if required:
            bad.add(f"{path}.{key}", "missing" + (" (write [] for none)" if empty_ok else ""))
        return None
    v = obj[key]
    if not isinstance(v, list) or (not v and not empty_ok) \
            or not all(isinstance(s, str) and s.strip() for s in v):
        bad.add(f"{path}.{key}", "want a list of non-empty strings" + ("" if empty_ok else ", at least one"))
        return None
    return [s.strip() for s in v]


def seconds(obj, key, path, bad):
    if key not in obj:
        return None
    v = obj[key]
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        bad.add(f"{path}.{key}", "want whole seconds (an integer, 0 or more)")
        return None
    return v


def check_explain(v, path, bad):
    if not isinstance(v, list) or not v:
        bad.add(path, "want a list of {label, text}, at least one")
        return None
    out, last = [], -1
    for i, item in enumerate(v):
        p = f"{path}[{i}]"
        if not isinstance(item, dict):
            bad.add(p, "want {label, text}")
            continue
        label, body = text(item, "label", p, bad), text(item, "text", p, bad)
        for k in item:
            if k not in ("label", "text"):
                bad.add(f"{p}.{k}", "unknown field (label, text)")
        if label is None:
            continue
        if label not in LABELS:
            bad.add(f"{p}.label", f"'{label}' isn't one of {', '.join(LABELS)}")
            continue
        k = LABELS.index(label)
        if k <= last:
            bad.add(f"{p}.label", f"'{label}' out of order: the labels go {', '.join(LABELS)}, each once")
            continue
        last = k
        if body is not None:
            out.append((label, body))
    return out


def check_pick(pick, path, bad, known):
    if not isinstance(pick, dict):
        bad.add(path, "want an object")
        return None
    kind = pick.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        bad.add(f"{path}.kind", f"unknown kind {json.dumps(kind)} (video, segment, yours or notes)")
        return None
    p = {"kind": kind, "path": path}
    if kind == "notes":
        for k in VIDEO_FIELDS:
            if k in pick:
                bad.add(f"{path}.{k}", "a notes row has no video: drop it, or make the row a video")
        p["title"] = text(pick, "title", path, bad, required=False) or "Read the notes"
        p["explain"] = check_explain(pick["explain"], f"{path}.explain", bad) if "explain" in pick else None
    else:
        if "explain" in pick:
            bad.add(f"{path}.explain", "only a notes row takes explain")
        p["title"] = text(pick, "title", path, bad)
        p["channel"] = text(pick, "channel", path, bad)
        vid = text(pick, "video_id", path, bad)
        if vid is not None and not VIDEO_ID.match(vid):
            bad.add(f"{path}.video_id", f"{json.dumps(vid)} isn't a YouTube id (11 of A-Z a-z 0-9 _ -)")
            vid = None
        p["video_id"] = vid
        p["start"], p["end"] = seconds(pick, "start", path, bad), seconds(pick, "end", path, bad)
        if kind == "segment" and "start" not in pick:
            bad.add(f"{path}.start", "a segment needs start (seconds into the lecture)")
        if p["end"] is not None and p["end"] <= (p["start"] or 0):
            bad.add(f"{path}.end", f"end {p['end']} isn't after start {p['start'] or 0}")
            p["end"] = None
        p["length"] = text(pick, "length", path, bad, required=False)
        p["visuals"] = text(pick, "visuals", path, bad, required=False)
        why = pick.get("why")
        if isinstance(why, str):
            p["why"] = text(pick, "why", path, bad)
            p["why"] = [p["why"]] if p["why"] else None
        else:
            p["why"] = texts(pick, "why", path, bad)
        p["flags"] = texts(pick, "flags", path, bad, required=False) or []
        if kind == "segment":
            lec = text(pick, "lecture", path, bad)
            if lec is not None and not SLUG.match(lec):
                bad.add(f"{path}.lecture", f"{json.dumps(lec)} isn't a key (a-z, 0-9, hyphens)")
                lec = None
            p["lecture"] = lec
            p["chapter"] = text(pick, "chapter", path, bad, required=False)
        else:
            for k in ("lecture", "chapter"):
                if k in pick:
                    bad.add(f"{path}.{k}", "only a segment takes a lecture and chapter")
    p["thread"] = text(pick, "thread", path, bad)
    p["differs"] = texts(pick, "differs", path, bad, empty_ok=True)
    p["tested"] = text(pick, "tested", path, bad)
    p["also"] = None
    if "also" in pick:
        a = pick["also"]
        if not isinstance(a, dict):
            bad.add(f"{path}.also", "want {lead, items}")
        else:
            p["also"] = (text(a, "lead", f"{path}.also", bad), texts(a, "items", f"{path}.also", bad))
    allowed = {"kind", "title", "explain", "thread", "differs", "tested", "also"} | set(VIDEO_FIELDS)
    for k in pick:
        if k not in allowed:
            bad.add(f"{path}.{k}", "unknown field")
    return p


def check(data, bad, known):
    """The data checked and normalized: (top, topics), problems recorded in bad."""
    if not isinstance(data, dict):
        bad.add("(top)", "want an object with exam, notes_url and topics")
        return None
    top = {"exam": text(data, "exam", "(top)", bad), "course": text(data, "course", "(top)", bad, False)}
    url = text(data, "notes_url", "(top)", bad)
    if url is not None and not NOTES_URL.match(url):
        bad.add("notes_url", "want the published notes page's https:// URL, with no # part")
        url = None
    top["notes_url"] = url or ""
    lectures = data.get("lectures")
    if lectures is not None and (not isinstance(lectures, dict) or not all(
            isinstance(k, str) and SLUG.match(k) and isinstance(v, str) and v.strip() for k, v in lectures.items())):
        bad.add("lectures", "want {lecture key: title}, keys of a-z, 0-9 and hyphens")
        lectures = None
    top["lectures"] = lectures
    for k in data:
        if k not in ("exam", "course", "notes_url", "lectures", "topics"):
            bad.add(k, "unknown field")
    raw = data.get("topics")
    if not isinstance(raw, list) or not raw:
        bad.add("topics", "want a list of topics, at least one")
        return top, []
    topics, keys = [], set()
    for ti, t in enumerate(raw):
        tp = f"topics[{ti}]"
        if not isinstance(t, dict):
            bad.add(tp, "want an object")
            continue
        key = text(t, "key", tp, bad)
        if key is not None and not SLUG.match(key):
            bad.add(f"{tp}.key", f"{json.dumps(key)} isn't a slug (a-z, 0-9, hyphens)")
        elif key is not None and key in keys:
            bad.add(f"{tp}.key", f"{json.dumps(key)} is another topic's key too")
        keys.add(key)
        sec = text(t, "section", tp, bad)
        if sec is not None and not SECTION.match(sec):
            bad.add(f"{tp}.section", f"{json.dumps(sec)} isn't a notes section label (§N)")
        topic = {"key": key or f"t{ti + 1}", "name": text(t, "name", tp, bad), "section": sec,
                 "intro": texts(t, "intro", tp, bad), "ideas": []}
        for k in t:
            if k not in ("key", "name", "section", "intro", "ideas"):
                bad.add(f"{tp}.{k}", "unknown field")
        ideas = t.get("ideas")
        if not isinstance(ideas, list) or not ideas:
            bad.add(f"{tp}.ideas", "want a list of ideas, at least one")
            ideas = []
        for ii, idea in enumerate(ideas):
            ip = f"{tp}.ideas[{ii}]"
            if not isinstance(idea, dict):
                bad.add(ip, "want an object")
                continue
            notes = texts(idea, "notes", ip, bad) or []
            for ni, nid in enumerate(notes):
                if not NOTES_ID.match(nid):
                    bad.add(f"{ip}.notes[{ni}]", f"{json.dumps(nid)} isn't a notes id (sec-N, sec-N-slug, "
                                                 "ex-N-slug or fig-N-slug)")
                elif known is not None and nid not in known:
                    bad.add(f"{ip}.notes[{ni}]", f"{json.dumps(nid)} isn't an id in {NOTES}")
            for k in idea:
                if k not in ("idea", "notes", "picks"):
                    bad.add(f"{ip}.{k}", "unknown field")
            entry = {"idea": text(idea, "idea", ip, bad), "notes": notes, "picks": []}
            picks = idea.get("picks")
            if not isinstance(picks, list) or not picks:
                bad.add(f"{ip}.picks", "want a list of picks, best first, at least one")
                picks = []
            for pi, pick in enumerate(picks):
                p = check_pick(pick, f"{ip}.picks[{pi}]", bad, known)
                if p:
                    entry["picks"].append(p)
            topic["ideas"].append(entry)
        topics.append(topic)
    cross_check(topics, top, bad)
    return top, topics


def span(p):
    return (p["start"] or 0, p["end"] if p["end"] is not None else float("inf"))


def cross_check(topics, top, bad):
    seen, lecture_video = {}, {}
    for t in topics:
        for idea in t["ideas"]:
            vids = [p for p in idea["picks"] if p.get("video_id")]
            for p in vids:
                at = (p["video_id"], p["start"] or 0)
                if at in seen:
                    bad.add(p["path"], f"the same stretch as {seen[at]} ({p['video_id']} from "
                                       f"{clock(at[1])}): fold it into that row's also")
                else:
                    seen[at] = p["path"]
                if p["kind"] == "segment" and p.get("lecture"):
                    lec = p["lecture"]
                    if top["lectures"] is not None and lec not in top["lectures"]:
                        bad.add(f"{p['path']}.lecture", f"{json.dumps(lec)} isn't in lectures")
                    first = lecture_video.setdefault(lec, (p["video_id"], p["path"]))
                    if first[0] != p["video_id"]:
                        bad.add(f"{p['path']}.video_id", f"lecture {lec} is video {first[0]} at {first[1]}: "
                                                         "one lecture key, one video")
            by_video = {}
            for p in vids:
                by_video.setdefault(p["video_id"], []).append(p)
            for group in by_video.values():
                group = sorted(group, key=span)
                for a, b in zip(group, group[1:]):
                    if span(a)[0] == span(b)[0]:
                        continue  # reported above as the same stretch
                    if span(b)[0] <= span(a)[1] + ADJACENT:
                        how = "overlaps" if span(b)[0] < span(a)[1] else "adjoins"
                        bad.add(b["path"], f"{how} {a['path']} (same video, {clock(span(a)[0])} and "
                                           f"{clock(span(b)[0])}): merge them into one row")


def clock(s):
    """Seconds as m:ss, or h:mm:ss from an hour."""
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def watch_url(vid, start):
    return f"https://www.youtube.com/watch?v={vid}" + (f"&t={start}s" if start else "")


def notes_ids(path):
    """The ids the built notes page has, with each heading's text."""
    with open(path, encoding="utf-8") as f:
        page = f.read()
    titles = {}
    for m in re.finditer(r'<h3 id="([^"]+)"[^>]*>(.*?)</h3>', page, re.S):
        titles[m.group(1)] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
    return set(re.findall(r'\bid="([^"]+)"', page)), titles


e = html.escape


def line(label, body, cls=""):
    return f'<div class="vline{(" " + cls) if cls else ""}"><span class="vlab">{label}</span><div>{body}</div></div>'


def bullets(items):
    return "<ul>" + "".join(f"<li>{e(s)}</li>" for s in items) + "</ul>"


def notes_link(top, nid, titles):
    label = titles.get(nid) or nid
    return (f'<a class="vnote" href="{e(top["notes_url"])}#{e(nid)}" target="_blank" rel="noopener">'
            f'{e(label)}</a>')


def pick_html(top, idea, p, pid, titles):
    kind = p["kind"]
    chip = f'<span class="kchip k-{kind}">{KINDS[kind]}</span>' if KINDS[kind] else ""
    out = [f'<li class="pick k-{kind}" id="{pid}">']
    if kind == "notes":
        first = idea["notes"][0] if idea["notes"] else ""
        out.append(f'<div class="ptop"><a class="vtitle" href="{e(top["notes_url"])}#{e(first)}" target="_blank" '
                   f'rel="noopener">{e(p["title"])}</a>{chip}</div>')
        if p["explain"]:
            out.append('<div class="concise"><ul>' + "".join(
                f"<li><strong>{e(lab)}</strong> {e(body)}</li>" for lab, body in p["explain"]) + "</ul></div>")
    else:
        vid = p["video_id"] or ""
        out.append(f'<div class="ptop"><a class="vtitle" href="{e(watch_url(vid, p["start"]))}" target="_blank" '
                   f'rel="noopener">{e(p["title"] or "")}</a>{chip}</div>')
        meta = [e(p["channel"] or "")]
        if p["start"] is not None or p["end"] is not None:
            rng = clock(p["start"] or 0) + (f"–{clock(p['end'])}" if p["end"] is not None else " on")
            meta.append(f'<span class="vtime">{rng}</span>')
        if p["length"]:
            meta.append(e(p["length"]))
        if kind == "segment" and p.get("chapter"):
            meta.append(e(p["chapter"]))
        out.append('<p class="vmeta">' + "".join(f"<span>{m}</span>" for m in meta) + "</p>")
        if p["flags"]:
            out.append('<p class="vflags">' + "".join(f'<span class="flag">{e(f)}</span>' for f in p["flags"]) + "</p>")
        if p["visuals"]:
            out.append(line("Visuals", e(p["visuals"])))
        if p["why"]:
            out.append(line("Why", e(p["why"][0]) if len(p["why"]) == 1 else bullets(p["why"])))
    out.append(line("Thread", e(p["thread"] or "")))
    if p["differs"]:
        out.append(line("Differs", bullets(p["differs"]), "vdiff"))
    else:
        out.append(line("Differs", "Matches your notes", "vsame"))
    out.append(line("Tested", e(p["tested"] or "")))
    if p["also"]:
        lead, items = p["also"]
        out.append(line("+ also", (f"<p>{e(lead)}</p>" if lead else "") + bullets(items or []), "valso"))
    out.append("</li>")
    return "\n".join(out)


def render(top, topics, titles):
    idea_view, segments, counts = [], {}, {k: 0 for k in KINDS}
    for t in topics:
        sec = (f'<section class="note" id="t-{t["key"]}">\n<h2><span class="n">{e(t["section"] or "")}</span> '
               f'{e(t["name"] or "")}</h2>\n<div class="vintro"><ul>'
               + "".join(f"<li>{e(s)}</li>" for s in t["intro"] or []) + "</ul></div>")
        parts = [sec]
        for ii, idea in enumerate(t["ideas"], 1):
            iid = f'i-{t["key"]}-{ii}'
            links = ", ".join(notes_link(top, n, titles) for n in idea["notes"])
            parts.append(f'<h3 id="{iid}">{e(idea["idea"] or "")}</h3>\n<p class="vnotes">In your notes: {links}</p>')
            rows = []
            for pi, p in enumerate(idea["picks"], 1):
                pid = f"{iid}-{pi}"
                counts[p["kind"]] += 1
                rows.append(pick_html(top, idea, p, pid, titles))
                if p["kind"] == "segment" and p.get("lecture"):
                    segments.setdefault(p["lecture"], []).append((p, t, idea, iid, pid))
            parts.append('<ol class="picks">\n' + "\n".join(rows) + "\n</ol>")
        idea_view.append("\n".join(parts) + "\n</section>")
    lecture_view = []
    for lec, segs in segments.items():
        segs.sort(key=lambda s: span(s[0]))
        name = (top["lectures"] or {}).get(lec) or lec
        vid = segs[0][0]["video_id"]
        rows, pos = [], 0
        for p, t, idea, iid, pid in segs:
            s, end = p["start"] or 0, p["end"]
            if pos is not None and s > pos:
                rows.append(f'<li class="lgap">Skipped {clock(pos)}–{clock(s)} ({clock(s - pos)})</li>')
            if pos is not None:
                pos = max(pos, end) if end is not None else None
            rng = clock(s) + (f"–{clock(end)}" if end is not None else " on")
            chap = f'<span class="lchap">{e(p["chapter"])}</span>' if p.get("chapter") else ""
            rows.append(f'<li class="lrow" data-start="{s}"><a class="ltime" href="{e(watch_url(vid, s))}" '
                        f'target="_blank" rel="noopener">{rng}</a>{chap}<a class="lback" href="#{pid}">'
                        f'{e(idea["idea"] or "")}</a><span class="lsec">{e(t["section"] or "")} '
                        f'{e(t["name"] or "")}</span></li>')
        lecture_view.append(f'<section class="lect" id="l-{lec}">\n<h2>{e(name)}</h2>\n'
                            f'<p class="vmeta"><span>{e(segs[0][0]["channel"] or "")}</span>'
                            f'<span><a href="{e(watch_url(vid, 0))}" target="_blank" rel="noopener">whole lecture'
                            f'</a></span></p>\n<ol class="lrows">\n' + "\n".join(rows) + "\n</ol>\n</section>")
    total = sum(counts.values())
    nideas = sum(len(t["ideas"]) for t in topics)
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"  # noqa: E731
    foot = (f'<footer class="vfoot">{plural(total, "pick")} ({counts["video"]} video, {counts["segment"]} '
            f'lecture, {counts["yours"]} yours, {counts["notes"]} notes) across {plural(nideas, "idea")} '
            f'in {plural(len(topics), "topic")}.</footer>')
    body = f'<div id="view-idea">\n' + "\n".join(idea_view) + "\n</div>\n"
    if lecture_view:
        body += '<div id="view-lecture">\n' + "\n".join(lecture_view) + "\n</div>\n"
    return body + foot, bool(lecture_view), total


def pagehead(top, has_lectures):
    title = (f'{e(top["course"])}: ' if top["course"] else "") + f'{e(top["exam"] or "")} watch list'
    legend = [('<span class="kchip k-yours">your pick</span>', "a link you sent, ranked on the same rules"),
              ('<span class="kchip k-segment">lecture</span>', "a stretch of a full lecture"),
              ('<span class="kchip k-notes">no good video</span>', "read the notes instead"),
              ('<span class="flag">flag</span>', "a warning about the video itself")]
    lede = ("Explainers for each idea, best first: each row says why it is ranked there, what it "
            "picks up from the row before, where it differs from your notes, and how the idea is tested.")
    if has_lectures:
        lede += " By lecture lists the lecture stretches in order, with what to skip."
    return (f'<header class="pagehead">\n      <h1>{title}</h1>\n      <p class="lede">{lede}</p>\n'
            '      <ul class="vlegend" aria-label="What the chips mean">'
            + "".join(f"<li>{c} {e(w)}</li>" for c, w in legend) + "</ul>\n"
            f'      <span class="examline"><a href="{e(top["notes_url"])}" target="_blank" rel="noopener">'
            f'Your notes</a></span>\n    </header>')


TOGGLE_HTML = ('<div class="vidtog" role="group" aria-label="Arrange the videos"><button type="button" '
               'data-vview="idea" aria-pressed="true">By idea</button><button type="button" '
               'data-vview="lecture" aria-pressed="false">By lecture</button></div>')


def build(top, topics, titles, assemble):
    body, has_lectures, total = render(top, topics, titles)
    with open(CHASSIS, encoding="utf-8") as f:
        page = f.read()
    with open(ADDON, encoding="utf-8") as f:
        addon = re.sub(r"\A<!--.*?-->\n", "", f.read(), count=1, flags=re.S)  # it names the tags
    style = re.search(r"<style>.*?</style>", addon, re.S).group(0)
    script = re.search(r"<script>.*?</script>", addon, re.S).group(0)
    page = re.sub(r"\A<!--.*?-->\n", "", page, count=1, flags=re.S)
    exam = e(top["exam"] or "")
    page = page.replace("{{TITLE}}", (f'{e(top["course"])} ' if top["course"] else "") + f"{exam} watch list", 1)
    small = (f'{e(top["course"])} · ' if top["course"] else "") + exam
    page = page.replace("{{BRAND}}<small>{{COURSE}} · {{EXAM}}</small>", f"Watch list<small>{small}</small>", 1)
    page = page.replace("{{BRAND}}", "Watch list", 1)
    page = PAGEHEAD.sub(lambda m: pagehead(top, has_lectures), page, count=1)
    page = TOGGLE.sub(lambda m: TOGGLE_HTML if has_lectures and "viewtog" in m.group(1) else "", page)
    page = page.replace("</style>", "</style>\n" + style, 1)
    page = page.replace("/* SECTION ACCENTS */", assemble.accents(len(topics)), 1)
    page = page.replace("<!-- EXAM-DAY MAP -->\n", "", 1)
    page = page.replace("<!-- SECTIONS -->", body, 1)
    page = page.replace("<!-- FIGURE SCRIPTS -->", script, 1)
    left = sorted(set(re.findall(r"\{\{[^}]*\}\}", page)))
    if left:
        raise RuntimeError(f"chassis placeholders left unfilled: {', '.join(left)}")
    return page, total


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the watch list, practice/videos.html.")
    ap.add_argument("--root", default=".", help="the hub root (default: the cwd)")
    args = ap.parse_args(argv)
    path = os.path.normpath(os.path.join(args.root, DATA))
    if not os.path.isfile(path):
        print(f"videos: no data at {path}: run from the hub root, or pass --root", file=sys.stderr)
        return 2
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError:
        print(f"videos: {path} isn't UTF-8 text", file=sys.stderr)
        return 2
    bad = Problems(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        print(f"{path}: line {err.lineno} column {err.colno}: not JSON: {err.msg}", file=sys.stderr)
        print("1 problem; practice/videos.html not written", file=sys.stderr)
        return 1
    known, titles = None, {}
    notes = os.path.join(args.root, NOTES)
    if os.path.isfile(notes):
        known, titles = notes_ids(notes)
    checked = check(data, bad, known)
    if bad.lines:
        for m in bad.lines:
            print(m, file=sys.stderr)
        n = len(bad.lines)
        print(f"{n} problem{'' if n == 1 else 's'}; practice/videos.html not written", file=sys.stderr)
        return 1
    top, topics = checked
    page, total = build(top, topics, titles, load_assemble())
    out = os.path.join(args.root, OUT)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, out)
    print(f"wrote {os.path.normpath(out)}: {total} picks in {len(topics)} topics"
          + ("" if known is not None else f" (notes ids checked for form only: no {NOTES})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
