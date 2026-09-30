"""Shared paths and loaders for the delegation tests (stdlib only)."""
import importlib.machinery
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "delegation")
SCRIPTS = os.path.join(SKILL, "scripts")
AGENTS = os.path.join(REPO, "agents")
HOOKS = os.path.join(REPO, "hooks")


def load_script(name):
    """Import an extensionless script (codex-delegate, delegation-ledger) as a module."""
    path = os.path.join(SCRIPTS, name)
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def frontmatter(path):
    """Flat `key: value` YAML frontmatter, which is all our agent files use."""
    with open(path) as f:
        text = f.read()
    assert text.startswith("---\n"), path
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body
