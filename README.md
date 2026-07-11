# 🦙 llama_tray

A cross-platform system-tray applet for managing your **llama.cpp server**.
Supports macOS, Windows, and Linux.

---

## Features

| Feature | Details |
|---|---|
| ▶ Start / ⏹ Stop / ↺ Restart | One-click server lifecycle |
| 🌐 Open Web UI | Launches your browser to the server's chat UI |
| 📋 View Logs | Scrollable colour-coded log viewer |
| ⚙️ Settings | Full GUI config: binary path, model, host, port, GPU layers, extra flags |
| Auto-start | Optionally start the server when the applet launches |
| Tray icon colours | Grey = stopped, Orange = starting, Green = running, Red = error |

---

## Requirements

- Python 3.10+
- `pillow` (for the tray icon)
- `tkinter` (for Settings and Logs windows — included in most Python installs)
- A compiled **llama-server** binary ([llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases))
- At least one `.gguf` model file

### Platform-specific dependencies

**Linux (recommended):**
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
```

**Windows / macOS / Linux fallback:**
```bash
pip install pystray
```

### Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## Quick Start

```bash
# 1. Install deps
pip install pillow

# 2. Run the applet
python main.py
```

On Linux, the app automatically uses native GTK3/AppIndicator3 if available.
If GTK3 is not installed, it falls back to pystray.

A tray icon appears in your system tray.

**First-time setup:**
1. Right-click the icon → **⚙️ Settings → General**
2. Set the path to your `llama-server` binary
3. Set your active model (`.gguf` file)
4. Click **Save**
5. Right-click → **▶ Start Server**

---

## Configuration

Settings are stored as JSON in a platform-appropriate location:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/llama_tray/config.json` |
| Windows | `%APPDATA%\llama_tray\config.json` |
| Linux | `~/.config/llama_tray/config.json` |

### Available settings

| Key | Default | Description |
|---|---|---|
| `llama_server_path` | auto-detected | Full path to `llama-server` binary |
| `active_model` | `""` | Path to the `.gguf` model to load |
| `models_dir` | `~/models` | Directory where downloaded models are saved |
| `host` | `127.0.0.1` | Bind address for the server |
| `port` | `8080` | Port for the server |
| `ctx_size` | `4096` | Context window size (tokens) |
| `n_parallel` | `1` | Number of parallel inference slots |
| `n_gpu_layers` | `0` | Layers offloaded to GPU (`-ngl`); 0 = CPU only |
| `extra_flags` | `""` | Extra raw CLI flags (e.g. `--threads 8 --mlock`) |
| `hf_token` | `""` | HuggingFace API token (optional) |
| `auto_start` | `false` | Start server automatically when applet launches |

---

## Auto-launch on login

### macOS (launchd)

Create `~/Library/LaunchAgents/com.llama_tray.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.llama_tray</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/llama-tray/main.py</string>
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
```
Then: `launchctl load ~/Library/LaunchAgents/com.llama_tray.plist`

### Windows (Task Scheduler)

Create a task that runs `pythonw.exe main.py` at login.
(`pythonw.exe` suppresses the console window.)

### Linux (autostart)

Create `~/.config/autostart/llama_tray.desktop`:
```ini
[Desktop Entry]
Type=Application
Name=llama.cpp Tray
Exec=python3 /path/to/llama-tray/main.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
```

---

## Architecture

```
main.py            Entry point — detects OS, loads appropriate backend
tray_base.py       Shared logic (server management, config, logging)
tray_gtk.py        Linux/GTK3 implementation (native)
tray_pystray.py    Windows/macOS/Linux fallback (pystray)
config.py          Config persistence
tool_detect.py     Cross-platform tool detection
model_manager.py   Model management GUI
settings_window.py Settings dialog
log_window.py      Log viewer
nvidia_window.py   GPU monitor
```

---

## Troubleshooting

**Icon not showing on Linux (GNOME):**
GNOME 40+ hides tray icons by default. Install the
[AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/).

**"llama-server binary not found":**
Download a release from [github.com/ggerganov/llama.cpp/releases](https://github.com/ggerganov/llama.cpp/releases),
extract it, and set the path in Settings → General.

**Server starts but Web UI is blank:**
Make sure you have a model set. Check the Logs window for details.
