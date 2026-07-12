"""
tray_pystray.py — Cross-platform system tray using pystray.

Works on Windows, macOS, and Linux (fallback when GTK3 is unavailable).
"""

from PIL import Image
from pystray import Icon, Menu, MenuItem

from tray_base import (
    LlamaTrayApp,
    APP_NAME,
    APP_ID,
    VERSION,
    make_icon_file,
    ICON_COLOURS,
)
from utility_functions import State, state_manager, build_server_label


class LlamaTrayPystray(LlamaTrayApp):

    def __init__(self):
        super().__init__()
        self._icon: Icon | None = None

    # ── State management ──────────────────────────────────────────────────

    def _set_state(self, server_id: str, state: str):
        state_manager.set_state(server_id, state)
        if self._icon:
            # Use the most "urgent" state for the tray icon
            priority = [State.ERROR, State.STARTING, State.RUNNING, State.STOPPED]
            worst = State.STOPPED
            for s in state_manager.all_states().values():
                if priority.index(s) < priority.index(worst):
                    worst = s
            self._icon.icon = Image.open(make_icon_file(worst))
            self._icon.title = f"{APP_NAME} ({worst.title()})"
            self._rebuild_menu()

    # ── Menu construction ─────────────────────────────────────────────────

    def _rebuild_menu(self):
        if not self._icon:
            return

        items = [
            MenuItem(f"{APP_NAME} v{VERSION}", None, enabled=False),
            Menu.SEPARATOR,
        ]

        # Per-server entries
        for srv in self.config.servers():
            sid = srv["id"]
            state = self._server_state(sid)
            state_icon = {
                State.RUNNING: "●",
                State.STARTING: "◌",
                State.ERROR: "!",
                State.STOPPED: "○",
            }.get(state, "?")

            # Server header
            items.append(
                MenuItem(
                    f"{state_icon}  {build_server_label(srv)}",
                    None,
                    enabled=False,
                )
            )
            items.append(
                MenuItem(
                    f"    Model: {self._model_name(srv)}",
                    None,
                    enabled=False,
                )
            )

            # Server actions
            if srv.get("is_local"):
                if state == State.STARTING:
                    items.append(MenuItem("    Starting…", None, enabled=False))
                elif state == State.RUNNING:
                    items.append(
                        MenuItem(
                            "    ⏹  Stop",
                            lambda icon, item, id=sid: self._on_stop(id),
                        )
                    )
                else:
                    items.append(
                        MenuItem(
                            "    ▶  Start",
                            lambda icon, item, id=sid: self._on_start(id),
                        )
                    )
                items.append(
                    MenuItem(
                        "    ↺  Restart",
                        lambda icon, item, id=sid: self._on_restart(id),
                        enabled=state != State.STOPPED,
                    )
                )
            else:
                # Remote server — check status + model list
                if state == State.RUNNING:
                    items.append(MenuItem("    Online", None, enabled=False))
                elif state == State.STARTING:
                    items.append(MenuItem("    Checking…", None, enabled=False))
                elif state == State.ERROR:
                    items.append(MenuItem("    Offline (error)", None, enabled=False))
                else:
                    items.append(MenuItem("    Offline", None, enabled=False))
                items.append(
                    MenuItem(
                        "    ↻  Check",
                        lambda icon, item, id=sid: self._on_check_remote(id),
                        enabled=state in (State.STOPPED, State.ERROR),
                    )
                )

            items.append(
                MenuItem(
                    "    🌐  Open Web UI",
                    lambda icon, item, id=sid: self._on_open_webui(id),
                    enabled=state == State.RUNNING,
                )
            )
            items.append(Menu.SEPARATOR)

        # Global actions
        items.append(MenuItem("📋  View Logs", self._on_open_logs))
        items.append(MenuItem("📦  Model Manager", self._on_model_manager))
        items.append(MenuItem("💬  Chat", self._on_chat))
        items.append(MenuItem("🖥  GPU Monitor", self._on_nvidia))
        items.append(Menu.SEPARATOR)

        # Tool badges
        for tool, label in [("opencode", "opencode"), ("llmfit", "llmfit"), ("vscode", "VS Code")]:
            found = self._tools.get(tool)
            mark = "●" if found else "○"
            items.append(MenuItem(f"{mark}  {label}", None, enabled=False))

        items.append(Menu.SEPARATOR)
        items.append(MenuItem("⚙  Settings", self._on_settings))
        items.append(MenuItem("Quit", self._on_quit))

        self._icon.menu = Menu(*items)

    # ── Quit handler ──────────────────────────────────────────────────────

    def _on_quit(self, icon, item):
        self._quit()
        icon.stop()

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def run(self):
        self._pre_run()

        self._icon = Icon(
            APP_ID,
            Image.open(make_icon_file(State.STOPPED)),
            APP_NAME,
        )
        self._rebuild_menu()

        self._log(f"{APP_NAME} v{VERSION} started (pystray).")
        self._icon.run()
