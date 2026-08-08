#!/usr/bin/env python3
"""Scaffold a new deck: tree, config, theme, shell, storyboard, vendored reveal.

Usage: python3 new_deck.py <target-dir> --title "..." [options]

Options:
  --title T             required
  --subtitle T          cover sub-line
  --subject T           what the deck is (goes in the PDF subject and the kicker)
  --audience A          internal | partner | external-investor | regulated-external
  --lang L              document language (default en)
  --slug S              defaults to the directory name
  --theme ID            a themes/ entry (default editorial-serif)
  --tokens FILE         use an extracted tokens.css instead of a built-in theme
  --canvas WxH          default 1920x1080
  --slides N            placeholder manifest rows (default 12)
  --facts MODE          deck | repo | none  (default: detected, then deck)
  --port N              serve port (default 8021)
  --reveal VERSION      default 6.0.1
  --reveal-from DIR     use an existing reveal dist instead of fetching
  --force               allow a non-empty target
  --dry-run             print what would be written, write nothing

Stdlib only. Reveal is vendored from a pinned, cached `npm pack`, never `npx`,
so the deliverable has no network dependency and the version is auditable.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402

SKILL = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = SKILL / "templates"
THEMES = SKILL / "themes"
CACHE = pathlib.Path.home() / ".cache" / "deckkit" / "reveal"

# Type scale at 1920x1080, as a ratio of canvas height, so a different canvas
# keeps the same visual rhythm instead of the same pixel numbers.
SCALE_RATIOS = {
    "--fs-hero": 280 / 1080, "--fs-giant": 168 / 1080, "--fs-h1": 88 / 1080,
    "--fs-h2": 60 / 1080, "--fs-h3": 40 / 1080, "--fs-stat": 96 / 1080,
    "--fs-body": 28 / 1080, "--fs-caption": 21 / 1080, "--fs-footnote": 15 / 1080,
    "--margin-slide": 96 / 1080,
}


def render(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{([A-Z_]+)\}\}", out)
    if leftover:
        raise deckcfg.ConfigError(f"template placeholders left unfilled: {sorted(set(leftover))}")
    return out


def rescale_tokens(css: str, height: int) -> str:
    """Rewrite the type scale for a non-1080 canvas. Palette is untouched."""
    if height == 1080:
        return css
    for token, ratio in SCALE_RATIOS.items():
        css = re.sub(rf"({re.escape(token)}:\s*)\d+px",
                     lambda m, r=ratio: f"{m.group(1)}{round(height * r)}px", css)
    return css


def detect_substrate(target: pathlib.Path, requested: str | None) -> tuple[str, str, str, str]:
    """Detected once, recorded in deck.toml, never re-detected."""
    if requested == "none":
        return "none", "", "", ""
    if requested != "repo":
        for parent in list(target.parents)[:4]:
            facts = parent / "facts"
            if facts.is_dir() and requested == "repo":
                break
        if requested == "deck":
            return "deck-local", "facts.md", "voice.md", "sensitive.md"
    for parent in list(target.parents)[:4]:
        if (parent / "facts").is_dir():
            rel = pathlib.Path("../" * len(target.relative_to(parent).parts))
            narrative = parent / "narrative"
            return ("repo", str(rel / "facts"),
                    str(rel / "narrative" / "voice.md") if narrative.is_dir() else "voice.md",
                    str(rel / "narrative" / "sensitive.md") if narrative.is_dir() else "sensitive.md")
    return "deck-local", "facts.md", "voice.md", "sensitive.md"


def font_blocks(theme: dict, want_cjk: bool) -> tuple[str, str]:
    """Emit deck.toml [[fonts]] entries and the base.css @font-face block."""
    toml_parts, face_parts = [], []
    for face in theme.get("fonts", []):
        if face.get("optional") and not want_cjk:
            continue
        family = face["family"]
        slug = family.lower().replace(" ", "-")
        toml_parts.append(
            f'[[fonts]]\nrole    = "{face["role"]}"\nfamily  = "{family}"\n'
            f'source  = "{face["source"]}"\nstyles  = {json.dumps(face["styles"])}\n'
            f'licence = "{face["licence"]}"\nsubset  = "{face["subset"]}"\n'
        )
        for style in face["styles"]:
            low = style.lower()
            weight = 700 if "bold" in low else 400
            italic = "italic" if "italic" in low else "normal"
            face_parts.append(
                f'@font-face {{ font-family: "{family}"; '
                f'src: url("../fonts/{slug}-{low}.woff2") format("woff2"); '
                f'font-weight: {weight}; font-style: {italic}; font-display: block; }}'
            )
    return "\n".join(toml_parts), "\n".join(face_parts)


def vendor_reveal(target: pathlib.Path, version: str, source_dir: str | None,
                  plugins: list[str], dry: bool) -> str:
    dest = target / "vendor" / "reveal"
    if dry:
        return f"(dry-run) would vendor reveal {version}"
    dest.mkdir(parents=True, exist_ok=True)

    def install_from(root: pathlib.Path, provenance: str) -> str:
        # Upstream has moved these around between majors (plugins were
        # plugin/<n>/<n>.js in reveal 4-5, dist/plugin/<n>.js in 6). Resolve
        # whichever layout is present into ONE stable destination so the
        # index.html template never has to know the upstream version.
        wanted: list[tuple[list[str], str]] = [
            (["dist/reveal.js", "js/reveal.js"], "reveal.js"),
            (["dist/reveal.css", "css/reveal.css"], "reveal.css"),
            (["LICENSE", "LICENSE.md"], "LICENSE"),
        ]
        for plugin in plugins:
            wanted.append((
                [f"dist/plugin/{plugin}.js", f"plugin/{plugin}/{plugin}.js"],
                f"plugin/{plugin}/{plugin}.js",
            ))
        unresolved = []
        for candidates, dst_rel in wanted:
            src = next((root / c for c in candidates if (root / c).exists()), None)
            if src is None:
                unresolved.append(dst_rel)
                continue
            out = dest / dst_rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
        note = f"unresolved: {', '.join(unresolved)}\n" if unresolved else ""
        (dest / "PROVENANCE.txt").write_text(
            f"reveal.js {version}\n{provenance}\n{note}vendored {datetime.date.today()}\n",
            encoding="utf-8")
        if unresolved:
            return f"{provenance} (MISSING {', '.join(unresolved)})"
        return provenance

    if source_dir:
        return install_from(pathlib.Path(source_dir).resolve(), f"copied from {source_dir}")

    local = target.parent / "node_modules" / "reveal.js"
    if local.is_dir():
        return install_from(local, f"copied from {local}")

    CACHE.mkdir(parents=True, exist_ok=True)
    tarball = next(CACHE.glob(f"reveal.js-{version}.tgz"), None)
    if tarball is None:
        result = subprocess.run(["npm", "pack", f"reveal.js@{version}", "--silent"],
                                cwd=CACHE, capture_output=True, text=True)
        if result.returncode != 0:
            return (f"reveal NOT vendored: `npm pack reveal.js@{version}` failed "
                    f"({result.stderr.strip()[:120]}). Re-run with --reveal-from DIR.")
        tarball = CACHE / result.stdout.strip().splitlines()[-1]
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    extract = CACHE / f"unpacked-{version}"
    if not extract.is_dir():
        with tarfile.open(tarball) as archive:
            archive.extractall(extract, filter="data")
    return install_from(extract / "package", f"npm pack reveal.js@{version}\nsha256 {digest}")


def main() -> int:  # noqa: C901 - a linear scaffold reads better than five helpers
    parser = argparse.ArgumentParser(description="Scaffold a new deck")
    parser.add_argument("target")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--audience", default="internal",
                        choices=["internal", "partner", "external-investor", "regulated-external"])
    parser.add_argument("--lang", default="en")
    parser.add_argument("--slug")
    parser.add_argument("--theme", default="editorial-serif")
    parser.add_argument("--tokens")
    parser.add_argument("--canvas", default="1920x1080")
    parser.add_argument("--slides", type=int, default=12)
    parser.add_argument("--facts", choices=["deck", "repo", "none"])
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--reveal", default="6.0.1")
    parser.add_argument("--reveal-from")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = pathlib.Path(args.target).resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        deckcfg.bail(f"{target} is not empty (use --force to scaffold into it anyway)")

    try:
        width, height = (int(v) for v in args.canvas.lower().split("x"))
    except ValueError:
        deckcfg.bail(f"--canvas must look like 1920x1080, got {args.canvas!r}")

    slug = args.slug or target.name
    today = datetime.date.today().isoformat()
    want_cjk = args.lang.startswith(("zh", "ja", "ko"))

    theme_dir = THEMES / args.theme
    if not args.tokens and not theme_dir.is_dir():
        available = sorted(p.name for p in THEMES.iterdir() if p.is_dir() and p.name != "_licences")
        deckcfg.bail(f"unknown theme {args.theme!r}; available: {', '.join(available)}")
    theme = {}
    if theme_dir.is_dir():
        with (theme_dir / "theme.toml").open("rb") as handle:
            theme = tomllib.load(handle)

    tier, facts_rel, voice_rel, sensitive_rel = detect_substrate(target, args.facts)
    fonts_toml, font_faces = font_blocks(theme, want_cjk)

    tokens_css = (pathlib.Path(args.tokens).read_text(encoding="utf-8") if args.tokens
                  else (theme_dir / theme.get("tokens", "tokens.css")).read_text(encoding="utf-8"))
    tokens_css = rescale_tokens(tokens_css, height)

    values = {
        "SLUG": slug, "TITLE": args.title, "SUBTITLE": args.subtitle,
        "SUBJECT": args.subject or args.title, "AUDIENCE": args.audience,
        "LANG": args.lang, "DATE": today,
        "CANVAS_WIDTH": str(width), "CANVAS_HEIGHT": str(height),
        "THEME": args.theme if not args.tokens else "extracted",
        "THEME_ORIGIN": "extracted" if args.tokens else "builtin",
        "FONT_BLOCKS": fonts_toml, "FONT_FACES": font_faces,
        "FRAGMENT_DIR": "slides", "PORT": str(args.port),
        "REVEAL_VERSION": args.reveal,
        "SUBSTRATE_TIER": tier, "SUBSTRATE_FACTS": facts_rel,
        "SUBSTRATE_VOICE": voice_rel, "SUBSTRATE_SENSITIVE": sensitive_rel,
        "LOCAL_ARCHETYPES_LINK": "",
        "WRAP_REQUIRED": ", ".join(deckcfg.DEFAULTS["archetypes.wrap_required"]),
        "VOICE_PATH": voice_rel or "(no voice file: substrate tier is none)",
        "FIRST_ACT": "open",
        "MANIFEST_ROWS": "",
        "PHASE": "Phase",
    }

    rows = [f"| 1 | slides/s01-cover.html | {args.title} | cover | open | built | | |",
            f"| 2 | slides/s02-numeral.html | (hero number) | numeral | open | built | F-001 | |"]
    rows += [f"| {n} | slides/s{n:02d}-slug.html | (title) | (archetype) | (act) | draft | | |"
             for n in range(3, args.slides + 1)]
    values["MANIFEST_ROWS"] = "\n".join(rows)

    writes: dict[str, str] = {
        "deck.toml": render((TEMPLATES / "deck.toml.tmpl").read_text(encoding="utf-8"), values),
        "index.html": render((TEMPLATES / "index.html.tmpl").read_text(encoding="utf-8"), values),
        "storyboard.md": render((TEMPLATES / "storyboard.md.tmpl").read_text(encoding="utf-8"), values),
        "BUILD-CONTRACT.md": render((TEMPLATES / "BUILD-CONTRACT.md.tmpl").read_text(encoding="utf-8"), values),
        "css/tokens.css": tokens_css,
        "css/base.css": render((TEMPLATES / "css" / "base.css.tmpl").read_text(encoding="utf-8"), values),
        "css/archetypes.css": (TEMPLATES / "css" / "archetypes.css").read_text(encoding="utf-8"),
        "slides/s01-cover.html": render((TEMPLATES / "slides" / "s01-cover.html.tmpl").read_text(encoding="utf-8"), values),
        "slides/s02-numeral.html": render((TEMPLATES / "slides" / "s02-numeral.html.tmpl").read_text(encoding="utf-8"), values),
        ".gitignore": "export/\n__pycache__/\n*.pyc\n",
    }
    if tier == "deck-local":
        for name in ("facts.md", "voice.md", "sensitive.md"):
            writes[name] = render((TEMPLATES / f"{name}.tmpl").read_text(encoding="utf-8"), values)
    for licence in theme.get("fonts", []):
        src = THEMES / "_licences" / licence.get("licence_file", "")
        if src.exists():
            writes[f"fonts/{src.name}"] = src.read_text(encoding="utf-8")

    if args.dry_run:
        print(f"(dry-run) would scaffold {target}")
        for rel in sorted(writes):
            first = writes[rel].splitlines()[0] if writes[rel].strip() else ""
            print(f"  {rel:34}  {len(writes[rel]):>7} bytes  {first[:48]}")
        print(f"  vendor/reveal/  reveal.js {args.reveal}")
        return deckcfg.EXIT_OK

    for rel, content in writes.items():
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    for extra in ("media", "renders", "reviews/briefs", "reviews/runs", "export", "fonts"):
        (target / extra).mkdir(parents=True, exist_ok=True)

    provenance = vendor_reveal(target, args.reveal, args.reveal_from,
                               deckcfg.DEFAULTS["vendor.plugins"], args.dry_run)

    print(f"scaffolded {target}")
    print(f"  theme      {values['THEME']} ({width}x{height})")
    print(f"  substrate  {tier}" + (f" -> {facts_rel}" if facts_rel else ""))
    print(f"  reveal     {provenance.splitlines()[0]}")
    print(f"  manifest   {args.slides} rows, 2 example fragments built")
    print("\nnext")
    print(f"  1. Write the storyboard, then set `status: approved` in its frontmatter.")
    print(f"     Until then `deckkit build` refuses: that gate is the point.")
    print(f"  2. deckkit fonts {target}      # subset the theme faces")
    print(f"  3. deckkit build {target} --allow-draft && deckkit lint {target}")
    print(f"  4. deckkit serve {target}      # http://localhost:{args.port}/")
    return deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
