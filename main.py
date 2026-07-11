#!/usr/bin/env python3
"""
main.py — Entry point for the llama.cpp system tray application.

Detects the platform and loads the appropriate backend:
  - Linux with GTK3/AppIndicator3 → tray_gtk (native)
  - Everything else → tray_pystray (cross-platform fallback)
"""

import platform
import sys


def main():
    system = platform.system()

    if system == "Linux":
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import Gtk, AppIndicator3  # noqa: F401
            from tray_gtk import LlamaTrayGTK as App
        except (ImportError, ValueError):
            print("[main] GTK3/AppIndicator3 not available, using pystray fallback.")
            from tray_pystray import LlamaTrayPystray as App
    else:
        from tray_pystray import LlamaTrayPystray as App

    App().run()


if __name__ == "__main__":
    main()
