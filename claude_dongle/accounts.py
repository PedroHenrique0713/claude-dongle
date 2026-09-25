"""Claude Code accounts on this machine: one config directory each.

Claude Code keeps everything of an account (token, identity, sessions,
transcripts) under one directory: ~/.claude by default, or whatever
CLAUDE_CONFIG_DIR points at. People with several subscriptions switch with a
wrapper such as `claude-work() { CLAUDE_CONFIG_DIR=~/.claude-work claude; }`.
The dongle watches one of those directories at a time (config `claude_dir`).

Every piece of state the dongle keeps about an account (usage cache, sent
notifications, telemetry flag) is keyed by that directory. Sharing them made
a switch look like a reset: an account at 80% followed by one at 10% read as
"the limit came back".
"""
import json
import re
from pathlib import Path

from . import config

DEFAULT_DIR = Path.home() / ".claude"


def _norm(claude_dir) -> Path:
    return Path(claude_dir).expanduser() if claude_dir else DEFAULT_DIR


def is_default(claude_dir) -> bool:
    try:
        return _norm(claude_dir).resolve() == DEFAULT_DIR.resolve()
    except OSError:
        return _norm(claude_dir) == DEFAULT_DIR


def key(claude_dir) -> str:
    """Short stable id of an account dir: '' for ~/.claude, 'work' for
    ~/.claude-work. The default stays '' so the files written before accounts
    existed keep belonging to it."""
    if is_default(claude_dir):
        return ""
    name = _norm(claude_dir).name.lstrip(".")
    if name.startswith("claude-"):
        name = name[len("claude-"):]
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower() or "account"


def credentials_path(claude_dir) -> Path:
    return _norm(claude_dir) / ".credentials.json"


def identity_path(claude_dir) -> Path:
    """The .claude.json holding oauthAccount. Without CLAUDE_CONFIG_DIR
    Claude Code writes it to ~/.claude.json; ~/.claude/.claude.json is an
    older location that can linger for months. Newest one wins."""
    d = _norm(claude_dir)
    cands = [d / ".claude.json"]
    if is_default(d):
        cands.append(Path.home() / ".claude.json")
    existing = [p for p in cands if p.exists()]
    if not existing:
        return cands[0]
    return max(existing, key=lambda p: p.stat().st_mtime)


def projects_dir(claude_dir) -> Path:
    return _norm(claude_dir) / "projects"


def state_path(filename: str, claude_dir) -> Path:
    """Per-account state file: sent_thresholds.json for the default account,
    sent_thresholds.work.json for ~/.claude-work."""
    k = key(claude_dir)
    if not k:
        return config.CONFIG_DIR / filename
    p = Path(filename)
    return config.CONFIG_DIR / f"{p.stem}.{k}{p.suffix}"


def _oauth_account(claude_dir) -> dict:
    try:
        data = json.loads(identity_path(claude_dir).read_text())
        oa = data.get("oauthAccount")
        return oa if isinstance(oa, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def label(claude_dir) -> str:
    """What the account is called on a button. Extra accounts go by their
    directory suffix, the name their owner typed in the wrapper (claude-work →
    'Work'); the default one has no suffix, so it borrows the account name."""
    k = key(claude_dir)
    if k:
        return k.upper() if len(k) <= 3 else k.replace("-", " ").title()
    oa = _oauth_account(claude_dir)
    name = oa.get("displayName") or oa.get("organizationName") or ""
    return name if name and len(name) <= 16 else "Default"


def discover(current=None) -> list:
    """Account dirs under home that hold a Claude Code login, default first.
    The configured dir is always listed, even if it lives elsewhere."""
    found = []
    try:
        for p in Path.home().iterdir():
            if (p.name == ".claude" or p.name.startswith(".claude-")) \
                    and p.is_dir() and credentials_path(p).exists():
                found.append(p)
    except OSError:
        pass
    if current and not any(_same(p, current) for p in found):
        found.append(_norm(current))
    found.sort(key=lambda p: (not is_default(p), p.name))
    return found


def _same(a, b) -> bool:
    try:
        return _norm(a).resolve() == _norm(b).resolve()
    except OSError:
        return _norm(a) == _norm(b)


def find(name, current=None):
    """Account dir matching a key, a label or a path (case-insensitive)."""
    if not name:
        return None
    n = str(name).strip().lower()
    for d in discover(current):
        if n in (key(d), label(d).lower(), d.name.lower(), str(d).lower()) \
                or (n == "default" and is_default(d)):
            return d
    p = Path(name).expanduser()
    return p if credentials_path(p).exists() else None
