"""
settings_window.py — llama_tray settings with multi-server support.
"""

import threading
from pathlib import Path

from config import make_server
from utility_functions import build_server_url, build_server_headers


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
    _apply_fn = [None]     # current apply_changes callable for save()

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
        v_local     = tk.BooleanVar(value=srv.get("is_local", True))
        tk.Label(detail_frame, text="Local (can start/stop)", anchor="w",
                 width=18).grid(row=1, column=0, sticky="w", pady=3)
        tk.Checkbutton(detail_frame, variable=v_local).grid(
            row=1, column=1, sticky="w", pady=3)

        # Local: Host + Port  |  Remote: URL — created at same rows, toggled
        _lbl_host = tk.Label(detail_frame, text="Host", anchor="w", width=18)
        _lbl_host.grid(row=2, column=0, sticky="w", pady=3)
        v_host = tk.StringVar(value=srv.get("host", "127.0.0.1"))
        _ent_host = tk.Entry(detail_frame, textvariable=v_host, width=20)
        _ent_host.grid(row=2, column=1, sticky="ew", pady=3)

        _lbl_port = tk.Label(detail_frame, text="Port", anchor="w", width=18)
        _lbl_port.grid(row=3, column=0, sticky="w", pady=3)
        v_port = tk.IntVar(value=srv.get("port", 8080))
        _sp_port = tk.Spinbox(detail_frame, textvariable=v_port, from_=1, to=65535, width=8)
        _sp_port.grid(row=3, column=1, sticky="w", pady=3)

        _lbl_url = tk.Label(detail_frame, text="URL", anchor="w", width=18)
        _lbl_url.grid(row=2, column=0, sticky="w", pady=3)
        v_url = tk.StringVar(value=srv.get("url", ""))
        _ent_url = tk.Entry(detail_frame, textvariable=v_url, width=30)
        _ent_url.grid(row=2, column=1, sticky="ew", pady=3)
        _lbl_urlhint = tk.Label(detail_frame, text="e.g. https://llama.example.com/",
                                fg="#888", font=("Helvetica", 8))
        _lbl_urlhint.grid(row=3, column=1, sticky="w")

        def _toggle_local_remote(*_):
            is_loc = v_local.get()
            for w in (_lbl_host, _ent_host, _lbl_port, _sp_port):
                w.grid() if is_loc else w.grid_remove()
            for w in (_lbl_url, _ent_url, _lbl_urlhint):
                w.grid_remove() if is_loc else w.grid()
            for w in (_lbl_binary, _frm_binary):
                w.grid() if is_loc else w.grid_remove()
            for w in (_lbl_preset, _preset_row_frame):
                w.grid() if is_loc else w.grid_remove()
            for w in (_lbl_ctx, _sp_ctx, _lbl_parallel, _sp_parallel,
                       _lbl_gpu, _sp_gpu):
                w.grid() if is_loc else w.grid_remove()
            for w in (_lbl_threads, _sp_threads, _lbl_flash, _chk_flash,
                       _lbl_cache_k, _cmb_cache_k, _lbl_cache_v, _cmb_cache_v,
                       _lbl_mlock, _chk_mlock, _lbl_mmap, _chk_mmap,
                       _lbl_metrics, _chk_metrics):
                w.grid() if is_loc else w.grid_remove()
            for w in (_lbl_extra, _ent_extra, _lbl_extra_hint):
                w.grid() if is_loc else w.grid_remove()
            _lbl_autostart.config(text="Auto-connect" if not is_loc else "Auto-start")

        v_local.trace_add("write", _toggle_local_remote)

        # ── Separator & Binary ────────────────────────────────────────────
        tk.Label(detail_frame, text="─" * 40, fg="#ccc").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=4)

        v_binary = tk.StringVar(value=srv.get("llama_server_path", ""))
        _lbl_binary = tk.Label(detail_frame, text="Server binary", anchor="w", width=18)
        _lbl_binary.grid(row=6, column=0, sticky="w", pady=3)
        _frm_binary = tk.Frame(detail_frame)
        _frm_binary.grid(row=6, column=1, sticky="ew", pady=3)
        tk.Entry(_frm_binary, textvariable=v_binary, width=22).pack(side="left", fill="x", expand=True)
        def browse_binary():
            p = filedialog.askopenfilename(
                initialdir=str(Path(v_binary.get()).parent) if v_binary.get() else str(Path.home()),
                filetypes=[("All files", "*")])
            if p:
                v_binary.set(p)
        ttk.Button(_frm_binary, text="…", command=browse_binary, width=3).pack(side="left", padx=2)

        # ── Preset (local-only) ───────────────────────────────────────────
        def _load_presets():
            """Load presets from config, with '— None —' prepended."""
            raw = config.get().get("server_presets", [])
            presets = {"— None —": {"settings": {}, "description": "Pick individual settings below"}}
            for p in raw:
                name = p.get("name", "")
                if name:
                    presets[name] = p
            return presets

        _presets_data = _load_presets()
        PRESET_NAMES = list(_presets_data.keys())

        _lbl_preset = tk.Label(detail_frame, text="Preset", anchor="w", width=18)
        _lbl_preset.grid(row=7, column=0, sticky="w", pady=3)
        _preset_row_frame = tk.Frame(detail_frame)
        _preset_row_frame.grid(row=7, column=1, sticky="ew", pady=3)
        v_preset = tk.StringVar(value="— None —")
        _cmb_preset = ttk.Combobox(_preset_row_frame, textvariable=v_preset,
                                   values=PRESET_NAMES, state="readonly", width=20)
        _cmb_preset.pack(side="left")
        _lbl_preset_hint = tk.Label(detail_frame, text="", fg="#888", font=("Helvetica", 8))
        _lbl_preset_hint.grid(row=8, column=1, columnspan=2, sticky="w")

        def _open_preset_manager():
            from preset_manager import open_preset_manager
            def _on_presets_changed():
                # Reload presets into the combobox
                nonlocal _presets_data
                _presets_data = _load_presets()
                _cmb_preset["values"] = list(_presets_data.keys())
            open_preset_manager(root, config, on_change=_on_presets_changed)

        ttk.Button(_preset_row_frame, text="Manage…", command=_open_preset_manager,
                   width=9).pack(side="left", padx=4)

        def _on_preset_change(*_):
            name = v_preset.get()
            preset = _presets_data.get(name, {})
            hint = preset.get("description", "")
            _lbl_preset_hint.config(text=hint)
            vals = preset.get("settings", {})
            if not vals:
                return
            if "flash_attn" in vals:   v_flash.set(vals["flash_attn"])
            if "cache_type_k" in vals: v_cache_k.set(vals["cache_type_k"])
            if "cache_type_v" in vals: v_cache_v.set(vals["cache_type_v"])
            if "mlock" in vals:        v_mlock.set(vals["mlock"])
            if "mmap" in vals:         v_mmap.set(vals["mmap"])
            if "metrics" in vals:      v_metrics.set(vals["metrics"])
            if "n_gpu_layers" in vals: v_gpu.set(vals["n_gpu_layers"])
            if "n_threads" in vals:    v_threads.set(vals["n_threads"])
            if "ctx_size" in vals:     v_ctx.set(vals["ctx_size"])

        v_preset.trace_add("write", _on_preset_change)

        # ── Active model ──────────────────────────────────────────────────
        v_model = tk.StringVar(value=srv.get("active_model", ""))
        tk.Label(detail_frame, text="Active model", anchor="w",
                 width=18).grid(row=9, column=0, sticky="w", pady=3)
        mf = tk.Frame(detail_frame)
        mf.grid(row=9, column=1, sticky="ew", pady=3)

        if srv.get("is_local"):
            tk.Entry(mf, textvariable=v_model, width=22).pack(side="left", fill="x", expand=True)
            def browse_model():
                p = filedialog.askopenfilename(
                    initialdir=str(Path(v_model.get()).parent) if v_model.get() else str(Path.home()),
                    filetypes=[("GGUF", "*.gguf"), ("All files", "*")])
                if p:
                    v_model.set(p)
            ttk.Button(mf, text="…", command=browse_model, width=3).pack(side="left", padx=2)
        else:
            v_model_cb = ttk.Combobox(mf, textvariable=v_model, width=30, state="readonly")
            v_model_cb.pack(side="left", fill="x", expand=True)

            def _fetch_remote_models():
                # Build a temp server dict from form values for utility functions
                _srv = {
                    "url": v_url.get().strip(),
                    "host": v_host.get().strip() or "127.0.0.1",
                    "port": int(v_port.get()) if v_port.get() else 8080,
                    "api_key": v_apikey.get().strip(),
                    "custom_headers": [],
                }
                # Parse current custom headers from the text widget
                for line in headers_text.get("1.0", "end").strip().split("\n"):
                    line = line.strip()
                    if ":" in line:
                        hk, hv = line.split(":", 1)
                        hk = hk.strip()
                        hv = hv.strip()
                        if hk:
                            _srv["custom_headers"].append({"key": hk, "value": hv})

                url = f"{build_server_url(_srv)}/v1/models"
                headers = build_server_headers(_srv)

                import urllib.request, urllib.error, json as _json
                def _do():
                    models = []
                    try:
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
            root.after(100, _fetch_remote_models)

        # ── Local-only: ctx, parallel, gpu ────────────────────────────────
        v_ctx      = sr("Context size",   10, srv.get("ctx_size", 4096), from_=512, to=131072)
        _lbl_ctx   = detail_frame.grid_slaves(row=10, column=0)[0]
        _sp_ctx    = detail_frame.grid_slaves(row=10, column=1)[0]
        v_parallel = sr("Parallel slots", 11, srv.get("n_parallel", 1), from_=1, to=32)
        _lbl_parallel = detail_frame.grid_slaves(row=11, column=0)[0]
        _sp_parallel  = detail_frame.grid_slaves(row=11, column=1)[0]
        v_gpu      = sr("GPU layers",    12, srv.get("n_gpu_layers", 0), from_=0, to=99)
        _lbl_gpu   = detail_frame.grid_slaves(row=12, column=0)[0]
        _sp_gpu    = detail_frame.grid_slaves(row=12, column=1)[0]

        # ── Local-only: threads, flash, kv cache, mlock, mmap, metrics ───
        v_threads  = sr("CPU threads",   13, srv.get("n_threads", 0), from_=0, to=128)
        _lbl_threads = detail_frame.grid_slaves(row=13, column=0)[0]
        _sp_threads  = detail_frame.grid_slaves(row=13, column=1)[0]
        tk.Label(detail_frame, text="0 = auto-detect", fg="#888",
                 font=("Helvetica", 8)).grid(row=14, column=1, sticky="w")

        v_flash = tk.BooleanVar(value=srv.get("flash_attn", False))
        _lbl_flash = tk.Label(detail_frame, text="Flash attention", anchor="w", width=18)
        _lbl_flash.grid(row=15, column=0, sticky="w", pady=3)
        _chk_flash = tk.Checkbutton(detail_frame, variable=v_flash)
        _chk_flash.grid(row=15, column=1, sticky="w", pady=3)
        tk.Label(detail_frame, text="-fa — big speed boost on supported GPUs",
                 fg="#888", font=("Helvetica", 8)).grid(row=16, column=1, sticky="w")

        _lbl_cache_k = tk.Label(detail_frame, text="KV cache type (K)", anchor="w", width=18)
        _lbl_cache_k.grid(row=17, column=0, sticky="w", pady=3)
        v_cache_k = tk.StringVar(value=srv.get("cache_type_k", "f16"))
        _cmb_cache_k = ttk.Combobox(detail_frame, textvariable=v_cache_k,
                                     values=["f16", "q8_0", "q4_0"], state="readonly", width=8)
        _cmb_cache_k.grid(row=17, column=1, sticky="w", pady=3)
        tk.Label(detail_frame, text="f16 = full, q8_0 = half VRAM, q4_0 = quarter VRAM",
                 fg="#888", font=("Helvetica", 8)).grid(row=18, column=1, sticky="w")

        _lbl_cache_v = tk.Label(detail_frame, text="KV cache type (V)", anchor="w", width=18)
        _lbl_cache_v.grid(row=19, column=0, sticky="w", pady=3)
        v_cache_v = tk.StringVar(value=srv.get("cache_type_v", "f16"))
        _cmb_cache_v = ttk.Combobox(detail_frame, textvariable=v_cache_v,
                                     values=["f16", "q8_0", "q4_0"], state="readonly", width=8)
        _cmb_cache_v.grid(row=19, column=1, sticky="w", pady=3)

        v_mlock = tk.BooleanVar(value=srv.get("mlock", False))
        _lbl_mlock = tk.Label(detail_frame, text="Lock in RAM (mlock)", anchor="w", width=18)
        _lbl_mlock.grid(row=20, column=0, sticky="w", pady=3)
        _chk_mlock = tk.Checkbutton(detail_frame, variable=v_mlock)
        _chk_mlock.grid(row=20, column=1, sticky="w", pady=3)
        tk.Label(detail_frame, text="Prevent model from being swapped to disk",
                 fg="#888", font=("Helvetica", 8)).grid(row=21, column=1, sticky="w")

        v_mmap = tk.BooleanVar(value=srv.get("mmap", True))
        _lbl_mmap = tk.Label(detail_frame, text="Memory map (mmap)", anchor="w", width=18)
        _lbl_mmap.grid(row=22, column=0, sticky="w", pady=3)
        _chk_mmap = tk.Checkbutton(detail_frame, variable=v_mmap)
        _chk_mmap.grid(row=22, column=1, sticky="w", pady=3)
        tk.Label(detail_frame, text="Memory-mapped I/O — faster load, slight perf cost",
                 fg="#888", font=("Helvetica", 8)).grid(row=23, column=1, sticky="w")

        v_metrics = tk.BooleanVar(value=srv.get("metrics", False))
        _lbl_metrics = tk.Label(detail_frame, text="Prometheus metrics", anchor="w", width=18)
        _lbl_metrics.grid(row=24, column=0, sticky="w", pady=3)
        _chk_metrics = tk.Checkbutton(detail_frame, variable=v_metrics)
        _chk_metrics.grid(row=24, column=1, sticky="w", pady=3)
        tk.Label(detail_frame, text="Enable /metrics endpoint for monitoring",
                 fg="#888", font=("Helvetica", 8)).grid(row=25, column=1, sticky="w")

        # ── Extra CLI flags ───────────────────────────────────────────────
        _lbl_extra = tk.Label(detail_frame, text="Extra CLI flags", anchor="w", width=18)
        _lbl_extra.grid(row=26, column=0, sticky="w", pady=3)
        v_extra = tk.StringVar(value=srv.get("extra_flags", ""))
        _ent_extra = tk.Entry(detail_frame, textvariable=v_extra, width=30)
        _ent_extra.grid(row=26, column=1, sticky="ew", pady=3)
        _lbl_extra_hint = tk.Label(detail_frame, text="e.g. --threads 8 --mlock",
                                   fg="#888", font=("Helvetica", 8))
        _lbl_extra_hint.grid(row=27, column=1, sticky="w")

        # ── Auto-start / Auto-connect (created before _toggle so ref exists) ─
        v_autostart = tk.BooleanVar(value=srv.get("auto_start", False))
        _lbl_autostart = tk.Label(detail_frame, text="Auto-start", anchor="w", width=18)
        _lbl_autostart.grid(row=28, column=0, sticky="w", pady=3)
        tk.Checkbutton(detail_frame, variable=v_autostart).grid(
            row=28, column=1, sticky="w", pady=3)

        _toggle_local_remote()

        # ── API Key ───────────────────────────────────────────────────────
        lbl(detail_frame, "API key", 29)
        v_apikey = tk.StringVar(value=srv.get("api_key", ""))
        akf = tk.Frame(detail_frame)
        akf.grid(row=29, column=1, sticky="ew", pady=3)
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
                 fg="#888", font=("Helvetica", 8)).grid(row=30, column=1, sticky="w")

        # ── Custom Headers ────────────────────────────────────────────────
        tk.Label(detail_frame, text="Custom headers", anchor="w",
                 width=18).grid(row=31, column=0, sticky="nw", pady=3)
        headers_text = tk.Text(detail_frame, height=3, width=30,
                               font=("Courier", 9))
        headers_text.grid(row=31, column=1, sticky="ew", pady=3)
        custom_headers = srv.get("custom_headers", [])
        headers_str = "\n".join(f"{h['key']}: {h['value']}" for h in custom_headers)
        headers_text.insert("1.0", headers_str)
        tk.Label(detail_frame, text="One per line: Key: Value",
                 fg="#888", font=("Helvetica", 8)).grid(row=32, column=1, sticky="w")

        # ── Model Router section (local servers only) ─────────────────────
        row = 33
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
                # New local-only fields
                "n_threads": int(v_threads.get()),
                "flash_attn": v_flash.get(),
                "cache_type_k": v_cache_k.get(),
                "cache_type_v": v_cache_v.get(),
                "mlock": v_mlock.get(),
                "mmap": v_mmap.get(),
                "metrics": v_metrics.get(),
            })
            refresh_listbox()
            listbox.selection_set(idx)

        apply_btn = ttk.Button(detail_frame, text="Apply", command=apply_changes)
        apply_btn.grid(row=row, column=1, sticky="w", pady=(8, 0))

        _apply_fn[0] = apply_changes

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

        TRANSPORTS = [
            ("stdio",          "Stdio (subprocess)"),
            ("sse",            "SSE (Server-Sent Events)"),
            ("streamable-http", "Streamable HTTP"),
            ("rpc",            "TCP RPC"),
        ]
        TRANSPORT_HINTS = {
            "stdio":          "Spawns a local process, communicates via stdin/stdout",
            "sse":            "HTTP GET /sse for events, POST /message for requests",
            "streamable-http": "HTTP POST /mcp with streaming JSON responses",
            "rpc":            "TCP socket JSON-RPC 2.0 (host:port)",
        }

        def er(label, row, default="", width=30):
            tk.Label(mcp_detail_frame, text=label, anchor="w", width=18).grid(
                row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=default)
            tk.Entry(mcp_detail_frame, textvariable=var, width=width).grid(
                row=row, column=1, sticky="ew", pady=3)
            return var

        row = 0
        v_name = er("Name", row, srv.get("name", ""))
        row += 1

        # Transport selector
        tk.Label(mcp_detail_frame, text="Transport", anchor="w", width=18).grid(
            row=row, column=0, sticky="w", pady=3)
        v_transport = tk.StringVar(value=srv.get("transport", "stdio"))
        cmb_transport = ttk.Combobox(mcp_detail_frame, textvariable=v_transport,
                                     values=[t[0] for t in TRANSPORTS],
                                     state="readonly", width=18)
        cmb_transport.grid(row=row, column=1, sticky="w", pady=3)
        row += 1
        _lbl_transport_hint = tk.Label(mcp_detail_frame, text=TRANSPORT_HINTS.get("stdio", ""),
                                       fg="#888", font=("Helvetica", 8))
        _lbl_transport_hint.grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1

        # ── Stdio-only fields ──────────────────────────────────────────────
        _lbl_command = tk.Label(mcp_detail_frame, text="Command", anchor="w", width=18)
        _lbl_command.grid(row=row, column=0, sticky="w", pady=3)
        v_command = tk.StringVar(value=srv.get("command", ""))
        _ent_command = tk.Entry(mcp_detail_frame, textvariable=v_command, width=30)
        _ent_command.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        _lbl_args = tk.Label(mcp_detail_frame, text="Arguments", anchor="w", width=18)
        _lbl_args.grid(row=row, column=0, sticky="w", pady=3)
        v_args = tk.StringVar(value=" ".join(srv.get("args", [])))
        _ent_args = tk.Entry(mcp_detail_frame, textvariable=v_args, width=30)
        _ent_args.grid(row=row, column=1, sticky="ew", pady=3)
        _lbl_args_hint = tk.Label(mcp_detail_frame, text="Space-separated",
                                  fg="#888", font=("Helvetica", 8))
        _lbl_args_hint.grid(row=row, column=2, sticky="w", padx=4)
        row += 1

        _lbl_env = tk.Label(mcp_detail_frame, text="Environment", anchor="w", width=18)
        _lbl_env.grid(row=row, column=0, sticky="nw", pady=3)
        env_text = tk.Text(mcp_detail_frame, height=4, width=30,
                           font=("Courier", 9))
        env_text.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        env_data = srv.get("env", {})
        env_str = "\n".join(f"{k}={v}" for k, v in env_data.items())
        env_text.insert("1.0", env_str)
        _lbl_env_hint = tk.Label(mcp_detail_frame, text="KEY=value, one per line",
                                 fg="#888", font=("Helvetica", 8))
        _lbl_env_hint.grid(row=row + 1, column=1, columnspan=2, sticky="w")
        row += 2

        # ── URL-based transport fields (SSE, HTTP, RPC) ────────────────────
        _lbl_url = tk.Label(mcp_detail_frame, text="URL", anchor="w", width=18)
        _lbl_url.grid(row=row, column=0, sticky="w", pady=3)
        v_url = tk.StringVar(value=srv.get("url", ""))
        _ent_url = tk.Entry(mcp_detail_frame, textvariable=v_url, width=30)
        _ent_url.grid(row=row, column=1, sticky="ew", pady=3)
        _lbl_url_hint = tk.Label(mcp_detail_frame, text="",
                                 fg="#888", font=("Helvetica", 8))
        _lbl_url_hint.grid(row=row, column=2, sticky="w", padx=4)
        row += 1

        _lbl_headers = tk.Label(mcp_detail_frame, text="Headers", anchor="w", width=18)
        _lbl_headers.grid(row=row, column=0, sticky="nw", pady=3)
        headers_text = tk.Text(mcp_detail_frame, height=3, width=30,
                               font=("Courier", 9))
        headers_text.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        hdr_data = srv.get("headers", {})
        hdr_str = "\n".join(f"{k}: {v}" for k, v in hdr_data.items())
        headers_text.insert("1.0", hdr_str)
        _lbl_headers_hint = tk.Label(mcp_detail_frame, text="Key: Value, one per line",
                                     fg="#888", font=("Helvetica", 8))
        _lbl_headers_hint.grid(row=row + 1, column=1, columnspan=2, sticky="w")
        row += 2

        # ── Enabled ────────────────────────────────────────────────────────
        v_enabled = tk.BooleanVar(value=srv.get("enabled", True))
        tk.Label(mcp_detail_frame, text="Enabled", anchor="w", width=18).grid(
            row=row, column=0, sticky="w", pady=3)
        tk.Checkbutton(mcp_detail_frame, variable=v_enabled).grid(
            row=row, column=1, sticky="w", pady=3)
        row += 1

        # ── Toggle visibility based on transport ───────────────────────────
        _stdio_widgets = (_lbl_command, _ent_command, _lbl_args, _ent_args,
                          _lbl_args_hint, _lbl_env, env_text, _lbl_env_hint)
        _url_widgets = (_lbl_url, _ent_url, _lbl_url_hint,
                        _lbl_headers, headers_text, _lbl_headers_hint)

        def _toggle_transport(*_):
            t = v_transport.get()
            _lbl_transport_hint.config(text=TRANSPORT_HINTS.get(t, ""))
            if t == "stdio":
                for w in _stdio_widgets:
                    w.grid()
                for w in _url_widgets:
                    w.grid_remove()
                _lbl_url_hint.config(text="")
            elif t == "rpc":
                for w in _stdio_widgets:
                    w.grid_remove()
                for w in _url_widgets:
                    w.grid()
                _lbl_url_hint.config(text="host:port")
            else:  # sse, streamable-http
                for w in _stdio_widgets:
                    w.grid_remove()
                for w in _url_widgets:
                    w.grid()
                _lbl_url_hint.config(text="https://example.com/mcp")

        v_transport.trace_add("write", _toggle_transport)
        _toggle_transport()

        # ── Apply ──────────────────────────────────────────────────────────
        def apply_mcp():
            srv["name"] = v_name.get().strip()
            srv["transport"] = v_transport.get()
            srv["command"] = v_command.get().strip()
            srv["args"] = v_args.get().strip().split() if v_args.get().strip() else []
            srv["url"] = v_url.get().strip()
            srv["enabled"] = v_enabled.get()
            # Parse env
            env = {}
            for line in env_text.get("1.0", "end").strip().split("\n"):
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            srv["env"] = env
            # Parse headers
            hdrs = {}
            for line in headers_text.get("1.0", "end").strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    hdrs[k.strip()] = v.strip()
            srv["headers"] = hdrs
            refresh_mcp_listbox()

        btn_apply = ttk.Button(mcp_detail_frame, text="Apply", command=apply_mcp)
        btn_apply.grid(row=row, column=1, sticky="w", pady=8)

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
            if selected_idx[0] is not None and _apply_fn[0] is not None:
                _apply_fn[0]()

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
        for name in root.tk.call('info', 'vars'):
            try:
                root.tk.call('destroy', name)
            except Exception:
                pass
        root.destroy()

    def _on_cancel():
        for name in root.tk.call('info', 'vars'):
            try:
                root.tk.call('destroy', name)
            except Exception:
                pass
        root.destroy()

    ttk.Button(btn_frame, text="Cancel", command=_on_cancel).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Save",   command=save).pack(side="right")

    root.mainloop()
