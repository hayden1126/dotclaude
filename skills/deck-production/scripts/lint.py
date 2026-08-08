#!/usr/bin/env python3
"""Deck lint: the mechanical audit the storyboard promises.

Usage: /usr/bin/python3 lint.py <deck-dir> [--baseline FILE] [--write-baseline]
                                           [--json] [--config PATH]
       (or `deckkit lint <deck>`, which picks the interpreter for you)

Universal checks, run at every substrate tier:
   U1. <style> scoping: every selector inside a fragment's <style> carries the
       section id, so one slide can never restyle another.
   U2. Unique section ids across fragments.
   U3. Relative asset links (src/href/poster) resolve on disk.
   U4. Glyph coverage: every rendered codepoint is in some shipped font cmap,
       so a copy change cannot silently tofu. (Needs fontTools.)
   U5. No `display:` on a selector whose subject is the section. reveal writes
       an inline display:block on the presented section, which beats any
       selector including #id, so such rules are dead CSS live -- and the
       fragment preview still looks right, which is what hides the bug.
       Layout attaches to a direct child div.wrap.
   U6. Sections carrying a wrap-archetype class contain a div.wrap.
   U7. Every .arch-* class used by a fragment is defined in the shared or local
       archetype CSS.
   U8. The storyboard is approved (frontmatter `status:`).

Registry checks, skipped when substrate.tier = "none":
   R1. Manifest fact-ID declarations vs the <!-- F-NNN --> comments in each
       fragment, both directions.
   R2. Every cited fact ID exists in the registry; trust flags reported LOUDLY.
   R3. Naked-number heuristic: digit groups in rendered text with no citation
       comment nearby (allowlist: footer.src, data-decor, aside.notes, years).
   R4. Fact IDs never appear in rendered text, only in comments.

Exit 1 on errors; warnings alone exit 0.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deckcfg  # noqa: E402
from build import frontmatter, manifest_rows, storyboard_approved  # noqa: E402


def strip_nontext(html: str) -> str:
    text = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    return re.sub(r"<script.*?</script>", "", text, flags=re.S)


NOTES_ASIDE_RE = re.compile(r'<aside[^>]*class="[^"]*notes[^"]*".*?</aside>', re.S)


def rendered_text(html: str) -> str:
    """What a viewer actually sees on the slide face.

    Presenter notes are excluded: reveal.css ships `aside.notes {display:none}`
    and the packager strips them from the distributable, so note prose may cite
    registry ids in the clear. Note text still has to pass the sensitive
    checklist independently, but that is the sweep's job, not lint's.
    """
    text = strip_nontext(html)
    text = NOTES_ASIDE_RE.sub("", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"<[^>]+>", "", text)


def parse_manifest(sb_text: str, fragment_dir: str, fid_re: re.Pattern) -> dict:
    """Manifest rows keyed by fragment path, carrying the declared fact IDs."""
    slides = {}
    row_re = re.compile(rf"\|\s*\d+\s*\|\s*{re.escape(fragment_dir)}/")
    for line in sb_text.splitlines():
        stripped = line.strip()
        if not row_re.match(stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 7:
            continue
        slides[cells[1]] = {"n": int(cells[0]), "fids": set(fid_re.findall(cells[6]))}
    return slides


def load_registry(root: pathlib.Path, fid_re: re.Pattern) -> dict:
    """Registry rows from a facts/ tree (repo tier) or one facts.md (deck tier)."""
    files = sorted(root.glob("*.md")) if root.is_dir() else [root]
    rows = {}
    anchored = re.compile(rf"\|\s*({fid_re.pattern})\s*\|")
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = anchored.match(line.strip())
            if not match:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[match.group(1)] = {
                "page": path.name,
                "claim": cells[1] if len(cells) > 1 else "",
                "flags": cells[5] if len(cells) > 5 else "",
            }
    return rows


def defined_archetypes(cfg: deckcfg.DeckConfig) -> set[str]:
    names: set[str] = set()
    for key in ("archetypes.css", "archetypes.local_css"):
        path = cfg.path(key)
        if path.exists():
            names |= set(re.findall(r"\.(arch-[\w-]+)", path.read_text(encoding="utf-8")))
    return names


def check_shared_css_display(cfg: deckcfg.DeckConfig, errors: list) -> None:
    """U5, shared-stylesheet half. Same trap, different file."""
    css_dir = cfg.deck / "css"
    if not css_dir.is_dir():
        return
    for path in sorted(css_dir.glob("*.css")):
        body = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for rule in body.split("}"):
            if "{" not in rule:
                continue
            selector, declarations = rule.split("{", 1)
            if not re.search(r"\bdisplay\s*:", declarations):
                continue
            for part in selector.split(","):
                subject = re.split(r"[\s>+~]+", part.strip())[-1]
                if subject.startswith("section") or re.fullmatch(r"\.arch-[\w-]+", subject):
                    errors.append(
                        f"css/{path.name}: 'display:' with section subject "
                        f"'{part.strip()[:60]}' is dead under reveal's inline "
                        f"display:block; attach layout to '> .wrap'"
                    )


def main() -> int:  # noqa: C901 - one pass over fragments, kept linear on purpose
    parser = argparse.ArgumentParser(description="Deck lint")
    deckcfg.add_common_args(parser)
    parser.add_argument("--baseline", help="compare the FLAG set against this file")
    parser.add_argument("--write-baseline", metavar="FILE", help="record the current FLAG set")
    parser.add_argument("--allow-draft", action="store_true",
                        help="demote the storyboard-approval error to a warning "
                             "(Phase B infrastructure checks, before the gate)")
    args = parser.parse_args()

    cfg = deckcfg.load(args.deck, args.config)
    deck = cfg.deck
    errors: list[str] = []
    warnings: list[str] = []
    flag_lines: list[str] = []

    storyboard = cfg.path("build.storyboard")
    if not storyboard.exists():
        deckcfg.bail(f"{storyboard} does not exist")
    sb_text = storyboard.read_text(encoding="utf-8")

    fid_re = deckcfg.slug_re(cfg.get("substrate.fact_id"))
    fragment_dir = cfg.get("build.fragment_dir")
    manifest = parse_manifest(sb_text, fragment_dir, fid_re)
    if not manifest:
        deckcfg.bail(f"no manifest rows parsed from {storyboard}")

    tier = cfg.substrate_tier
    registry: dict = {}
    if tier != "none":
        try:
            root = cfg.facts_root()
        except deckcfg.ConfigError as exc:
            hint = ""
            if cfg.source == "<defaults>":
                for guess in ("facts.md", "../../facts", "../facts"):
                    if (deck / guess).exists():
                        hint = (f"\n  hint: {deck / guess} exists. This deck has no deck.toml, "
                                f"so lint is using defaults. Set [substrate] tier and facts "
                                f"explicitly, or pass --config.")
                        break
            deckcfg.bail(f"{exc}{hint}")
        registry = load_registry(root, fid_re)

    # U8 storyboard approval
    if cfg.lint_enabled("lint.storyboard_approved"):
        approved, detail = storyboard_approved(sb_text)
        if not approved:
            (warnings if args.allow_draft else errors).append(
                f"storyboard is not approved: {detail} (gate before any build)")
        else:
            fields = frontmatter(sb_text)
            for field in ("approved_by", "approved_on"):
                if field not in fields:
                    warnings.append(f"storyboard frontmatter has no `{field}:` "
                                    f"(who approved it, and when, is durable state)")

    # storyboard-level fact IDs, so planning-stage typos surface before fragments exist
    if tier != "none" and cfg.lint_enabled("lint.fid_chain"):
        for fid in sorted(set(fid_re.findall(sb_text))):
            if fid not in registry:
                errors.append(f"storyboard cites {fid}: not found in the registry")

    known_arches = defined_archetypes(cfg)
    seen_ids: dict[str, list[str]] = {}
    wrap_required = set(cfg.get("archetypes.wrap_required"))
    window = cfg.get("lint.naked_number_window")
    all_text = ""

    built = [(rel, meta) for rel, meta in manifest.items() if (deck / rel).exists()]
    print(f"lint: {len(built)}/{len(manifest)} fragments built, "
          f"substrate tier {tier}, {len(registry)} registry rows, "
          f"rigor {cfg.derive_rigor(slide_count=len(manifest))}")

    for rel, meta in sorted(built, key=lambda kv: kv[1]["n"]):
        html = (deck / rel).read_text(encoding="utf-8")
        text_html = strip_nontext(html)
        all_text += rendered_text(html)
        used = set(re.findall(rf"<!--\s*({fid_re.pattern})", html))

        # R1 declared vs used, both directions
        if cfg.lint_enabled("lint.fid_chain"):
            for fid in sorted(meta["fids"] - used):
                warnings.append(f"{rel}: declared {fid} not cited in the fragment")
            for fid in sorted(used - meta["fids"]):
                errors.append(f"{rel}: cites {fid} not declared in the storyboard manifest")

        # R2 registry existence + loud flags
        if cfg.lint_enabled("lint.fid_registry_flags"):
            flag_words = cfg.get("substrate.flag_words")
            for fid in sorted(used):
                row = registry.get(fid)
                if row is None:
                    errors.append(f"{rel}: {fid} not found in the registry")
                    continue
                hits = [w for w in flag_words if w.lower() in row["flags"].lower()]
                if hits:
                    flag_lines.append(f"{rel} {fid} [{', '.join(hits)}]")
                    print(f"  FLAG {rel} {fid} [{', '.join(hits)}] "
                          f"{row['claim'][:60]} ({row['page']})")

        # R4 fact IDs must never render
        if cfg.lint_enabled("lint.fid_leak"):
            for fid in sorted(set(fid_re.findall(rendered_text(html)))):
                errors.append(f"{rel}: {fid} appears in RENDERED text; citations live in "
                              f"HTML comments, public sourcing lives in footer.src")

        # U1/U2/U5 section id, style scoping, dead display
        id_match = re.search(r"<section[^>]*\bid=\"([^\"]+)\"", html)
        section_id = id_match.group(1) if id_match else None
        if section_id:
            seen_ids.setdefault(section_id, []).append(rel)
        else:
            errors.append(f"{rel}: <section> has no id")

        for style in re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S):
            body = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
            body = re.sub(r"@media[^{]*\{", "", body)
            for rule in body.split("}"):
                selector = rule.split("{")[0].strip()
                if not selector or selector.startswith("@") or "{" not in rule:
                    continue
                if cfg.lint_enabled("lint.style_scoping") and section_id \
                        and f"#{section_id}" not in selector:
                    errors.append(f"{rel}: unscoped selector '{selector[:50]}'")
                if cfg.lint_enabled("lint.reveal_display") and section_id \
                        and re.search(r"\bdisplay\s*:", rule.split("{", 1)[1]):
                    for part in selector.split(","):
                        if re.fullmatch(rf"#{re.escape(section_id)}[^\s>+~]*", part.strip()):
                            errors.append(
                                f"{rel}: 'display:' on section selector "
                                f"'{part.strip()[:50]}' is dead under reveal's inline "
                                f"display:block; attach layout to a direct child div.wrap"
                            )

        # U6/U7 archetype classes
        class_match = re.search(r"<section[^>]*\bclass=\"([^\"]*)\"", html)
        classes = class_match.group(1).split() if class_match else []
        arches = [c for c in classes if c.startswith("arch-")]
        if cfg.lint_enabled("lint.wrap_archetypes"):
            needs_wrap = [c for c in arches if c in wrap_required]
            if needs_wrap and not re.search(r"class=\"[^\"]*\bwrap\b[^\"]*\"", html):
                warnings.append(
                    f"{rel}: {needs_wrap[0]} layout attaches to a direct child div.wrap; "
                    f"none found (renders stacked under reveal)"
                )
        if known_arches:
            for arch in arches:
                if arch not in known_arches:
                    warnings.append(f"{rel}: archetype class '{arch}' is not defined in "
                                    f"the shared or local archetype CSS")

        # R3 naked numbers. Offsets and the search window must index the SAME
        # string: raw-html offsets are shifted by the stripped blocks.
        if cfg.lint_enabled("lint.naked_numbers"):
            content = re.sub(r"<footer[^>]*class=\"[^\"]*src[^\"]*\".*?</footer>", "",
                             text_html, flags=re.S)
            content = re.sub(r"<[^>]*data-decor[^>]*>.*?</[^>]+>", "", content, flags=re.S)
            content = re.sub(r"<aside[^>]*class=\"[^\"]*notes[^\"]*\".*?</aside>", "",
                             content, flags=re.S)
            allow_years = cfg.get("lint.allow_naked_years")
            for segment in re.finditer(r">([^<]*)<", content):
                for number in re.finditer(r"\d[\d,\.]*\s*(?:%|[MBk]\b|billion|million)?",
                                          segment.group(1)):
                    token = number.group(0).strip().rstrip(",.")
                    if not token:
                        continue
                    if allow_years and re.fullmatch(r"(19|20)\d{2}", token):
                        continue
                    if len(re.sub(r"\D", "", token)) < 2 and "%" not in token:
                        continue
                    start = max(0, segment.start() - window)
                    if "<!-- " not in content[start:segment.end() + window] or \
                            not fid_re.search(content[start:segment.end() + window]):
                        warnings.append(f"{rel}: naked number '{token}' "
                                        f"(no citation comment within range)")

        # U3 asset links. Markup attributes are scanned on live markup only
        # (comments and <style> bodies stripped), and CSS url() is scanned
        # separately on comment-free style bodies. A reference inside a comment
        # is documentation, not a broken link; flagging it teaches people to
        # ignore the check, which is worse than not having it.
        if cfg.lint_enabled("lint.asset_links"):
            live_markup = re.sub(r"<!--.*?-->", "", strip_nontext(html), flags=re.S)
            targets = [m.group(1) for m in
                       re.finditer(r"(?:src|href|poster)=\"([^\"]+)\"", live_markup)]
            for style in re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S):
                body = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
                targets += [m.group(1) for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)", body)]
            for target in targets:
                if target.startswith(("http", "#", "data:", "//")):
                    continue
                if not (deck / target).exists():
                    errors.append(f"{rel}: missing asset {target}")

    if cfg.lint_enabled("lint.reveal_display"):
        check_shared_css_display(cfg, errors)

    if cfg.lint_enabled("lint.unique_section_ids"):
        for section_id, rels in seen_ids.items():
            if len(rels) > 1:
                errors.append(f"duplicate section id #{section_id}: {', '.join(rels)}")

    # U4 glyph coverage
    if cfg.lint_enabled("lint.glyph_coverage"):
        fonts = sorted((deck / "fonts").glob("*.woff2"))
        if fonts and all_text:
            try:
                from fontTools.ttLib import TTFont

                cmap: set[int] = set()
                for font in fonts:
                    cmap |= set(TTFont(font).getBestCmap().keys())
                missing = sorted({c for c in all_text
                                  if ord(c) > 0x7E and not c.isspace() and ord(c) not in cmap})
                for char in missing:
                    errors.append(f"glyph not in any shipped font: {char!r} "
                                  f"(U+{ord(char):04X}) -- re-run `deckkit fonts`")
            except ImportError:
                warnings.append("fontTools unavailable in this interpreter -- glyph coverage "
                                "skipped (run via `deckkit lint`, which picks /usr/bin/python3)")

    # FLAG baseline: the regression fingerprint for registry-backed decks
    flag_lines.sort()
    if args.write_baseline:
        pathlib.Path(args.write_baseline).write_text("\n".join(flag_lines) + "\n",
                                                     encoding="utf-8")
        print(f"  wrote {len(flag_lines)} FLAG lines to {args.write_baseline}")
    if args.baseline:
        baseline_path = pathlib.Path(args.baseline)
        if not baseline_path.exists():
            warnings.append(f"baseline {baseline_path} does not exist "
                            f"(create it with --write-baseline)")
        else:
            recorded = [ln for ln in baseline_path.read_text(encoding="utf-8").splitlines() if ln]
            added = sorted(set(flag_lines) - set(recorded))
            removed = sorted(set(recorded) - set(flag_lines))
            for line in added:
                errors.append(f"FLAG baseline: new flagged citation '{line}' "
                              f"(document the delta or fix the slide)")
            for line in removed:
                warnings.append(f"FLAG baseline: citation '{line}' is gone (delta to document)")

    for warning in warnings:
        print(f"  WARN {warning}")
    for error in errors:
        print(f"  ERROR {error}")
    print(f"lint: {len(errors)} errors, {len(warnings)} warnings, {len(flag_lines)} FLAG")

    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "flags": flag_lines,
                          "tier": tier, "fragments": len(built)}))
    return deckcfg.EXIT_FAIL if errors else deckcfg.EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
