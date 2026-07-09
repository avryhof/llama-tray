#!/usr/bin/env python3
"""
llama_tray.py — System tray applet for llama.cpp server management.
Linux only. Uses GTK3 + AppIndicator3 directly (no pystray).

Requirements:
    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
    pip install pillow
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")

from gi.repository import Gtk, GLib, AppIndicator3

import os
import sys
import signal
import threading
import subprocess
import time
import tempfile
import webbrowser
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw

# ── Verify imports work before going further ─────────────────────────────────
try:
    from config import Config
    from tool_detect import detect_tools
    from model_manager import show_model_manager
    from nvidia_window import show_nvidia_window
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure config.py and hf_browser.py are in the same directory.")
    sys.exit(1)

APP_NAME  = "llama.cpp Server"
APP_ID    = "llama-tray"
VERSION   = "1.0.0"


# ── Icon generation ──────────────────────────────────────────────────────────

_ICON_COLOURS = {
    "stopped":  "#6c757d",
    "starting": "#fd7e14",
    "running":  "#28a745",
    "error":    "#dc3545",
}

_icon_tmp_files: dict[str, str] = {}   # state → tmp PNG path


def _make_icon_file(state: str) -> str:
    """Render a coloured circle+L icon to a temp PNG and return its path."""
    if state in _icon_tmp_files:
        return _icon_tmp_files[state]

    colour = _ICON_COLOURS[state]
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=colour, outline="#ffffff", width=2)
    fs = int(size * 0.55)
    x, y = int(size * 0.28), int(size * 0.18)
    sw = max(2, size // 20)
    d.rectangle([x, y, x + sw, y + fs], fill="#ffffff")
    d.rectangle([x, y + fs - sw, x + fs // 2 + sw, y + fs], fill="#ffffff")

    tmp = tempfile.NamedTemporaryFile(suffix=f"_{state}.png", delete=False)
    img.save(tmp.name, "PNG")
    _icon_tmp_files[state] = tmp.name
    return tmp.name


# ── Server state ─────────────────────────────────────────────────────────────

class State:
    STOPPED  = "stopped"
    STARTING = "starting"
    RUNNING  = "running"
    ERROR    = "error"


# ── Main application ─────────────────────────────────────────────────────────

class LlamaTrayApp:

    def __init__(self):
        self.config       = Config()
        self.server_proc  = None
        self.state        = State.STOPPED
        self.log_lines: list[str] = []
        self._lock        = threading.Lock()
        self._indicator   = None
        self._menu        = None
        self._tools       = {}   # populated in run()

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-200:]
        print(line, flush=True)

    # ── State changes (always called from GTK main thread via GLib.idle_add) ─

    def _set_state(self, state: str):
        """Update state + icon + menu.  Must be called on the GTK thread."""
        with self._lock:
            self.state = state
        if self._indicator:
            self._indicator.set_icon_full(_make_icon_file(state), state)
        self._rebuild_menu()

    def _set_state_idle(self, state: str):
        """Thread-safe wrapper: schedules _set_state on the GTK main loop."""
        GLib.idle_add(self._set_state, state)

    # ── Menu construction ─────────────────────────────────────────────────────

    def _rebuild_menu(self):
        """Build and attach a fresh Gtk.Menu to the indicator."""
        is_running = self.state == State.RUNNING
        is_stopped = self.state == State.STOPPED
        model_name = self._model_name()

        menu = Gtk.Menu()

        def mi(label, handler=None, enabled=True):
            it = Gtk.MenuItem(label=label)
            if handler:
                it.connect("activate", handler)
            it.set_sensitive(enabled)
            menu.append(it)
            return it

        def sep():
            menu.append(Gtk.SeparatorMenuItem())

        mi(f"🦙  {APP_NAME} v{VERSION}", enabled=False)
        sep()
        mi(f"Status : {self.state.capitalize()}", enabled=False)
        mi(f"Model  : {model_name}",              enabled=False)
        sep()
        mi("▶  Start Server",   self._on_start,   enabled=is_stopped)
        mi("⏹  Stop Server",    self._on_stop,    enabled=is_running)
        mi("↺  Restart Server", self._on_restart, enabled=not is_stopped)
        sep()
        mi("🌐  Open Web UI",              self._on_open_webui,  enabled=is_running)
        mi("📋  View Logs",                self._on_open_logs)
        sep()
        mi("📦  Model Manager", self._on_model_manager)
        mi("🖥️   GPU Monitor",   self._on_nvidia)
        sep()

        # Tool status badges (read-only informational items)
        oc  = self._tools.get("opencode")
        lmf = self._tools.get("llmfit")
        vsc = self._tools.get("vscode")
        mi(("🟢" if oc  else "⚪") + "  opencode",  enabled=False)
        mi(("🟢" if lmf else "⚪") + "  llmfit",    enabled=False)
        mi(("🟢" if vsc else "⚪") + "  VS Code",   enabled=False)
        sep()
        mi("⚙️   Settings", self._on_settings)
        sep()
        mi("Quit", self._on_quit)

        menu.show_all()
        self._indicator.set_menu(menu)
        self._menu = menu   # keep a reference so GTK doesn't GC it

    def _model_name(self) -> str:
        m = self.config.get().get("active_model", "")
        return Path(m).name if m else "No model selected"

    # ── Menu action handlers (called on GTK thread) ───────────────────────────

    def _on_start(self, _):
        if self.state in (State.RUNNING, State.STARTING):
            return
        threading.Thread(target=self._start_thread, daemon=True).start()

    def _on_stop(self, _):
        threading.Thread(target=self._stop_thread, daemon=True).start()

    def _on_restart(self, _):
        def _do():
            self._stop_thread()
            time.sleep(1)
            self._start_thread()
        threading.Thread(target=_do, daemon=True).start()

    def _on_open_webui(self, _):
        cfg = self.config.get()
        webbrowser.open(f"http://{cfg.get('host','127.0.0.1')}:{cfg.get('port',8080)}")

    def _on_open_logs(self, _):
        from log_window import show_log_window
        show_log_window(self.log_lines)

    def _on_settings(self, _):
        from settings_window import show_settings_window
        show_settings_window(self.config, on_save=lambda: GLib.idle_add(self._rebuild_menu))

    def _on_model_manager(self, _):
        show_model_manager(self.config,
                           on_save=lambda: GLib.idle_add(self._rebuild_menu))

    def _on_nvidia(self, _):
        show_nvidia_window()

    def _on_quit(self, _):
        self._log("Quitting…")
        if self.state != State.STOPPED:
            self._stop_thread()
        # Clean up temp icon files
        for p in _icon_tmp_files.values():
            try:
                os.unlink(p)
            except OSError:
                pass
        Gtk.main_quit()

    # ── Server lifecycle (background threads) ─────────────────────────────────

    def _build_cmd(self) -> list[str]:
        cfg = self.config.get()
        cmd = [cfg["llama_server_path"]]
        model = cfg.get("active_model", "")
        if model:
            cmd += ["-m", model]
        cmd += [
            "--host", cfg.get("host", "127.0.0.1"),
            "--port", str(cfg.get("port", 8080)),
            "-c",    str(cfg.get("ctx_size", 4096)),
            "-np",   str(cfg.get("n_parallel", 1)),
            "--log-disable",
        ]
        n_gpu = cfg.get("n_gpu_layers", 0)
        if n_gpu:
            cmd += ["-ngl", str(n_gpu)]
        extra = cfg.get("extra_flags", "").strip()
        if extra:
            cmd += extra.split()
        return cmd

    def _start_thread(self):
        self._set_state_idle(State.STARTING)
        cfg = self.config.get()

        binary = cfg.get("llama_server_path", "")
        if not binary or not Path(binary).is_file():
            self._log(f"ERROR: binary not found: {binary!r}")
            self._log("Open ⚙️ Settings → General to set the correct path.")
            self._set_state_idle(State.ERROR)
            return

        model = cfg.get("active_model", "")
        if model and not Path(model).is_file():
            self._log(f"ERROR: model not found: {model!r}")
            self._set_state_idle(State.ERROR)
            return

        cmd = self._build_cmd()
        self._log("Starting: " + " ".join(cmd))

        try:
            self.server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._log(f"Failed to launch: {e}")
            self._set_state_idle(State.ERROR)
            return

        threading.Thread(target=self._read_output, daemon=True).start()

        host = cfg.get("host", "127.0.0.1")
        port = cfg.get("port", 8080)
        url  = f"http://{host}:{port}/health"

        for _ in range(60):
            time.sleep(0.5)
            if self.server_proc.poll() is not None:
                self._log("Server exited unexpectedly.")
                self._set_state_idle(State.ERROR)
                return
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        self._log(f"Server ready at http://{host}:{port}")
                        self._set_state_idle(State.RUNNING)
                        threading.Thread(target=self._health_monitor,
                                         args=(url,), daemon=True).start()
                        return
            except Exception:
                pass

        self._log("Server did not become healthy within 30 s.")
        self._set_state_idle(State.ERROR)

    def _stop_thread(self):
        proc = self.server_proc
        if not proc:
            self._set_state_idle(State.STOPPED)
            return
        self._log("Stopping server…")
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as e:
            self._log(f"Stop error: {e}")
        finally:
            self.server_proc = None
        self._log("Server stopped.")
        self._set_state_idle(State.STOPPED)

    def _read_output(self):
        if not self.server_proc:
            return
        for line in self.server_proc.stdout:
            self._log(line.rstrip())

    def _health_monitor(self, url: str):
        while True:
            time.sleep(5)
            with self._lock:
                if self.state != State.RUNNING:
                    break
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status != 200:
                        raise ValueError("non-200")
            except Exception:
                with self._lock:
                    if self.state == State.RUNNING:
                        self._log("Health check failed — server may have crashed.")
                        self._set_state_idle(State.ERROR)
                break

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def run(self):
        # Pre-render all icon states so the first show is instant
        for s in _ICON_COLOURS:
            _make_icon_file(s)

        self._indicator = AppIndicator3.Indicator.new(
            APP_ID,
            _make_icon_file(State.STOPPED),
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title(APP_NAME)

        self._rebuild_menu()

        cfg = self.config.get()
        if cfg.get("auto_start"):
            GLib.idle_add(lambda: (
                threading.Thread(target=self._start_thread, daemon=True).start(),
                False   # don't repeat
            ))

        self._log(f"llama.cpp Tray v{VERSION} started.")

        # Detect external tools once at startup (off the GTK thread).
        # Saved config overrides take precedence over auto-detection.
        def _detect_and_refresh():
            detected = detect_tools()
            cfg = self.config.get()
            merged = {}
            for name in ("opencode", "llmfit", "vscode"):
                saved = cfg.get(f"tool_{name}_path", "").strip()
                if saved and Path(saved).exists():
                    merged[name] = saved
                elif detected.get(name):
                    merged[name] = detected[name]
                else:
                    merged[name] = None
            self._tools = merged
            for name, path in merged.items():
                if path:
                    self._log(f"[tools] {name}: {path}")
                else:
                    self._log(f"[tools] {name}: not found")
            GLib.idle_add(self._rebuild_menu)
        threading.Thread(target=_detect_and_refresh, daemon=True).start()

        # Let Ctrl-C work
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        Gtk.main()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = LlamaTrayApp()
    app.run()
