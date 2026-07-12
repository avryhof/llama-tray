import json
import threading
from typing import Callable, Optional
from urllib import request, error

from config import Config

# ── Server state constants ─────────────────────────────────────────────────


class State:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# ── Centralized server state manager ──────────────────────────────────────


class ServerStateManager:
    """Single source of truth for server states.

    Observers are called as  callback(server_id, new_state, old_state)
    outside any lock — safe to update tkinter widgets directly from them
    (via root.after for cross-thread safety).
    """

    def __init__(self):
        self._states: dict[str, str] = {}
        self._observers: list[Callable] = []
        self._lock = threading.Lock()

    def get_state(self, server_id: str) -> str:
        with self._lock:
            return self._states.get(server_id, State.STOPPED)

    def all_states(self) -> dict[str, str]:
        """Return a snapshot of all server states."""
        with self._lock:
            return dict(self._states)

    def set_state(self, server_id: str, state: str):
        with self._lock:
            old = self._states.get(server_id, State.STOPPED)
            self._states[server_id] = state
        for observer in list(self._observers):
            try:
                observer(server_id, state, old)
            except Exception:
                pass

    def add_observer(self, callback: Callable):
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable):
        try:
            self._observers.remove(callback)
        except ValueError:
            pass


# Module-level singleton shared across the entire application.
state_manager = ServerStateManager()


# ── Server lookup helpers ─────────────────────────────────────────────────


def get_server(server_id: str) -> Optional[dict]:
    config: Config = Config()
    return config.get_server(server_id)


def build_server_label(srv: dict) -> str:
    """Human-readable label: 'My Server (127.0.0.1:8080)'"""
    if srv.get("is_local"):
        return f"{srv['name']} ({srv['host']}:{srv['port']})"
    else:
        return f"{srv['name']} ({srv.get('url', 'unknown')})"


def build_server_url(srv: dict) -> str:
    """Build base URL from server config (url field or host:port)."""
    url = srv.get("url", "").strip()
    if url:
        try:
            scheme, host, port = url.split(":")
        except ValueError:
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            return url.rstrip("/")
        else:
            host = host.lstrip("/")
            port = int(port.rstrip("/"))
            scheme = "https" if port == 443 else "http"
            return f"{scheme}://{host}:{port}"
    else:
        host = srv.get("host", "127.0.0.1")
        port = srv.get("port", 8080)
        scheme = "https" if port == 443 else "http"
        return f"{scheme}://{host}:{port}"


def build_server_headers(srv: dict, chat: bool = False) -> dict:
    """Build request headers with API key and custom headers."""
    headers = {"User-Agent": "LlamaTray/1.0"}

    if chat:
        headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
        )

    api_key = srv.get("api_key", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for h in srv.get("custom_headers", []):
        key = h.get("key", "").strip()
        value = h.get("value", "").strip()
        if key:
            headers[key] = value
    return headers


# ── Network helpers ───────────────────────────────────────────────────────


def check_server_health(server) -> dict:
    """Check if a server is reachable.  Accepts a server dict or server ID.

    Returns {"result": "ok"} or {"result": "error", "message": "..."}.
    """
    if isinstance(server, str):
        server = get_server(server)
    if not server:
        return {"result": "error", "message": "Server not found"}

    url = f"{build_server_url(server)}/health"
    try:
        req = request.Request(url, method="GET", headers=build_server_headers(server))
        with request.urlopen(req, timeout=5) as r:
            if r.status == 200:
                return {"result": "ok"}
            else:
                return {"result": "error", "message": f"HTTP {r.status}"}
    except error.HTTPError as e:
        return {"result": "error", "message": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"result": "error", "message": str(e)}


def get_server_models(srv: dict) -> list[str]:
    """Fetch available model IDs from GET /v1/models."""
    url = f"{build_server_url(srv)}/v1/models"
    headers = build_server_headers(srv)

    try:
        req = request.Request(url, method="GET", headers=headers)
        with request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            return [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception:
        active = srv.get("active_model", "")
        if active:
            from pathlib import Path

            return [Path(active).stem]
        return ["local"]
