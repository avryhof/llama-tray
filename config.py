"""
config.py — Persistent configuration for llama_tray.
Stores settings in a platform-appropriate user-config directory.
"""

import json
import os
import platform
from pathlib import Path

OS = platform.system()


def _default_binary() -> str:
    """Guess the most likely llama-server binary location."""
    candidates = []
    if OS == "Windows":
        candidates = [
            r"C:\llama.cpp\llama-server.exe",
            str(Path.home() / "llama.cpp" / "llama-server.exe"),
            "llama-server.exe",
        ]
    elif OS == "Darwin":
        candidates = [
            "/usr/local/bin/llama-server",
            "/opt/homebrew/bin/llama-server",
            str(Path.home() / "llama.cpp" / "llama-server"),
            "llama-server",
        ]
    else:  # Linux
        candidates = [
            "/usr/local/bin/llama-server",
            str(Path.home() / "llama.cpp" / "llama-server"),
            "llama-server",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return candidates[-1]  # return the last as a placeholder


# Default configuration values (defined after _default_binary)
DEFAULTS = {
    # Path to llama-server binary
    "llama_server_path": _default_binary(),
    # Model settings
    "active_model": "",
    "models_dir": str(Path.home() / "models"),
    # Server network settings
    "host": "127.0.0.1",
    "port": 8080,
    # Inference settings
    "ctx_size": 4096,
    "n_parallel": 1,
    "n_gpu_layers": 0,
    # HuggingFace
    "hf_token": "",  # optional HF access token
    "hf_search_query": "gguf",  # default HF search
    # Advanced
    "extra_flags": "",  # raw CLI flags appended to the command
    "auto_start": False,  # start server on app launch
    # External tool paths (empty = auto-detect)
    "tool_opencode_path": "",
    "tool_opencode_config": "",
    "tool_llmfit_path": "",
    "tool_vscode_path": "",
    "tool_vscode_config": "",
}


def _config_path() -> Path:
    """Return path to the config JSON file."""
    if OS == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif OS == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = base / "llama_tray"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


class Config:
    def __init__(self):
        self._path = _config_path()
        self._data: dict = {}
        self.load()

    def load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
            except Exception:
                saved = {}
        else:
            saved = {}
        # Merge: saved values override defaults, new defaults fill gaps
        self._data = {**DEFAULTS, **saved}

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self) -> dict:
        return dict(self._data)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    def update(self, updates: dict):
        self._data.update(updates)
        self.save()

    @property
    def config_file(self) -> Path:
        return self._path
