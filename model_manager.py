"""
model_manager.py — Unified Model Manager for llama_tray.

Tabs:
  1. My Models    — browse/activate/delete local .gguf files
  2. HuggingFace  — search & download GGUF models from HF
  3. llmfit       — hardware-scored model browser via llmfit serve API
  4. opencode     — write llama.cpp provider into opencode config
  5. VS Code      — write llama.cpp into chatLanguageModels.json
"""

import json
import os
import platform
import re
import subprocess
import threading
import time
import urllib.request
import urllib.parse

from pathlib import Path

OS = platform.system()

from huggingface_hub import HfApi, hf_hub_download

from tool_detect import (detect_tools, find_binary, CONTINUE_CONFIG_PATHS,
                         OPENCODE_CONFIG_DEFAULT, OPENCODE_AUTH_DEFAULT)

from model_router import (load_models_ini, save_models_ini, default_models_ini_path,
                          list_gguf_files as router_list_gguf, model_name_from_path,
                          make_model_entry, add_model_to_data, remove_model_from_data,
                          toggle_model_active, models_ini_as_text)

LLMFIT_PORT = 8787
LLMFIT_BASE = f"http://127.0.0.1:{LLMFIT_PORT}"


# ── Cross-platform helpers ────────────────────────────────────────────────────

def _open_folder(path: Path):
    """Open a folder in the system file manager."""
    folder = str(path)
    if OS == "Windows":
        subprocess.Popen(["explorer", folder])
    elif OS == "Darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


def _kill_port(port: int) -> bool:
    """Kill whatever process is listening on *port*. Returns True if killed."""
    import signal as _sig
    killed = False

    if OS == "Windows":
        # Windows: use netstat + taskkill
        try:
            r = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=5,
            )
            pids = set()
            for line in r.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            pids.add(int(parts[-1]))
                        except ValueError:
                            pass
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                    )
                    killed = True
                except Exception:
                    pass
        except Exception:
            pass
    else:
        # Linux/macOS: fuser → lsof fallback
        try:
            r = subprocess.run(
                ["fuser", "-k", "-TERM", f"{port}/tcp"],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                killed = True
        except FileNotFoundError:
            pass
        except Exception:
            pass

        if not killed:
            try:
                r = subprocess.run(
                    ["lsof", "-ti", f"tcp:{port}"],
                    capture_output=True, text=True, timeout=5,
                )
                pids = [int(p) for p in r.stdout.split() if p.strip().isdigit()]
                for pid in pids:
                    try:
                        os.kill(pid, _sig.SIGTERM)
                        killed = True
                    except ProcessLookupError:
                        pass
            except FileNotFoundError:
                pass
            except Exception:
                pass

    return killed


# ── llmfit REST helpers ───────────────────────────────────────────────────────

def _lmf_get(path: str, timeout: int = 8) -> dict | None:
    try:
        with urllib.request.urlopen(LLMFIT_BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _llmfit_running() -> bool:
    return _lmf_get("/health") is not None


# ── opencode / Continue config helpers ───────────────────────────────────────

def _rw_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), "utf-8")


def _find_continue_cfg() -> Path | None:
    for p in CONTINUE_CONFIG_PATHS:
        if p.exists():
            return p
    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def show_model_manager(llama_config, on_save=None):
    threading.Thread(target=_show, args=(llama_config, on_save), daemon=True).start()


