"""Where the vendored core and the repo's profile live, how prompts' `{dotted.key}` values resolve, and which core
version is running.

Vendored layout: `<repo>/.claude/routines/{pipeline.yml, core/bin/<this file>}`. `PIPELINE_PROFILE` overrides the
profile path, for tests and local runs.
"""

from __future__ import annotations

import os
import site
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

BIN = Path(__file__).resolve().parent
CORE = BIN.parent
ROUTINES = CORE.parent
DEFAULT_PROFILE = ROUTINES / "pipeline.yml"


def yaml_module():
    """PyYAML, which the cloud image may lack. The environment's setup script should install it; pip is the fallback."""
    try:
        import yaml

        return yaml
    except ImportError:
        pass
    for extra in ([], ["--user"]):
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *extra, "pyyaml"], capture_output=True)
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.append(user_site)
    try:
        import yaml

        return yaml
    except ImportError:
        sys.exit("PyYAML is missing and `pip install pyyaml` failed: add it to the cloud environment's setup script")


def profile_path(path: Optional[str] = None) -> Path:
    return Path(path or os.environ.get("PIPELINE_PROFILE") or DEFAULT_PROFILE)


def load(path: Optional[str] = None) -> dict:
    return yaml_module().safe_load(profile_path(path).read_text()) or {}


def lookup(profile: dict, dotted: str) -> Any:
    """The value at a dotted key, or None when it is missing or empty."""
    node: Any = profile
    for part in dotted.split("."):
        if not isinstance(node, dict) or node.get(part) in (None, "", [], {}):
            return None
        node = node[part]
    return node


def front_matter(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}
    return yaml_module().safe_load(text[4 : text.index("\n---", 4)]) or {}


def routine(profile: dict, key: str) -> Optional[dict]:
    return next((r for r in profile.get("routines") or [] if r.get("key") == key), None)


def prompt_file(entry: dict, core: Path = CORE) -> Path:
    """A routine's prompt: its core role, or its local prompt next to the profile."""
    if entry.get("prompt"):
        return profile_path().parent / entry["prompt"]
    return core / "roles" / f"{entry['role']}.md"


def git(*args: str, cwd: Optional[Path] = None, stdin: Optional[str] = None) -> str:
    """A git command in the repo, its stdout stripped. Raises on failure, with git's own message."""
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd or CORE, input=stdin)
    if proc.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def core_version() -> str:
    """`<VERSION>+<tree>`: the release in core/VERSION and the core folder's committed tree hash."""
    version = (CORE / "VERSION").read_text().strip() if (CORE / "VERSION").exists() else "0"
    try:
        prefix = git("rev-parse", "--show-prefix").rstrip("/")
        tree = git("rev-parse", "--short", f"HEAD:{prefix}") if prefix else ""
    except RuntimeError:
        tree = ""
    return f"{version}+{tree or 'uncommitted'}"
