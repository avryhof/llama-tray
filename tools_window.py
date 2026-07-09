"""
tools_window.py — External tool integrations for llama_tray.

Tabs:
  1. Tools      — detect / manually set paths for opencode, llmfit, vscode
  2. llmfit     — spin up llmfit serve, browse hardware-compatible models, download
  3. Models     — manage which .gguf files llama.cpp loads (active model selector)
  4. opencode   — write llama.cpp provider into opencode config
  5. VS Code    — write llama.cpp into VS Code Continue / Copilot config
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Tool detection
# ─────────────────────────────────────────────────────────────────────────────

# Common install locations beyond $PATH
_EXTRA_PATHS = [
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / ".cargo" / "bin"),
    str(Path.home() / ".npm-global" / "bin"),
    str(Path.home() / "node_modules" / ".bin"),
    "/usr/local/bin",
    "/usr/bin",
    "/snap/bin",
    "/opt/homebrew/bin",
]

# VS Code variant executable names
_VSCODE_BINS = ["code", "code-insiders", "codium", "vscodium"]

# VS Code config locations to check for Continue extension
_VSCODE_CONTINUE_PATHS = [
    Path.home() / ".continue" / "config.json",
    Path.home() / ".config" / "continue" / "config.json",
]

# opencode global config
_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "config.json"


def _find_binary(name: str) -> str | None:
    """Search PATH + _EXTRA_PATHS for an executable."""
    found = shutil.which(name)
    if found:
        return found
    for d in _EXTRA_PATHS:
        p = Path(d) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def detect_tools() -> dict:
    """
    Return dict with keys: opencode, llmfit, vscode
    Values are str path or None.
    """
    vscode = None
    for name in _VSCODE_BINS:
        p = _find_binary(name)
        if p:
            vscode = p
            break

    return {
        "opencode": _find_binary("opencode"),
        "llmfit": _find_binary("llmfit"),
        "vscode": vscode,
    }


# ─────────────────────────────────────────────────────────────────────────────
# llmfit serve helpers
# ─────────────────────────────────────────────────────────────────────────────

LLMFIT_PORT = 8787
LLMFIT_BASE = f"http://127.0.0.1:{LLMFIT_PORT}"


def _lmf_get(path: str, timeout: int = 8) -> dict | None:
    try:
        url = LLMFIT_BASE + path
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def llmfit_is_running() -> bool:
    return _lmf_get("/health") is not None


def llmfit_system() -> dict | None:
    return _lmf_get("/api/v1/system")


def llmfit_top_models(limit: int = 50, min_fit: str = "marginal", use_case: str = "coding") -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "limit": limit,
            "min_fit": min_fit,
            "use_case": use_case,
        }
    )
    data = _lmf_get(f"/api/v1/models/top?{params}")
    if data and "models" in data:
        return data["models"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# opencode config helpers
# ─────────────────────────────────────────────────────────────────────────────


def _read_oc_config() -> dict:
    if _OPENCODE_CONFIG.exists():
        try:
            return json.loads(_OPENCODE_CONFIG.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _write_oc_config(data: dict):
    _OPENCODE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _OPENCODE_CONFIG.write_text(json.dumps(data, indent=2), "utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# VS Code / Continue config helpers
# ─────────────────────────────────────────────────────────────────────────────


def _find_continue_config() -> Path | None:
    for p in _VSCODE_CONTINUE_PATHS:
        if p.exists():
            return p
    return None


def _read_continue_config() -> dict:
    p = _find_continue_config()
    if p:
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _write_continue_config(data: dict):
    p = _find_continue_config() or _VSCODE_CONTINUE_PATHS[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), "utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────


def show_tools_window(llama_config, on_save=None):
    threading.Thread(target=_show, args=(llama_config, on_save), daemon=True).start()


def _show(llama_config, on_save):
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
    except ImportError:
        print("tkinter not available")
        return

    cfg_snap = llama_config.get()

    root = tk.Tk()
    root.title("Tool Integrations")
    root.geometry("820x640")
    root.resizable(True, True)

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=8)

    # ── shared helpers ────────────────────────────────────────────────────────

    def _tab(label):
        f = tk.Frame(nb, padx=12, pady=10)
        nb.add(f, text=f"  {label}  ")
        return f

    def _badge(parent, text, ok, row=None, col=0, colspan=1):
        colour = "#28a745" if ok else "#dc3545"
        lbl = tk.Label(
            parent, text=("● " if ok else "○ ") + text, fg=colour, anchor="w", font=("Helvetica", 10, "bold")
        )
        if row is not None:
            lbl.grid(row=row, column=col, columnspan=colspan, sticky="w", pady=2)
        else:
            lbl.pack(anchor="w", pady=2)
        return lbl

    def _lbl(parent, text, row, col=0, width=18, **kw):
        tk.Label(parent, text=text, anchor="w", width=width, **kw).grid(row=row, column=col, sticky="w", pady=3)

    def _entry(parent, row, default="", col=1, width=40):
        var = tk.StringVar(value=default)
        tk.Entry(parent, textvariable=var, width=width).grid(row=row, column=col, sticky="ew", pady=3, padx=(0, 4))
        return var

    def _browse_file(var, filetypes=None):
        kw = {}
        if filetypes:
            kw["filetypes"] = filetypes
        p = filedialog.askopenfilename(**kw)
        if p:
            var.set(p)

    def _browse_dir(var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _btn(parent, text, cmd, **kw):
        b = ttk.Button(parent, text=text, command=cmd, **kw)
        return b

    def _code_box(parent, height=10):
        f = tk.Frame(parent)
        f.pack(fill="both", expand=True, pady=4)
        sb = ttk.Scrollbar(f)
        sb.pack(side="right", fill="y")
        t = tk.Text(
            f,
            height=height,
            bg="#1e1e2e",
            fg="#cdd6f4",
            font=("Courier", 9),
            wrap="none",
            yscrollcommand=sb.set,
            state="disabled",
        )
        t.pack(fill="both", expand=True)
        sb.config(command=t.yview)
        return t

    def _code_set(widget, text, tags=None):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.config(state="disabled")

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1 — Tool Paths
    # ═══════════════════════════════════════════════════════════════════════
    t_paths = _tab("Tool Paths")
    t_paths.columnconfigure(1, weight=1)

    detected = detect_tools()

    # Read saved overrides from config
    saved_oc = cfg_snap.get("tool_opencode_path", "") or detected.get("opencode") or ""
    saved_lmf = cfg_snap.get("tool_llmfit_path", "") or detected.get("llmfit") or ""
    saved_vsc = cfg_snap.get("tool_vscode_path", "") or detected.get("vscode") or ""
    saved_oc_cfg = cfg_snap.get("tool_opencode_config", str(_OPENCODE_CONFIG))
    saved_lmf_cfg = cfg_snap.get("tool_llmfit_config", "")

    def _path_row(parent, row, label, default, filetypes=None):
        """Returns (StringVar, badge_label)"""
        _lbl(parent, label, row)
        var = tk.StringVar(value=default)
        frame = tk.Frame(parent)
        frame.grid(row=row, column=1, sticky="ew", pady=3, padx=(0, 4))
        frame.columnconfigure(0, weight=1)
        e = tk.Entry(frame, textvariable=var)
        e.grid(row=0, column=0, sticky="ew")
        _btn(frame, "…", lambda: _browse_file(var, filetypes)).grid(row=0, column=1, padx=(2, 0))
        ok_var = tk.BooleanVar(value=bool(default and Path(default).exists()))
        badge = tk.Label(frame, text="", width=2)
        badge.grid(row=0, column=2, padx=2)

        def _refresh(*_):
            p = var.get().strip()
            ok = bool(p and Path(p).exists() and os.access(p, os.X_OK))
            badge.config(text="●" if ok else "○", fg="#28a745" if ok else "#dc3545")

        var.trace_add("write", _refresh)
        _refresh()
        return var

    # opencode
    tk.Label(t_paths, text="opencode", font=("Helvetica", 10, "bold"), anchor="w").grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 2)
    )
    v_oc_bin = _path_row(t_paths, 1, "Binary", saved_oc)
    v_oc_cfg_path = _path_row(t_paths, 2, "Config file", saved_oc_cfg, filetypes=[("JSON", "*.json"), ("All", "*")])

    ttk.Separator(t_paths, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

    # llmfit
    tk.Label(t_paths, text="llmfit", font=("Helvetica", 10, "bold"), anchor="w").grid(
        row=4, column=0, columnspan=3, sticky="w", pady=(0, 2)
    )
    v_lmf_bin = _path_row(t_paths, 5, "Binary", saved_lmf)

    ttk.Separator(t_paths, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)

    # VS Code
    tk.Label(t_paths, text="VS Code", font=("Helvetica", 10, "bold"), anchor="w").grid(
        row=7, column=0, columnspan=3, sticky="w", pady=(0, 2)
    )
    v_vsc_bin = _path_row(t_paths, 8, "Binary (code)", saved_vsc)

    ttk.Separator(t_paths, orient="horizontal").grid(row=9, column=0, columnspan=3, sticky="ew", pady=8)

    def _save_paths():
        llama_config.update(
            {
                "tool_opencode_path": v_oc_bin.get().strip(),
                "tool_opencode_config": v_oc_cfg_path.get().strip(),
                "tool_llmfit_path": v_lmf_bin.get().strip(),
                "tool_vscode_path": v_vsc_bin.get().strip(),
            }
        )
        if on_save:
            on_save()
        messagebox.showinfo("Saved", "Tool paths saved.")

    def _redetect():
        fresh = detect_tools()
        if fresh["opencode"] and not v_oc_bin.get():
            v_oc_bin.set(fresh["opencode"])
        if fresh["llmfit"] and not v_lmf_bin.get():
            v_lmf_bin.set(fresh["llmfit"])
        if fresh["vscode"] and not v_vsc_bin.get():
            v_vsc_bin.set(fresh["vscode"])
        messagebox.showinfo(
            "Re-detect",
            f"Scan complete.\nopencode: {fresh['opencode'] or 'not found'}\nllmfit: {fresh['llmfit'] or 'not found'}\nvscode: {fresh['vscode'] or 'not found'}",
        )

    btn_row = tk.Frame(t_paths)
    btn_row.grid(row=10, column=0, columnspan=3, sticky="e", pady=4)
    _btn(btn_row, "↺  Re-detect", _redetect).pack(side="left", padx=4)
    _btn(btn_row, "💾  Save Paths", _save_paths).pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2 — llmfit Browser
    # ═══════════════════════════════════════════════════════════════════════
    t_lmf = _tab("llmfit Browser")

    # llmfit serve process handle
    _lmf_proc = [None]
    _lmf_models = []  # cached list

    # ── top bar ───────────────────────────────────────────────────────────
    top = tk.Frame(t_lmf)
    top.pack(fill="x", pady=(0, 6))

    srv_status = tk.Label(top, text="○ llmfit server stopped", fg="#dc3545", font=("Helvetica", 10, "bold"), anchor="w")
    srv_status.pack(side="left")

    hw_label = tk.Label(top, text="", fg="#555", font=("Helvetica", 9), anchor="w")
    hw_label.pack(side="left", padx=12)

    def _get_lmf_binary():
        return llama_config.get().get("tool_llmfit_path") or detected.get("llmfit") or _find_binary("llmfit")

    def _update_srv_status():
        if llmfit_is_running():
            srv_status.config(text="● llmfit server running", fg="#28a745")
            stop_btn.config(state="normal")
            start_btn.config(state="disabled")
            _load_hw_info()
        else:
            srv_status.config(text="○ llmfit server stopped", fg="#dc3545")
            start_btn.config(state="normal")
            stop_btn.config(state="disabled")
            hw_label.config(text="")

    def _load_hw_info():
        def _do():
            sys_info = llmfit_system()
            if sys_info:
                gpu = sys_info.get("gpu", {})
                name = gpu.get("name", "?")
                vram = gpu.get("vram_gb", "?")
                ram = sys_info.get("ram_gb", "?")
                txt = f"GPU: {name}  VRAM: {vram}GB  RAM: {ram}GB"
                root.after(0, lambda: hw_label.config(text=txt))

        threading.Thread(target=_do, daemon=True).start()

    def _start_lmf_server():
        lmf = _get_lmf_binary()
        if not lmf:
            messagebox.showerror("Not found", "llmfit binary not found. Set path in Tool Paths tab.")
            return
        if llmfit_is_running():
            _update_srv_status()
            return
        try:
            _lmf_proc[0] = subprocess.Popen(
                [lmf, "serve", "--host", "127.0.0.1", "--port", str(LLMFIT_PORT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            messagebox.showerror("Launch error", str(e))
            return

        # Poll until healthy
        def _wait():
            for _ in range(20):
                time.sleep(0.5)
                if llmfit_is_running():
                    root.after(0, _update_srv_status)
                    root.after(0, _refresh_models)
                    return
            root.after(0, lambda: messagebox.showwarning("Timeout", "llmfit server didn't start in 10s."))

        threading.Thread(target=_wait, daemon=True).start()

    def _stop_lmf_server():
        if _lmf_proc[0]:
            try:
                _lmf_proc[0].terminate()
            except Exception:
                pass
            _lmf_proc[0] = None
        root.after(500, _update_srv_status)

    ctrl = tk.Frame(top)
    ctrl.pack(side="right")
    start_btn = _btn(ctrl, "▶ Start llmfit server", _start_lmf_server)
    start_btn.pack(side="left", padx=2)
    stop_btn = _btn(ctrl, "⏹ Stop", _stop_lmf_server, state="disabled")
    stop_btn.pack(side="left")

    # ── filters ────────────────────────────────────────────────────────────
    flt = tk.Frame(t_lmf)
    flt.pack(fill="x", pady=(0, 4))

    tk.Label(flt, text="Use case:").pack(side="left")
    v_usecase = tk.StringVar(value="coding")
    ttk.Combobox(
        flt,
        textvariable=v_usecase,
        width=12,
        state="readonly",
        values=["coding", "general", "reasoning", "chat", "multimodal", "embedding"],
    ).pack(side="left", padx=4)

    tk.Label(flt, text="Min fit:").pack(side="left", padx=(8, 0))
    v_minfit = tk.StringVar(value="marginal")
    ttk.Combobox(flt, textvariable=v_minfit, width=10, state="readonly", values=["perfect", "good", "marginal"]).pack(
        side="left", padx=4
    )

    tk.Label(flt, text="Limit:").pack(side="left", padx=(8, 0))
    v_limit = tk.IntVar(value=50)
    tk.Spinbox(flt, textvariable=v_limit, from_=5, to=200, width=5).pack(side="left", padx=4)

    refresh_btn = _btn(flt, "↺ Refresh", lambda: _refresh_models())
    refresh_btn.pack(side="left", padx=8)

    filter_var = tk.StringVar()
    tk.Label(flt, text="Filter:").pack(side="left", padx=(8, 0))
    filter_entry = tk.Entry(flt, textvariable=filter_var, width=20)
    filter_entry.pack(side="left", padx=2)

    # ── model table ────────────────────────────────────────────────────────
    tbl_frame = tk.Frame(t_lmf)
    tbl_frame.pack(fill="both", expand=True)

    cols = ("name", "fit", "quant", "tps", "mem", "ctx", "params")
    tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings", selectmode="browse", height=14)

    for col, hdr, w in [
        ("name", "Model", 280),
        ("fit", "Fit", 70),
        ("quant", "Quant", 80),
        ("tps", "tok/s", 60),
        ("mem", "Mem GB", 65),
        ("ctx", "Context", 70),
        ("params", "Params", 65),
    ]:
        tbl.heading(col, text=hdr)
        tbl.column(col, width=w, anchor="w" if col == "name" else "center")

    tbl.tag_configure("perfect", foreground="#56d364")
    tbl.tag_configure("good", foreground="#79c0ff")
    tbl.tag_configure("marginal", foreground="#e3b341")
    tbl.tag_configure("tight", foreground="#ff7b72")

    vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=tbl.yview)
    tbl.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    tbl.pack(fill="both", expand=True)

    status_bar = tk.Label(
        t_lmf, text="Start the llmfit server to browse models.", anchor="w", fg="#555", font=("Helvetica", 9)
    )
    status_bar.pack(fill="x")

    def _populate_table(models: list):
        # Apply text filter
        q = filter_var.get().strip().lower()
        tbl.delete(*tbl.get_children())
        shown = 0
        for m in models:
            name = m.get("name", m.get("id", ""))
            if q and q not in name.lower():
                continue
            fit = m.get("fit", "")
            quant = m.get("quant", m.get("quantization", ""))
            tps = m.get("speed_toks", m.get("tps", ""))
            mem = m.get("vram_gb", m.get("memory_gb", ""))
            ctx = m.get("context_size", m.get("ctx", ""))
            par = m.get("params", m.get("params_b", ""))
            tag = fit.lower().replace(" ", "") if fit else ""
            tbl.insert(
                "",
                "end",
                values=(
                    name,
                    fit,
                    quant,
                    f"{tps:.0f}" if isinstance(tps, float) else str(tps),
                    f"{mem:.1f}" if isinstance(mem, float) else str(mem),
                    str(ctx),
                    str(par),
                ),
                tags=(tag,),
            )
            shown += 1
        status_bar.config(text=f"{shown} models shown (of {len(models)} fetched).")

    filter_var.trace_add("write", lambda *_: _populate_table(_lmf_models))

    def _refresh_models():
        if not llmfit_is_running():
            status_bar.config(text="llmfit server is not running.")
            return
        status_bar.config(text="Fetching models…")
        refresh_btn.config(state="disabled")

        def _do():
            models = llmfit_top_models(
                limit=v_limit.get(),
                min_fit=v_minfit.get(),
                use_case=v_usecase.get(),
            )
            nonlocal _lmf_models
            _lmf_models = models
            root.after(0, lambda: _populate_table(models))
            root.after(0, lambda: refresh_btn.config(state="normal"))

        threading.Thread(target=_do, daemon=True).start()

    # ── download panel ────────────────────────────────────────────────────
    dl_frame = tk.LabelFrame(t_lmf, text="Download selected model", padx=8, pady=6)
    dl_frame.pack(fill="x", pady=4)
    dl_frame.columnconfigure(1, weight=1)

    tk.Label(dl_frame, text="Model dir:", anchor="w", width=12).grid(row=0, column=0, sticky="w")
    v_dl_dir = tk.StringVar(value=cfg_snap.get("models_dir", str(Path.home() / "models")))
    dir_entry = tk.Entry(dl_frame, textvariable=v_dl_dir)
    dir_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))
    _btn(dl_frame, "…", lambda: _browse_dir(v_dl_dir)).grid(row=0, column=2)

    dl_btn = _btn(dl_frame, "⬇  Download & Activate", lambda: _do_download())
    dl_btn.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
    dl_status = tk.Label(dl_frame, text="", anchor="w", fg="#555", font=("Helvetica", 9))
    dl_status.grid(row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))

    dl_prog = ttk.Progressbar(dl_frame, mode="indeterminate")

    def _do_download():
        sel = tbl.selection()
        if not sel:
            messagebox.showwarning("Select model", "Select a model from the table first.")
            return
        vals = tbl.item(sel[0])["values"]
        if not vals:
            return
        model_name = vals[0]

        dest_dir = Path(v_dl_dir.get().strip())
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Find the full model record
        model_rec = next((m for m in _lmf_models if m.get("name", m.get("id", "")) == model_name), {})
        hf_repo = model_rec.get("hf_id", model_rec.get("id", ""))
        quant = model_rec.get("quant", model_rec.get("quantization", "Q4_K_M"))

        dl_status.config(text=f"Preparing download of {model_name}…")
        dl_prog.grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        dl_prog.start(10)
        dl_btn.config(state="disabled")

        def _worker():
            # Try llmfit download command first (it knows the right GGUF file)
            lmf = _get_lmf_binary()
            success = False
            dest_file = None

            if lmf and hf_repo:
                try:
                    cmd = [lmf, "download", hf_repo, "--quant", quant, "--dest", str(dest_dir)]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    if proc.returncode == 0:
                        # Find the newest .gguf in dest_dir
                        ggufs = sorted(dest_dir.glob("*.gguf"), key=lambda f: f.stat().st_mtime)
                        if ggufs:
                            dest_file = ggufs[-1]
                            success = True
                except Exception:
                    pass

            # Fallback: direct HF download
            if not success and hf_repo:
                try:
                    filename = f"{hf_repo.split('/')[-1]}-{quant}.gguf"
                    dest_file = dest_dir / filename
                    url = f"https://huggingface.co/{hf_repo}/resolve/main/" f"{filename}"
                    req = urllib.request.Request(url)
                    hf_tok = llama_config.get().get("hf_token", "")
                    if hf_tok:
                        req.add_header("Authorization", f"Bearer {hf_tok}")
                    with urllib.request.urlopen(req, timeout=60) as r:
                        total = int(r.headers.get("Content-Length", 0))
                        done = 0
                        with open(dest_file, "wb") as out:
                            while True:
                                buf = r.read(262144)
                                if not buf:
                                    break
                                out.write(buf)
                                done += len(buf)
                                if total:
                                    mb = done / 1_048_576
                                    pct = done / total * 100
                                    root.after(
                                        0,
                                        lambda m=mb, p=pct: dl_status.config(
                                            text=f"Downloading… {m:.0f}/{total/1_048_576:.0f} MB ({p:.0f}%)"
                                        ),
                                    )
                    success = True
                except Exception as e:
                    root.after(0, lambda: dl_status.config(text=f"Download failed: {e}"))

            def _finish():
                dl_prog.stop()
                dl_prog.grid_remove()
                dl_btn.config(state="normal")
                if success and dest_file and dest_file.exists():
                    dl_status.config(text=f"✅  Saved: {dest_file.name}")
                    llama_config.update(
                        {
                            "active_model": str(dest_file),
                            "models_dir": str(dest_dir),
                        }
                    )
                    if on_save:
                        on_save()
                    # Refresh model selector tab
                    _refresh_model_list()
                    messagebox.showinfo(
                        "Downloaded",
                        f"{dest_file.name} downloaded and set as active model.\n" "Restart llama-server to load it.",
                    )
                elif not success:
                    dl_status.config(text="Download failed — see logs.")

            root.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    # Check if already running
    root.after(500, _update_srv_status)

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 3 — Model Manager
    # ═══════════════════════════════════════════════════════════════════════
    t_models = _tab("Models")
    t_models.columnconfigure(0, weight=1)

    tk.Label(t_models, text="Manage models served by llama.cpp", font=("Helvetica", 10, "bold"), anchor="w").pack(
        fill="x", pady=(0, 4)
    )

    # Models directory
    dir_frame = tk.Frame(t_models)
    dir_frame.pack(fill="x", pady=4)
    tk.Label(dir_frame, text="Models dir:", width=12, anchor="w").pack(side="left")
    v_mdir = tk.StringVar(value=cfg_snap.get("models_dir", str(Path.home() / "models")))
    tk.Entry(dir_frame, textvariable=v_mdir, width=45).pack(side="left", padx=4)
    _btn(dir_frame, "…", lambda: (_browse_dir(v_mdir), _refresh_model_list())).pack(side="left")
    _btn(dir_frame, "↺", _refresh_model_list := lambda: None).pack(side="left", padx=2)  # placeholder

    # Model list
    ml_frame = tk.Frame(t_models)
    ml_frame.pack(fill="both", expand=True, pady=4)

    ml_cols = ("active", "name", "size", "path")
    ml = ttk.Treeview(ml_frame, columns=ml_cols, show="headings", selectmode="browse", height=12)
    ml.heading("active", text="Active")
    ml.heading("name", text="File name")
    ml.heading("size", text="Size")
    ml.heading("path", text="Full path")
    ml.column("active", width=50, anchor="center")
    ml.column("name", width=250, anchor="w")
    ml.column("size", width=80, anchor="e")
    ml.column("path", width=340, anchor="w")

    ml_vsb = ttk.Scrollbar(ml_frame, orient="vertical", command=ml.yview)
    ml.configure(yscrollcommand=ml_vsb.set)
    ml_vsb.pack(side="right", fill="y")
    ml.pack(fill="both", expand=True)

    ml_status = tk.Label(t_models, text="", anchor="w", fg="#555", font=("Helvetica", 9))
    ml_status.pack(fill="x")

    def _fmt_size(path: Path) -> str:
        b = path.stat().st_size
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def _refresh_model_list():
        mdir = Path(v_mdir.get())
        active = llama_config.get().get("active_model", "")
        ml.delete(*ml.get_children())
        if not mdir.is_dir():
            ml_status.config(text=f"Directory not found: {mdir}")
            return
        ggufs = sorted(mdir.glob("*.gguf"))
        for g in ggufs:
            is_active = str(g) == active
            ml.insert(
                "",
                "end",
                values=("✓" if is_active else "", g.name, _fmt_size(g), str(g)),
                tags=("active",) if is_active else (),
            )
        ml.tag_configure("active", foreground="#56d364")
        ml_status.config(text=f"{len(ggufs)} .gguf file(s) in {mdir}")

    # Now replace the placeholder and bind the button properly
    for w in dir_frame.winfo_children():
        pass  # already packed; just call _refresh_model_list directly

    def _real_refresh():
        _refresh_model_list()

    # Rebuild dir_frame buttons properly
    for w in dir_frame.winfo_children():
        w.destroy()
    tk.Label(dir_frame, text="Models dir:", width=12, anchor="w").pack(side="left")
    v_mdir = tk.StringVar(value=cfg_snap.get("models_dir", str(Path.home() / "models")))
    tk.Entry(dir_frame, textvariable=v_mdir, width=45).pack(side="left", padx=4)
    _btn(dir_frame, "…", lambda: [_browse_dir(v_mdir), _refresh_model_list()]).pack(side="left")
    _btn(dir_frame, "↺", _refresh_model_list).pack(side="left", padx=2)

    # Activate selected
    def _activate_selected():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][3]
        llama_config.set("active_model", path)
        if on_save:
            on_save()
        _refresh_model_list()
        messagebox.showinfo("Activated", f"Active model set to:\n{Path(path).name}\n\nRestart llama-server to apply.")

    def _reveal_selected():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][3]
        subprocess.Popen(["xdg-open", str(Path(path).parent)])

    def _delete_selected():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][3]
        if messagebox.askyesno("Delete", f"Permanently delete:\n{Path(path).name}?"):
            try:
                Path(path).unlink()
                _refresh_model_list()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    act_row = tk.Frame(t_models)
    act_row.pack(fill="x", pady=4)
    _btn(act_row, "✓  Set Active", _activate_selected).pack(side="left", padx=2)
    _btn(act_row, "📂  Reveal in Files", _reveal_selected).pack(side="left", padx=2)
    _btn(act_row, "🗑  Delete", _delete_selected).pack(side="left", padx=2)

    tk.Label(
        t_models, text="Active model is loaded when llama-server starts.", fg="#888", font=("Helvetica", 8), anchor="w"
    ).pack(fill="x")

    _refresh_model_list()

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 4 — opencode config
    # ═══════════════════════════════════════════════════════════════════════
    t_oc = _tab("opencode")
    t_oc.columnconfigure(1, weight=1)

    oc_data = _read_oc_config()
    oc_prov = oc_data.get("provider", {}).get("llama.cpp", {})
    oc_models = oc_prov.get("models", {})
    first_mid = next(iter(oc_models), "")
    first_m = oc_models.get(first_mid, {})
    oc_url = oc_prov.get("options", {}).get("baseURL", "")
    _mu = re.match(r"http://([^:/]+):(\d+)/v1", oc_url)
    _ex_host = _mu.group(1) if _mu else cfg_snap.get("host", "127.0.0.1")
    _ex_port = int(_mu.group(2)) if _mu else cfg_snap.get("port", 8080)

    # Status
    oc_path_used = llama_config.get().get("tool_opencode_config") or str(_OPENCODE_CONFIG)
    oc_exists = Path(oc_path_used).exists()
    oc_bin_ok = bool(llama_config.get().get("tool_opencode_path") or detected.get("opencode"))

    sf = tk.LabelFrame(t_oc, text="Status", padx=8, pady=4)
    sf.pack(fill="x", pady=(0, 8))
    _badge(sf, f"opencode binary {'found' if oc_bin_ok else 'not found'}", oc_bin_ok)
    _badge(sf, f"Config: {oc_path_used}", oc_exists)

    # Form
    pf = tk.LabelFrame(t_oc, text="llama.cpp Provider Block", padx=10, pady=8)
    pf.pack(fill="x", pady=4)
    pf.columnconfigure(1, weight=1)

    _lbl(pf, "Host", 0)
    v_oc_host = _entry(pf, 0, _ex_host, width=20)
    _lbl(pf, "Port", 1)
    v_oc_port = tk.IntVar(value=_ex_port)
    tk.Spinbox(pf, textvariable=v_oc_port, from_=1, to=65535, width=8).grid(row=1, column=1, sticky="w", pady=3)
    _lbl(pf, "Model ID", 2)
    v_oc_mid = _entry(pf, 2, first_mid or "local-model")
    _lbl(pf, "Display name", 3)
    v_oc_mname = _entry(pf, 3, first_m.get("name", "Local Model"))
    _lbl(pf, "Context (tokens)", 4)
    v_oc_ctx = tk.IntVar(value=first_m.get("limit", {}).get("context", 16384))
    tk.Spinbox(pf, textvariable=v_oc_ctx, from_=512, to=262144, width=9).grid(row=4, column=1, sticky="w", pady=3)
    _lbl(pf, "Max output", 5)
    v_oc_out = tk.IntVar(value=first_m.get("limit", {}).get("output", 8192))
    tk.Spinbox(pf, textvariable=v_oc_out, from_=512, to=65536, width=9).grid(row=5, column=1, sticky="w", pady=3)
    v_oc_default = tk.BooleanVar(value=oc_data.get("model", "").startswith("llama.cpp/"))
    tk.Checkbutton(pf, text='Set "llama.cpp/<id>" as default model', variable=v_oc_default).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=4
    )

    def _sync_oc_from_tray():
        c = llama_config.get()
        v_oc_host.set(c.get("host", "127.0.0.1"))
        v_oc_port.set(c.get("port", 8080))
        v_oc_ctx.set(c.get("ctx_size", 16384))
        m = c.get("active_model", "")
        if m:
            stem = Path(m).stem
            v_oc_mid.set(stem)
            v_oc_mname.set(stem.replace("-", " ").replace("_", " "))

    _btn(t_oc, "↻ Sync from llama_tray config", _sync_oc_from_tray).pack(anchor="w", pady=4)

    # Preview
    tk.Label(t_oc, text="Config preview:", anchor="w", fg="#888", font=("Helvetica", 8)).pack(anchor="w")
    oc_preview = _code_box(t_oc, height=8)

    def _oc_refresh_preview(*_):
        try:
            block = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "llama-server (local)",
                "options": {"baseURL": f"http://{v_oc_host.get()}:{v_oc_port.get()}/v1"},
                "models": {
                    v_oc_mid.get(): {
                        "name": v_oc_mname.get(),
                        "limit": {"context": v_oc_ctx.get(), "output": v_oc_out.get()},
                    }
                },
            }
            snippet = {"$schema": "https://opencode.ai/config.json", "provider": {"llama.cpp": block}}
            if v_oc_default.get():
                snippet["model"] = f"llama.cpp/{v_oc_mid.get()}"
            _code_set(oc_preview, json.dumps(snippet, indent=2))
        except Exception as e:
            _code_set(oc_preview, f"(error: {e})")

    for v in (v_oc_host, v_oc_mid, v_oc_mname):
        v.trace_add("write", _oc_refresh_preview)
    for v in (v_oc_port, v_oc_ctx, v_oc_out):
        v.trace_add("write", _oc_refresh_preview)
    v_oc_default.trace_add("write", _oc_refresh_preview)
    _oc_refresh_preview()

    def _save_oc():
        try:
            cfg_path = Path(llama_config.get().get("tool_opencode_config") or str(_OPENCODE_CONFIG))
            data = {}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text("utf-8"))
                except Exception:
                    pass
            data["$schema"] = "https://opencode.ai/config.json"
            data.setdefault("provider", {})
            data["provider"]["llama.cpp"] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "llama-server (local)",
                "options": {"baseURL": f"http://{v_oc_host.get()}:{v_oc_port.get()}/v1"},
                "models": {
                    v_oc_mid.get(): {
                        "name": v_oc_mname.get(),
                        "limit": {"context": int(v_oc_ctx.get()), "output": int(v_oc_out.get())},
                    }
                },
            }
            if v_oc_default.get():
                data["model"] = f"llama.cpp/{v_oc_mid.get()}"
            elif data.get("model", "").startswith("llama.cpp/"):
                del data["model"]
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(data, indent=2), "utf-8")
            messagebox.showinfo("Saved", f"opencode config written to:\n{cfg_path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    _btn(t_oc, "💾  Write to opencode config", _save_oc).pack(anchor="e", pady=6)

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 5 — VS Code (Continue)
    # ═══════════════════════════════════════════════════════════════════════
    t_vsc = _tab("VS Code")
    t_vsc.columnconfigure(1, weight=1)

    cont_cfg = _read_continue_config()
    cont_path = _find_continue_config()
    vsc_ok = bool(detected.get("vscode") or llama_config.get().get("tool_vscode_path"))

    sf2 = tk.LabelFrame(t_vsc, text="Status", padx=8, pady=4)
    sf2.pack(fill="x", pady=(0, 8))
    _badge(sf2, f"VS Code binary {'found' if vsc_ok else 'not found'}", vsc_ok)
    _badge(sf2, f"Continue config: {cont_path or 'not found'}", cont_path is not None)
    tk.Label(
        sf2,
        text="Install the Continue extension in VS Code to enable local model support.",
        fg="#888",
        font=("Helvetica", 8),
        anchor="w",
    ).pack(fill="x")

    pf2 = tk.LabelFrame(t_vsc, text="Add llama.cpp as a Continue provider", padx=10, pady=8)
    pf2.pack(fill="x", pady=4)
    pf2.columnconfigure(1, weight=1)

    _lbl(pf2, "Host", 0)
    v_vsc_host = _entry(pf2, 0, cfg_snap.get("host", "127.0.0.1"), width=20)
    _lbl(pf2, "Port", 1)
    v_vsc_port = tk.IntVar(value=cfg_snap.get("port", 8080))
    tk.Spinbox(pf2, textvariable=v_vsc_port, from_=1, to=65535, width=8).grid(row=1, column=1, sticky="w", pady=3)
    _lbl(pf2, "Model title", 2)
    active_m = cfg_snap.get("active_model", "")
    v_vsc_title = _entry(pf2, 2, Path(active_m).stem if active_m else "llama-local")
    _lbl(pf2, "Model name", 3)
    v_vsc_mname = _entry(pf2, 3, Path(active_m).stem if active_m else "local-model")
    _lbl(pf2, "Context len", 4)
    v_vsc_ctx = tk.IntVar(value=cfg_snap.get("ctx_size", 4096))
    tk.Spinbox(pf2, textvariable=v_vsc_ctx, from_=512, to=262144, width=9).grid(row=4, column=1, sticky="w", pady=3)

    tk.Label(t_vsc, text="Config preview:", anchor="w", fg="#888", font=("Helvetica", 8)).pack(anchor="w")
    vsc_preview = _code_box(t_vsc, height=9)

    def _vsc_model_block():
        return {
            "title": v_vsc_title.get(),
            "provider": "openai",
            "model": v_vsc_mname.get(),
            "apiBase": f"http://{v_vsc_host.get()}:{v_vsc_port.get()}/v1",
            "apiKey": "not-required",
            "contextLength": int(v_vsc_ctx.get()),
        }

    def _vsc_refresh_preview(*_):
        block = _vsc_model_block()
        snippet = {"models": [block]}
        _code_set(vsc_preview, "// Add to ~/.continue/config.json  → models array:\n" + json.dumps(snippet, indent=2))

    for v in (v_vsc_host, v_vsc_title, v_vsc_mname):
        v.trace_add("write", _vsc_refresh_preview)
    for v in (v_vsc_port, v_vsc_ctx):
        v.trace_add("write", _vsc_refresh_preview)
    _vsc_refresh_preview()

    def _save_vsc():
        try:
            cfg_path = _find_continue_config() or _VSCODE_CONTINUE_PATHS[0]
            data = {}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text("utf-8"))
                except Exception:
                    pass

            block = _vsc_model_block()
            models = data.get("models", [])
            # Remove any existing entry with same title
            models = [m for m in models if m.get("title") != block["title"]]
            models.append(block)
            data["models"] = models

            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(data, indent=2), "utf-8")
            messagebox.showinfo(
                "Saved",
                f"Continue config updated:\n{cfg_path}\n\n"
                "Reload VS Code window to pick up the change (Ctrl+Shift+P → Reload Window).",
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    _btn(t_vsc, "💾  Write to Continue config", _save_vsc).pack(anchor="e", pady=6)

    root.mainloop()
