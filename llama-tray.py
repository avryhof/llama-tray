import json
import shutil
import socket
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageDraw
from huggingface_hub import scan_cache_dir, HfApi
from pystray import Icon, Menu, MenuItem

# ============================================================
# Configuration
# ============================================================

PROFILE_DIR = Path.home()
CONFIG_DIR = PROFILE_DIR / ".local" / "share" / "llama-tray"

BASE_PATH = Path("D:\\", "llama")
ICON_PATH = BASE_PATH / "icons"
CONFIG_FILE = CONFIG_DIR / "settings.json"

LLAMA_EXE = BASE_PATH / "llama-server.exe"

DEFAULT_MODEL = "unsloth/Phi-4-mini-instruct-GGUF:Q4_K_M"

settings = {
    "selected_model": DEFAULT_MODEL,
    "host": "127.0.0.1",
    "port": 8081,
    "ngl": 99,
    "context_size": 16384,
    "flash_attention": True,
    "hf_token": ""
}

llama_process = None


# ============================================================
# Settings
# ============================================================


def load_settings():
    global settings

    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir()

    if not CONFIG_FILE.exists() and (BASE_PATH / "settings.json").exists():
        shutil.move(BASE_PATH / "settings.json", CONFIG_FILE)

    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text())
            settings.update(loaded)
        except Exception as e:
            print(f"Failed to load settings: {e}")


def save_settings():
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir()

    try:
        CONFIG_FILE.write_text(json.dumps(settings, indent=4))
    except Exception as e:
        print(f"Failed to save settings: {e}")


load_settings()


# ============================================================
# Helpers
# ============================================================


def get_hf_api():
    token = settings.get("hf_token", "").strip()

    if token:
        api = HfApi(token=token)
    else:
        api = HfApi()

    return api


def build_hf_model_string(repo, filename):
    stem = Path(filename).stem

    quant = stem.split("-")[-1]

    return f"{repo}:{quant}"


def get_selected_model():
    return settings["selected_model"]


def is_port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return (
                s.connect_ex(
                    (
                        settings["host"],
                        int(settings["port"])
                    )
                )
                == 0
        )


def is_llama_running():
    return llama_process is not None or is_port_open()


def get_status_icon_path():
    return ICON_PATH / ("stop.png" if is_llama_running() else "start.png")


def update_status(icon=None):
    if icon is None:
        return

    icon.icon = Image.open(get_status_icon_path())

    icon.title = (
        f"LLaMA Server "
        f"({'Running' if is_llama_running() else 'Stopped'}) "
        f"- {get_selected_model()}"
    )

    icon.update_menu()


# ============================================================
# HF Search
# ============================================================


def query_hf_models(query, limit=50):
    api = get_hf_api()

    models = api.list_models(
        search=query,
        filter="gguf",
        limit=limit
    )

    return [
        model.id
        for model in models
    ]


# ============================================================
# Local Models
# ============================================================


LOCAL_MODEL_DIRS = [
    Path.home() / ".cache" / "llama.cpp",
    Path.home() / "AppData" / "Local" / "llama.cpp",
    BASE_PATH / "models",
]


def get_local_models():
    models = []

    try:
        cache_info = scan_cache_dir()

        for repo in cache_info.repos:

            if repo.repo_type != "model":
                continue

            ggufs = []

            for revision in repo.revisions:

                if not revision.files:
                    continue

                for file in revision.files:

                    path = getattr(file, "file_name", "")

                    if path.lower().endswith(".gguf"):
                        ggufs.append(path)

            if ggufs:

                for gguf in sorted(ggufs):
                    models.append(build_hf_model_string(repo.repo_id, gguf))

            else:

                models.append(repo.repo_id)

    except Exception as exc:
        print(exc)

    return sorted(models)


# ============================================================
# Model Selection
# ============================================================


