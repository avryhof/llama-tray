"""
settings_window.py — llama_tray settings (General + Server only).
HuggingFace config has moved to the Model Manager window.
"""

import threading
from pathlib import Path


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
    root.geometry("660x580")
    root.resizable(False, False)

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

    # ── General ───────────────────────────────────────────────────────────────
    t1 = tab("General")
    t1.columnconfigure(1, weight=1)

    v_binary    = file_row(t1, "llama-server binary", 0,
                           default=cfg.get("llama_server_path", ""),
                           filetypes=[("All files", "*")])
    v_models_dir= dir_row(t1, "Models directory",     1, default=cfg.get("models_dir", ""))
    v_auto_start= bool_row(t1, "Auto-start on launch", 2, default=cfg.get("auto_start", False))

    tk.Label(t1, text="Config file:", anchor="w", fg="#777").grid(
        row=3, column=0, sticky="w", pady=(16, 0))
    tk.Label(t1, text=str(config.config_file), anchor="w", fg="#555",
             wraplength=340, justify="left").grid(row=3, column=1, sticky="w", pady=(16, 0))

    tk.Label(t1, text="Active model and HF settings\nare in the Model Manager.",
             fg="#888", font=("Helvetica", 8), justify="left").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

    # ── Server ────────────────────────────────────────────────────────────────
    t2 = tab("Server")
    t2.columnconfigure(1, weight=1)

    v_host     = entry_row(t2, "Bind host",         0, default=cfg.get("host", "127.0.0.1"), width=20)
    v_port     = spin_row( t2, "Port",              1, default=cfg.get("port", 8080), from_=1, to=65535)
    v_ctx      = spin_row( t2, "Context size",      2, default=cfg.get("ctx_size", 4096), from_=512, to=131072)
    v_parallel = spin_row( t2, "Parallel slots",    3, default=cfg.get("n_parallel", 1), from_=1, to=32)
    v_gpu      = spin_row( t2, "GPU layers (-ngl)", 4, default=cfg.get("n_gpu_layers", 0), from_=0, to=999)

    lbl(t2, "Extra CLI flags", 5)
    v_extra = tk.StringVar(value=cfg.get("extra_flags", ""))
    tk.Entry(t2, textvariable=v_extra, width=36).grid(row=5, column=1, sticky="ew", pady=4)
    tk.Label(t2, text="e.g. --threads 8 --mlock", fg="#888",
             font=("Helvetica", 9)).grid(row=6, column=1, sticky="w")

    # ── Tool Paths ────────────────────────────────────────────────────────────
    t3 = tab("Tool Paths")
    t3.columnconfigure(1, weight=1)

    tk.Label(t3,
             text="If auto-detection fails, set paths here manually.\n"
                  "Saved paths take priority over auto-detection on every restart.",
             fg="#555", font=("Helvetica", 9), justify="left").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    def _path_field(parent, row, label, key, filetypes=None):
        """Entry + browse + live ●/○ indicator. Returns StringVar."""
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
    # Config file path — separate from binary so you can target VSCodium, Cursor, etc.
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

    # HuggingFace token
    tk.Label(t3, text="HuggingFace", font=("Helvetica", 9, "bold"),
             anchor="w").grid(row=13, column=0, columnspan=2, sticky="w")
    lbl(t3, "HF Access Token", 14)
    v_hf_tok = tk.StringVar(value=cfg.get("hf_token", ""))
    tk.Entry(t3, textvariable=v_hf_tok, show="*", width=34).grid(
        row=14, column=1, sticky="ew", pady=3)
    tk.Label(t3, text="Optional — needed for gated HuggingFace models",
             fg="#888", font=("Helvetica", 8)).grid(row=15, column=1, sticky="w")

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
        row=16, column=0, columnspan=2, sticky="w", pady=6)

    # ── Buttons ───────────────────────────────────────────────────────────────
    btn_frame = tk.Frame(root)
    btn_frame.pack(side="bottom", fill="x", padx=10, pady=8)

    def save():
        try:
            config.update({
                "llama_server_path": v_binary.get().strip(),
                "models_dir":        v_models_dir.get().strip(),
                "auto_start":        v_auto_start.get(),
                "host":              v_host.get().strip(),
                "port":              int(v_port.get()),
                "ctx_size":          int(v_ctx.get()),
                "n_parallel":        int(v_parallel.get()),
                "n_gpu_layers":      int(v_gpu.get()),
                "extra_flags":       v_extra.get().strip(),
                "tool_opencode_path":   v_tp_oc.get().strip(),
                "tool_opencode_config": v_tp_occ.get().strip(),
                "tool_llmfit_path":     v_tp_lmf.get().strip(),
                "tool_vscode_path":     v_tp_vsc.get().strip(),
                "tool_vscode_config":   v_tp_vsc_cfg.get().strip(),
                "hf_token":             v_hf_tok.get().strip(),
            })
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
