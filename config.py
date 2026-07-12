"""
config.py — Persistent configuration for llama_tray.
Stores settings in a platform-appropriate user-config directory.

Supports multiple server profiles via the "servers" list.
"""

import json
import os
import platform
import uuid
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
    return candidates[-1]


def _make_server_id() -> str:
    return uuid.uuid4().hex[:8]


def make_mcp_server(
    name: str = "",
    transport: str = "stdio",
    command: str = "",
    args: list[str] = None,
    env: dict[str, str] = None,
    url: str = "",
    headers: dict[str, str] = None,
    enabled: bool = True,
) -> dict:
    """Create a new MCP server config dict.

    transport: "stdio", "sse", "streamable-http", "rpc"
    """
    return {
        "id": _make_server_id(),
        "name": name,
        "transport": transport,
        "command": command,
        "args": args or [],
        "env": env or {},
        "url": url,
        "headers": headers or {},
        "enabled": enabled,
    }


def make_server(
    name: str = "Local",
    host: str = "127.0.0.1",
    port: int = 8080,
    is_local: bool = True,
    llama_server_path: str = "",
    active_model: str = "",
    ctx_size: int = 4096,
    n_parallel: int = 1,
    n_gpu_layers: int = 0,
    extra_flags: str = "",
    auto_start: bool = False,
    use_router: bool = False,
    models_preset_path: str = "",
    api_key: str = "",
    url: str = "",
    custom_headers: list[dict[str, str]] = None,
    n_threads: int = 0,
    flash_attn: bool = False,
    cache_type_k: str = "f16",
    cache_type_v: str = "f16",
    mlock: bool = False,
    mmap: bool = True,
    metrics: bool = False,
    lora_path: str = "",
    lora_scale: float = 1.0,
) -> dict:
    """Create a new server profile dict."""
    if not llama_server_path:
        llama_server_path = _default_binary()
    return {
        "id": _make_server_id(),
        "name": name,
        "host": host,
        "port": port,
        "is_local": is_local,
        "llama_server_path": llama_server_path,
        "active_model": active_model,
        "ctx_size": ctx_size,
        "n_parallel": n_parallel,
        "n_gpu_layers": n_gpu_layers,
        "extra_flags": extra_flags,
        "auto_start": auto_start,
        "use_router": use_router,
        "models_preset_path": models_preset_path,
        "api_key": api_key,
        "url": url,
        "custom_headers": custom_headers or [],
        "n_threads": n_threads,
        "flash_attn": flash_attn,
        "cache_type_k": cache_type_k,
        "cache_type_v": cache_type_v,
        "mlock": mlock,
        "mmap": mmap,
        "metrics": metrics,
        "lora_path": lora_path,
        "lora_scale": lora_scale,
    }


# Global config keys (not per-server)
GLOBAL_DEFAULTS = {
    "models_dir": str(Path.home() / "models"),
    "hf_token": "",
    "hf_search_query": "gguf",
    "tool_opencode_path": "",
    "tool_opencode_config": "",
    "tool_llmfit_path": "",
    "tool_vscode_path": "",
    "tool_vscode_config": "",
    "chat_history": {},
    "mcp_servers": [],
    "server_presets": [
        {
            "name": "Balanced",
            "description": "Factory defaults — safe starting point",
            "settings": {},
        },
        {
            "name": "Max Speed",
            "description": "Flash attn + q4 KV cache — fastest inference, moderate VRAM",
            "settings": {
                "flash_attn": True,
                "cache_type_k": "q4_0",
                "cache_type_v": "q4_0",
            },
        },
        {
            "name": "Max VRAM Savings",
            "description": "Aggressive quant + mlock — minimal VRAM, model stays in RAM",
            "settings": {
                "flash_attn": True,
                "cache_type_k": "q4_0",
                "cache_type_v": "q4_0",
                "mlock": True,
            },
        },
        {
            "name": "CPU Only",
            "description": "No GPU offload — 8 threads, model locked in RAM",
            "settings": {
                "n_gpu_layers": 0,
                "n_threads": 8,
                "mlock": True,
            },
        },
        {
            "name": "Development",
            "description": "Prometheus /metrics endpoint + mmap — for monitoring/debugging",
            "settings": {
                "metrics": True,
                "mmap": True,
            },
        },
        {
            "name": "Long Context",
            "description": "32K context with q8 KV cache — needs ~24 GB VRAM",
            "settings": {
                "ctx_size": 32768,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
            },
        },
    ],
}