def select_hf_model(icon, item):
    def run_window():
        root = tk.Tk()
        root.title("Select Model")
        root.geometry("900x600")

        current = tk.Label(
            root,
            text=f"Current Model: {get_selected_model()}",
            anchor="w"
        )
        current.pack(fill="x", padx=10, pady=(10, 0))

        search_frame = tk.Frame(root)
        search_frame.pack(fill="x", padx=10)

        tk.Label(
            search_frame,
            text="Search Hugging Face:"
        ).pack(side="left")

        query_var = tk.StringVar(
            value=get_selected_model()
        )

        tk.Entry(
            search_frame,
            textvariable=query_var,
            width=50
        ).pack(side="left", padx=5)

        content = tk.PanedWindow(
            root,
            orient=tk.VERTICAL
        )
        content.pack(fill="both", expand=True)

        # Local Models

        local_frame = tk.LabelFrame(
            content,
            text="Local GGUF Models"
        )

        local_list = tk.Listbox(local_frame)

        local_scroll = tk.Scrollbar(
            local_frame,
            command=local_list.yview
        )

        local_list.configure(
            yscrollcommand=local_scroll.set
        )

        local_scroll.pack(side="right", fill="y")
        local_list.pack(fill="both", expand=True)

        content.add(local_frame)

        for model in get_local_models():
            local_list.insert(tk.END, model)

        # HF Models

        hf_frame = tk.LabelFrame(
            content,
            text="Hugging Face Search Results"
        )

        hf_list = tk.Listbox(hf_frame)

        hf_scroll = tk.Scrollbar(
            hf_frame,
            command=hf_list.yview
        )

        hf_list.configure(
            yscrollcommand=hf_scroll.set
        )

        hf_scroll.pack(side="right", fill="y")
        hf_list.pack(fill="both", expand=True)

        content.add(hf_frame)

        status_var = tk.StringVar(
            value="Ready."
        )

        tk.Label(
            root,
            textvariable=status_var
        ).pack(fill="x", padx=10)

        def do_search():

            query = query_var.get().strip()

            if not query:
                return

            status_var.set("Searching...")

            def search_worker():

                try:
                    results = query_hf_models(query)

                    def finish():

                        hf_list.delete(0, tk.END)

                        for model_id in results:
                            hf_list.insert(tk.END, model_id)

                        status_var.set(
                            f"Found {len(results)} models."
                        )

                    root.after(0, finish)

                except Exception as exc:

                    def fail():

                        error_text = str(exc)

                        def fail():
                            messagebox.showerror(
                                "Search Failed",
                                error_text
                            )

                            status_var.set(
                                "Search failed."
                            )

                        root.after(0, fail)

            threading.Thread(
                target=search_worker,
                daemon=True
            ).start()

        def choose_model():

            local_selection = local_list.curselection()
            hf_selection = hf_list.curselection()

            if local_selection:
                model = local_list.get(
                    local_selection[0]
                )

            elif hf_selection:
                model = hf_list.get(
                    hf_selection[0]
                )

            else:
                messagebox.showwarning(
                    "Select Model",
                    "Choose a model first."
                )
                return

            settings["selected_model"] = model
            save_settings()

            update_status(icon)

            root.destroy()

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", padx=10, pady=10)

        tk.Button(
            button_frame,
            text="Search",
            command=do_search
        ).pack(side="left")

        tk.Button(
            button_frame,
            text="Select",
            command=choose_model
        ).pack(side="right")

        tk.Button(
            button_frame,
            text="Cancel",
            command=root.destroy
        ).pack(side="right", padx=5)

        root.mainloop()

    threading.Thread(
        target=run_window,
        daemon=True
    ).start()


# ============================================================
# Settings Window
# ============================================================


