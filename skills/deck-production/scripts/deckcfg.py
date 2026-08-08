#!/usr/bin/env python3
"""Shared config layer for the deck-production tools. Stdlib only.

Every tool takes a deck directory and reads `<deck>/deck.toml` through this
module, so `build.py` and `package.py` keep their stdlib-only property and the
regression harness can drive a deck that has no deck.toml at all (see
`synthesize`).

Precedence, uniform across every script:
    CLI flag  >  DECKKIT_* env var  >  deck.toml  >  built-in default

Exit codes, uniform across every script:
    0 ok · 1 check failed · 2 usage/config error · 3 environment missing
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sys
import tomllib

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_ENV = 0, 1, 2, 3

# Built-in defaults. Dotted keys; a deck.toml overrides any leaf.
DEFAULTS: dict = {
    "deck.slug": None,               # defaults to the deck dir name
    "deck.title": "Untitled deck",
    "deck.subtitle": "",
    "deck.subject": "",
    "deck.audience": "internal",     # internal|partner|external-investor|regulated-external
    "deck.language": "en",
    "deck.issuer_listed": False,
    "deck.rigor": None,              # sketch|standard|regulated; derived when absent
    "deck.rigor_reason": "",
    "canvas.width": 1920,
    "canvas.height": 1080,
    "theme.id": "editorial-serif",
    "theme.origin": "builtin",       # builtin|extracted
    "theme.tokens": "css/tokens.css",
    "substrate.tier": "deck-local",  # repo|deck-local|none
    "substrate.facts": "facts.md",
    "substrate.voice": "voice.md",
    "substrate.sensitive": "sensitive.md",
    "substrate.assets": "media",
    "substrate.fact_id": r"F-\d{3,4}",
    "substrate.flag_words": [
        "VERBAL", "UNVERIFIED", "DECK-ONLY", "CONFLICT",
        "press-grade", "unsourced", "PARTIAL", "projection",
    ],
    "build.storyboard": "storyboard.md",
    "build.fragment_dir": "slides",
    "build.index": "index.html",
    "build.begin_marker": "<!-- BUILD:SLIDES:BEGIN",
    "build.end_marker": "<!-- BUILD:SLIDES:END -->",
    "build.serve_port": 8021,
    "build.require_approved_storyboard": True,
    "archetypes.css": "css/archetypes.css",
    "archetypes.local_css": "css/archetypes.local.css",
    # Exactly the shipped archetypes whose layout hangs off `> .wrap`. Keep this
    # in sync with templates/css/archetypes.css; a deck adding a local archetype
    # with a wrap child appends its class here.
    "archetypes.wrap_required": [
        "arch-numeral", "arch-data", "arch-compare", "arch-chapter", "arch-proof",
    ],
    "vendor.reveal_version": "6.0.1",
    "vendor.plugins": ["notes"],
    "export.site.runtime": ["index.html", "css", "fonts", "vendor", "media"],
    "export.site.strip_notes": True,
    "export.site.zip": True,
    "export.pdf.size": None,          # defaults to "<width>x<height>"
    "export.pdf.url": "?export",
    "export.pdf.out": "renders/{slug}.pdf",
    "export.pptx.slide_size": "16:9",
    "export.pptx.cjk_ea_typeface": "Microsoft YaHei",
    "lint.fid_chain": True,
    "lint.fid_registry_flags": True,
    "lint.fid_leak": True,
    "lint.naked_numbers": True,
    "lint.style_scoping": True,
    "lint.unique_section_ids": True,
    "lint.asset_links": True,
    "lint.glyph_coverage": True,
    "lint.reveal_display": True,
    "lint.wrap_archetypes": True,
    "lint.storyboard_approved": True,
    "lint.allow_naked_years": True,
    "lint.naked_number_window": 250,
    "env.fonttools_python": "/usr/bin/python3",
    "env.pptx_python": "",           # resolved to <repo>/.venv/bin/python when empty
    "env.chrome": "",
    "env.node": "node",
}

# Checks that need a fact registry. Force-disabled when substrate.tier == "none".
REGISTRY_CHECKS = ("lint.fid_chain", "lint.fid_registry_flags", "lint.naked_numbers")


class ConfigError(Exception):
    """Raised with a dotted field path so the message points at the fix."""


def _dig(tree: dict, dotted: str):
    node = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def _coerce(dotted: str, raw: str, default):
    """Env vars arrive as strings; coerce to the default's type."""
    if isinstance(default, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{dotted}: expected a boolean, got {raw!r}")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"{dotted}: expected an integer, got {raw!r}") from None
    if isinstance(default, list):
        return [p.strip() for p in raw.split(",") if p.strip()]
    return raw


class DeckConfig:
    """Resolved configuration for one deck directory."""

    def __init__(self, deck: pathlib.Path, tree: dict, source: str):
        self.deck = deck
        self.tree = tree
        self.source = source          # path to deck.toml, or "<synthesized>"
        self._overrides: dict = {}

    # ---------------------------------------------------------------- access

    def set(self, dotted: str, value) -> None:
        """Apply a CLI override. Highest precedence."""
        if value is not None:
            self._overrides[dotted] = value

    def get(self, dotted: str, default=...):
        if dotted in self._overrides:
            return self._overrides[dotted]

        env_key = "DECKKIT_" + dotted.replace(".", "_").upper()
        if env_key in os.environ:
            fallback = DEFAULTS.get(dotted) if default is ... else default
            return _coerce(dotted, os.environ[env_key], fallback)

        try:
            value = _dig(self.tree, dotted)
        except KeyError:
            if default is not ...:
                return default
            if dotted in DEFAULTS:
                return DEFAULTS[dotted]
            raise ConfigError(f"{dotted}: required and not set in {self.source}") from None

        expected = DEFAULTS.get(dotted)
        if expected is not None and not isinstance(value, type(expected)):
            # bool is a subclass of int, so check it first
            if not (isinstance(expected, int) and isinstance(value, bool)):
                raise ConfigError(
                    f"{self.source}: [{dotted}] must be {type(expected).__name__}, "
                    f"got {type(value).__name__}"
                )
        return value

    def path(self, dotted: str, default=...) -> pathlib.Path:
        """A config value interpreted as a path relative to the deck dir."""
        return (self.deck / self.get(dotted, default)).resolve()

    # ------------------------------------------------------------- derived

    @property
    def slug(self) -> str:
        return self.get("deck.slug") or self.deck.name

    @property
    def canvas(self) -> tuple[int, int]:
        return self.get("canvas.width"), self.get("canvas.height")

    @property
    def fonts(self) -> list[dict]:
        faces = self.tree.get("fonts", [])
        if isinstance(faces, dict):          # [fonts] table instead of [[fonts]]
            faces = faces.get("face", [])
        for i, face in enumerate(faces):
            for required in ("role", "family", "source"):
                if required not in face:
                    raise ConfigError(f"{self.source}: [[fonts]][{i}] is missing '{required}'")
        return faces

    @property
    def substrate_tier(self) -> str:
        tier = self.get("substrate.tier")
        if tier not in ("repo", "deck-local", "none"):
            raise ConfigError(
                f"{self.source}: [substrate.tier] must be repo|deck-local|none, got {tier!r}"
            )
        return tier

    def facts_root(self) -> pathlib.Path | None:
        """Directory (repo tier) or file (deck-local tier) holding the registry."""
        if self.substrate_tier == "none":
            return None
        target = self.path("substrate.facts")
        if not target.exists():
            raise ConfigError(
                f"substrate.tier={self.substrate_tier} but {target} does not exist. "
                "Fix the path or set substrate.tier = \"none\"; falling back silently "
                "would validate every slide against an empty registry."
            )
        return target

    def lint_enabled(self, check: str) -> bool:
        if self.substrate_tier == "none" and check in REGISTRY_CHECKS:
            return False
        return bool(self.get(check))

    def derive_rigor(self, slide_count: int = 0, external_refs: int = 0) -> str:
        """Declared tier wins; otherwise derive. Printed by lint on every run."""
        declared = self.get("deck.rigor")
        if declared:
            if declared not in ("sketch", "standard", "regulated"):
                raise ConfigError(
                    f"{self.source}: [deck.rigor] must be sketch|standard|regulated, "
                    f"got {declared!r}"
                )
            return declared
        audience = self.get("deck.audience")
        if self.get("deck.issuer_listed") or audience in ("external-investor", "regulated-external"):
            return "regulated"
        if slide_count and slide_count <= 15 and audience == "internal" and external_refs == 0:
            return "sketch"
        return "standard"

    # ------------------------------------------------------- environment

    def interpreter(self, kind: str) -> str:
        """Which python runs a given tool. See references/pitfalls.md."""
        if kind == "fonttools":
            return self.get("env.fonttools_python")
        if kind == "pptx":
            configured = self.get("env.pptx_python")
            if configured:
                return configured
            for depth in (self.deck, *self.deck.parents):
                candidate = depth / ".venv" / "bin" / "python"
                if candidate.exists():
                    return str(candidate)
            return sys.executable
        return sys.executable


def find_chrome(cfg: DeckConfig | None = None) -> str | None:
    """Puppeteer cache first (that is what decktape and the probes expect)."""
    if cfg is not None:
        configured = cfg.get("env.chrome")
        if configured:
            return configured
    if os.environ.get("PUPPETEER_EXECUTABLE_PATH"):
        return os.environ["PUPPETEER_EXECUTABLE_PATH"]
    cache = pathlib.Path.home() / ".cache" / "puppeteer" / "chrome"
    if cache.is_dir():
        builds = sorted(cache.glob("*/chrome-linux64/chrome"), reverse=True)
        if builds:
            return str(builds[0])
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def require_capabilities(*modules: str) -> None:
    """Import hard deps; on failure print the exact fix and exit 3."""
    missing = []
    for name in modules:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return
    hint = {
        "fontTools": "run under /usr/bin/python3 (it has fontTools), or: pip install fonttools",
        "brotli": "pip install brotli   (woff2 output needs it)",
        "pptx": "pip install python-pptx",
        "PIL": "pip install pillow",
        "pypdf": "pip install pypdf",
    }
    print(f"environment: missing {', '.join(missing)}", file=sys.stderr)
    for name in missing:
        print(f"  {name}: {hint.get(name, 'pip install ' + name)}", file=sys.stderr)
    print(f"  current interpreter: {sys.executable}", file=sys.stderr)
    sys.exit(EXIT_ENV)


# ------------------------------------------------------------------ loading

def _resolve_deck(argv_deck: str | None) -> pathlib.Path:
    if argv_deck:
        deck = pathlib.Path(argv_deck).resolve()
        if not deck.is_dir():
            raise ConfigError(f"{deck} is not a directory")
        return deck
    here = pathlib.Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "deck.toml").exists():
            return candidate
    raise ConfigError("no deck directory given and no deck.toml found above the cwd")


