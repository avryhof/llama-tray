"""
log_window.py — Scrollable log viewer for llama_tray.
"""

import threading


def show_log_window(log_lines: list[str]):
    """Open a scrollable log window in a background thread."""
    lines_copy = list(log_lines)
    threading.Thread(target=_show, args=(lines_copy,), daemon=True).start()


def _show(lines: list[str]):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("\n".join(lines))
        return

    root = tk.Tk()
    root.title("llama.cpp Server — Logs")
    root.geometry("760x480")

    # Dark background text widget
    frame = tk.Frame(root, bg="#0d1117")
    frame.pack(fill="both", expand=True)

    scrollbar = ttk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")

    text = tk.Text(
        frame,
        wrap="word",
        state="normal",
        bg="#0d1117",
        fg="#c9d1d9",
        font=("Courier", 10),
        yscrollcommand=scrollbar.set,
        padx=8,
        pady=8,
    )
    text.pack(fill="both", expand=True)
    scrollbar.config(command=text.yview)

    # Colour tags
    text.tag_config("error",   foreground="#ff7b72")
    text.tag_config("warn",    foreground="#e3b341")
    text.tag_config("info",    foreground="#79c0ff")
    text.tag_config("success", foreground="#56d364")

    def _tag_for(line: str):
        low = line.lower()
        if "error" in low or "failed" in low or "fatal" in low:
            return "error"
        if "warn" in low:
            return "warn"
        if "ready" in low or "started" in low or "✅" in low:
            return "success"
        return None

    for line in lines:
        tag = _tag_for(line)
        if tag:
            text.insert("end", line + "\n", tag)
        else:
            text.insert("end", line + "\n")

    text.see("end")
    text.config(state="disabled")

    # Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=6)

    def copy_all():
        root.clipboard_clear()
        root.clipboard_append("\n".join(lines))

    ttk.Button(btn_frame, text="Copy All", command=copy_all).pack(side="left")
    ttk.Button(btn_frame, text="Close", command=root.destroy).pack(side="right")

    root.mainloop()
