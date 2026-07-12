"""
tray_base.py — Shared logic for the llama.cpp system tray application.

Supports multiple server profiles. Platform-specific subclasses
(tray_gtk, tray_pystray) implement the UI parts.
"""

import os
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from urllib import request

from PIL import Image, ImageDraw

from config import Config
from tool_detect import detect_tools
from utility_functions import (
    State,
    state_manager,
    build_server_url,
    build_server_headers,
    build_server_label,
    check_server_health,
    get_server,
)

APP_NAME = "llama.cpp Server"
APP_ID = "llama-tray"
VERSION = "2.0.0"

ICON_COLOURS = {
    "stopped": "#6c757d",
    "starting": "#fd7e14",
    "running": "#28a745",
    "error": "#dc3545",
}

HEALTH_CHECK_INTERVAL = 120  # seconds


def _icons_dir() -> Path:
    """Return the persistent icons directory inside the config folder."""
    from config import _config_path
    d = _config_path().parent / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_icon_file(state: str) -> str:
    """Return the path to the icon PNG for *state*, generating it if needed."""
    icon_path = _icons_dir() / f"{state}.png"
    if icon_path.exists():
        return str(icon_path)

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colour = ICON_COLOURS.get(state, "#6c757d")
    draw.ellipse([2, 2, size - 2, size - 2], fill=colour, outline="white", width=2)
    draw.text((18, 12), "L", fill="white")

    img.save(str(icon_path))
    return str(icon_path)


