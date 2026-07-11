"""
nvidia_window.py — Live nvidia-smi viewer for llama_tray.

Shows GPU name, driver, CUDA version, and a per-GPU table of:
  utilization, memory used/total, temperature, power draw, fan speed,
  running processes.

Auto-refreshes every 2 seconds.  Falls back gracefully if nvidia-smi
is not found or no NVIDIA GPU is present.
"""

import subprocess
import threading
import xml.etree.ElementTree as ET
from pathlib import Path


def show_nvidia_window():
    threading.Thread(target=_show, daemon=True).start()


# ── nvidia-smi helpers ────────────────────────────────────────────────────────

def _find_nvidia_smi() -> str | None:
    import shutil, os, platform
    from tool_detect import _merged_path
    found = shutil.which("nvidia-smi", path=_merged_path())
    if found:
        return found
    candidates = ["/usr/bin/nvidia-smi", "/usr/local/bin/nvidia-smi"]
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            r"C:\Windows\System32\nvidia-smi.exe",
        ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _query_xml(binary: str) -> ET.Element | None:
    try:
        result = subprocess.run(
            [binary, "-q", "-x"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        return ET.fromstring(result.stdout)
    except Exception:
        return None


def _txt(el: ET.Element | None, tag: str, default: str = "N/A") -> str:
    if el is None:
        return default
    child = el.find(tag)
    return child.text.strip() if child is not None and child.text else default


def _parse_gpus(root: ET.Element) -> list[dict]:
    gpus = []
    for gpu in root.findall("gpu"):
        fb   = gpu.find("fb_memory_usage")
        util = gpu.find("utilization")
        temp = gpu.find("temperature")
        pwr  = gpu.find("power_readings") or gpu.find("gpu_power_readings")
        fan  = gpu.find("fan_speed")
        clks = gpu.find("clocks")
        procs = gpu.find("processes")

        processes = []
        if procs is not None:
            for p in procs.findall("process_info"):
                processes.append({
                    "pid":    _txt(p, "pid"),
                    "name":   _txt(p, "process_name"),
                    "mem":    _txt(p, "used_memory"),
                    "type":   _txt(p, "type"),
                })

        gpus.append({
            "id":           gpu.get("id", ""),
            "name":         _txt(gpu, "product_name"),
            "uuid":         _txt(gpu, "uuid"),
            "driver":       _txt(root, "driver_version"),
            "cuda":         _txt(root, "cuda_version"),
            "mem_used":     _txt(fb,   "used")   if fb   else "N/A",
            "mem_total":    _txt(fb,   "total")  if fb   else "N/A",
            "mem_free":     _txt(fb,   "free")   if fb   else "N/A",
            "gpu_util":     _txt(util, "gpu_util")    if util else "N/A",
            "mem_util":     _txt(util, "memory_util") if util else "N/A",
            "temp_gpu":     _txt(temp, "gpu_temp")          if temp else "N/A",
            "temp_limit":   _txt(temp, "gpu_temp_slow_threshold") if temp else "N/A",
            "pwr_draw":     _txt(pwr,  "power_draw")        if pwr  else "N/A",
            "pwr_limit":    _txt(pwr,  "current_power_limit") if pwr else "N/A",
            "fan":          fan.text.strip()  if fan  is not None and fan.text else "N/A",
            "clk_graphics": _txt(clks, "graphics_clock") if clks else "N/A",
            "clk_mem":      _txt(clks, "mem_clock")      if clks else "N/A",
            "perf":         _txt(gpu, "performance_state"),
            "processes":    processes,
        })
    return gpus


# ── GUI ───────────────────────────────────────────────────────────────────────

def _show():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("tkinter not available")
        return

    binary = _find_nvidia_smi()

    root = tk.Tk()
    root.title("GPU Monitor  (nvidia-smi)")
    root.geometry("820x620")
    root.resizable(True, True)

    # ── Colour scheme ─────────────────────────────────────────────────────────
    BG      = "#0d1117"
    FG      = "#c9d1d9"
    FG_DIM  = "#6e7681"
    GREEN   = "#56d364"
    YELLOW  = "#e3b341"
    RED     = "#ff7b72"
    BLUE    = "#79c0ff"
    PURPLE  = "#d2a8ff"

    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Dark.TFrame",         background=BG)
    style.configure("Dark.TLabel",         background=BG, foreground=FG)
    style.configure("Dim.TLabel",          background=BG, foreground=FG_DIM)
    style.configure("Header.TLabel",       background=BG, foreground=BLUE,
                    font=("Helvetica", 11, "bold"))
    style.configure("Value.TLabel",        background=BG, foreground=GREEN,
                    font=("Courier", 10, "bold"))
    style.configure("Warn.TLabel",         background=BG, foreground=YELLOW,
                    font=("Courier", 10, "bold"))
    style.configure("Crit.TLabel",         background=BG, foreground=RED,
                    font=("Courier", 10, "bold"))
    style.configure("Dark.Treeview",       background="#161b22", foreground=FG,
                    fieldbackground="#161b22", rowheight=22)
    style.configure("Dark.Treeview.Heading", background="#21262d", foreground=BLUE,
                    font=("Helvetica", 9, "bold"))
    style.map("Dark.Treeview", background=[("selected", "#1f6feb")])
    style.configure("Dark.TNotebook",      background=BG, tabmargins=[2, 4, 0, 0])
    style.configure("Dark.TNotebook.Tab",  background="#161b22", foreground=FG,
                    padding=[10, 4])
    style.map("Dark.TNotebook.Tab",
              background=[("selected", "#21262d")],
              foreground=[("selected", BLUE)])

    # ── Top bar ───────────────────────────────────────────────────────────────
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=10, pady=(8, 0))

    if not binary:
        tk.Label(top, text="⚠  nvidia-smi not found. Is an NVIDIA driver installed?",
                 bg=BG, fg=YELLOW, font=("Helvetica", 11)).pack(side="left")
        root.mainloop()
        return

    title_lbl = tk.Label(top, text="", bg=BG, fg=BLUE,
                          font=("Helvetica", 12, "bold"))
    title_lbl.pack(side="left")

    refresh_lbl = tk.Label(top, text="", bg=BG, fg=FG_DIM,
                            font=("Helvetica", 9))
    refresh_lbl.pack(side="right")

    v_interval = tk.IntVar(value=2)
    tk.Label(top, text="Refresh (s):", bg=BG, fg=FG_DIM,
             font=("Helvetica", 9)).pack(side="right", padx=(0, 2))
    tk.Spinbox(top, textvariable=v_interval, from_=1, to=10, width=3,
               bg="#161b22", fg=FG, insertbackground=FG,
               buttonbackground="#21262d").pack(side="right", padx=(0, 6))

    # Pause toggle
    _paused = [False]
    def _toggle_pause():
        _paused[0] = not _paused[0]
        pause_btn.config(text="▶  Resume" if _paused[0] else "⏸  Pause")
    pause_btn = tk.Button(top, text="⏸  Pause", command=_toggle_pause,
                          bg="#21262d", fg=FG, relief="flat",
                          activebackground="#30363d", activeforeground=FG,
                          font=("Helvetica", 9), padx=8)
    pause_btn.pack(side="right", padx=4)

    # ── Notebook (one tab per GPU) ────────────────────────────────────────────
    nb = ttk.Notebook(root, style="Dark.TNotebook")
    nb.pack(fill="both", expand=True, padx=8, pady=6)

    # Tab for raw output
    raw_frame = tk.Frame(nb, bg=BG)
    nb.add(raw_frame, text="  Raw  ")
    raw_sb = ttk.Scrollbar(raw_frame)
    raw_sb.pack(side="right", fill="y")
    raw_text = tk.Text(raw_frame, bg=BG, fg=FG, font=("Courier", 9),
                       yscrollcommand=raw_sb.set, state="disabled", wrap="none")
    raw_text.pack(fill="both", expand=True)
    raw_sb.config(command=raw_text.yview)

    # Per-GPU tab state
    _gpu_tabs: dict[str, dict] = {}   # uuid → widget refs

    def _ensure_gpu_tab(gpu: dict):
        uid = gpu["uuid"]
        if uid in _gpu_tabs:
            return

        frm = tk.Frame(nb, bg=BG)
        nb.insert(0, frm, text=f"  {gpu['name']}  ")
        widgets = {}

        # ── Header strip ──────────────────────────────────────────────────
        hdr = tk.Frame(frm, bg="#161b22", pady=6, padx=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=gpu["name"], bg="#161b22", fg=BLUE,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        tk.Label(hdr, text=f"  Driver {gpu['driver']}  ·  CUDA {gpu['cuda']}",
                 bg="#161b22", fg=FG_DIM, font=("Helvetica", 9)).pack(side="left")
        tk.Label(hdr, text=gpu["uuid"], bg="#161b22", fg=FG_DIM,
                 font=("Courier", 8)).pack(side="right")

        # ── Gauge grid ────────────────────────────────────────────────────
        gauges = tk.Frame(frm, bg=BG)
        gauges.pack(fill="x", padx=10, pady=8)
        gauges.columnconfigure(list(range(6)), weight=1)

        def _gauge_cell(parent, row, col, title):
            cell = tk.Frame(parent, bg="#161b22", padx=8, pady=6,
                            relief="flat", bd=1)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            tk.Label(cell, text=title, bg="#161b22", fg=FG_DIM,
                     font=("Helvetica", 8)).pack()
            val_lbl = tk.Label(cell, text="—", bg="#161b22", fg=GREEN,
                               font=("Courier", 13, "bold"))
            val_lbl.pack()
            bar = ttk.Progressbar(cell, mode="determinate", length=100)
            bar.pack(fill="x", pady=(2, 0))
            return val_lbl, bar

        wg = {}
        wg["gpu_util_val"], wg["gpu_util_bar"] = _gauge_cell(gauges, 0, 0, "GPU  util")
        wg["mem_val"],      wg["mem_bar"]      = _gauge_cell(gauges, 0, 1, "VRAM  used")
        wg["temp_val"],     wg["temp_bar"]     = _gauge_cell(gauges, 0, 2, "Temperature")
        wg["pwr_val"],      wg["pwr_bar"]      = _gauge_cell(gauges, 0, 3, "Power  draw")
        wg["fan_val"],      wg["fan_bar"]      = _gauge_cell(gauges, 0, 4, "Fan  speed")
        wg["perf_val"],     wg["perf_bar"]     = _gauge_cell(gauges, 0, 5, "Perf  state")

        # ── Extra stats row ────────────────────────────────────────────────
        extra = tk.Frame(frm, bg=BG)
        extra.pack(fill="x", padx=10)

        def _stat(parent, label):
            f = tk.Frame(parent, bg=BG)
            f.pack(side="left", padx=12)
            tk.Label(f, text=label, bg=BG, fg=FG_DIM,
                     font=("Helvetica", 8)).pack()
            v = tk.Label(f, text="—", bg=BG, fg=FG, font=("Courier", 9))
            v.pack()
            return v

        wg["clk_g"]   = _stat(extra, "Graphics clock")
        wg["clk_m"]   = _stat(extra, "Mem clock")
        wg["mem_free"] = _stat(extra, "VRAM free")
        wg["mem_util"] = _stat(extra, "Mem util %")

        # ── Processes table ────────────────────────────────────────────────
        proc_hdr = tk.Frame(frm, bg=BG)
        proc_hdr.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(proc_hdr, text="Processes", bg=BG, fg=PURPLE,
                 font=("Helvetica", 9, "bold")).pack(side="left")

        proc_tv = ttk.Treeview(frm, style="Dark.Treeview",
                                columns=("pid","type","name","mem"),
                                show="headings", height=5)
        proc_tv.heading("pid",  text="PID")
        proc_tv.heading("type", text="Type")
        proc_tv.heading("name", text="Process")
        proc_tv.heading("mem",  text="GPU Mem")
        proc_tv.column("pid",  width=70,  anchor="center")
        proc_tv.column("type", width=60,  anchor="center")
        proc_tv.column("name", width=480, anchor="w")
        proc_tv.column("mem",  width=100, anchor="e")
        proc_vsb = ttk.Scrollbar(frm, orient="vertical", command=proc_tv.yview)
        proc_tv.configure(yscrollcommand=proc_vsb.set)
        proc_vsb.pack(side="right", fill="y", padx=(0, 8))
        proc_tv.pack(fill="both", expand=True, padx=10, pady=(2, 8))

        wg["proc_tv"] = proc_tv
        widgets.update(wg)
        _gpu_tabs[uid] = {"frame": frm, "widgets": widgets}

    def _pct(val_str: str) -> float:
        """Extract numeric percent from a string like '42 %' or '42%'."""
        try:
            return float(val_str.replace("%", "").replace("MiB", "")
                                .replace("W", "").replace("MHz", "")
                                .replace("N/A", "0").strip())
        except ValueError:
            return 0.0

    def _colour_for(pct: float) -> str:
        if pct >= 90:
            return RED
        if pct >= 70:
            return YELLOW
        return GREEN

    def _update_gpu_tab(gpu: dict):
        uid = gpu["uuid"]
        if uid not in _gpu_tabs:
            return
        wg = _gpu_tabs[uid]["widgets"]

        # GPU utilisation
        gu = _pct(gpu["gpu_util"])
        wg["gpu_util_val"].config(text=gpu["gpu_util"],
                                   fg=_colour_for(gu))
        wg["gpu_util_bar"]["value"] = min(gu, 100)

        # Memory
        used  = _pct(gpu["mem_used"])
        total = _pct(gpu["mem_total"]) or 1
        mpct  = used / total * 100
        wg["mem_val"].config(text=f"{gpu['mem_used']} / {gpu['mem_total']}",
                              fg=_colour_for(mpct))
        wg["mem_bar"]["value"] = min(mpct, 100)

        # Temperature
        tc = _pct(gpu["temp_gpu"])
        wg["temp_val"].config(text=gpu["temp_gpu"], fg=_colour_for(tc / 100 * 100
            if tc <= 100 else tc))
        wg["temp_bar"]["value"] = min(tc, 100)

        # Power
        pd   = _pct(gpu["pwr_draw"])
        plim = _pct(gpu["pwr_limit"]) or 100
        ppct = pd / plim * 100
        wg["pwr_val"].config(text=f"{gpu['pwr_draw']} / {gpu['pwr_limit']}",
                              fg=_colour_for(ppct))
        wg["pwr_bar"]["value"] = min(ppct, 100)

        # Fan
        fan = _pct(gpu["fan"])
        wg["fan_val"].config(text=gpu["fan"], fg=_colour_for(fan))
        wg["fan_bar"]["value"] = min(fan, 100)

        # Perf state (P0–P12)
        perf_n = _pct(gpu["perf"].replace("P", "")) if gpu["perf"] != "N/A" else 12
        perf_pct = (12 - perf_n) / 12 * 100
        wg["perf_val"].config(text=gpu["perf"], fg=GREEN if perf_n == 0 else FG)
        wg["perf_bar"]["value"] = perf_pct

        # Extra stats
        wg["clk_g"].config(text=gpu["clk_graphics"])
        wg["clk_m"].config(text=gpu["clk_mem"])
        wg["mem_free"].config(text=gpu["mem_free"])
        wg["mem_util"].config(text=gpu["mem_util"])

        # Processes
        tv = wg["proc_tv"]
        tv.delete(*tv.get_children())
        if gpu["processes"]:
            for p in gpu["processes"]:
                tv.insert("", "end",
                          values=(p["pid"], p["type"], p["name"], p["mem"]))
        else:
            tv.insert("", "end", values=("", "", "(no processes)", ""))

    # ── Raw output update ─────────────────────────────────────────────────────
    def _update_raw():
        try:
            result = subprocess.run(
                [binary, "--query-gpu=index,name,driver_version,memory.used,"
                 "memory.total,memory.free,utilization.gpu,utilization.memory,"
                 "temperature.gpu,power.draw,power.limit,fan.speed,"
                 "clocks.current.graphics,clocks.current.memory,pstate",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
            )
            text = result.stdout.strip() if result.returncode == 0 else result.stderr
        except Exception as e:
            text = str(e)

        raw_text.config(state="normal")
        raw_text.delete("1.0", "end")
        raw_text.insert("end", text)
        raw_text.config(state="disabled")

    # ── Main poll loop ────────────────────────────────────────────────────────
    _running = [True]

    def _poll():
        import time as _time
        while _running[0]:
            if not _paused[0]:
                root.after(0, _tick)
            interval = max(1, v_interval.get())
            _time.sleep(interval)

    def _tick():
        xml_root = _query_xml(binary)
        if xml_root is None:
            title_lbl.config(text="⚠  nvidia-smi returned no data")
            return

        gpus = _parse_gpus(xml_root)
        if not gpus:
            title_lbl.config(text="No NVIDIA GPUs detected")
            return

        title_lbl.config(
            text=f"{len(gpus)} GPU{'s' if len(gpus) > 1 else ''}  ·  "
                 f"Driver {gpus[0]['driver']}  ·  CUDA {gpus[0]['cuda']}")

        import time as _t
        refresh_lbl.config(text=f"Updated {_t.strftime('%H:%M:%S')}")

        for g in gpus:
            _ensure_gpu_tab(g)
            _update_gpu_tab(g)

        _update_raw()

    def _on_close():
        _running[0] = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    threading.Thread(target=_poll, daemon=True).start()
    root.after(100, _tick)   # immediate first draw
    root.mainloop()