def load(argv_deck: str | None = None, config_path: str | None = None) -> DeckConfig:
    """Load `<deck>/deck.toml`, or an empty tree if the deck has none."""
    deck = _resolve_deck(argv_deck)
    toml_path = pathlib.Path(config_path).resolve() if config_path else deck / "deck.toml"
    if not toml_path.exists():
        if config_path:
            raise ConfigError(f"{toml_path} does not exist")
        return DeckConfig(deck, {}, "<defaults>")
    try:
        with toml_path.open("rb") as handle:
            tree = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{toml_path}: {exc}") from None
    return DeckConfig(deck, tree, str(toml_path))


def synthesize(deck: pathlib.Path, overrides: dict) -> DeckConfig:
    """Build an in-memory config for a deck we must not write into.

    This is what lets `deckkit regress` drive the untouched bella deck: no
    deck.toml is ever created there.
    """
    cfg = DeckConfig(pathlib.Path(deck).resolve(), {}, "<synthesized>")
    for dotted, value in overrides.items():
        cfg.set(dotted, value)
    return cfg


def add_common_args(parser) -> None:
    """The flags every tool accepts, so muscle memory transfers."""
    parser.add_argument("deck", nargs="?", help="deck directory (default: nearest deck.toml)")
    parser.add_argument("--config", help="path to a deck.toml outside the deck dir")
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def bail(message: str, code: int = EXIT_USAGE):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def slug_re(pattern: str) -> re.Pattern:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"substrate.fact_id is not a valid regex: {exc}") from None
