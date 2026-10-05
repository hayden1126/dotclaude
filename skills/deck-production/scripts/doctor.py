#!/usr/bin/env python3
"""Environment probe: what the deck tools need, what is here, what to install.

Usage: python3 doctor.py [<deck-dir>] [--json] [--config PATH]

Reports rather than fixes. Exit 3 if something required for the core loop is
missing: the fonts python, or any browser for `deckkit geometry`, whose 0/0 is
part of every exit gate from phase C on. Optional gaps are reported and exit 0,
because a deck that never ships a PDF does not need decktape; full Chrome in
place of the headless shell is one of them. --json exits the same way.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402
import geometry  # noqa: E402

OK, WARN, BAD = "ok", "optional", "missing"


def probe_python(path: str, modules: tuple[str, ...]) -> dict:
    if not pathlib.Path(path).exists() and not shutil.which(path):
        return {"state": BAD, "detail": "interpreter not found"}
    code = ("import sys,json;out={}\n"
            "for m in %r:\n"
            "    try:\n"
            "        __import__(m); out[m]=True\n"
            "    except ImportError:\n"
            "        out[m]=False\n"
            "print(json.dumps({'v':sys.version.split()[0],'mods':out}))" % (list(modules),))
    try:
        raw = subprocess.run([path, "-c", code], capture_output=True, text=True, timeout=30)
        data = json.loads(raw.stdout.strip())
    except Exception as exc:  # noqa: BLE001 - any failure means unusable
        return {"state": BAD, "detail": f"probe failed: {exc}"}
    absent = [m for m, present in data["mods"].items() if not present]
    return {
        "state": OK if not absent else WARN,
        "detail": f"python {data['v']}" + (f", missing {', '.join(absent)}" if absent else ""),
        "missing": absent,
    }


def probe_binary(name: str, args: list[str] | None = None) -> dict:
    found = shutil.which(name)
    if not found:
        return {"state": BAD, "detail": "not on PATH"}
    if args:
        try:
            raw = subprocess.run([found, *args], capture_output=True, text=True, timeout=20)
            first = (raw.stdout or raw.stderr).strip().splitlines()
            return {"state": OK, "detail": first[0][:60] if first else found}
        except Exception:  # noqa: BLE001
            return {"state": OK, "detail": found}
    return {"state": OK, "detail": found}


def probe_geometry_browser(cfg: deckcfg.DeckConfig) -> dict:
    """The browser `deckkit geometry` would drive, found by geometry.py itself
    so the two can never disagree. The headless shell is preferred: full
    Chrome aborts inside the Claude Code sandbox."""
    found = geometry.find_browser(cfg)
    if found is None:
        return {"state": BAD, "detail": "no headless Chrome found", "hint": geometry.INSTALL_HINT}
    binary, headless_shell = found
    source = " (from [env] chrome)" if cfg.get("env.chrome") else ""
    if not (pathlib.Path(binary).exists() or shutil.which(binary)):
        return {"state": BAD, "detail": f"{binary}{source} does not exist",
                "hint": geometry.INSTALL_HINT}
    if headless_shell:
        return {"state": OK, "detail": f"headless shell {binary}{source}"}
    return {"state": WARN, "detail": f"Chrome {binary}{source}; the headless shell is "
                                     "preferred (full Chrome aborts in a sandbox)",
            "hint": geometry.INSTALL_HINT}


HINTS = {
    "fontTools": "sudo apt install python3-fonttools   (or: pip install fonttools)",
    "brotli": "pip install brotli   (woff2 output needs it)",
    "pptx": "pip install python-pptx   (into the .venv named by [env] pptx_python)",
    "PIL": "pip install pillow",
    "pypdf": "pip install pypdf   (optional: PDF page-count assertions)",
    "node": "install Node 18+ (nvm, or your distro package)",
    "chrome": "npx puppeteer browsers install chrome   (or set [env] chrome)",
    "decktape": "no install needed; the PDF tool runs it via npx on demand",
    "ffmpeg": "sudo apt install ffmpeg   (only needed for video ingest)",
}

# Landmines that cost a session each. Printed every run: they are environment
# facts, not bugs, and forgetting them is what makes them expensive.
NOTES = [
    "`python3 -m http.server` serves no HTTP Range header, so seeking inside a "
    "video restarts the stream. Linear autoplay is unaffected. Use `deckkit "
    "serve` if seeking matters.",
    "decktape joins --screenshots-directory with the PDF path's dirname, so a "
    "nested output path silently breaks the write. Use a bare basename and cd "
    "into the output directory.",
    "A 50-slide decktape run takes 4 to 7 minutes, past the default shell "
    "timeout. Background it or batch with --slides.",
    "An orphaned headless Chrome holds the profile lock. Clear stale "
    "Singleton* files before the first page of a sitting.",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Environment probe for the deck tools")
    deckcfg.add_common_args(parser)
    args = parser.parse_args()

    try:
        cfg = deckcfg.load(args.deck, args.config)
    except deckcfg.ConfigError:
        cfg = deckcfg.DeckConfig(pathlib.Path.cwd(), {}, "<defaults>")

    checks: dict[str, dict] = {}

    checks["python (core tools)"] = {"state": OK, "detail": f"python {sys.version.split()[0]}"}
    fonttools_py = cfg.get("env.fonttools_python")
    checks[f"python for fonts ({fonttools_py})"] = probe_python(fonttools_py, ("fontTools", "brotli"))
    pptx_py = cfg.interpreter("pptx")
    checks[f"python for pptx ({pptx_py})"] = probe_python(pptx_py, ("pptx", "PIL"))

    checks["node"] = probe_binary(cfg.get("env.node"), ["-v"])
    checks["npm"] = probe_binary("npm", ["-v"])

    chrome = deckcfg.find_chrome(cfg)
    checks["chrome"] = ({"state": OK, "detail": chrome} if chrome
                        else {"state": BAD, "detail": "no chrome found"})
    checks["geometry browser"] = probe_geometry_browser(cfg)
    checks["ffmpeg"] = probe_binary("ffmpeg", ["-version"])
    checks["ffprobe"] = probe_binary("ffprobe", ["-version"])
    checks["powershell.exe (WSL pptx render)"] = probe_binary("powershell.exe")

    # Deck-local state, only when pointed at a real deck
    deck_checks: dict[str, dict] = {}
    if (cfg.deck / cfg.get("build.index")).exists():
        for name, rel in (("storyboard", cfg.get("build.storyboard")),
                          ("index.html", cfg.get("build.index")),
                          ("vendored reveal", "vendor/reveal/reveal.js"),
                          ("tokens.css", cfg.get("theme.tokens"))):
            present = (cfg.deck / rel).exists()
            deck_checks[name] = {"state": OK if present else BAD,
                                 "detail": rel if present else f"{rel} absent"}
        fonts = list((cfg.deck / "fonts").glob("*.woff2"))
        deck_checks["subset fonts"] = ({"state": OK, "detail": f"{len(fonts)} woff2"} if fonts
                                       else {"state": WARN, "detail": "none yet; run `deckkit fonts`"})

    core = (f"python for fonts ({fonttools_py})", "geometry browser")
    exit_code = (deckcfg.EXIT_ENV if any(checks[name]["state"] == BAD for name in core)
                 else deckcfg.EXIT_OK)

    if args.json:
        print(json.dumps({"tools": checks, "deck": deck_checks}, indent=2))
        return exit_code

    width = max(len(k) for k in {**checks, **deck_checks})
    print("environment")
    for name, result in checks.items():
        mark = {OK: "  ok ", WARN: "  .. ", BAD: "  XX "}[result["state"]]
        print(f"{mark}{name.ljust(width)}  {result['detail']}")
    if deck_checks:
        print("\ndeck")
        for name, result in deck_checks.items():
            mark = {OK: "  ok ", WARN: "  .. ", BAD: "  XX "}[result["state"]]
            print(f"{mark}{name.ljust(width)}  {result['detail']}")

    gaps: list[str] = []
    for name, result in checks.items():
        for module in result.get("missing", []):
            gaps.append(f"{module}: {HINTS.get(module, 'pip install ' + module)}")
        key = name.split()[0]
        if "hint" in result:
            gaps.append(f"{key}: {result['hint']}")
        elif result["state"] == BAD and key in HINTS:
            gaps.append(f"{key}: {HINTS[key]}")
    if gaps:
        print("\nto install")
        for gap in dict.fromkeys(gaps):
            print(f"  {gap}")

    print("\nknown landmines")
    for note in NOTES:
        print(f"  - {note}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
