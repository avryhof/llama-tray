"""
tray_gtk.py — Linux system tray using GTK3 + AppIndicator3.

Requirements:
    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
    pip install pillow
"""

import signal
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")

from gi.repository import Gtk, GLib, AppIndicator3

from tray_base import (
    LlamaTrayApp, State, APP_NAME, APP_ID, VERSION,
    make_icon_file, ICON_COLOURS,
)


class LlamaTrayGTK(LlamaTrayApp):

    def __init__(self):
        super().__init__()
        self._indicator = None
        self._menu = None

    # ── Thread-safe state update (schedules on GTK main loop) ─────────────

    def _notify_state(self, server_id: str, state: str):
        GLib.idle_add(self._set_state, server_id, state)

    # ── State management (called on GTK thread) ───────────────────────────

    def _set_state(self, server_id: str, state: str):
        with self._lock:
            self.states[server_id] = state
        # Use the most "urgent" state for the tray icon
        self._update_tray_icon()
        self._rebuild_menu()

    def _update_tray_icon(self):
        """Set tray icon to the most urgent server state."""
        priority = [State.ERROR, State.STARTING, State.RUNNING, State.STOPPED]
        worst = State.STOPPED
        for state in self.states.values():
            if priority.index(state) < priority.index(worst):
                worst = state
        if self._indicator:
            self._indicator.set_icon_full(make_icon_file(worst), worst)

    # ── Menu construction ─────────────────────────────────────────────────

    def _rebuild_menu(self):
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

        # Header
        mi(f"{APP_NAME} v{VERSION}", enabled=False)
        sep()

        # Per-server submenus
        servers = self.config.servers()
        for srv in servers:
            sid = srv["id"]
            state = self._server_state(sid)
            state_icon = {
                State.RUNNING: "●",
                State.STARTING: "◌",
                State.ERROR: "!",
                State.STOPPED: "○",
            }.get(state, "?")

            # Server header (non-clickable)
            label = f"{state_icon}  {self._server_label(srv)}"
            mi(label, enabled=False)
            mi(f"    Model: {self._model_name(srv)}", enabled=False)

            # Submenu items
            if srv.get("is_local"):
                if state == State.STARTING:
                    mi("    Starting…", enabled=False)
                elif state == State.RUNNING:
                    mi("    ⏹  Stop", lambda _, id=sid: self._on_stop(id))
                else:
                    mi("    ▶  Start", lambda _, id=sid: self._on_start(id))
                mi("    ↺  Restart", lambda _, id=sid: self._on_restart(id),
                   enabled=state != State.STOPPED)
            else:
                # Remote server — check status + model list
                if state == State.RUNNING:
                    mi("    Online", enabled=False)
                elif state == State.STARTING:
                    mi("    Checking…", enabled=False)
                elif state == State.ERROR:
                    mi("    Offline (error)", enabled=False)
                else:
                    mi("    Offline", enabled=False)
                mi("    ↻  Check", lambda _, id=sid: self._on_check_remote(id),
                   enabled=state in (State.STOPPED, State.ERROR))

            mi("    🌐  Open Web UI", lambda _, id=sid: self._on_open_webui(id),
               enabled=state == State.RUNNING)

            sep()

        # Global actions
        mi("📋  View Logs", self._on_open_logs)
        mi("📦  Model Manager", self._on_model_manager)
        mi("💬  Chat", self._on_chat)
        mi("🖥️   GPU Monitor", self._on_nvidia)
        sep()

        # Tool status badges
        for tool, label in [("opencode", "opencode"), ("llmfit", "llmfit"), ("vscode", "VS Code")]:
            found = self._tools.get(tool)
            mi(("🟢" if found else "⚪") + f"  {label}", enabled=False)

        sep()
        mi("⚙️   Settings", self._on_settings)
        sep()
        mi("Quit", self._on_quit)

        menu.show_all()
        self._indicator.set_menu(menu)
        self._menu = menu

    # ── Quit handler ──────────────────────────────────────────────────────

    def _on_quit(self, _):
        self._quit()
        Gtk.main_quit()

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def run(self):
        self._pre_run()

        self._indicator = AppIndicator3.Indicator.new(
            APP_ID,
            make_icon_file(State.STOPPED),
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title(APP_NAME)

        self._rebuild_menu()

        self._log(f"{APP_NAME} v{VERSION} started (GTK3).")
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        Gtk.main()