def _show(llama_config, on_save):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("tkinter not available")
        return

    root = tk.Tk()
    root.title("Model Manager")
    root.geometry("920x680")
    root.resizable(True, True)

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=6, pady=6)

    # ── Shared widget helpers ─────────────────────────────────────────────────

    def cfg():
        return llama_config.get()

    def _tab(label):
        f = tk.Frame(nb, padx=10, pady=8)
        nb.add(f, text=f"  {label}  ")
        return f

    def _lbl(parent, text, row, col=0, width=16, **kw):
        tk.Label(parent, text=text, anchor="w", width=width, **kw).grid(
            row=row, column=col, sticky="w", pady=3)

    def _strvar(parent, row, default="", col=1, width=38, colspan=1):
        var = tk.StringVar(value=default)
        e = tk.Entry(parent, textvariable=var, width=width)
        e.grid(row=row, column=col, columnspan=colspan, sticky="ew", pady=3, padx=(0, 4))
        return var

    def _intvar(parent, row, default=0, col=1, from_=0, to=99999):
        var = tk.IntVar(value=default)
        tk.Spinbox(parent, textvariable=var, from_=from_, to=to, width=9).grid(
            row=row, column=col, sticky="w", pady=3)
        return var

    def _browse_file(var, filetypes=None):
        kw = {}
        if filetypes:
            kw["filetypes"] = filetypes
        p = filedialog.askopenfilename(**kw)
        if p:
            var.set(p)

    def _browse_dir(var, callback=None):
        d = filedialog.askdirectory()
        if d:
            var.set(d)
            if callback:
                callback()

    def _code_box(parent, height=8):
        frm = tk.Frame(parent)
        frm.pack(fill="both", expand=True, pady=4)
        sb = ttk.Scrollbar(frm)
        sb.pack(side="right", fill="y")
        t = tk.Text(frm, height=height, bg="#1e1e2e", fg="#cdd6f4",
                    font=("Courier", 9), wrap="none",
                    yscrollcommand=sb.set, state="disabled")
        t.pack(fill="both", expand=True)
        sb.config(command=t.yview)
        return t

    def _code_put(w, text):
        w.config(state="normal")
        w.delete("1.0", "end")
        w.insert("end", text)
        w.config(state="disabled")

    def _badge(parent, text, ok):
        colour = "#28a745" if ok else "#dc3545"
        tk.Label(parent, text=("● " if ok else "○ ") + text,
                 fg=colour, anchor="w", font=("Helvetica", 9, "bold")).pack(
            anchor="w", pady=1)

    def _scrolled_treeview(parent, columns, headings, widths,
                           height=14, expand=True):
        frm = tk.Frame(parent)
        frm.pack(fill="both", expand=expand)
        vsb = ttk.Scrollbar(frm, orient="vertical")
        vsb.pack(side="right", fill="y")
        tv = ttk.Treeview(frm, columns=columns, show="headings",
                          selectmode="browse", height=height,
                          yscrollcommand=vsb.set)
        for col, hdr, w in zip(columns, headings, widths):
            tv.heading(col, text=hdr)
            tv.column(col, width=w,
                      anchor="w" if w > 100 else "center")
        vsb.config(command=tv.yview)
        tv.pack(fill="both", expand=True)
        return tv

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — My Models
    # ═══════════════════════════════════════════════════════════════════════════
    t_mine = _tab("My Models")

    # Dir picker
    dir_row = tk.Frame(t_mine)
    dir_row.pack(fill="x", pady=(0, 6))
    tk.Label(dir_row, text="Models dir:", width=12, anchor="w").pack(side="left")
    v_mdir = tk.StringVar(value=cfg().get("models_dir", str(Path.home() / "models")))
    tk.Entry(dir_row, textvariable=v_mdir, width=50).pack(side="left", padx=4)

    def _refresh_mine():
        mdir = Path(v_mdir.get())
        active = cfg().get("active_model", "")
        ml.delete(*ml.get_children())

        # Load current router data to check membership
        router_names = set()
        try:
            rtr_path = default_models_ini_path()
            rtr_data = load_models_ini(rtr_path)
            router_names = {m["name"] for m in rtr_data.get("models", [])}
        except Exception:
            pass

        if not mdir.is_dir():
            mine_status.config(text=f"Not a directory: {mdir}")
            return
        files = sorted(mdir.glob("*.gguf"))
        for f in files:
            size_b = f.stat().st_size
            size_s = _fmt_size(size_b)
            is_act = str(f) == active
            mname = model_name_from_path(f.name)
            in_router = "R" if mname in router_names else ""
            ml.insert("", "end",
                      values=("✓" if is_act else "", f.name, size_s, in_router, str(f)),
                      tags=("active",) if is_act else ())
        ml.tag_configure("active", foreground="#56d364", font=("Helvetica", 9, "bold"))
        mine_status.config(text=f"{len(files)} model(s) in {mdir}")

    ttk.Button(dir_row, text="…",
               command=lambda: _browse_dir(v_mdir, _refresh_mine)).pack(side="left")
    ttk.Button(dir_row, text="↺ Refresh", command=_refresh_mine).pack(side="left", padx=4)

    ml = _scrolled_treeview(t_mine,
        columns=("active", "name", "size", "router", "path"),
        headings=("", "File name", "Size", "Router", "Full path"),
        widths=(30, 280, 80, 50, 400), height=16)

    mine_status = tk.Label(t_mine, text="", anchor="w", fg="#555", font=("Helvetica", 9))
    mine_status.pack(fill="x")

    def _activate_selected_mine():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][4]
        llama_config.set("active_model", str(path))
        if on_save:
            on_save()
        _refresh_mine()
        messagebox.showinfo("Activated",
                            f"{Path(path).name} set as active model.\n"
                            "Restart the server to load it.")

    def _delete_selected_mine():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][4]
        if messagebox.askyesno("Delete", f"Permanently delete:\n{Path(path).name}?"):
            try:
                Path(path).unlink()
                _refresh_mine()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _reveal_selected_mine():
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][4]
        _open_folder(Path(path).parent)

    def _toggle_router_mine():
        """Add or remove the selected model from the router preset."""
        sel = ml.selection()
        if not sel:
            return
        path = ml.item(sel[0])["values"][4]
        fname = ml.item(sel[0])["values"][1]
        mname = model_name_from_path(fname)

        rtr_path = default_models_ini_path()
        rtr_data = load_models_ini(rtr_path)
        existing = {m["name"] for m in rtr_data.get("models", [])}

        if mname in existing:
            remove_model_from_data(rtr_data, mname)
            save_models_ini(rtr_path, rtr_data)
        else:
            entry = make_model_entry(mname, local_path=str(path))
            add_model_to_data(rtr_data, entry)
            save_models_ini(rtr_path, rtr_data)

        _refresh_mine()

    act_row = tk.Frame(t_mine)
    act_row.pack(fill="x", pady=4)
    ttk.Button(act_row, text="✓  Set Active",       command=_activate_selected_mine).pack(side="left", padx=2)
    ttk.Button(act_row, text="📂  Reveal in Files", command=_reveal_selected_mine).pack(side="left", padx=2)
    ttk.Button(act_row, text="🗑  Delete",           command=_delete_selected_mine).pack(side="left", padx=2)
    ttk.Separator(act_row, orient="vertical").pack(side="left", fill="y", padx=6)
    ttk.Button(act_row, text="R  Toggle Router",
               command=lambda: _toggle_router_mine()).pack(side="left", padx=2)

    _refresh_mine()

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — HuggingFace Search
    # ═══════════════════════════════════════════════════════════════════════════
    t_hf = _tab("HuggingFace")

    # Search bar
    hf_search_row = tk.Frame(t_hf)
    hf_search_row.pack(fill="x", pady=(0, 4))
    tk.Label(hf_search_row, text="Search:", width=8, anchor="w").pack(side="left")
    v_hf_q = tk.StringVar(value=cfg().get("hf_search_query", "gguf"))
    hf_entry = tk.Entry(hf_search_row, textvariable=v_hf_q, width=36)
    hf_entry.pack(side="left", padx=4)
    hf_search_btn = ttk.Button(hf_search_row, text="Search")
    hf_search_btn.pack(side="left", padx=6)

    # Split pane: models left, files right
    panes = ttk.PanedWindow(t_hf, orient="horizontal")
    panes.pack(fill="both", expand=True, pady=4)

    left = tk.Frame(panes)
    panes.add(left, weight=2)
    tk.Label(left, text="Models", font=("Helvetica", 9, "bold")).pack(anchor="w")
    hf_model_sb = ttk.Scrollbar(left)
    hf_model_sb.pack(side="right", fill="y")
    hf_model_list = tk.Listbox(left, yscrollcommand=hf_model_sb.set,
                                font=("Courier", 9), activestyle="dotbox")
    hf_model_list.pack(fill="both", expand=True)
    hf_model_sb.config(command=hf_model_list.yview)

    right = tk.Frame(panes)
    panes.add(right, weight=3)
    tk.Label(right, text="GGUF Files", font=("Helvetica", 9, "bold")).pack(anchor="w")
    hf_file_cols = ("filename", "size")
    hf_file_tree = ttk.Treeview(right, columns=hf_file_cols,
                                  show="headings", selectmode="browse")
    hf_file_tree.heading("filename", text="File")
    hf_file_tree.heading("size",     text="Size")
    hf_file_tree.column("filename", width=380)
    hf_file_tree.column("size",     width=90, anchor="e")
    hf_file_sb = ttk.Scrollbar(right, command=hf_file_tree.yview)
    hf_file_tree.configure(yscrollcommand=hf_file_sb.set)
    hf_file_sb.pack(side="right", fill="y")
    hf_file_tree.pack(fill="both", expand=True)

    hf_status = tk.Label(t_hf, text="Enter a query and press Search.", anchor="w",
                          fg="#555", font=("Helvetica", 9))
    hf_status.pack(fill="x")

    # Download row
    hf_dl_row = tk.Frame(t_hf)
    hf_dl_row.pack(fill="x", pady=(2, 0))
    tk.Label(hf_dl_row, text="Save to:", anchor="w").pack(side="left")
    v_hf_dir = tk.StringVar(value=cfg().get("models_dir", str(Path.home() / "models")))
    tk.Entry(hf_dl_row, textvariable=v_hf_dir, width=36).pack(side="left", padx=4)
    ttk.Button(hf_dl_row, text="…",
               command=lambda: _browse_dir(v_hf_dir)).pack(side="left")
    hf_dl_btn = ttk.Button(hf_dl_row, text="⬇  Download & Activate", state="disabled")
    hf_dl_btn.pack(side="right", padx=4)
    hf_dl_prog = ttk.Progressbar(t_hf, mode="determinate")

    _hf_models: list[dict] = []
    _hf_files:  list[dict] = []
    _hf_repo:   dict = {}

    def _hf_api():
        tok = cfg().get("hf_token", "").strip() or None
        return HfApi(token=tok)

    def _hf_fmt_size(b):
        if b is None:
            return "?"
        for u in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {u}"
            b /= 1024
        return f"{b:.1f} TB"

    def _hf_do_search():
        q = v_hf_q.get().strip()
        if not q:
            return
        llama_config.set("hf_search_query", q)
        hf_model_list.delete(0, "end")
        hf_file_tree.delete(*hf_file_tree.get_children())
        hf_dl_btn.config(state="disabled")
        hf_status.config(text=f'Searching "{q}"…')
        hf_search_btn.config(state="disabled")

        def _do():
            try:
                api = _hf_api()
                models = list(api.list_models(
                    search=q, filter="gguf", limit=30,
                    sort="downloads", direction=-1,
                ))
                data = [{"id": m.id, "downloads": m.downloads or 0}
                        for m in models]
                nonlocal _hf_models
                _hf_models = data

                def _upd():
                    hf_model_list.delete(0, "end")
                    for m in data:
                        dl = m["downloads"]
                        k = f"{dl//1000}k" if dl >= 1000 else str(dl)
                        hf_model_list.insert("end", f"{'↓'+k:>7}  {m['id']}")
                    hf_status.config(text=f"{len(data)} models found.")
                    hf_search_btn.config(state="normal")
                root.after(0, _upd)
            except Exception as e:
                root.after(0, lambda: (
                    hf_status.config(text=f"Search error: {e}"),
                    hf_search_btn.config(state="normal"),
                ))
        threading.Thread(target=_do, daemon=True).start()

    def _hf_on_model_select(event):
        sel = hf_model_list.curselection()
        if not sel or sel[0] >= len(_hf_models):
            return
        repo = _hf_models[sel[0]]
        nonlocal _hf_repo
        _hf_repo = repo
        hf_file_tree.delete(*hf_file_tree.get_children())
        hf_dl_btn.config(state="disabled")
        hf_status.config(text=f"Loading files for {repo.get('id','')}…")

        def _do():
            try:
                api = _hf_api()
                info = api.repo_info(repo.get("id", ""))
                siblings = info.siblings or []
                files = [{"rfilename": s.rfilename, "size": s.size}
                         for s in siblings
                         if s.rfilename and s.rfilename.endswith(".gguf")]
                nonlocal _hf_files
                _hf_files = files

                def _upd():
                    hf_file_tree.delete(*hf_file_tree.get_children())
                    for f in files:
                        hf_file_tree.insert("", "end",
                            values=(f["rfilename"],
                                    _hf_fmt_size(f.get("size"))))
                    hf_status.config(text=f"{len(files)} GGUF file(s).")
                root.after(0, _upd)
            except Exception as e:
                root.after(0, lambda: hf_status.config(text=f"Error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def _hf_on_file_select(event):
        hf_dl_btn.config(state="normal" if hf_file_tree.selection() else "disabled")

    def _hf_do_download():
        sel = hf_file_tree.selection()
        if not sel or not _hf_repo:
            return
        filename = hf_file_tree.item(sel[0])["values"][0]
        repo_id  = _hf_repo.get("id", "")
        dest_dir = Path(v_hf_dir.get())
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest     = dest_dir / filename

        if dest.exists():
            if not messagebox.askyesno("Overwrite", f"{filename} exists. Overwrite?"):
                return

        hf_dl_btn.config(state="disabled")
        hf_dl_prog.pack(fill="x", pady=2)
        hf_dl_prog.config(mode="indeterminate")
        hf_dl_prog.start(10)

        def _do():
            try:
                hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(dest_dir),
                    token=cfg().get("hf_token", "").strip() or None,
                )
                root.after(0, lambda: _hf_finish(dest))
            except Exception as e:
                root.after(0, lambda: (
                    hf_status.config(text=f"Download error: {e}"),
                    hf_dl_btn.config(state="normal"),
                    hf_dl_prog.stop(),
                    hf_dl_prog.pack_forget(),
                ))

        def _hf_finish(path):
            hf_dl_prog.stop()
            hf_dl_prog.pack_forget()
            hf_dl_btn.config(state="normal")
            hf_status.config(text=f"✅  {path.name}")
            llama_config.update({
                "active_model": str(path),
                "models_dir":   str(dest_dir),
            })
            if on_save:
                on_save()
            _refresh_mine()
            messagebox.showinfo("Done", f"{path.name} downloaded and activated.")

        threading.Thread(target=_do, daemon=True).start()

    hf_search_btn.config(command=_hf_do_search)
    hf_entry.bind("<Return>", lambda e: _hf_do_search())
    hf_model_list.bind("<<ListboxSelect>>", _hf_on_model_select)
    hf_file_tree.bind("<<TreeviewSelect>>", _hf_on_file_select)
    hf_dl_btn.config(command=_hf_do_download)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — llmfit Browser
    # ═══════════════════════════════════════════════════════════════════════════
    t_lmf = _tab("llmfit")

    # Server control bar
    lmf_top = tk.Frame(t_lmf)
    lmf_top.pack(fill="x", pady=(0, 4))
    lmf_srv_lbl = tk.Label(lmf_top, text="○ llmfit server stopped",
                            fg="#dc3545", font=("Helvetica", 9, "bold"), anchor="w")
    lmf_srv_lbl.pack(side="left")
    lmf_hw_lbl = tk.Label(lmf_top, text="", fg="#555",
                           font=("Helvetica", 9), anchor="w")
    lmf_hw_lbl.pack(side="left", padx=10)

    _lmf_proc = [None]   # our own Popen handle, if we started it
    _lmf_rows: list[dict] = []

    def _lmf_binary():
        return (cfg().get("tool_llmfit_path", "").strip() or
                find_binary("llmfit"))

    def _lmf_update_status():
        if _llmfit_running():
            lmf_srv_lbl.config(text="● llmfit server running", fg="#28a745")
            lmf_start_btn.config(state="disabled")
            lmf_stop_btn.config(state="normal")
        else:
            lmf_srv_lbl.config(text="○ llmfit server stopped", fg="#dc3545")
            lmf_start_btn.config(state="normal")
            lmf_stop_btn.config(state="disabled")

    def _lmf_load_hw():
        def _do():
            gpu_name = vram_gb = ram_gb = None

            # Try nvidia-smi directly
            try:
                r = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=name,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and r.stdout.strip():
                    line = r.stdout.strip().split("\n")[0]
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        gpu_name = parts[0]
                        vram_gb = round(int(parts[1]) / 1024, 1)
            except Exception:
                pass

            # Try /proc/meminfo for RAM
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            ram_gb = round(kb / 1048576, 1)
                            break
            except Exception:
                pass

            # Fallback to llmfit API if direct detection missed something
            if gpu_name is None or ram_gb is None:
                d = _lmf_get("/api/v1/system")
                if d:
                    g = d.get("gpu", {})
                    if gpu_name is None:
                        gpu_name = g.get("name")
                    if vram_gb is None:
                        v = g.get("vram_gb")
                        if v is not None:
                            vram_gb = round(float(v), 1)
                    if ram_gb is None:
                        r = d.get("ram_gb")
                        if r is not None:
                            ram_gb = round(float(r), 1)

            parts = []
            if gpu_name:
                parts.append(f"GPU: {gpu_name}")
            if vram_gb is not None:
                parts.append(f"VRAM: {vram_gb} GB")
            if ram_gb is not None:
                parts.append(f"RAM: {ram_gb} GB")
            txt = "  ".join(parts) if parts else "Hardware info unavailable"
            root.after(0, lambda: lmf_hw_lbl.config(text=txt))
        threading.Thread(target=_do, daemon=True).start()

    def _lmf_start():
        b = _lmf_binary()
        if not b:
            messagebox.showerror("Not found",
                "llmfit not found. Set the path in Settings → Tool Paths.")
            return
        if _llmfit_running():
            _lmf_update_status()
            return
        try:
            _lmf_proc[0] = subprocess.Popen(
                [b, "serve", "--host", "127.0.0.1", "--port", str(LLMFIT_PORT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            messagebox.showerror("Launch error", str(e))
            return

        def _wait():
            for _ in range(24):
                time.sleep(0.5)
                if _llmfit_running():
                    root.after(0, _lmf_update_status)
                    root.after(0, _lmf_refresh)
                    return
            root.after(0, lambda: messagebox.showwarning("Timeout",
                "llmfit server didn't respond within 12 s."))
        threading.Thread(target=_wait, daemon=True).start()

    def _lmf_kill_by_port():
        """
        Kill whatever process is listening on LLMFIT_PORT.
        Works whether we started it or it was already running externally.
        """
        _kill_port(LLMFIT_PORT)

        # Also terminate our own Popen handle if we have one
        p = _lmf_proc[0]
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
        _lmf_proc[0] = None

    def _lmf_stop():
        lmf_stop_btn.config(state="disabled")
        lmf_srv_lbl.config(text="◌ stopping…", fg="#fd7e14")

        def _do_stop():
            _lmf_kill_by_port()
            # Wait up to 4 s for the port to actually free up
            for _ in range(8):
                time.sleep(0.5)
                if not _llmfit_running():
                    break
            root.after(0, _lmf_update_status)

        threading.Thread(target=_do_stop, daemon=True).start()

    ctrl_row = tk.Frame(lmf_top)
    ctrl_row.pack(side="right")
    lmf_start_btn = ttk.Button(ctrl_row, text="▶ Start llmfit server", command=_lmf_start)
    lmf_start_btn.pack(side="left", padx=2)
    lmf_stop_btn = ttk.Button(ctrl_row, text="⏹ Stop", command=_lmf_stop, state="disabled")
    lmf_stop_btn.pack(side="left")

    # Filters
    flt_row = tk.Frame(t_lmf)
    flt_row.pack(fill="x", pady=(0, 4))
    tk.Label(flt_row, text="Use case:").pack(side="left")
    v_lmf_uc = tk.StringVar(value="coding")
    ttk.Combobox(flt_row, textvariable=v_lmf_uc, width=11, state="readonly",
                 values=["coding","general","reasoning","chat","multimodal","embedding"]
                 ).pack(side="left", padx=4)
    tk.Label(flt_row, text="Min fit:").pack(side="left", padx=(6, 0))
    v_lmf_fit = tk.StringVar(value="marginal")
    ttk.Combobox(flt_row, textvariable=v_lmf_fit, width=9, state="readonly",
                 values=["perfect","good","marginal"]).pack(side="left", padx=4)
    tk.Label(flt_row, text="Limit:").pack(side="left", padx=(6, 0))
    v_lmf_lim = tk.IntVar(value=60)
    tk.Spinbox(flt_row, textvariable=v_lmf_lim, from_=5, to=300, width=5).pack(
        side="left", padx=4)
    tk.Label(flt_row, text="Filter:").pack(side="left", padx=(6, 0))
    v_lmf_filter = tk.StringVar()
    tk.Entry(flt_row, textvariable=v_lmf_filter, width=18).pack(side="left", padx=2)
    lmf_ref_btn = ttk.Button(flt_row, text="↺ Refresh", command=lambda: _lmf_refresh())
    lmf_ref_btn.pack(side="left", padx=6)

    # Table
    lmf_tv = _scrolled_treeview(t_lmf,
        columns=("name","fit","quant","tps","mem","ctx","params"),
        headings=("Model","Fit","Quant","tok/s","VRAM GB","Context","Params"),
        widths=(260,75,80,60,70,75,65), height=13)
    lmf_tv.tag_configure("perfect",  foreground="#56d364")
    lmf_tv.tag_configure("good",     foreground="#79c0ff")
    lmf_tv.tag_configure("marginal", foreground="#e3b341")
    lmf_tv.tag_configure("tootight", foreground="#ff7b72")

    lmf_status = tk.Label(t_lmf, text="Start the llmfit server to browse models.",
                           anchor="w", fg="#555", font=("Helvetica", 9))
    lmf_status.pack(fill="x")

    def _lmf_populate(rows):
        # Real llmfit API field names (from AlexsJones/llmfit API.md):
        #   fit_level / fit_label, estimated_tps, best_quant,
        #   memory_required_gb, context_length, params_b
        q = v_lmf_filter.get().strip().lower()
        lmf_tv.delete(*lmf_tv.get_children())
        shown = 0
        for m in rows:
            name  = m.get("name", m.get("id", ""))
            if q and q not in name.lower():
                continue
            fit   = m.get("fit_label",  m.get("fit_level", m.get("fit", "")))
            quant = m.get("best_quant", m.get("quant", m.get("quantization", "")))
            tps   = m.get("estimated_tps", m.get("speed_toks", m.get("tps", "")))
            mem   = m.get("memory_required_gb", m.get("vram_gb", m.get("memory_gb", "")))
            ctx   = m.get("context_length", m.get("context_size", ""))
            par   = m.get("params_b",    m.get("parameter_count", m.get("params", "")))
            tag   = fit.lower().replace(" ","").replace("-","").replace("+","")
            if tag not in ("perfect","good","marginal"):
                tag = "tootight"
            lmf_tv.insert("", "end",
                values=(name, fit, quant,
                        f"{tps:.0f}" if isinstance(tps, (int, float)) else str(tps),
                        f"{mem:.1f}" if isinstance(mem, (int, float)) else str(mem),
                        str(ctx), str(par)),
                tags=(tag,))
            shown += 1
        if shown == 0 and len(rows) > 0:
            lmf_status.config(text=f"0 shown — filter too strict? ({len(rows)} fetched)")
        else:
            lmf_status.config(text=f"{shown} of {len(rows)} models shown.")

    v_lmf_filter.trace_add("write", lambda *_: _lmf_populate(_lmf_rows))

    def _lmf_refresh():
        if not _llmfit_running():
            lmf_status.config(text="llmfit server not running.")
            return
        lmf_status.config(text="Fetching…")
        lmf_ref_btn.config(state="disabled")

        # Build params at call time (not before the widgets exist)
        def _do():
            params = urllib.parse.urlencode({
                "limit":    v_lmf_lim.get(),
                "min_fit":  v_lmf_fit.get(),
                "use_case": v_lmf_uc.get(),
            })
            data = _lmf_get(f"/api/v1/models/top?{params}", timeout=20)
            if data is None:
                root.after(0, lambda: lmf_status.config(
                    text="No response from llmfit — is it still starting up?"))
                root.after(0, lambda: lmf_ref_btn.config(state="normal"))
                return
            rows = data.get("models", [])
            nonlocal _lmf_rows
            _lmf_rows = rows
            root.after(0, lambda: _lmf_populate(rows))
            root.after(0, lambda: lmf_ref_btn.config(state="normal"))
        threading.Thread(target=_do, daemon=True).start()

    # Download panel
    lmf_dl = tk.LabelFrame(t_lmf, text="Download selected", padx=8, pady=4)
    lmf_dl.pack(fill="x", pady=(4, 0))
    lmf_dl.columnconfigure(1, weight=1)
    tk.Label(lmf_dl, text="Save to:", anchor="w", width=9).grid(row=0, column=0, sticky="w")
    v_lmf_dir = tk.StringVar(value=cfg().get("models_dir", str(Path.home() / "models")))
    tk.Entry(lmf_dl, textvariable=v_lmf_dir).grid(row=0, column=1, sticky="ew", padx=(0,4))
    ttk.Button(lmf_dl, text="…",
               command=lambda: _browse_dir(v_lmf_dir)).grid(row=0, column=2)

    lmf_dl_btn  = ttk.Button(lmf_dl, text="⬇  Download & Activate",
                              command=lambda: _lmf_download())
    lmf_dl_btn.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4,0))
    lmf_dl_lbl  = tk.Label(lmf_dl, text="", anchor="w", fg="#555", font=("Helvetica",9))
    lmf_dl_lbl.grid(row=1, column=1, columnspan=2, sticky="w", pady=(4,0))
    lmf_dl_prog = ttk.Progressbar(lmf_dl, mode="indeterminate")

    def _lmf_download():
        sel = lmf_tv.selection()
        if not sel:
            messagebox.showwarning("Select", "Select a model first.")
            return
        vals  = lmf_tv.item(sel[0])["values"]
        mname = vals[0]
        quant = vals[2]
        rec   = next((m for m in _lmf_rows
                      if m.get("name", m.get("id","")) == mname), {})
        hf_id = rec.get("hf_id", rec.get("id", ""))
        dst   = Path(v_lmf_dir.get())
        dst.mkdir(parents=True, exist_ok=True)

        lmf_dl_lbl.config(text=f"Preparing {mname}…")
        lmf_dl_prog.grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        lmf_dl_prog.start(10)
        lmf_dl_btn.config(state="disabled")

        def _worker():
            b = _lmf_binary()
            result_file = None
            ok = False

            if b and hf_id:
                try:
                    cmd = [b, "download", hf_id, "--quant", quant, "--dest", str(dst)]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    if proc.returncode == 0:
                        ggufs = sorted(dst.glob("*.gguf"),
                                       key=lambda f: f.stat().st_mtime)
                        if ggufs:
                            result_file = ggufs[-1]
                            ok = True
                except Exception:
                    pass

            def _done():
                lmf_dl_prog.stop()
                lmf_dl_prog.grid_remove()
                lmf_dl_btn.config(state="normal")
                if ok and result_file:
                    lmf_dl_lbl.config(text=f"✅  {result_file.name}")
                    llama_config.update({
                        "active_model": str(result_file),
                        "models_dir":   str(dst),
                    })
                    if on_save:
                        on_save()
                    _refresh_mine()
                    messagebox.showinfo("Done",
                        f"{result_file.name} downloaded and set as active model.")
                else:
                    lmf_dl_lbl.config(
                        text="Download failed — try HuggingFace tab or check llmfit logs.")

            root.after(0, _done)
        threading.Thread(target=_worker, daemon=True).start()

    root.after(600, _lmf_update_status)
    root.after(400, _lmf_load_hw)

    # snap and _detected_once used by TAB 4 (opencode) and TAB 5 (VS Code)
    snap = cfg()
    _detected_once = detect_tools(snap)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4 — opencode
    # ═══════════════════════════════════════════════════════════════════════════
    t_oc = _tab("opencode")
    t_oc.columnconfigure(1, weight=1)

    # ── Server selector for opencode ──────────────────────────────────────
    _oc_servers = llama_config.servers()
    _oc_server_names = [f"{s['name']} ({s['host']}:{s['port']})" for s in _oc_servers]
    _oc_selected_server = [None]  # mutable for closure

    _oc_sf_hdr = tk.LabelFrame(t_oc, text="Server", padx=8, pady=4)
    _oc_sf_hdr.pack(fill="x", pady=(0, 4))
    _oc_sf_hdr.columnconfigure(1, weight=1)
    tk.Label(_oc_sf_hdr, text="Configure for:", anchor="w").grid(row=0, column=0, sticky="w")
    _oc_server_var = tk.StringVar()
    _oc_server_cb = ttk.Combobox(_oc_sf_hdr, textvariable=_oc_server_var,
                                  values=_oc_server_names, state="readonly", width=36)
    _oc_server_cb.grid(row=0, column=1, sticky="w", padx=4)

    def _oc_on_server_select(_event=None):
        idx = _oc_server_cb.current()
        if idx < 0 or idx >= len(_oc_servers):
            return
        srv = _oc_servers[idx]
        _oc_selected_server[0] = srv
        # Update host/port from selected server
        v_oc_host.set(srv.get("host", "127.0.0.1"))
        v_oc_port.set(srv.get("port", 8080))
        v_oc_ctx.set(srv.get("ctx_size", 16384))
        m = srv.get("active_model", "")
        if m:
            stem = Path(m).stem
            v_oc_mid.set(stem)
            v_oc_name.set(stem.replace("-", " ").replace("_", " "))
        # Try to load existing provider for this server
        prov_key = "llama.cpp" if srv.get("is_local") else f"llama-{srv['name'].lower().replace(' ', '-')}"
        prov = oc_data.get("provider", {}).get(prov_key, {})
        if prov:
            url = prov.get("options", {}).get("baseURL", "")
            mu = re.match(r"http://([^:/]+):(\d+)/v1", url)
            if mu:
                v_oc_host.set(mu.group(1))
                v_oc_port.set(int(mu.group(2)))
            mods = prov.get("models", {})
            if mods:
                mid = next(iter(mods))
                v_oc_mid.set(mid)
                v_oc_name.set(mods[mid].get("name", mid))

    _oc_server_cb.bind("<<ComboboxSelected>>", _oc_on_server_select)

    oc_cfg_path_str = (snap.get("tool_opencode_config") or str(OPENCODE_CONFIG_DEFAULT))
    oc_auth_path_str = str(OPENCODE_AUTH_DEFAULT)
    oc_data   = _rw_json(Path(oc_cfg_path_str))
    oc_prov   = oc_data.get("provider", {}).get("llama.cpp", {})
    oc_mods   = oc_prov.get("models", {})
    first_mid = next(iter(oc_mods), "")
    first_mod = oc_mods.get(first_mid, {})
    oc_url    = oc_prov.get("options", {}).get("baseURL", "")
    _mu = re.match(r"http://([^:/]+):(\d+)/v1", oc_url)
    ex_host   = _mu.group(1) if _mu else snap.get("host", "127.0.0.1")
    ex_port   = int(_mu.group(2)) if _mu else snap.get("port", 8080)

    oc_sf = tk.LabelFrame(t_oc, text="Status", padx=8, pady=4)
    oc_sf.pack(fill="x", pady=(0, 8))
    oc_bin = snap.get("tool_opencode_path") or _detected_once.get("opencode")
    _badge(oc_sf, f"opencode: {oc_bin or 'not found'}", bool(oc_bin))
    _badge(oc_sf, f"Config:   {oc_cfg_path_str}", Path(oc_cfg_path_str).exists())
    _badge(oc_sf, f"Auth:     {oc_auth_path_str}", Path(oc_auth_path_str).exists())

    pf = tk.LabelFrame(t_oc, text="llama.cpp Provider", padx=10, pady=8)
    pf.pack(fill="x", pady=4)
    pf.columnconfigure(1, weight=1)

    _lbl(pf, "Host",              0)
    v_oc_host = _strvar(pf, 0, ex_host, width=20)
    _lbl(pf, "Port",              1)
    v_oc_port = _intvar(pf, 1, ex_port, from_=1, to=65535)
    _lbl(pf, "Model ID",          2)
    v_oc_mid  = _strvar(pf, 2, first_mid or "local-model")
    _lbl(pf, "Display name",      3)
    v_oc_name = _strvar(pf, 3, first_mod.get("name", "Local Model"))
    _lbl(pf, "Context (tokens)",  4)
    v_oc_ctx  = _intvar(pf, 4, first_mod.get("limit",{}).get("context", 16384))
    _lbl(pf, "Max output",        5)
    v_oc_out  = _intvar(pf, 5, first_mod.get("limit",{}).get("output",   8192))
    v_oc_def  = tk.BooleanVar(
        value=oc_data.get("model","").startswith("llama.cpp/"))
    tk.Checkbutton(pf, text='Set as default model ("llama.cpp/<id>")',
                   variable=v_oc_def).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=4)

    def _oc_sync():
        srv = _oc_selected_server[0]
        if srv:
            v_oc_host.set(srv.get("host", "127.0.0.1"))
            v_oc_port.set(srv.get("port", 8080))
            v_oc_ctx.set(srv.get("ctx_size", 16384))
            m = srv.get("active_model", "")
            if m:
                stem = Path(m).stem
                v_oc_mid.set(stem)
                v_oc_name.set(stem.replace("-", " ").replace("_", " "))
            # Pull API key from server config
            v_oc_apikey.set(srv.get("api_key", ""))
        else:
            # Fallback to global config
            c = cfg()
            v_oc_host.set(c.get("host", "127.0.0.1"))
            v_oc_port.set(c.get("port", 8080))
            v_oc_ctx.set(c.get("ctx_size", 16384))
            m = c.get("active_model", "")
            if m:
                stem = Path(m).stem
                v_oc_mid.set(stem)
                v_oc_name.set(stem.replace("-", " ").replace("_", " "))
    ttk.Button(t_oc, text="↻ Sync from server config", command=_oc_sync
               ).pack(anchor="w", pady=4)

    # ── auth.json section ─────────────────────────────────────────────────
    auth_sf = tk.LabelFrame(t_oc, text="Credentials (auth.json)", padx=10, pady=6)
    auth_sf.pack(fill="x", pady=4)
    auth_sf.columnconfigure(1, weight=1)

    oc_auth_data = _rw_json(Path(oc_auth_path_str))
    existing_key = oc_auth_data.get("llama.cpp", {}).get("apiKey", "")

    _lbl(auth_sf, "API key", 0)
    v_oc_apikey = _strvar(auth_sf, 0, existing_key, width=36)
    tk.Label(auth_sf, text="For local llama.cpp, any value works (or leave empty).",
             fg="#888", font=("Helvetica", 8), anchor="w").grid(
        row=1, column=0, columnspan=2, sticky="w")

    # ── Preview ───────────────────────────────────────────────────────────
    tk.Label(t_oc, text="Config preview (merged with existing):", fg="#888",
             font=("Helvetica", 8), anchor="w").pack(anchor="w")
    oc_prev = _code_box(t_oc, height=8)

    def _oc_refresh(*_):
        try:
            # Start from the existing config on disk
            merged = _rw_json(Path(oc_cfg_path_str))
            merged["$schema"] = "https://opencode.ai/config.json"
            merged.setdefault("provider", {})

            # Determine provider key based on selected server
            srv = _oc_selected_server[0]
            if srv:
                prov_key = "llama.cpp" if srv.get("is_local") else f"llama-{srv['name'].lower().replace(' ', '-')}"
                prov_name = f"llama-server ({srv['name']})"
            else:
                prov_key = "llama.cpp"
                prov_name = "llama-server (local)"

            # Build the llama.cpp provider block
            block = {
                "npm": "@ai-sdk/openai-compatible",
                "name": prov_name,
                "options": {"baseURL": f"http://{v_oc_host.get()}:{v_oc_port.get()}/v1"},
                "models": {v_oc_mid.get(): {
                    "name": v_oc_name.get(),
                    "limit": {"context": int(v_oc_ctx.get()),
                              "output":  int(v_oc_out.get())}
                }}
            }
            merged["provider"][prov_key] = block

            if v_oc_def.get():
                merged["model"] = f"{prov_key}/{v_oc_mid.get()}"
            elif merged.get("model", "").startswith(("llama.cpp/", "llama-")):
                del merged["model"]

            _code_put(oc_prev, json.dumps(merged, indent=2))
        except Exception as e:
            _code_put(oc_prev, f"(error: {e})")

    for v in (v_oc_host, v_oc_mid, v_oc_name):
        v.trace_add("write", _oc_refresh)
    for v in (v_oc_port, v_oc_ctx, v_oc_out):
        v.trace_add("write", _oc_refresh)
    v_oc_def.trace_add("write", _oc_refresh)
    _oc_refresh()

    def _oc_save():
        try:
            # Determine provider key based on selected server
            srv = _oc_selected_server[0]
            if srv:
                prov_key = "llama.cpp" if srv.get("is_local") else f"llama-{srv['name'].lower().replace(' ', '-')}"
                prov_name = f"llama-server ({srv['name']})"
            else:
                prov_key = "llama.cpp"
                prov_name = "llama-server (local)"

            # ── Save config.json ──────────────────────────────────────────
            dst = Path(snap.get("tool_opencode_config") or str(OPENCODE_CONFIG_DEFAULT))
            data = _rw_json(dst)
            data["$schema"] = "https://opencode.ai/config.json"
            data.setdefault("provider", {})
            data["provider"][prov_key] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": prov_name,
                "options": {"baseURL": f"http://{v_oc_host.get()}:{v_oc_port.get()}/v1"},
                "models": {v_oc_mid.get(): {
                    "name": v_oc_name.get(),
                    "limit": {"context": int(v_oc_ctx.get()),
                              "output":  int(v_oc_out.get())}
                }}
            }
            if v_oc_def.get():
                data["model"] = f"{prov_key}/{v_oc_mid.get()}"
            elif data.get("model", "").startswith(("llama.cpp/", "llama-")):
                del data["model"]
            _write_json(dst, data)

            # ── Save auth.json ────────────────────────────────────────────
            auth_dst = Path(oc_auth_path_str)
            auth_data = _rw_json(auth_dst)
            # Prefer server's API key, fall back to manually-entered value
            api_key = (srv.get("api_key", "") if srv else "").strip() or v_oc_apikey.get().strip()
            if api_key:
                auth_data.setdefault(prov_key, {})
                auth_data[prov_key]["apiKey"] = api_key
            elif prov_key in auth_data:
                del auth_data[prov_key]
            if auth_data:
                _write_json(auth_dst, auth_data)
            elif auth_dst.exists():
                auth_dst.unlink()

            msg = f"Config written:\n{dst}"
            if api_key:
                msg += f"\n\nAuth written:\n{auth_dst}"
            messagebox.showinfo("Saved", msg)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ttk.Button(t_oc, text="💾  Save config + auth", command=_oc_save
               ).pack(anchor="e", pady=6)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 5 — VS Code
    # ═══════════════════════════════════════════════════════════════════════════
    t_vsc = _tab("VS Code")
    t_vsc.columnconfigure(1, weight=1)

    # ── Server selector for VS Code ───────────────────────────────────────
    _vsc_servers = llama_config.servers()
    _vsc_server_names = [f"{s['name']} ({s['host']}:{s['port']})" for s in _vsc_servers]
    _vsc_selected_server = [None]  # mutable for closure

    _vsc_sf_hdr = tk.LabelFrame(t_vsc, text="Server", padx=8, pady=4)
    _vsc_sf_hdr.pack(fill="x", pady=(0, 4))
    _vsc_sf_hdr.columnconfigure(1, weight=1)
    tk.Label(_vsc_sf_hdr, text="Configure for:", anchor="w").grid(row=0, column=0, sticky="w")
    _vsc_server_var = tk.StringVar()
    _vsc_server_cb = ttk.Combobox(_vsc_sf_hdr, textvariable=_vsc_server_var,
                                   values=_vsc_server_names, state="readonly", width=36)
    _vsc_server_cb.grid(row=0, column=1, sticky="w", padx=4)

    def _vsc_on_server_select(_event=None):
        idx = _vsc_server_cb.current()
        if idx < 0 or idx >= len(_vsc_servers):
            return
        srv = _vsc_servers[idx]
        _vsc_selected_server[0] = srv
        # Update host/port from selected server
        v_vsc_host.set(srv.get("host", "127.0.0.1"))
        v_vsc_port.set(srv.get("port", 8080))
        v_vsc_in.set(srv.get("ctx_size", 4096))
        m = srv.get("active_model", "")
        if m:
            stem = Path(m).stem
            v_vsc_id.set(stem)
            v_vsc_dname.set(stem.replace("-", " ").replace("_", " "))
        # Pull API key from server config
        v_vsc_key.set(srv.get("api_key", "") or "not-required")
        # Update group name based on server
        group_name = "llama-local" if srv.get("is_local") else f"llama-{srv['name'].lower().replace(' ', '-')}"
        v_vsc_group.set(group_name)

    _vsc_server_cb.bind("<<ComboboxSelected>>", _vsc_on_server_select)

    # VS Code / derivative native custom endpoint config.
    # The chatLanguageModels.json format is shared by VS Code, VS Code OSS,
    # VSCodium, Cursor, Windsurf, Antigravity IDE, and any other derivative
    # that implements the BYOK language model API.
    #
    # Known config locations (auto-detected in order; first existing wins):
    _KNOWN_CONFIG_LOCATIONS = [
        # upstream VS Code
        Path.home() / ".config" / "Code"              / "User" / "chatLanguageModels.json",
        Path.home() / ".config" / "Code - OSS"        / "User" / "chatLanguageModels.json",
        # Insiders
        Path.home() / ".config" / "Code - Insiders"   / "User" / "chatLanguageModels.json",
        # VSCodium / VSCodium OSS
        Path.home() / ".config" / "VSCodium"           / "User" / "chatLanguageModels.json",
        Path.home() / ".config" / "VSCodium - OSS"     / "User" / "chatLanguageModels.json",
        # Cursor
        Path.home() / ".config" / "Cursor"             / "User" / "chatLanguageModels.json",
        # Windsurf
        Path.home() / ".config" / "Windsurf"           / "User" / "chatLanguageModels.json",
        # Google Antigravity IDE (reported path pattern)
        Path.home() / ".config" / "Antigravity"        / "User" / "chatLanguageModels.json",
        Path.home() / ".config" / "Google Antigravity" / "User" / "chatLanguageModels.json",
        # Generic lowercase variants
        Path.home() / ".config" / "code-insiders"      / "User" / "chatLanguageModels.json",
        Path.home() / ".config" / "vscodium"           / "User" / "chatLanguageModels.json",
    ]

    def _auto_detect_vsc_config() -> Path | None:
        """Return first existing known config path, or None."""
        for p in _KNOWN_CONFIG_LOCATIONS:
            if p.exists():
                return p
        return None

    # Resolve config path: saved override → auto-detect → first known path as fallback
    _saved_cfg   = snap.get("tool_vscode_config", "").strip()
    _auto_cfg    = _auto_detect_vsc_config()
    _vsc_cfg_initial = Path(_saved_cfg) if _saved_cfg else (_auto_cfg or _KNOWN_CONFIG_LOCATIONS[0])

    vsc_bin_path = snap.get("tool_vscode_path") or _detected_once.get("vscode")

    # ── Config path field (editable, at top of tab) ───────────────────────
    cfg_path_frame = tk.LabelFrame(t_vsc, text="Config file (chatLanguageModels.json)",
                                    padx=8, pady=6)
    cfg_path_frame.pack(fill="x", pady=(0, 6))
    cfg_path_frame.columnconfigure(1, weight=1)

    tk.Label(cfg_path_frame, text="Path:", anchor="w", width=8).grid(
        row=0, column=0, sticky="w")
    v_vsc_cfg_path = tk.StringVar(value=str(_vsc_cfg_initial))
    cfg_path_entry = tk.Entry(cfg_path_frame, textvariable=v_vsc_cfg_path)
    cfg_path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

    def _browse_vsc_cfg():
        p = filedialog.askopenfilename(
            title="Select chatLanguageModels.json",
            initialdir=str(Path(v_vsc_cfg_path.get()).parent),
            filetypes=[("JSON", "*.json"), ("All files", "*")],
        )
        if p:
            v_vsc_cfg_path.set(p)
            _vsc_update_status()
            llama_config.set("tool_vscode_config", p)

    ttk.Button(cfg_path_frame, text="…", command=_browse_vsc_cfg, width=3).grid(
        row=0, column=2)

    # Preset dropdown for known IDE variants
    tk.Label(cfg_path_frame, text="Preset:", anchor="w", width=8).grid(
        row=1, column=0, sticky="w", pady=(4, 0))
    _preset_labels = [
        "VS Code",
        "VS Code - OSS",
        "VS Code Insiders",
        "VSCodium",
        "VSCodium - OSS",
        "Cursor",
        "Windsurf",
        "Google Antigravity",
        "Other Google Antigravity",
        "code-insiders (lowercase)",
        "vscodium (lowercase)",
    ]
    preset_var = tk.StringVar(value="— pick a preset —")
    preset_cb = ttk.Combobox(cfg_path_frame, textvariable=preset_var,
                              values=_preset_labels, state="readonly", width=28)
    preset_cb.grid(row=1, column=1, sticky="w", pady=(4, 0))

    def _on_preset(event=None):
        idx = _preset_labels.index(preset_var.get()) if preset_var.get() in _preset_labels else -1
        if idx >= 0:
            v_vsc_cfg_path.set(str(_KNOWN_CONFIG_LOCATIONS[idx]))
            _vsc_update_status()

    preset_cb.bind("<<ComboboxSelected>>", _on_preset)

    # Status badges (update dynamically as path changes)
    vsc_sf = tk.LabelFrame(t_vsc, text="Status", padx=8, pady=4)
    vsc_sf.pack(fill="x", pady=(0, 6))
    vsc_bin_lbl = tk.Label(vsc_sf, text="", anchor="w", font=("Helvetica", 9, "bold"))
    vsc_bin_lbl.pack(anchor="w", pady=1)
    vsc_cfg_lbl = tk.Label(vsc_sf, text="", anchor="w", font=("Helvetica", 9, "bold"))
    vsc_cfg_lbl.pack(anchor="w", pady=1)
    tk.Label(vsc_sf,
             text=(
                 "Writes to chatLanguageModels.json - VS Code native BYOK format.\n"
                 "Works with VS Code, VSCodium, Cursor, Windsurf, Antigravity, and derivatives."
             ),
             fg="#888", font=("Helvetica", 8), justify="left").pack(anchor="w")

    def _vsc_update_status(*_):
        p = Path(v_vsc_cfg_path.get().strip()) if v_vsc_cfg_path.get().strip() else None
        exists = p and p.exists() if p else False
        bin_ok = bool(vsc_bin_path)
        vsc_bin_lbl.config(
            text=("● " if bin_ok else "○ ") + f"Binary: {vsc_bin_path or 'not found'}",
            fg="#28a745" if bin_ok else "#dc3545")
        vsc_cfg_lbl.config(
            text=("● " if exists else "○ ") + f"Config: {p or 'not set'}",
            fg="#28a745" if exists else "#e3b341")  # yellow = path set but not created yet

    v_vsc_cfg_path.trace_add("write", _vsc_update_status)
    _vsc_update_status()

    pf_vsc = tk.LabelFrame(t_vsc, text="Custom Endpoint Model", padx=10, pady=8)
    pf_vsc.pack(fill="x", pady=4)
    pf_vsc.columnconfigure(1, weight=1)

    active_m = snap.get("active_model", "")
    m_stem   = Path(active_m).stem if active_m else ""

    _lbl(pf_vsc, "Group name",      0)
    v_vsc_group = _strvar(pf_vsc, 0, "llama-local", width=24)
    _lbl(pf_vsc, "Host",            1)
    v_vsc_host  = _strvar(pf_vsc, 1, snap.get("host", "127.0.0.1"), width=20)
    _lbl(pf_vsc, "Port",            2)
    v_vsc_port  = _intvar(pf_vsc, 2, snap.get("port", 8080), from_=1, to=65535)
    _lbl(pf_vsc, "Model ID",        3)
    v_vsc_id    = _strvar(pf_vsc, 3, m_stem or "local-model")
    _lbl(pf_vsc, "Display name",    4)
    v_vsc_dname = _strvar(pf_vsc, 4, m_stem.replace("-"," ").replace("_"," ") if m_stem else "Local Model")
    _lbl(pf_vsc, "API key",         5)
    v_vsc_key   = _strvar(pf_vsc, 5, "not-required", width=24)
    _lbl(pf_vsc, "Max input tokens", 6)
    v_vsc_in    = _intvar(pf_vsc, 6, snap.get("ctx_size", 4096), from_=512, to=262144)
    _lbl(pf_vsc, "Max output tokens", 7)
    v_vsc_out   = _intvar(pf_vsc, 7, 4096, from_=512, to=65536)
    v_vsc_tools = tk.BooleanVar(value=True)
    tk.Checkbutton(pf_vsc, text="Tool calling (required for agent mode)",
                   variable=v_vsc_tools).grid(
        row=8, column=0, columnspan=2, sticky="w", pady=4)

    def _vsc_sync():
        srv = _vsc_selected_server[0]
        if srv:
            v_vsc_host.set(srv.get("host", "127.0.0.1"))
            v_vsc_port.set(srv.get("port", 8080))
            v_vsc_in.set(srv.get("ctx_size", 4096))
            m = srv.get("active_model", "")
            if m:
                stem = Path(m).stem
                v_vsc_id.set(stem)
                v_vsc_dname.set(stem.replace("-", " ").replace("_", " "))
            v_vsc_key.set(srv.get("api_key", "") or "not-required")
            group_name = "llama-local" if srv.get("is_local") else f"llama-{srv['name'].lower().replace(' ', '-')}"
            v_vsc_group.set(group_name)
        else:
            # Fallback to global config
            c = cfg()
            v_vsc_host.set(c.get("host", "127.0.0.1"))
            v_vsc_port.set(c.get("port", 8080))
            v_vsc_in.set(c.get("ctx_size", 4096))
            m = c.get("active_model", "")
            if m:
                stem = Path(m).stem
                v_vsc_id.set(stem)
                v_vsc_dname.set(stem.replace("-", " ").replace("_", " "))
    ttk.Button(t_vsc, text="↻ Sync from server config", command=_vsc_sync
               ).pack(anchor="w", pady=(4,0))

    tk.Label(t_vsc, text="Preview:", fg="#888", font=("Helvetica", 8),
             anchor="w").pack(anchor="w")
    vsc_prev = _code_box(t_vsc, height=8)

    def _vsc_entry() -> dict:
        return {
            "id":             v_vsc_id.get().strip(),
            "name":           v_vsc_dname.get().strip(),
            "url":            f"http://{v_vsc_host.get().strip()}:{v_vsc_port.get()}/v1",
            "apiKey":         v_vsc_key.get().strip(),
            "maxInputTokens": int(v_vsc_in.get()),
            "maxOutputTokens":int(v_vsc_out.get()),
            "toolCalling":    v_vsc_tools.get(),
        }

    def _vsc_group_block() -> dict:
        return {
            "name":    v_vsc_group.get().strip(),
            "vendor":  "customendpoint",
            "models":  [_vsc_entry()],
        }

    def _vsc_refresh_preview(*_):
        try:
            snippet = [_vsc_group_block()]
            _code_put(vsc_prev, json.dumps(snippet, indent=2))
        except Exception as e:
            _code_put(vsc_prev, f"(error: {e})")

    for v in (v_vsc_group, v_vsc_host, v_vsc_id, v_vsc_dname, v_vsc_key):
        v.trace_add("write", _vsc_refresh_preview)
    for v in (v_vsc_port, v_vsc_in, v_vsc_out):
        v.trace_add("write", _vsc_refresh_preview)
    v_vsc_tools.trace_add("write", _vsc_refresh_preview)
    _vsc_refresh_preview()

    def _vsc_save():
        try:
            dst = Path(v_vsc_cfg_path.get().strip()) if v_vsc_cfg_path.get().strip()                   else _KNOWN_CONFIG_LOCATIONS[0]
            # Persist the chosen path to config
            llama_config.set("tool_vscode_config", str(dst))
            # Read existing array
            existing = []
            if dst.exists():
                try:
                    existing = json.loads(dst.read_text("utf-8"))
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []

            new_group = _vsc_group_block()
            group_name = new_group["name"]
            model_id   = new_group["models"][0]["id"]

            # Find or create the provider group
            group_idx = next((i for i, g in enumerate(existing)
                              if g.get("name") == group_name), None)
            if group_idx is not None:
                # Merge model into existing group (replace if same id)
                grp = existing[group_idx]
                models = grp.get("models", [])
                models = [m for m in models if m.get("id") != model_id]
                models.append(new_group["models"][0])
                grp["models"] = models
            else:
                existing.append(new_group)

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(existing, indent=2), "utf-8")
            messagebox.showinfo(
                "Saved",
                f"chatLanguageModels.json updated:\n{dst}\n\n"
                "In VS Code: open the model picker → your model will appear\n"
                "under the group \"{group_name}\"."
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ttk.Button(t_vsc, text="💾  Write to chatLanguageModels.json", command=_vsc_save
               ).pack(anchor="e", pady=6)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 6 — Model Router
    # ═══════════════════════════════════════════════════════════════════════════
    t_rtr = _tab("Model Router")

    # ── INI file path selector ────────────────────────────────────────────
    rtr_path_row = tk.Frame(t_rtr)
    rtr_path_row.pack(fill="x", pady=(0, 6))
    tk.Label(rtr_path_row, text="INI file:", width=10, anchor="w").pack(side="left")
    v_rtr_ini = tk.StringVar(value=str(default_models_ini_path()))
    tk.Entry(rtr_path_row, textvariable=v_rtr_ini, width=50).pack(side="left", padx=4)
    ttk.Button(rtr_path_row, text="…",
               command=lambda: _browse_file(v_rtr_ini, [("INI", "*.ini"), ("All", "*")])
               ).pack(side="left")

    # ── Split: left = defaults + model list, right = editor + preview ─────
    rtr_panes = ttk.PanedWindow(t_rtr, orient="horizontal")
    rtr_panes.pack(fill="both", expand=True, pady=4)

    # Left pane: global defaults + model list
    rtr_left = tk.Frame(rtr_panes)
    rtr_panes.add(rtr_left, weight=1)

    # Global defaults
    rtr_def_frame = tk.LabelFrame(rtr_left, text="Global defaults ([*])", padx=6, pady=4)
    rtr_def_frame.pack(fill="x", pady=(0, 4))
    rtr_def_frame.columnconfigure(1, weight=1)

    tk.Label(rtr_def_frame, text="Context size", anchor="w", width=12).grid(
        row=0, column=0, sticky="w", pady=2)
    v_rtr_def_ctx = tk.StringVar(value="4096")
    tk.Entry(rtr_def_frame, textvariable=v_rtr_def_ctx, width=10).grid(
        row=0, column=1, sticky="w", pady=2)

    tk.Label(rtr_def_frame, text="GPU layers", anchor="w", width=12).grid(
        row=1, column=0, sticky="w", pady=2)
    v_rtr_def_ngl = tk.StringVar(value="0")
    tk.Entry(rtr_def_frame, textvariable=v_rtr_def_ngl, width=10).grid(
        row=1, column=1, sticky="w", pady=2)

    tk.Label(rtr_def_frame, text="Temperature", anchor="w", width=12).grid(
        row=2, column=0, sticky="w", pady=2)
    v_rtr_def_temp = tk.StringVar(value="0.7")
    tk.Entry(rtr_def_frame, textvariable=v_rtr_def_temp, width=10).grid(
        row=2, column=1, sticky="w", pady=2)

    tk.Label(rtr_def_frame, text="Extra params", anchor="w", width=12).grid(
        row=3, column=0, sticky="w", pady=2)
    v_rtr_def_extra = tk.StringVar(value="")
    tk.Entry(rtr_def_frame, textvariable=v_rtr_def_extra, width=24).grid(
        row=3, column=1, sticky="ew", pady=2)
    tk.Label(rtr_def_frame, text="key=value pairs, one per line",
             fg="#888", font=("Helvetica", 8)).grid(row=4, column=1, sticky="w")

    # Model list
    tk.Label(rtr_left, text="Models:", font=("Helvetica", 9, "bold"),
             anchor="w").pack(anchor="w", pady=(4, 2))
    rtr_model_list = tk.Listbox(rtr_left, height=12, font=("Courier", 9))
    rtr_model_list.pack(fill="both", expand=True)

    rtr_model_btn_row = tk.Frame(rtr_left)
    rtr_model_btn_row.pack(fill="x", pady=(2, 0))
    ttk.Button(rtr_model_btn_row, text="+ Add from file",
               command=lambda: _rtr_add_from_file()).pack(side="left", padx=2)
    ttk.Button(rtr_model_btn_row, text="+ Add HF repo",
               command=lambda: _rtr_add_hf()).pack(side="left", padx=2)
    ttk.Button(rtr_model_btn_row, text="- Remove",
               command=lambda: _rtr_remove()).pack(side="left", padx=2)
    ttk.Button(rtr_model_btn_row, text="Toggle active",
               command=lambda: _rtr_toggle()).pack(side="left", padx=2)

    # Right pane: selected model editor + preview
    rtr_right = tk.Frame(rtr_panes)
    rtr_panes.add(rtr_right, weight=2)

    # Model editor (shown when a model is selected)
    rtr_editor = tk.LabelFrame(rtr_right, text="Model settings", padx=8, pady=6)
    rtr_editor.pack(fill="x", pady=(0, 4))
    rtr_editor.columnconfigure(1, weight=1)

    tk.Label(rtr_editor, text="Name", anchor="w", width=12).grid(
        row=0, column=0, sticky="w", pady=2)
    v_rtr_mname = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mname, width=30).grid(
        row=0, column=1, sticky="ew", pady=2)

    tk.Label(rtr_editor, text="HF repo:tag", anchor="w", width=12).grid(
        row=1, column=0, sticky="w", pady=2)
    v_rtr_mhf = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mhf, width=30).grid(
        row=1, column=1, sticky="ew", pady=2)
    tk.Label(rtr_editor, text="e.g.bartowski/Llama-3-8B-GGUF:Q4_K_M",
             fg="#888", font=("Helvetica", 8)).grid(row=2, column=1, sticky="w")

    tk.Label(rtr_editor, text="Local model", anchor="w", width=12).grid(
        row=3, column=0, sticky="w", pady=2)
    v_rtr_mlocal = tk.StringVar(value="")
    rtr_local_row = tk.Frame(rtr_editor)
    rtr_local_row.grid(row=3, column=1, sticky="ew", pady=2)
    tk.Entry(rtr_local_row, textvariable=v_rtr_mlocal, width=24).pack(
        side="left", fill="x", expand=True)
    ttk.Button(rtr_local_row, text="…", width=3,
               command=lambda: _browse_file(v_rtr_mlocal, [("GGUF", "*.gguf"), ("All", "*")])
               ).pack(side="left", padx=2)

    tk.Label(rtr_editor, text="Context size", anchor="w", width=12).grid(
        row=4, column=0, sticky="w", pady=2)
    v_rtr_mctx = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mctx, width=10).grid(
        row=4, column=1, sticky="w", pady=2)

    tk.Label(rtr_editor, text="GPU layers", anchor="w", width=12).grid(
        row=5, column=0, sticky="w", pady=2)
    v_rtr_mngl = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mngl, width=10).grid(
        row=5, column=1, sticky="w", pady=2)

    tk.Label(rtr_editor, text="Temperature", anchor="w", width=12).grid(
        row=6, column=0, sticky="w", pady=2)
    v_rtr_mtemp = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mtemp, width=10).grid(
        row=6, column=1, sticky="w", pady=2)

    tk.Label(rtr_editor, text="Extra params", anchor="w", width=12).grid(
        row=7, column=0, sticky="w", pady=2)
    v_rtr_mextra = tk.StringVar(value="")
    tk.Entry(rtr_editor, textvariable=v_rtr_mextra, width=30).grid(
        row=7, column=1, sticky="ew", pady=2)
    tk.Label(rtr_editor, text="key=value pairs, one per line",
             fg="#888", font=("Helvetica", 8)).grid(row=8, column=1, sticky="w")

    ttk.Button(rtr_editor, text="Apply changes",
               command=lambda: _rtr_apply_model()).grid(row=9, column=1, sticky="w", pady=(4, 0))

    # Preview
    tk.Label(rtr_right, text="Preview:", fg="#888", font=("Helvetica", 8),
             anchor="w").pack(anchor="w", pady=(4, 0))
    rtr_preview = _code_box(rtr_right, height=10)

    # Status
    rtr_status = tk.Label(t_rtr, text="", anchor="w", fg="#555", font=("Helvetica", 9))
    rtr_status.pack(fill="x")

    # ── Router data state ─────────────────────────────────────────────────
    _rtr_data = {"version": 1, "defaults": {}, "models": []}
    _rtr_selected_idx = None  # index into _rtr_data["models"]

    def _rtr_load():
        """Load models.ini into _rtr_data and refresh UI."""
        nonlocal _rtr_data
        path = Path(v_rtr_ini.get())
        _rtr_data = load_models_ini(path)

        # Populate defaults
        d = _rtr_data.get("defaults", {})
        v_rtr_def_ctx.set(d.get("c", "4096"))
        v_rtr_def_ngl.set(d.get("n-gpu-layers", "0"))
        v_rtr_def_temp.set(d.get("temp", "0.7"))
        # Extra params: everything except the known keys
        known = {"c", "n-gpu-layers", "temp"}
        extra_parts = [f"{k}={v}" for k, v in d.items() if k not in known]
        v_rtr_def_extra.set("\n".join(extra_parts))

        _rtr_refresh_list()
        _rtr_update_preview()

    def _rtr_refresh_list():
        """Refresh the model listbox from _rtr_data."""
        rtr_model_list.delete(0, tk.END)
        for m in _rtr_data.get("models", []):
            marker = "●" if m.get("active", True) else "○"
            rtr_model_list.insert(tk.END, f" {marker} {m['name']}")
        rtr_status.config(
            text=f"{len(_rtr_data.get('models', []))} model(s) in router preset")

    def _rtr_update_preview():
        """Update the INI preview from current state."""
        _sync_defaults_to_data()
        txt = models_ini_as_text(_rtr_data)
        _code_put(rtr_preview, txt)

    def _sync_defaults_to_data():
        """Push the defaults UI fields back into _rtr_data."""
        defaults = {}
        ctx = v_rtr_def_ctx.get().strip()
        if ctx:
            defaults["c"] = ctx
        ngl = v_rtr_def_ngl.get().strip()
        if ngl:
            defaults["n-gpu-layers"] = ngl
        temp = v_rtr_def_temp.get().strip()
        if temp:
            defaults["temp"] = temp
        # Parse extra params
        for line in v_rtr_def_extra.get().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                defaults[k.strip()] = v.strip()
        _rtr_data["defaults"] = defaults

    def _rtr_on_select(_event):
        """Show editor for selected model."""
        nonlocal _rtr_selected_idx
        sel = rtr_model_list.curselection()
        if not sel:
            _rtr_selected_idx = None
            return
        idx = sel[0]
        if idx >= len(_rtr_data.get("models", [])):
            _rtr_selected_idx = None
            return
        _rtr_selected_idx = idx
        m = _rtr_data["models"][idx]
        params = m.get("params", {})
        v_rtr_mname.set(m["name"])
        v_rtr_mhf.set(params.get("hf", ""))
        v_rtr_mlocal.set(params.get("model", ""))
        v_rtr_mctx.set(params.get("c", ""))
        v_rtr_mngl.set(params.get("n-gpu-layers", ""))
        v_rtr_mtemp.set(params.get("temp", ""))
        # Extra params
        known = {"hf", "model", "c", "n-gpu-layers", "temp"}
        extra_parts = [f"{k}={v}" for k, v in params.items() if k not in known]
        v_rtr_mextra.set("\n".join(extra_parts))

    rtr_model_list.bind("<<ListboxSelect>>", _rtr_on_select)

    def _rtr_apply_model():
        """Push editor fields back into the selected model."""
        if _rtr_selected_idx is None:
            return
        m = _rtr_data["models"][_rtr_selected_idx]
        m["name"] = v_rtr_mname.get().strip() or m["name"]
        params = {}
        hf = v_rtr_mhf.get().strip()
        if hf:
            params["hf"] = hf
        local = v_rtr_mlocal.get().strip()
        if local:
            params["model"] = local
        ctx = v_rtr_mctx.get().strip()
        if ctx:
            params["c"] = ctx
        ngl = v_rtr_mngl.get().strip()
        if ngl:
            params["n-gpu-layers"] = ngl
        temp = v_rtr_mtemp.get().strip()
        if temp:
            params["temp"] = temp
        for line in v_rtr_mextra.get().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                params[k.strip()] = v.strip()
        m["params"] = params
        _rtr_refresh_list()
        _rtr_update_preview()
        # Re-select to keep editor in sync
        rtr_model_list.selection_set(_rtr_selected_idx)

    def _rtr_add_from_file():
        """Add a local GGUF model to the router."""
        mdir = Path(cfg().get("models_dir", str(Path.home() / "models")))
        p = filedialog.askopenfilename(
            initialdir=str(mdir) if mdir.is_dir() else str(Path.home()),
            filetypes=[("GGUF", "*.gguf"), ("All files", "*")])
        if not p:
            return
        name = model_name_from_path(p)
        entry = make_model_entry(name, local_path=p)
        add_model_to_data(_rtr_data, entry)
        _rtr_refresh_list()
        _rtr_update_preview()

    def _rtr_add_hf():
        """Add a HuggingFace model to the router."""
        from tkinter import simpledialog
        hf_id = simpledialog.askstring(
            "HuggingFace model",
            "Enter HF repo:tag\n(e.g. bartowski/Llama-3-8B-GGUF:Q4_K_M)")
        if not hf_id:
            return
        # Use last path component as name
        parts = hf_id.split(":")
        name = parts[0].split("/")[-1]
        if len(parts) > 1:
            name += "-" + parts[1]
        entry = make_model_entry(name, hf=hf_id)
        add_model_to_data(_rtr_data, entry)
        _rtr_refresh_list()
        _rtr_update_preview()

    def _rtr_remove():
        """Remove selected model from router."""
        if _rtr_selected_idx is None:
            return
        name = _rtr_data["models"][_rtr_selected_idx]["name"]
        if messagebox.askyesno("Remove", f"Remove '{name}' from router?"):
            remove_model_from_data(_rtr_data, name)
            _rtr_selected_idx = None
            _rtr_refresh_list()
            _rtr_update_preview()

    def _rtr_toggle():
        """Toggle active/inactive for selected model."""
        if _rtr_selected_idx is None:
            return
        m = _rtr_data["models"][_rtr_selected_idx]
        toggle_model_active(_rtr_data, m["name"], not m.get("active", True))
        _rtr_refresh_list()
        _rtr_update_preview()
        # Update selection
        rtr_model_list.selection_set(_rtr_selected_idx)

    def _rtr_save():
        """Write models.ini to disk."""
        _sync_defaults_to_data()
        path = Path(v_rtr_ini.get())
        try:
            save_models_ini(path, _rtr_data)
            messagebox.showinfo("Saved", f"Router preset saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # Load initial data
    root.after(200, _rtr_load)

    # Watch for INI path changes
    v_rtr_ini.trace_add("write", lambda *_: root.after(100, _rtr_load))

    ttk.Button(t_rtr, text="💾  Save models.ini", command=_rtr_save
               ).pack(anchor="e", pady=4)

    def _on_close():
        for name in root.tk.call('info', 'vars'):
            try:
                root.tk.call('destroy', name)
            except Exception:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


# ── Shared size formatter ─────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"
