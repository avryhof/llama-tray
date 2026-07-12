"""
tool_detect.py — Reliable tool detection for llama_tray.

The core problem: GTK apps launched from Cinnamon/XFCE inherit the *session*
PATH set by ~/.xprofile or ~/.profile at login, not the richer PATH that an
interactive terminal builds by sourcing ~/.bashrc.  Tools installed by npm
(opencode), cargo (llmfit), or nvm are typically added to PATH only in
~/.bashrc, so shutil.which() in the tray process can't see them even though
`which foo` in a terminal works fine.

Fix: ask a login shell for its PATH, then use that for all lookups.
On Windows, PATH is already inherited correctly, so we skip this step.
"""

import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

OS = platform.system()
SEP = ";" if OS == "Windows" else ":"


# ── Get the login shell's PATH ────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _login_path() -> str:
    """
    On Linux/macOS: launch a bash login shell, print its PATH, return it.
    On Windows: return the current process PATH (Windows inherits correctly).
    Falls back to os.environ["PATH"] if bash isn't available.
    Cached after the first call.
    """
    if OS == "Windows":
        return os.environ.get("PATH", "")
    try:
        result = subprocess.run(
            ["bash", "--login", "-c", "echo $PATH"],
            capture_output=True, text=True, timeout=5,
        )
        p = result.stdout.strip()
        if p:
            return p
    except Exception:
        pass
    return os.environ.get("PATH", "")


def _merged_path() -> str:
    """Merge the login shell PATH with the current process PATH, deduped."""
    login   = _login_path().split(SEP)
    current = os.environ.get("PATH", "").split(SEP)
    seen = set()
    merged = []
    for d in login + current:
        if d and d not in seen:
            seen.add(d)
            merged.append(d)
    return SEP.join(merged)


# ── Find a single binary ──────────────────────────────────────────────────────

def find_binary(name: str, override: str = "") -> str | None:
    """
    Return the full path to `name` or None.

    Priority:
      1. `override` — a manually configured path (if the file exists & is executable)
      2. Login shell PATH (captures npm/cargo/nvm installs)
      3. Current process PATH
      4. Hard-coded fallback locations
    """
    if override:
        p = Path(override.strip())
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)

    merged = _merged_path()
    found = shutil.which(name, path=merged)
    if found:
        return found

    return None


# ── VS Code variant names ─────────────────────────────────────────────────────

_VSCODE_NAMES = ["code", "code-insiders", "codium", "vscodium"]

# Continue extension config locations
CONTINUE_CONFIG_PATHS = [
    Path.home() / ".continue" / "config.json",
    Path.home() / ".config" / "continue" / "config.json",
]
if OS == "Windows":
    _appdata = Path(os.environ.get("APPDATA", Path.home()))
    CONTINUE_CONFIG_PATHS.append(_appdata / "Continue" / "config.json")

# opencode global config
OPENCODE_CONFIG_DEFAULT = Path.home() / ".config" / "opencode" / "config.json"
if OS == "Windows":
    _appdata = Path(os.environ.get("APPDATA", Path.home()))
    OPENCODE_CONFIG_DEFAULT = _appdata / "opencode" / "config.json"

# opencode auth (provider credentials)
OPENCODE_AUTH_DEFAULT = Path.home() / ".local" / "share" / "opencode" / "auth.json"
if OS == "Windows":
    OPENCODE_AUTH_DEFAULT = (Path(os.environ.get("LOCALAPPDATA", Path.home()))
                             / "opencode" / "auth.json")


def detect_tools(overrides: dict | None = None) -> dict[str, str | None]:
    """
    Return {'opencode': path|None, 'llmfit': path|None, 'vscode': path|None}.
    `overrides` maps tool name → manually configured path.
    """
    ov = overrides or {}
    result = {}

    for name in ("opencode", "llmfit"):
        result[name] = find_binary(name, ov.get(f"tool_{name}_path", ""))

    # VS Code — try each variant
    vsc_override = ov.get("tool_vscode_path", "")
    vsc = find_binary("", vsc_override) if vsc_override else None
    if not vsc:
        for vname in _VSCODE_NAMES:
            vsc = find_binary(vname)
            if vsc:
                break
    result["vscode"] = vsc

    return result