# Keys that were per-server in the old flat format
_SERVER_KEYS = [
    "llama_server_path",
    "active_model",
    "host",
    "port",
    "ctx_size",
    "n_parallel",
    "n_gpu_layers",
    "extra_flags",
    "auto_start",
    "use_router",
    "models_preset_path",
    "api_key",
    "url",
    "custom_headers",
    "n_threads",
    "flash_attn",
    "cache_type_k",
    "cache_type_v",
    "mlock",
    "mmap",
    "metrics",
    "lora_path",
    "lora_scale",
]

DEFAULTS = {
    **GLOBAL_DEFAULTS,
    "servers": [make_server()],
    "mcp_servers": [],
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


def _migrate_flat_to_servers(saved: dict) -> dict:
    """Convert old flat config to new servers-list format."""
    if "servers" in saved:
        return saved  # already migrated

    # Build a server from the old flat keys
    server = make_server(
        name="Local",
        host=saved.get("host", "127.0.0.1"),
        port=saved.get("port", 8080),
        is_local=True,
        llama_server_path=saved.get("llama_server_path", ""),
        active_model=saved.get("active_model", ""),
        ctx_size=saved.get("ctx_size", 4096),
        n_parallel=saved.get("n_parallel", 1),
        n_gpu_layers=saved.get("n_gpu_layers", 0),
        extra_flags=saved.get("extra_flags", ""),
        auto_start=saved.get("auto_start", False),
    )

    # Remove per-server keys from saved, keep globals
    migrated = {k: v for k, v in saved.items() if k not in _SERVER_KEYS}
    migrated["servers"] = [server]
    return migrated


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

        # Migrate old flat format if needed
        saved = _migrate_flat_to_servers(saved)

        # Merge: saved values override defaults, new defaults fill gaps
        self._data = {**DEFAULTS, **saved}

        # Ensure every server has an id
        for srv in self._data["servers"]:
            if "id" not in srv:
                srv["id"] = _make_server_id()

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self) -> dict:
        """Return the full config dict."""
        return dict(self._data)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    def update(self, updates: dict):
        self._data.update(updates)
        self.save()

    # ── Server helpers ────────────────────────────────────────────────────

    def servers(self) -> list[dict]:
        """Return the list of server profiles."""
        return self._data.get("servers", [])

    def get_server(self, server_id: str) -> dict | None:
        """Find a server by its id."""
        for srv in self._data.get("servers", []):
            if srv.get("id") == server_id:
                return srv
        return None

    def get_server_by_index(self, index: int) -> dict | None:
        """Return the server at the given index, or None."""
        servers = self._data.get("servers", [])
        if 0 <= index < len(servers):
            return servers[index]
        return None

    def add_server(self, server: dict):
        """Append a new server profile and save."""
        if "id" not in server:
            server["id"] = _make_server_id()
        self._data.setdefault("servers", []).append(server)
        self.save()

    def update_server(self, server_id: str, updates: dict):
        """Update fields on an existing server profile."""
        srv = self.get_server(server_id)
        if srv:
            srv.update(updates)
            self.save()

    def remove_server(self, server_id: str):
        """Remove a server profile by id."""
        servers = self._data.get("servers", [])
        self._data["servers"] = [s for s in servers if s.get("id") != server_id]
        self.save()

    def move_server(self, server_id: str, direction: int):
        """Move a server up (-1) or down (+1) in the list."""
        servers = self._data.get("servers", [])
        for i, srv in enumerate(servers):
            if srv.get("id") == server_id:
                new_idx = i + direction
                if 0 <= new_idx < len(servers):
                    servers[i], servers[new_idx] = servers[new_idx], servers[i]
                    self.save()
                break

    @property
    def config_file(self) -> Path:
        return self._path

    # ── MCP server helpers ────────────────────────────────────────────────

    def mcp_servers(self) -> list[dict]:
        """Return the list of MCP server profiles."""
        return self._data.get("mcp_servers", [])

    def get_mcp_server(self, server_id: str) -> dict | None:
        """Find an MCP server by its id."""
        for srv in self._data.get("mcp_servers", []):
            if srv.get("id") == server_id:
                return srv
        return None

    def add_mcp_server(self, server: dict):
        """Append a new MCP server profile and save."""
        if "id" not in server:
            server["id"] = _make_server_id()
        self._data.setdefault("mcp_servers", []).append(server)
        self.save()

    def update_mcp_server(self, server_id: str, updates: dict):
        """Update fields on an existing MCP server profile."""
        srv = self.get_mcp_server(server_id)
        if srv:
            srv.update(updates)
            self.save()

    def remove_mcp_server(self, server_id: str):
        """Remove an MCP server profile by id."""
        servers = self._data.get("mcp_servers", [])
        self._data["mcp_servers"] = [s for s in servers if s.get("id") != server_id]
        self.save()
