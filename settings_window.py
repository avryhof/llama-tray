"""
settings_window.py — llama_tray settings with multi-server support.
"""

import threading
from pathlib import Path

from config import make_server


def show_settings_window(config, on_save=None):
    threading.Thread(target=_show, args=(config, on_save), daemon=True).start()


def _show(config, on_save):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("tkinter not available")
        return

    cfg = config.get()
    root = tk.Tk()
    root.title("llama.cpp Tray — Settings")
    root.geometry("750x680")
    root.minsize(600, 500)
    root.resizable(True, True)

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=10, pady=10)

    def tab(label):
        f = tk.Frame(nb, padx=16, pady=16)
        nb.add(f, text=label)
        return f

    def lbl(parent, text, row):
        tk.Label(parent, text=text, anchor="w", width=22).grid(
            row=row, column=0, sticky="w", pady=4)

    def entry_row(parent, label, row, default="", width=36):
        lbl(parent, label, row)
        var = tk.StringVar(value=default)
        tk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, sticky="ew", pady=4)
        return var

    def spin_row(parent, label, row, default=0, from_=0, to=99999):
        lbl(parent, label, row)
        var = tk.IntVar(value=default)
        tk.Spinbox(parent, textvariable=var, from_=from_, to=to, width=10).grid(
            row=row, column=1, sticky="w", pady=4)
        return var

    def bool_row(parent, label, row, default=False):
        lbl(parent, label, row)
        var = tk.BooleanVar(value=default)
        tk.Checkbutton(parent, variable=var).grid(row=row, column=1, sticky="w", pady=4)
        return var

    def file_row(parent, label, row, default="", filetypes=None):
        lbl(parent, label, row)
        var = tk.StringVar(value=default)
        frm = tk.Frame(parent)
        frm.grid(row=row, column=1, sticky="ew", pady=4)
        tk.Entry(frm, textvariable=var, width=28).pack(side="left", fill="x", expand=True)
        def browse():
            kw = {"initialdir": str(Path(var.get()).parent) if var.get() else str(Path.home())}
            if filetypes:
                kw["filetypes"] = filetypes
            p = filedialog.askopenfilename(**kw)
            if p:
                var.set(p)
        ttk.Button(frm, text="…", command=browse, width=3).pack(side="left", padx=2)
        return var

    def dir_row(parent, label, row, default=""):
        lbl(parent, label, row)
        var = tk.StringVar(value=default)
        frm = tk.Frame(parent)
        frm.grid(row=row, column=1, sticky="ew", pady=4)
        tk.Entry(frm, textvariable=var, width=28).pack(side="left", fill="x", expand=True)
        def browse():
            d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
            if d:
                var.set(d)
        ttk.Button(frm, text="…", command=browse, width=3).pack(side="left", padx=2)
        return var

    def masked_row(parent, label, row, default="", width=28):
        """Entry with show/hide toggle for passwords/tokens."""
        lbl(parent, label, row)
        var = tk.StringVar(value=default)
        frm = tk.Frame(parent)
        frm.grid(row=row, column=1, sticky="ew", pady=4)
        entry = tk.Entry(frm, textvariable=var, width=width, show="*")
        entry.pack(side="left", fill="x", expand=True)
        visible = [False]
        def toggle():
            visible[0] = not visible[0]
            entry.config(show="" if visible[0] else "*")
            toggle_btn.config(text="🙈" if visible[0] else "👁")
        toggle_btn = tk.Button(frm, text="👁", command=toggle, width=2,
                               relief="flat", font=("Helvetica", 10))
        toggle_btn.pack(side="left", padx=2)
        return var

    # ── General tab ──────────────────────────────────────────────────────────
    t1 = tab("General")
    t1.columnconfigure(1, weight=1)

    v_models_dir = dir_row(t1, "Models directory", 0, default=cfg.get("models_dir", ""))

    tk.Label(t1, text="HuggingFace", font=("Helvetica", 9, "bold"),
             anchor="w").grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
    lbl(t1, "HF Access Token", 2)
    v_hf_tok = masked_row(t1, "", 2, default=cfg.get("hf_token", ""))
    tk.Label(t1, text="Optional — needed for gated HuggingFace models",
             fg="#888", font=("Helvetica", 8)).grid(row=3, column=1, sticky="w")

    tk.Label(t1, text="Config file:", anchor="w", fg="#777").grid(
        row=4, column=0, sticky="w", pady=(16, 0))
    tk.Label(t1, text=str(config.config_file), anchor="w", fg="#555",
             wraplength=400, justify="left").grid(row=4, column=1, sticky="w", pady=(16, 0))

    # ── Servers tab ──────────────────────────────────────────────────────────
    t2 = tab("Servers")

    # Left side: server list + buttons
    list_frame = tk.Frame(t2)
    list_frame.pack(side="left", fill="y", padx=(0, 10))

    tk.Label(list_frame, text="Servers:", font=("Helvetica", 9, "bold")).pack(anchor="w")

    listbox = tk.Listbox(list_frame, width=22, height=12)
    listbox.pack(fill="both", expand=True)

    btn_frm = tk.Frame(list_frame)
    btn_frm.pack(fill="x", pady=(4, 0))

    # Right side: selected server's settings (scrollable)
    detail_canvas = tk.Canvas(t2, highlightthickness=0)
    detail_scrollbar = ttk.Scrollbar(t2, orient="vertical", command=detail_canvas.yview)
    detail_frame = tk.Frame(detail_canvas)
    detail_frame.bind("<Configure>", lambda e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
    detail_canvas.create_window((0, 0), window=detail_frame, anchor="nw")
    detail_canvas.configure(yscrollcommand=detail_scrollbar.set)

    detail_scrollbar.pack(side="right", fill="y")
    detail_canvas.pack(side="right", fill="both", expand=True)

    # Enable mouse wheel scrolling on the detail canvas
    def _on_detail_mousewheel(event):
        detail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _on_detail_mousewheel_linux(event):
        if event.num == 4:
            detail_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            detail_canvas.yview_scroll(1, "units")
    detail_canvas.bind("<MouseWheel>", _on_detail_mousewheel)
    detail_canvas.bind("<Button-4>", _on_detail_mousewheel_linux)
    detail_canvas.bind("<Button-5>", _on_detail_mousewheel_linux)
    detail_frame.bind("<MouseWheel>", _on_detail_mousewheel)
    detail_frame.bind("<Button-4>", _on_detail_mousewheel_linux)
    detail_frame.bind("<Button-5>", _on_detail_mousewheel_linux)

    detail_frame.columnconfigure(1, weight=1)

    # State for current edits
    servers_copy = [dict(s) for s in config.servers()]
    selected_idx = [None]  # mutable container for closure

    def refresh_listbox():
        listbox.delete(0, tk.END)
        for s in servers_copy:
            marker = "🟢" if s.get("is_local") else "🔵"
            listbox.insert(tk.END, f"{marker} {s['name']}")

    def show_server(idx):
        """Populate detail_frame with server at index."""
        selected_idx[0] = idx
        for w in detail_frame.winfo_children():
            widget = w
            widget.destroy()

        if idx is None or idx >= len(servers_copy):
            tk.Label(detail_frame, text="Select a server to edit.",
                     fg="#888").pack(anchor="w")
            return

        srv = servers_copy[idx]
        detail_frame.columnconfigure(1, weight=1)

        def er(label, row, default="", width=30):
            tk.Label(detail_frame, text=label, anchor="w", width=18).grid(
                row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=default)
            tk.Entry(detail_frame, textvariable=var, width=width).grid(
                row=row, column=1, sticky="ew", pady=3)
            return var

        def sr(label, row, default=0, from_=0, to=99999):
            tk.Label(detail_frame, text=label, anchor="w", width=18).grid(
                row=row, column=0, sticky="w", pady=3)
            var = tk.IntVar(value=default)
            tk.Spinbox(detail_frame, textvariable=var, from_=from_, to=to, width=8).grid(
                row=row, column=1, sticky="w", pady=3)
            return var

        v_name      = er("Name",          0, srv.get("name", "Server"))
        v_host      = er("Host",          1, srv.get("host", "127.0.0.1"), width=20)
        v_port      = sr("Port",          2, srv.get("port", 8080), from_=1, to=65535)
        v_url       = er("URL",           3, srv.get("url", ""), width=30)
        tk.Label(detail_frame, text="e.g. https://llama.example.com/ (remote only)",
                 fg="#888", font=("Helvetica", 8)).grid(row=3, column=1, sticky="w")
        v_local     = tk.BooleanVar(value=srv.get("is_local", True))
        tk.Label(detail_frame, text="Local (can start/stop)", anchor="w",
                 width=18).grid(row=4, column=0, sticky="w", pady=3)
        tk.Checkbutton(detail_frame, variable=v_local).grid(
            row=4, column=1, sticky="w", pady=3)

        tk.Label(detail_frame, text="─" * 40, fg="#ccc").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=4)

        v_binary = tk.StringVar(value=srv.get("llama_server_path", ""))
        tk.Label(detail_frame, text="Server binary", anchor="w",
                 width=18).grid(row=6, column=0, sticky="w", pady=3)
        bf = tk.Frame(detail_frame)
        bf.grid(row=6, column=1, sticky="ew", pady=3)
        tk.Entry(bf, textvariable=v_binary, width=22).pack(side="left", fill="x", expand=True)
        def browse_binary():
            p = filedialog.askopenfilename(
                initialdir=str(Path(v_binary.get()).parent) if v_binary.get() else str(Path.home()),
                filetypes=[("All files", "*")])
            if p:
                v_binary.set(p)
        ttk.Button(bf, text="…", command=browse_binary, width=3).pack(side="left", padx=2)

        v_model = tk.StringVar(value=srv.get("active_model", ""))
        tk.Label(detail_frame, text="Active model", anchor="w",
                 width=18).grid(row=7, column=0, sticky="w", pady=3)
        mf = tk.Frame(detail_frame)
        mf.grid(row=7, column=1, sticky="ew", pady=3)

        if srv.get("is_local"):
            # Local server — file picker for GGUF files
            tk.Entry(mf, textvariable=v_model, width=22).pack(side="left", fill="x", expand=True)
            def browse_model():
                p = filedialog.askopenfilename(
                    initialdir=str(Path(v_model.get()).parent) if v_model.get() else str(Path.home()),
                    filetypes=[("GGUF", "*.gguf"), ("All files", "*")])
                if p:
                    v_model.set(p)
            ttk.Button(mf, text="…", command=browse_model, width=3).pack(side="left", padx=2)
        else:
            # Remote server — dropdown populated from GET /v1/models
            v_model_cb = ttk.Combobox(mf, textvariable=v_model, width=30, state="readonly")
            v_model_cb.pack(side="left", fill="x", expand=True)

            def _build_base_url():
                """Build base URL from URL field or host:port."""
                url_val = v_url.get().strip()
                if url_val:
                    # Normalize: ensure it has a scheme
                    if not url_val.startswith(("http://", "https://")):
                        url_val = "http://" + url_val
                    # Remove trailing slash for consistency
                    return url_val.rstrip("/")
                else:
                    host = v_host.get().strip() or "127.0.0.1"
                    port = int(v_port.get()) if v_port.get() else 8080
                    return f"http://{host}:{port}"

            def _fetch_remote_models():
                """Query the remote server for available models."""
                base = _build_base_url()
                api_key = v_apikey.get().strip()
                url = f"{base}/v1/models"
                import urllib.request, urllib.error, json as _json
                def _do():
                    models = []
                    try:
                        headers = {}
                        if api_key:
                            headers["Authorization"] = f"Bearer {api_key}"
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, timeout=5) as r:
                            data = _json.loads(r.read().decode())
                            for m in data.get("data", []):
                                mid = m.get("id", "")
                                if mid:
                                    models.append(mid)
                    except Exception:
                        pass
                    def _upd():
                        v_model_cb["values"] = models
                        if models and v_model.get() not in models:
                            v_model.set(models[0])
                        elif not models and v_model.get():
                            v_model_cb["values"] = [v_model.get()]
                    try:
                        root.after(0, _upd)
                    except Exception:
                        pass
                threading.Thread(target=_do, daemon=True).start()

            ttk.Button(mf, text="↻", command=_fetch_remote_models, width=3).pack(side="left", padx=2)
            # Auto-fetch on first show
            root.after(100, _fetch_remote_models)

        v_ctx      = sr("Context size",   8, srv.get("ctx_size", 4096), from_=512, to=131072)
        v_parallel = sr("Parallel slots", 9, srv.get("n_parallel", 1), from_=1, to=32)
        v_gpu      = sr("GPU layers",    10, srv.get("n_gpu_layers", 0), from_=0, to=99)

        tk.Label(detail_frame, text="Extra CLI flags", anchor="w",
                 width=18).grid(row=11, column=0, sticky="w", pady=3)
        v_extra = tk.StringVar(value=srv.get("extra_flags", ""))
        tk.Entry(detail_frame, textvariable=v_extra, width=30).grid(
            row=11, column=1, sticky="ew", pady=3)
        tk.Label(detail_frame, text="e.g. --threads 8 --mlock",
                 fg="#888", font=("Helvetica", 8)).grid(row=12, column=1, sticky="w")

        v_autostart = tk.BooleanVar(value=srv.get("auto_start", False))
        tk.Label(detail_frame, text="Auto-start", anchor="w",
                 width=18).grid(row=13, column=0, sticky="w", pady=3)
        tk.Checkbutton(detail_frame, variable=v_autostart).grid(
            row=13, column=1, sticky="w", pady=3)

        # ── API Key ───────────────────────────────────────────────────────
        lbl(detail_frame, "API key", 14)
        v_apikey = tk.StringVar(value=srv.get("api_key", ""))
        akf = tk.Frame(detail_frame)
        akf.grid(row=14, column=1, sticky="ew", pady=3)
        akf.columnconfigure(0, weight=1)
        ak_entry = tk.Entry(akf, textvariable=v_apikey, show="*")
        ak_entry.grid(row=0, column=0, sticky="ew")
        ak_visible = [False]
        def toggle_ak():
            ak_visible[0] = not ak_visible[0]
            ak_entry.config(show="" if ak_visible[0] else "*")
            ak_toggle.config(text="🙈" if ak_visible[0] else "👁")
        ak_toggle = tk.Button(akf, text="👁", command=toggle_ak, width=2,
                               relief="flat", font=("Helvetica", 10))
        ak_toggle.grid(row=0, column=1, padx=2)
        tk.Label(detail_frame, text="Used for server auth + tool configs",
                 fg="#888", font=("Helvetica", 8)).grid(row=15, column=1, sticky="w")

        # ── Custom Headers ────────────────────────────────────────────────
        tk.Label(detail_frame, text="Custom headers", anchor="w",
                 width=18).grid(row=16, column=0, sticky="nw", pady=3)
        headers_text = tk.Text(detail_frame, height=3, width=30,
                               font=("Courier", 9))
        headers_text.grid(row=16, column=1, sticky="ew", pady=3)
        custom_headers = srv.get("custom_headers", [])
        headers_str = "\n".join(f"{h['key']}: {h['value']}" for h in custom_headers)
        headers_text.insert("1.0", headers_str)
        tk.Label(detail_frame, text="One per line: Key: Value",
                 fg="#888", font=("Helvetica", 8)).grid(row=17, column=1, sticky="w")

        # ── Model Router section (local servers only) ─────────────────────
        row = 18
        if srv.get("is_local"):
            tk.Label(detail_frame, text="─" * 40, fg="#ccc").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=4)
            row += 1

            v_router = tk.BooleanVar(value=srv.get("use_router", False))
            tk.Label(detail_frame, text="Use model router", anchor="w",
                     width=18).grid(row=row, column=0, sticky="w", pady=3)
            tk.Checkbutton(detail_frame, variable=v_router).grid(
                row=row, column=1, sticky="w", pady=3)
            row += 1
            tk.Label(detail_frame, text="Use --models-preset instead of -m flag",
                     fg="#888", font=("Helvetica", 8)).grid(row=row, column=1, sticky="w")
            row += 1

            from model_router import default_models_ini_path
            default_preset = str(default_models_ini_path())
            v_preset = tk.StringVar(value=srv.get("models_preset_path", "") or default_preset)
            tk.Label(detail_frame, text="Preset path (.ini)", anchor="w",
                     width=18).grid(row=row, column=0, sticky="w", pady=3)
            pf = tk.Frame(detail_frame)
            pf.grid(row=row, column=1, sticky="ew", pady=3)
            tk.Entry(pf, textvariable=v_preset, width=22).pack(side="left", fill="x", expand=True)
            def browse_preset():
                p = filedialog.askopenfilename(
                    initialdir=str(Path(v_preset.get()).parent) if v_preset.get() else str(Path.home()),
                    filetypes=[("INI files", "*.ini"), ("All files", "*")])
                if p:
                    v_preset.set(p)
            ttk.Button(pf, text="…", command=browse_preset, width=3).pack(side="left", padx=2)
            row += 1
        else:
            v_router = tk.BooleanVar(value=False)
            v_preset = tk.StringVar(value="")

        def apply_changes():
            # Parse custom headers from text widget
            custom_hdrs = []
            for line in headers_text.get("1.0", "end").strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    custom_hdrs.append({"key": k.strip(), "value": v.strip()})

            servers_copy[idx].update({
                "name": v_name.get().strip() or "Server",
                "host": v_host.get().strip() or "127.0.0.1",
                "port": int(v_port.get()),
                "url": v_url.get().strip(),
                "is_local": v_local.get(),
                "llama_server_path": v_binary.get().strip(),
                "active_model": v_model.get().strip(),
                "ctx_size": int(v_ctx.get()),
                "n_parallel": int(v_parallel.get()),
                "n_gpu_layers": int(v_gpu.get()),
                "extra_flags": v_extra.get().strip(),
                "auto_start": v_autostart.get(),
                "api_key": v_apikey.get().strip(),
                "use_router": v_router.get(),
                "models_preset_path": v_preset.get().strip(),
                "custom_headers": custom_hdrs,
            })
            refresh_listbox()
            listbox.selection_set(idx)

        apply_btn = ttk.Button(detail_frame, text="Apply", command=apply_changes)
        apply_btn.grid(row=row, column=1, sticky="w", pady=(8, 0))

    def on_list_select(_event):
        sel = listbox.curselection()
        if sel:
            show_server(sel[0])

    listbox.bind("<<ListboxSelect>>", on_list_select)

    def add_server():
        new = make_server(name=f"Server {len(servers_copy) + 1}", is_local=False)
        servers_copy.append(new)
        refresh_listbox()
        listbox.selection_set(len(servers_copy) - 1)
        show_server(len(servers_copy) - 1)

    def remove_server():
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = servers_copy[idx]["name"]
        if not messagebox.askyesno("Remove", f"Remove server '{name}'?"):
            return
        servers_copy.pop(idx)
        refresh_listbox()
        selected_idx[0] = None
        show_server(None)

    def move_server(direction):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(servers_copy):
            servers_copy[idx], servers_copy[new_idx] = servers_copy[new_idx], servers_copy[idx]
            refresh_listbox()
            listbox.selection_set(new_idx)
            show_server(new_idx)

    ttk.Button(btn_frm, text="+ Add",    command=add_server).pack(fill="x", pady=1)
    ttk.Button(btn_frm, text="- Remove", command=remove_server).pack(fill="x", pady=1)
    ttk.Separator(btn_frm, orient="horizontal").pack(fill="x", pady=4)
    ttk.Button(btn_frm, text="▲ Up",     command=lambda: move_server(-1)).pack(fill="x", pady=1)
    ttk.Button(btn_frm, text="▼ Down",   command=lambda: move_server(1)).pack(fill="x", pady=1)

    refresh_listbox()
    if servers_copy:
        show_server(0)
        listbox.selection_set(0)

    # ── Tool Paths tab ───────────────────────────────────────────────────────
    t3 = tab("Tool Paths")
    t3.columnconfigure(1, weight=1)

    tk.Label(t3,
             text="If auto-detection fails, set paths here manually.\n"
                  "Saved paths take priority over auto-detection on every restart.",
             fg="#555", font=("Helvetica", 9), justify="left").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    def _path_field(parent, row, label, key, filetypes=None):
        tk.Label(parent, text=label, anchor="w", width=22).grid(
            row=row, column=0, sticky="w", pady=3)
        saved = cfg.get(key, "")
        var = tk.StringVar(value=saved)
        frm = tk.Frame(parent)
        frm.grid(row=row, column=1, sticky="ew", pady=3, padx=(0, 4))
        frm.columnconfigure(0, weight=1)
        tk.Entry(frm, textvariable=var).grid(row=0, column=0, sticky="ew")
        dot = tk.Label(frm, text="○", fg="#dc3545", width=2)
        dot.grid(row=0, column=2, padx=2)
        def _browse():
            kw = {}
            if filetypes:
                kw["filetypes"] = filetypes
            p = filedialog.askopenfilename(**kw)
            if p:
                var.set(p)
        ttk.Button(frm, text="…", command=_browse, width=3).grid(row=0, column=1, padx=(2,0))
        def _upd(*_):
            p = var.get().strip()
            ok = bool(p and Path(p).exists())
            dot.config(text="●" if ok else "○",
                       fg="#28a745" if ok else "#dc3545")
        var.trace_add("write", _upd)
        _upd()
        return var

    # opencode
    tk.Label(t3, text="opencode", font=("Helvetica", 9, "bold"),
             anchor="w").grid(row=1, column=0, columnspan=2, sticky="w")
    v_tp_oc  = _path_field(t3, 2, "Binary", "tool_opencode_path")
    v_tp_occ = _path_field(t3, 3, "Config file", "tool_opencode_config",
                            filetypes=[("JSON", "*.json"), ("All", "*")])

    ttk.Separator(t3, orient="horizontal").grid(
        row=4, column=0, columnspan=2, sticky="ew", pady=6)

    # llmfit
    tk.Label(t3, text="llmfit", font=("Helvetica", 9, "bold"),
             anchor="w").grid(row=5, column=0, columnspan=2, sticky="w")
    v_tp_lmf = _path_field(t3, 6, "Binary", "tool_llmfit_path")

    ttk.Separator(t3, orient="horizontal").grid(
        row=7, column=0, columnspan=2, sticky="ew", pady=6)

    # VS Code
    tk.Label(t3, text="VS Code / IDE Derivatives", font=("Helvetica", 9, "bold"),
             anchor="w").grid(row=8, column=0, columnspan=2, sticky="w")
    v_tp_vsc = _path_field(t3, 9, "Binary (code/codium/…)", "tool_vscode_path")

    tk.Label(t3, text="chatLanguageModels.json", anchor="w", width=22).grid(
        row=10, column=0, sticky="w", pady=3)
    _vsc_cfg_saved = cfg.get("tool_vscode_config", "")
    v_tp_vsc_cfg = tk.StringVar(value=_vsc_cfg_saved)
    _vsc_cfg_frm = tk.Frame(t3)
    _vsc_cfg_frm.grid(row=10, column=1, sticky="ew", pady=3, padx=(0, 4))
    _vsc_cfg_frm.columnconfigure(0, weight=1)
    tk.Entry(_vsc_cfg_frm, textvariable=v_tp_vsc_cfg).grid(row=0, column=0, sticky="ew")
    _vsc_cfg_dot = tk.Label(_vsc_cfg_frm, text="○", fg="#dc3545", width=2)
    _vsc_cfg_dot.grid(row=0, column=2, padx=2)
    def _browse_vsc_cfg():
        p = filedialog.askopenfilename(
            title="Select chatLanguageModels.json",
            filetypes=[("JSON", "*.json"), ("All files", "*")])
        if p:
            v_tp_vsc_cfg.set(p)
    ttk.Button(_vsc_cfg_frm, text="…", command=_browse_vsc_cfg, width=3).grid(
        row=0, column=1, padx=(2, 0))
    def _upd_vsc_cfg(*_):
        p = v_tp_vsc_cfg.get().strip()
        ok = bool(p and Path(p).exists())
        _vsc_cfg_dot.config(text="●" if ok else "○",
                             fg="#28a745" if ok else "#e3b341")
    v_tp_vsc_cfg.trace_add("write", _upd_vsc_cfg)
    _upd_vsc_cfg()
    tk.Label(t3, text="e.g. ~/.config/VSCodium/User/chatLanguageModels.json",
             fg="#888", font=("Helvetica", 8), anchor="w").grid(
        row=11, column=1, sticky="w")

    ttk.Separator(t3, orient="horizontal").grid(
        row=12, column=0, columnspan=2, sticky="ew", pady=6)

    def _tp_redetect():
        from tool_detect import detect_tools
        fresh = detect_tools()
        changed = []
        if fresh.get("opencode") and not v_tp_oc.get():
            v_tp_oc.set(fresh["opencode"]); changed.append(f"opencode: {fresh['opencode']}")
        if fresh.get("llmfit") and not v_tp_lmf.get():
            v_tp_lmf.set(fresh["llmfit"]); changed.append(f"llmfit: {fresh['llmfit']}")
        if fresh.get("vscode") and not v_tp_vsc.get():
            v_tp_vsc.set(fresh["vscode"]); changed.append(f"vscode: {fresh['vscode']}")
        summary = "\n".join(changed) if changed else "Nothing new detected."
        messagebox.showinfo("Re-detect", summary)

    ttk.Button(t3, text="↺ Re-detect tools", command=_tp_redetect).grid(
        row=13, column=0, columnspan=2, sticky="w", pady=6)

    # ── MCP Servers tab ──────────────────────────────────────────────────────
    t4 = tab("MCP Servers")

    # Left side: MCP server list + buttons
    mcp_list_frame = tk.Frame(t4)
    mcp_list_frame.pack(side="left", fill="y", padx=(0, 10))

    tk.Label(mcp_list_frame, text="MCP Servers:", font=("Helvetica", 9, "bold")).pack(anchor="w")

    mcp_listbox = tk.Listbox(mcp_list_frame, width=22, height=12)
    mcp_listbox.pack(fill="both", expand=True)

    mcp_btn_frm = tk.Frame(mcp_list_frame)
    mcp_btn_frm.pack(fill="x", pady=(4, 0))

    # Right side: selected MCP server's settings
    mcp_detail_frame = tk.Frame(t4)
    mcp_detail_frame.pack(side="right", fill="both", expand=True)
    mcp_detail_frame.columnconfigure(1, weight=1)

    # State for current edits
    mcp_servers_copy = [dict(s) for s in config.mcp_servers()]
    mcp_selected_idx = [None]

    def refresh_mcp_listbox():
        mcp_listbox.delete(0, tk.END)
        for s in mcp_servers_copy:
            marker = "🟢" if s.get("enabled", True) else "⚪"
            mcp_listbox.insert(tk.END, f"{marker} {s.get('name', 'Unnamed')}")

    def show_mcp_server(idx):
        mcp_selected_idx[0] = idx
        for w in mcp_detail_frame.winfo_children():
            w.destroy()

        if idx is None or idx >= len(mcp_servers_copy):
            tk.Label(mcp_detail_frame, text="Select an MCP server to edit.",
                     fg="#888").pack(anchor="w")
            return

        srv = mcp_servers_copy[idx]
        mcp_detail_frame.columnconfigure(1, weight=1)

        def er(label, row, default="", width=30):
            tk.Label(mcp_detail_frame, text=label, anchor="w", width=18).grid(
                row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=default)
            tk.Entry(mcp_detail_frame, textvariable=var, width=width).grid(
                row=row, column=1, sticky="ew", pady=3)
            return var

        v_name = er("Name", 0, srv.get("name", ""))
        v_command = er("Command", 1, srv.get("command", ""))
        v_args = er("Arguments", 2, " ".join(srv.get("args", [])))
        v_enabled = tk.BooleanVar(value=srv.get("enabled", True))
        tk.Label(mcp_detail_frame, text="Enabled", anchor="w", width=18).grid(
            row=3, column=0, sticky="w", pady=3)
        tk.Checkbutton(mcp_detail_frame, variable=v_enabled).grid(
            row=3, column=1, sticky="w", pady=3)

        # Environment variables (as key=value pairs, one per line)
        tk.Label(mcp_detail_frame, text="Environment", anchor="w", width=18).grid(
            row=4, column=0, sticky="nw", pady=3)
        env_text = tk.Text(mcp_detail_frame, height=4, width=30,
                           font=("Courier", 9))
        env_text.grid(row=4, column=1, sticky="ew", pady=3)
        env_data = srv.get("env", {})
        env_str = "\n".join(f"{k}={v}" for k, v in env_data.items())
        env_text.insert("1.0", env_str)

        def apply_mcp():
            srv["name"] = v_name.get().strip()
            srv["command"] = v_command.get().strip()
            # Parse args from space-separated string
            srv["args"] = v_args.get().strip().split() if v_args.get().strip() else []
            srv["enabled"] = v_enabled.get()
            # Parse env from text widget
            env = {}
            for line in env_text.get("1.0", "end").strip().split("\n"):
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            srv["env"] = env
            refresh_mcp_listbox()

        tk.Label(mcp_detail_frame, text="Format: KEY=value, one per line",
                 fg="#888", font=("Helvetica", 8)).grid(row=5, column=1, sticky="w")

        btn_apply = ttk.Button(mcp_detail_frame, text="Apply", command=apply_mcp)
        btn_apply.grid(row=6, column=1, sticky="w", pady=8)

    def add_mcp_server():
        from config import make_mcp_server
        mcp_servers_copy.append(make_mcp_server(name="New MCP Server"))
        refresh_mcp_listbox()
        mcp_listbox.selection_set(len(mcp_servers_copy) - 1)
        show_mcp_server(len(mcp_servers_copy) - 1)

    def remove_mcp_server():
        sel = mcp_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        mcp_servers_copy.pop(idx)
        refresh_mcp_listbox()
        if mcp_servers_copy:
            new_idx = min(idx, len(mcp_servers_copy) - 1)
            mcp_listbox.selection_set(new_idx)
            show_mcp_server(new_idx)
        else:
            show_mcp_server(None)

    ttk.Button(mcp_btn_frm, text="+ Add", command=add_mcp_server).pack(fill="x", pady=1)
    ttk.Button(mcp_btn_frm, text="- Remove", command=remove_mcp_server).pack(fill="x", pady=1)

    refresh_mcp_listbox()
    if mcp_servers_copy:
        show_mcp_server(0)
        mcp_listbox.selection_set(0)

    # ── Save / Cancel buttons ────────────────────────────────────────────────
    btn_frame = tk.Frame(root)
    btn_frame.pack(side="bottom", fill="x", padx=10, pady=8)

    def save():
        try:
            # Apply any pending edits from the detail frame
            if selected_idx[0] is not None:
                # Trigger Apply if a server is being edited
                pass  # edits are applied via the Apply button

            # Save global settings
            config.update({
                "models_dir":         v_models_dir.get().strip(),
                "hf_token":           v_hf_tok.get().strip(),
                "tool_opencode_path":   v_tp_oc.get().strip(),
                "tool_opencode_config": v_tp_occ.get().strip(),
                "tool_llmfit_path":     v_tp_lmf.get().strip(),
                "tool_vscode_path":     v_tp_vsc.get().strip(),
                "tool_vscode_config":   v_tp_vsc_cfg.get().strip(),
            })

            # Save server list
            config.set("servers", servers_copy)

            # Save MCP server list
            config.set("mcp_servers", mcp_servers_copy)

        except Exception as e:
            messagebox.showerror("Save error", str(e))
            return
        if on_save:
            on_save()
        messagebox.showinfo("Saved", "Settings saved.")
        root.destroy()

    ttk.Button(btn_frame, text="Cancel", command=root.destroy).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Save",   command=save).pack(side="right")

    root.mainloop()