def show_settings(icon, item):
    def run_window():

        root = tk.Tk()
        root.title("LLaMA Settings")
        root.geometry("450x250")

        host_var = tk.StringVar(
            value=settings["host"]
        )

        port_var = tk.StringVar(
            value=str(settings["port"])
        )

        ngl_var = tk.StringVar(
            value=str(settings["ngl"])
        )

        ctx_var = tk.StringVar(
            value=str(settings["context_size"])
        )

        fa_var = tk.BooleanVar(
            value=settings["flash_attention"]
        )

        fields = [
            ("Host", host_var),
            ("Port", port_var),
            ("GPU Layers (-ngl)", ngl_var),
            ("Context Size (-c)", ctx_var),
        ]

        row = 0

        for label, var in fields:
            tk.Label(
                root,
                text=label
            ).grid(
                row=row,
                column=0,
                sticky="w",
                padx=10,
                pady=5
            )

            tk.Entry(
                root,
                textvariable=var,
                width=25
            ).grid(
                row=row,
                column=1,
                padx=10
            )

            row += 1

        tk.Checkbutton(
            root,
            text="Enable Flash Attention",
            variable=fa_var
        ).grid(
            row=row,
            column=0,
            columnspan=2,
            padx=10,
            pady=10,
            sticky="w"
        )

        tk.Label(root, text="HF Token").grid(
            row=row,
            column=0,
            sticky="w"
        )

        token_var = tk.StringVar(
            value=settings["hf_token"]
        )

        tk.Entry(
            root,
            textvariable=token_var,
            show="*",
            width=40
        ).grid(
            row=row,
            column=1
        )

        def save():

            try:
                settings["host"] = host_var.get()
                settings["port"] = int(port_var.get())
                settings["ngl"] = int(ngl_var.get())
                settings["context_size"] = int(ctx_var.get())
                settings["flash_attention"] = fa_var.get()
                settings["hf_token"] = token_var.get().strip()

                save_settings()

                root.destroy()

            except ValueError:
                messagebox.showerror(
                    "Invalid Value",
                    "Port, ngl and context size must be numeric."
                )

        tk.Button(
            root,
            text="Save",
            command=save
        ).grid(
            row=row + 1,
            column=0,
            columnspan=2,
            pady=10
        )

        root.mainloop()

    threading.Thread(
        target=run_window,
        daemon=True
    ).start()


# ============================================================
# Tray Icons
# ============================================================

size = 256


def save_icon(name, draw_fn):
    img = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    draw_fn(draw)

    img.save(
        f"{ICON_PATH / name}.png"
    )


def draw_play(draw):
    draw.polygon(
        [
            (80, 60),
            (80, 196),
            (196, 128)
        ],
        fill=(255, 255, 255, 255)
    )


def draw_stop(draw):
    draw.rectangle(
        [
            (72, 72),
            (184, 184)
        ],
        fill=(255, 255, 255, 255)
    )


# ============================================================
# LLaMA Control
# ============================================================


def start_llama(icon, item):
    global llama_process

    if is_llama_running():
        return

    try:

        cmd = [
            str(LLAMA_EXE),
            "-hf",
            get_selected_model(),
            "--host",
            settings["host"],
            "--port",
            str(settings["port"]),
            "-ngl",
            str(settings["ngl"]),
            "-c",
            str(settings["context_size"]),
        ]

        if settings["flash_attention"]:
            cmd.extend([
                "-fa",
                "on"
            ])

        print("Launching:")
        print(" ".join(cmd))

        llama_process = subprocess.Popen(cmd)

    except Exception as exc:
        print(exc)

    update_status(icon)


def stop_llama(icon, item):
    global llama_process

    if llama_process is None:
        update_status(icon)
        return

    try:
        llama_process.terminate()
        llama_process = None
    except Exception as e:
        print(e)

    update_status(icon)


def toggle_llama(icon, item):
    if is_llama_running():
        stop_llama(icon, item)
    else:
        start_llama(icon, item)


def on_exit(icon, item):
    stop_llama(icon, item)
    icon.stop()


# ============================================================
# Menu
# ============================================================


def get_menu_items():
    label = (
        "Stop LLaMA Server"
        if is_llama_running()
        else "Start LLaMA Server"
    )

    return (
        MenuItem(
            label,
            toggle_llama,
            default=True
        ),
        MenuItem(
            "Select Model",
            select_hf_model
        ),
        MenuItem(
            "Settings",
            show_settings
        ),
        MenuItem(
            "Exit",
            on_exit
        ),
    )


def create_icon():
    return Image.open(
        get_status_icon_path()
    )


# ============================================================
# Startup
# ============================================================

ICON_PATH.mkdir(
    parents=True,
    exist_ok=True
)

if not (ICON_PATH / "start.png").exists():
    save_icon("start", draw_play)

if not (ICON_PATH / "stop.png").exists():
    save_icon("stop", draw_stop)

menu = Menu(get_menu_items)

icon = Icon(
    "llama_tray",
    create_icon(),
    "LLaMA Server",
    menu
)

update_status(icon)

if __name__ == "__main__":
    icon.run()