class LlamaTrayApp:
    """Base class with shared server management logic.

    Subclasses must implement:
        _set_state(server_id, state)  — update icon and state
        _rebuild_menu()               — rebuild the tray menu
        _on_quit(*args)               — framework-specific quit handler
        run()                         — bootstrap and start the main loop
    """

    def __init__(self):
        self.config: Config = Config()

        # Per-server subprocess handles
        self.server_procs: dict[str, subprocess.Popen] = {}

        # Shared log buffer (tagged with server names)
        self.log_lines: list[str] = []
        self._lock = threading.Lock()

        # Global tool paths (not per-server)
        self._tools: dict[str, str | None] = {}

    # ── Logging ───────────────────────────────────────────────────────────

    def _log(self, msg: str, server_name: str = ""):
        ts = time.strftime("%H:%M:%S")
        prefix = f"[{server_name}] " if server_name else ""
        line = f"[{ts}] {prefix}{msg}"
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > 500:
                self.log_lines = self.log_lines[-500:]
        print(line, flush=True)

    # ── Thread-safe state notification ────────────────────────────────────

    def _notify_state(self, server_id: str, state: str):
        """Schedule a state update. Thread-safe by default (calls _set_state).

        GTK subclass overrides this to use GLib.idle_add.
        """
        state_manager.set_state(server_id, state)

    # ── Server helpers ────────────────────────────────────────────────────

    def _model_name(self, srv: dict) -> str:
        m = srv.get("active_model", "")
        return Path(m).name if m else "No model selected"

    def _server_state(self, server_id: str) -> str:
        return state_manager.get_state(server_id)

    # ── Build server command ──────────────────────────────────────────────
    def _build_cmd(self, srv: dict) -> list[str]:
        cmd = [srv["llama_server_path"]]

        # Router mode: use --models-preset instead of -m
        use_router = srv.get("use_router", False)
        if use_router:
            preset = srv.get("models_preset_path", "")
            if preset:
                cmd += ["--models-preset", preset]
        else:
            model = srv.get("active_model", "")
            if model:
                cmd += ["-m", model]

        cmd += [
            "--host",
            srv.get("host", "127.0.0.1"),
            "--port",
            str(srv.get("port", 8080)),
        ]

        if not use_router:
            cmd += ["-c", str(srv.get("ctx_size", 4096))]
            if srv.get("n_parallel", 1) > 1:
                cmd += ["-np", str(srv["n_parallel"])]
            if srv.get("n_gpu_layers", 0) > 0:
                cmd += ["-ngl", str(srv["n_gpu_layers"])]

        # CPU threads (0 = auto)
        n_threads = srv.get("n_threads", 0)
        if n_threads > 0:
            cmd += ["--threads", str(n_threads)]

        # Flash attention
        if srv.get("flash_attn", False):
            cmd += ["--flash-attn"]

        # KV cache quantization
        cache_k = srv.get("cache_type_k", "f16")
        if cache_k != "f16":
            cmd += ["--cache-type-k", cache_k]
        cache_v = srv.get("cache_type_v", "f16")
        if cache_v != "f16":
            cmd += ["--cache-type-v", cache_v]

        # Memory management
        if srv.get("mlock", False):
            cmd += ["--mlock"]
        if not srv.get("mmap", True):
            cmd += ["--no-mmap"]

        # Prometheus metrics
        if srv.get("metrics", False):
            cmd += ["--metrics"]

        cmd.append("--log-disable")

        # API key for auth
        api_key = srv.get("api_key", "").strip()
        if api_key:
            cmd += ["--api-key", api_key]

        extra = srv.get("extra_flags", "").strip()
        if extra:
            cmd += extra.split()
        return cmd

    # ── Menu action handlers (per-server) ─────────────────────────────────

    def _on_start(self, server_id: str, *args):
        state = self._server_state(server_id)
        if state in (State.RUNNING, State.STARTING):
            return
        threading.Thread(target=self._start_thread, args=(server_id,), daemon=True).start()

    def _on_stop(self, server_id: str, *args):
        state = self._server_state(server_id)
        if state not in (State.RUNNING, State.STARTING):
            return
        threading.Thread(target=self._stop_thread, args=(server_id,), daemon=True).start()

    def _on_restart(self, server_id: str, *args):
        state = self._server_state(server_id)
        if state == State.STOPPED:
            return

        def _restart():
            self._stop_thread(server_id)
            time.sleep(1)
            self._start_thread(server_id)

        threading.Thread(target=_restart, daemon=True).start()

    def _on_check_remote(self, server_id: str, *args):
        """Check if a remote server is reachable via health endpoint."""
        srv = get_server(server_id)
        if not srv:
            return
        name = srv.get("name", "")
        self._notify_state(server_id, State.STARTING)

        def _do_check():
            base = build_server_url(srv)
            self._log(f"Checking remote server at {base}…", name)
            result = check_server_health(srv)
            if result["result"] == "ok":
                self._log(f"Remote server online ({base})", name)
                self._notify_state(server_id, State.RUNNING)
            else:
                self._log(f"Remote server error: {result['message']}", name)
                self._notify_state(server_id, State.ERROR)

        threading.Thread(target=_do_check, daemon=True).start()

    def _on_open_webui(self, server_id: str, *args):
        srv = get_server(server_id)
        if srv:
            webbrowser.open(build_server_url(srv))

    def _on_open_logs(self, *args):
        from log_window import show_log_window

        show_log_window(self.log_lines)

    def _on_settings(self, *args):
        from settings_window import show_settings_window

        show_settings_window(self.config, on_save=self._rebuild_menu)

    def _on_model_manager(self, *args):
        from model_manager import show_model_manager

        show_model_manager(self.config, on_save=self._rebuild_menu)

    def _on_chat(self, *args):
        from chat_window import show_chat_window

        show_chat_window(self.config)

    def _on_nvidia(self, *args):
        from nvidia_window import show_nvidia_window

        show_nvidia_window()

    # ── Server lifecycle (background threads) ─────────────────────────────

    def _start_thread(self, server_id: str):
        srv = get_server(server_id)
        if not srv:
            return
        name = srv["name"]
        self._notify_state(server_id, State.STARTING)

        binary = srv.get("llama_server_path", "")
        if not binary or not Path(binary).is_file():
            self._log(f"Binary not found: {binary}", name)
            self._log("Open Settings to set the correct path.", name)
            self._notify_state(server_id, State.ERROR)
            return

        # In router mode, models come from the preset file — skip individual model check
        use_router = srv.get("use_router", False)
        if not use_router:
            model = srv.get("active_model", "")
            if model and not Path(model).is_file():
                self._log(f"Model not found: {model}", name)
                self._notify_state(server_id, State.ERROR)
                return

        cmd = self._build_cmd(srv)
        self._log("Starting: " + " ".join(cmd), name)

        try:
            self.server_procs[server_id] = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._log(f"Failed to launch: {e}", name)
            self._notify_state(server_id, State.ERROR)
            return

        threading.Thread(target=self._read_output, args=(server_id,), daemon=True).start()

        url = build_server_url(srv)
        headers = build_server_headers(srv)

        for _ in range(60):
            time.sleep(0.5)
            proc = self.server_procs.get(server_id)
            if proc and proc.poll() is not None:
                self._log("Server exited unexpectedly.", name)
                self._notify_state(server_id, State.ERROR)
                return
            try:
                req = request.Request(url, headers=headers)
                with request.urlopen(req, timeout=2) as r:
                    if r.status == 200:
                        self._log(f"Server ready at {url}", name)
                        self._notify_state(server_id, State.RUNNING)
                        threading.Thread(
                            target=self._health_monitor,
                            args=(server_id,),
                            daemon=True,
                        ).start()
                        return
            except Exception:
                pass

        self._log("Server did not become healthy within 30 s.", name)
        self._notify_state(server_id, State.ERROR)

    def _stop_thread(self, server_id: str):
        proc = self.server_procs.get(server_id)
        srv = get_server(server_id)
        name = srv["name"] if srv else ""

        if proc is None:
            self._notify_state(server_id, State.STOPPED)
            return
        self._log("Stopping server…", name)
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        except Exception:
            pass
        self.server_procs.pop(server_id, None)
        self._log("Server stopped.", name)
        self._notify_state(server_id, State.STOPPED)

    def _read_output(self, server_id: str):
        proc = self.server_procs.get(server_id)
        srv = get_server(server_id)
        name = srv["name"] if srv else ""
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log(line.rstrip(), name)

    def _health_monitor(self, server_id: str):
        srv = get_server(server_id)
        name = srv["name"] if srv else ""
        url = build_server_url(srv)
        headers = build_server_headers(srv)
        while True:
            time.sleep(HEALTH_CHECK_INTERVAL)
            with self._lock:
                if state_manager.get_state(server_id) != State.RUNNING:
                    break
            try:
                req = request.Request(url, headers=headers)
                with request.urlopen(req, timeout=5) as r:
                    if r.status != 200:
                        raise ValueError("non-200")
            except Exception:
                if state_manager.get_state(server_id) == State.RUNNING:
                    self._log("Health check failed — server may have crashed.", name)
                    self._notify_state(server_id, State.ERROR)
                break

    # ── Shared pre-run setup ──────────────────────────────────────────────

    def _pre_run(self):
        """Pre-render icons, detect tools, start auto-start servers."""
        for state in ICON_COLOURS:
            make_icon_file(state)

        # Detect tools (global, not per-server)
        def _detect_and_refresh():
            detected = detect_tools()
            cfg = self.config.get()
            merged = {}
            for tool_name in ("opencode", "llmfit", "vscode"):
                saved = cfg.get(f"tool_{tool_name}_path", "").strip()
                if saved and Path(saved).exists():
                    merged[tool_name] = saved
                elif detected.get(tool_name):
                    merged[tool_name] = detected[tool_name]
                else:
                    merged[tool_name] = None
            self._tools = merged
            for tool_name, path in merged.items():
                self._log(f"[tools] {tool_name}: {path or 'not found'}")
            self._rebuild_menu()

        threading.Thread(target=_detect_and_refresh, daemon=True).start()

        # Auto-start local servers
        for srv in self.config.servers():
            if srv.get("auto_start") and srv.get("is_local"):
                sid = srv["id"]
                state_manager.set_state(sid, State.STOPPED)
                threading.Thread(target=self._start_thread, args=(sid,), daemon=True).start()
            elif not srv["is_local"]:
                self._on_check_remote(srv['id'])

    def _quit(self):
        """Shared quit cleanup: stop all servers."""
        self._log("Quitting…")
        for server_id in list(self.server_procs.keys()):
            self._stop_thread(server_id)

    # ── Abstract methods (must be implemented by subclasses) ───────────────

    def _set_state(self, server_id: str, state: str):
        """Update state, icon, and menu for a server. Called on the main thread."""
        raise NotImplementedError

    def _rebuild_menu(self):
        """Rebuild the tray menu."""
        raise NotImplementedError

    def _on_quit(self, *args):
        """Framework-specific quit handler. Should call self._quit() first."""
        raise NotImplementedError

    def run(self):
        """Bootstrap and start the main loop."""
        raise NotImplementedError
