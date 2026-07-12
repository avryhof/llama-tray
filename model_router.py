"""
model_router.py — Read/write llama.cpp models.ini preset files.

INI format (version = 1):

    version = 1

    [*]
    c = 4096
    n-gpu-layers = 8
    temp = 0.7

    [my-model]
    hf = user/repo:quant
    c = 2048
    n-gpu-layers = 123
    temp = 0.8
    n-predict = 512

    [disabled-model]          ; inactive — prefixed with ;
    hf = user/repo2:q4_0
    c = 4096

Keys map directly to llama-server CLI flags (without leading dashes).
The [*] section provides defaults inherited by every model.
Sections prefixed with ; are inactive/disabled.
"""

import configparser
import re
from pathlib import Path


def _config_dir() -> Path:
    """Platform config directory (same as config.py)."""
    import os, platform
    OS = platform.system()
    if OS == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif OS == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "llama_tray"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_models_ini_path() -> Path:
    """Default location for models.ini, next to config.json."""
    return _config_dir() / "models.ini"


# ── Parser ────────────────────────────────────────────────────────────────────

def load_models_ini(path: Path | str) -> dict:
    """
    Parse a models.ini file and return a structured dict.

    Returns:
        {
            "version": 1,
            "defaults": {"c": "4096", "n-gpu-layers": "8", ...},
            "models": [
                {"name": "my-model", "active": True, "params": {"hf": "...", "c": "2048"}},
                {"name": "disabled-model", "active": False, "params": {"hf": "..."}},
            ]
        }
    """
    path = Path(path)
    result = {"version": 1, "defaults": {}, "models": []}

    if not path.exists():
        return result

    raw = path.read_text(encoding="utf-8")

    # We parse manually because configparser doesn't handle [*] well
    # and we need to track commented-out sections.
    current_section = None
    current_params: dict[str, str] = {}
    current_active = True

    for line in raw.splitlines():
        stripped = line.strip()

        # Skip empty lines and plain comments (# style)
        if not stripped or stripped.startswith("#"):
            continue

        # Section header: [name] or ;[name] (inactive)
        m = re.match(r"^;?\[(.+?)\]\s*(?:;.*)?$", stripped)
        if m:
            # Save previous section
            if current_section is not None:
                if current_section == "*":
                    result["defaults"] = current_params
                else:
                    result["models"].append({
                        "name": current_section,
                        "active": current_active,
                        "params": current_params,
                    })

            section_name = m.group(1).strip()
            # Check if this section is commented out (inactive)
            current_active = not stripped.startswith(";")

            current_section = section_name
            current_params = {}
            continue

        # version = N
        vm = re.match(r"^version\s*=\s*(\d+)\s*$", stripped)
        if vm:
            result["version"] = int(vm.group(1))
            continue

        # key = value
        km = re.match(r"^([a-zA-Z0-9_-]+)\s*=\s*(.+?)\s*$", stripped)
        if km and current_section is not None:
            current_params[km.group(1)] = km.group(2)
            continue

    # Save last section
    if current_section is not None:
        if current_section == "*":
            result["defaults"] = current_params
        else:
            result["models"].append({
                "name": current_section,
                "active": current_active,
                "params": current_params,
            })

    return result


# ── Writer ────────────────────────────────────────────────────────────────────

def save_models_ini(path: Path | str, data: dict):
    """
    Write a models.ini file from a structured dict (same format as load_models_ini output).
    """
    path = Path(path)
    lines = [f"version = {data.get('version', 1)}", ""]

    # Global defaults
    defaults = data.get("defaults", {})
    if defaults:
        lines.append("[*]")
        for k, v in defaults.items():
            lines.append(f"{k} = {v}")
        lines.append("")

    # Per-model sections
    for model in data.get("models", []):
        name = model["name"]
        active = model.get("active", True)
        params = model.get("params", {})

        if not active:
            lines.append(f";[{name}]")
        else:
            lines.append(f"[{name}]")

        for k, v in params.items():
            lines.append(f"{k} = {v}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_gguf_files(models_dir: Path | str) -> list[Path]:
    """Return sorted list of .gguf files in the given directory."""
    d = Path(models_dir)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.gguf"), key=lambda f: f.name.lower())


def model_name_from_path(path: Path | str) -> str:
    """Extract a clean model name from a file path (stem, cleaned up)."""
    name = Path(path).stem
    # Remove common quant suffixes for cleaner display
    for suffix in ["-IMAT", "-GGUF", "_gguf"]:
        if name.upper().endswith(suffix.upper()):
            name = name[: -len(suffix)]
    return name


def make_model_entry(
    name: str,
    hf: str = "",
    local_path: str = "",
    params: dict | None = None,
) -> dict:
    """Create a model entry dict for use in models.ini data."""
    p = dict(params) if params else {}
    if hf:
        p["hf"] = hf
    if local_path:
        p["model"] = local_path
    return {"name": name, "active": True, "params": p}


def add_model_to_data(data: dict, entry: dict) -> dict:
    """Add or replace a model in the data dict. Returns the updated data."""
    name = entry["name"]
    # Remove existing entry with same name
    data["models"] = [m for m in data["models"] if m["name"] != name]
    data["models"].append(entry)
    return data


def remove_model_from_data(data: dict, name: str) -> dict:
    """Remove a model by name. Returns the updated data."""
    data["models"] = [m for m in data["models"] if m["name"] != name]
    return data


def toggle_model_active(data: dict, name: str, active: bool) -> dict:
    """Enable or disable a model. Returns the updated data."""
    for m in data["models"]:
        if m["name"] == name:
            m["active"] = active
            break
    return data


def models_ini_as_text(data: dict) -> str:
    """Render models.ini data as raw INI text (for preview)."""
    import io
    lines = [f"version = {data.get('version', 1)}", ""]

    defaults = data.get("defaults", {})
    if defaults:
        lines.append("[*]")
        for k, v in defaults.items():
            lines.append(f"{k} = {v}")
        lines.append("")

    for model in data.get("models", []):
        name = model["name"]
        active = model.get("active", True)
        params = model.get("params", {})

        if not active:
            lines.append(f";[{name}]")
        else:
            lines.append(f"[{name}]")

        for k, v in params.items():
            lines.append(f"{k} = {v}")
        lines.append("")

    return "\n".join(lines)
