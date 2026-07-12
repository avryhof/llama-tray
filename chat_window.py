"""
chat_window.py — Chat interface for llama.cpp servers.

Connects to running servers via the OpenAI-compatible /v1/chat/completions API.
Supports streaming responses, conversation memory, basic markdown rendering,
and MCP (Model Context Protocol) tool calling.
"""

import json
import re
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk, messagebox

# ── Markdown renderer for tkinter Text widget ─────────────────────────────────
from utility_functions import (
    State,
    state_manager,
    build_server_label,
    build_server_url,
    build_server_headers,
    check_server_health,
    get_server_models,
)


class MarkdownRenderer:
    """Parse basic markdown and render into a tkinter Text widget."""

    # Patterns for inline formatting
    _BOLD = re.compile(r"\*\*(.+?)\*\*")
    _ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    _CODE_INLINE = re.compile(r"`([^`]+)`")
    _HEADER = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    _LIST_ITEM = re.compile(r"^(\s*[-*])\s+(.+)$", re.MULTILINE)
    _ORDERED_LIST = re.compile(r"^(\s*\d+\.)\s+(.+)$", re.MULTILINE)
    _CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

    def __init__(self, text_widget: tk.Text):
        self.text = text_widget
        self._setup_tags()

    def _setup_tags(self):
        """Configure text tags for markdown rendering."""
        # Bold
        self.text.tag_configure("bold", font=("Sans", 10, "bold"))
        # Italic
        self.text.tag_configure("italic", font=("Sans", 10, "italic"))
        # Inline code
        self.text.tag_configure(
            "code_inline", font=("Courier", 9), background="#2d2d2d", foreground="#e0e0e0", relief="flat", borderwidth=1
        )
        # Code block
        self.text.tag_configure(
            "code_block",
            font=("Courier", 9),
            background="#1e1e2e",
            foreground="#cdd6f4",
            relief="flat",
            borderwidth=2,
            lmargin1=10,
            lmargin2=10,
            spacing1=4,
            spacing3=4,
        )
        # Code block language label
        self.text.tag_configure("code_lang", font=("Sans", 8, "italic"), foreground="#89b4fa")
        # Headers
        self.text.tag_configure("h1", font=("Sans", 13, "bold"), spacing1=8, spacing3=4)
        self.text.tag_configure("h2", font=("Sans", 11, "bold"), spacing1=6, spacing3=3)
        self.text.tag_configure("h3", font=("Sans", 10, "bold"), spacing1=4, spacing3=2)
        # List items
        self.text.tag_configure("list_bullet", font=("Sans", 10), lmargin1=20, lmargin2=36, offset=16)
        # User message background
        self.text.tag_configure(
            "msg_user",
            background="#1a3a5c",
            foreground="#e0e0e0",
            lmargin1=6,
            lmargin2=6,
            rmargin=40,
            spacing1=2,
            spacing3=6,
            relief="flat",
            borderwidth=0,
        )
        # Assistant message background
        self.text.tag_configure(
            "msg_assistant",
            background="#2d4a2d",
            foreground="#e0e0e0",
            lmargin1=6,
            lmargin2=6,
            rmargin=40,
            spacing1=2,
            spacing3=6,
            relief="flat",
            borderwidth=0,
        )
        # Role label
        self.text.tag_configure("role_label", font=("Sans", 9, "bold"), foreground="#89b4fa")
        # System message
        self.text.tag_configure(
            "msg_system",
            background="#3d3d3d",
            foreground="#aaaaaa",
            font=("Sans", 9, "italic"),
            lmargin1=6,
            lmargin2=6,
            rmargin=40,
            spacing1=2,
            spacing3=6,
        )
        # Separator
        self.text.tag_configure("separator", foreground="#555555", spacing1=4, spacing3=4)
        # Tool call
        self.text.tag_configure(
            "tool_call",
            background="#3d2d1d",
            foreground="#e0c080",
            font=("Courier", 9),
            lmargin1=10,
            lmargin2=10,
            spacing1=2,
            spacing3=2,
        )
        # Tool result
        self.text.tag_configure(
            "tool_result",
            background="#2d3d2d",
            foreground="#a0c0a0",
            font=("Courier", 9),
            lmargin1=10,
            lmargin2=10,
            spacing1=2,
            spacing3=2,
        )
        # Tool label
        self.text.tag_configure("tool_label", font=("Sans", 8, "bold"), foreground="#e0c080")

    def render_role_label(self, role: str):
        """Insert a role label (e.g. '👤 User')."""
        labels = {
            "user": "👤 You",
            "assistant": "🤖 Assistant",
            "system": "⚙ System",
            "tool": "🔧 Tool",
        }
        label = labels.get(role, role)
        self.text.insert("end", f"{label}\n", "role_label")

    def render_message(self, content: str, role: str):
        """Render a full message with markdown formatting."""
        tag = f"msg_{role}"
        self.render_role_label(role)

        # Process code blocks first (they contain text that shouldn't be
        # processed for inline formatting)
        parts = self._split_code_blocks(content)
        for part_type, text, lang in parts:
            if part_type == "code_block":
                self._render_code_block(text, lang, tag)
            else:
                self._render_text(text, tag)

        # Add separator
        self.text.insert("end", "─" * 60 + "\n", "separator")

    def render_tool_call(self, tool_name: str, arguments: dict):
        """Render a tool call in the chat display."""
        self.text.insert("end", "🔧 Tool Call\n", "tool_label")
        args_str = json.dumps(arguments, indent=2)
        self.text.insert("end", f"  {tool_name}\n", "tool_call")
        self.text.insert("end", f"  {args_str}\n", "tool_call")
        self.text.insert("end", "─" * 60 + "\n", "separator")

    def render_tool_result(self, tool_name: str, result: dict):
        """Render a tool result in the chat display."""
        self.text.insert("end", "🔧 Tool Result\n", "tool_label")
        result_str = json.dumps(result, indent=2)
        self.text.insert("end", f"  {result_str}\n", "tool_result")
        self.text.insert("end", "─" * 60 + "\n", "separator")

    def _split_code_blocks(self, text: str):
        """Split text into alternating (text, code_block) parts."""
        parts = []
        last_end = 0
        for m in self._CODE_BLOCK.finditer(text):
            if m.start() > last_end:
                parts.append(("text", text[last_end: m.start()], ""))
            parts.append(("code_block", m.group(2), m.group(1)))
            last_end = m.end()
        if last_end < len(text):
            parts.append(("text", text[last_end:], ""))
        return parts

    def _render_code_block(self, code: str, lang: str, parent_tag: str):
        """Render a fenced code block."""
        if lang:
            self.text.insert("end", f"  {lang}\n", "code_lang")
        # Insert code with code_block tag
        lines = code.split("\n")
        for i, line in enumerate(lines):
            suffix = "\n" if i < len(lines) - 1 else "\n"
            self.text.insert("end", f"  {line}{suffix}", "code_block")

    def _render_text(self, text: str, parent_tag: str):
        """Render text with inline markdown (bold, italic, code, headers, lists)."""
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()

            # Headers
            hm = re.match(r"^(#{1,3})\s+(.+)$", stripped)
            if hm:
                level = len(hm.group(1))
                tag = f"h{level}"
                self.text.insert("end", hm.group(2) + "\n", tag)
                continue

            # List items (- or * or 1.)
            lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.+)$", stripped)
            if lm:
                bullet = lm.group(2)
                if lm.group(1):
                    # Nested list
                    bullet = "  " + bullet
                self.text.insert("end", f"  {bullet} ", "list_bullet")
                self._render_inline(lm.group(3), parent_tag)
                self.text.insert("end", "\n")
                continue

            # Regular line with inline formatting
            if stripped:
                self._render_inline(stripped, parent_tag)
                self.text.insert("end", "\n")
            else:
                self.text.insert("end", "\n")

    def _render_inline(self, text: str, parent_tag: str):
        """Render inline markdown: bold, italic, inline code."""
        # Simple approach: process tokens sequentially
        pos = 0
        # Combined pattern for bold, italic, code
        inline_re = re.compile(
            r"(\*\*(.+?)\*\*)"  # bold
            r"|(`([^`]+)`)"  # inline code
            r"|(?<!\*)(\*(?!\*)(.+?)(?<!\*)\*(?!\*))"  # italic
        )

        for m in inline_re.finditer(text):
            # Text before match
            if m.start() > pos:
                self.text.insert("end", text[pos: m.start()], parent_tag)

            if m.group(2):  # bold
                self.text.insert("end", m.group(2), "bold")
            elif m.group(4):  # inline code
                self.text.insert("end", m.group(4), "code_inline")
            elif m.group(6):  # italic
                self.text.insert("end", m.group(6), "italic")

            pos = m.end()

        # Remaining text
        if pos < len(text):
            self.text.insert("end", text[pos:], parent_tag)

    def clear(self):
        """Clear all text."""
        self.text.config(state="normal")
        self.text.delete("1.0", "end")


# ── SSE streaming parser ──────────────────────────────────────────────────────


def _parse_sse_lines(buffer: str):
    """Parse SSE data lines from a streaming response buffer.

    Yields parsed JSON objects from 'data: ' lines.
    """
    for line in buffer.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                pass


# ── Chat window ───────────────────────────────────────────────────────────────


def show_chat_window(config):
    """Open the chat interface window."""
    threading.Thread(target=_show, args=(config,), daemon=True).start()


def _show(config):
    root = tk.Tk()
    root.title("llama.cpp Chat")
    root.geometry("780x670")
    root.minsize(500, 400)

    # ── State ─────────────────────────────────────────────────────────────
    servers = config.servers()
    # Filter to servers that are likely running (have host/port)
    server_map = {build_server_label(s): s for s in servers}
    server_names = list(server_map.keys())

    history_key = "chat_history"
    chat_history: dict[str, list] = config.get().get(history_key, {})
    current_server_id = [None]
    streaming = [False]
    stop_event = threading.Event()
    abort_flag = [False]

    # ── MCP setup ──────────────────────────────────────────────────────────
    from mcp_client import MCPManager

    mcp_manager = MCPManager()

    def _connect_mcp_servers():
        """Connect to all enabled MCP servers."""

        def _do():
            for srv in config.mcp_servers():
                if not srv.get("enabled", True):
                    continue
                name = srv.get("name", "Unnamed")
                transport = srv.get("transport", "stdio")
                server_id = srv.get("id", "")
                print(f"MCP: Connecting to {name} (transport={transport})...")
                ok = mcp_manager.connect_server(
                    server_id=server_id,
                    transport=transport,
                    command=srv.get("command", ""),
                    args=srv.get("args", []),
                    env=srv.get("env", {}),
                    url=srv.get("url", ""),
                    headers=srv.get("headers", {}),
                    name=name,
                    timeout=10,
                )
                if ok:
                    tools = mcp_manager.get_server(server_id).tools
                    print(f"MCP: Connected to {name} ({len(tools)} tools)")
                else:
                    print(f"MCP: Failed to connect to {name}")

        threading.Thread(target=_do, daemon=True).start()

    def _get_mcp_tools_for_api() -> list[dict]:
        """Convert MCP tools to OpenAI API format."""
        api_tools = []
        for tool in mcp_manager.all_tools:
            api_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            api_tools.append(api_tool)
        return api_tools

    def _execute_tool_call(tool_name: str, arguments: dict) -> dict:
        """Execute a tool call via MCP."""
        return mcp_manager.call_tool(tool_name, arguments)

    # Connect to MCP servers on startup
    _connect_mcp_servers()

    # ── Top bar: server selector + model selector + status ────────────────
    top_bar = tk.Frame(root, padx=8, pady=4)
    top_bar.pack(fill="x")

    tk.Label(top_bar, text="Server:", font=("Helvetica", 9, "bold")).pack(side="left")
    v_server = tk.StringVar()
    cb_server = ttk.Combobox(top_bar, textvariable=v_server, values=server_names, state="readonly", width=30)
    cb_server.pack(side="left", padx=(4, 12))

    tk.Label(top_bar, text="Model:", font=("Helvetica", 9, "bold")).pack(side="left")
    v_model = tk.StringVar()
    cb_model = ttk.Combobox(top_bar, textvariable=v_model, values=[], state="readonly", width=30)
    cb_model.pack(side="left", padx=4)

    lbl_status = tk.Label(top_bar, text="○ Not connected", fg="#dc3545", font=("Helvetica", 9))
    lbl_status.pack(side="right")

    ttk.Button(top_bar, text="↻", command=lambda: _check_server(), width=3).pack(side="right", padx=2)

    # ── System prompt ─────────────────────────────────────────────────────
    sp_frame = tk.Frame(root, padx=8, pady=2)
    sp_frame.pack(fill="x")
    tk.Label(sp_frame, text="System:", font=("Helvetica", 9), width=8, anchor="w").pack(side="left")
    v_sysprompt = tk.StringVar(value="You are a helpful assistant.")
    tk.Entry(sp_frame, textvariable=v_sysprompt, width=80).pack(side="left", fill="x", expand=True, padx=4)

    # ── Chat display ──────────────────────────────────────────────────────
    chat_frame = tk.Frame(root, padx=4, pady=4)
    chat_frame.pack(fill="both", expand=True)

    chat_text = tk.Text(
        chat_frame,
        wrap="word",
        font=("Sans", 10),
        bg="#1e1e2e",
        fg="#cdd6f4",
        insertbackground="#cdd6f4",
        relief="flat",
        borderwidth=0,
        state="disabled",
        cursor="arrow",
    )
    chat_scroll = ttk.Scrollbar(chat_frame, command=chat_text.yview)
    chat_text.config(yscrollcommand=chat_scroll.set)
    chat_scroll.pack(side="right", fill="y")
    chat_text.pack(side="left", fill="both", expand=True)

    renderer = MarkdownRenderer(chat_text)

    # ── Input area ────────────────────────────────────────────────────────
    input_frame = tk.Frame(root, padx=8, pady=6)
    input_frame.pack(fill="x")

    input_text = tk.Text(
        input_frame,
        height=3,
        font=("Sans", 10),
        bg="#2d2d2d",
        fg="#cdd6f4",
        insertbackground="#cdd6f4",
        relief="flat",
        borderwidth=1,
        wrap="word",
    )
    input_text.pack(side="left", fill="both", expand=True)

    btn_frame = tk.Frame(input_frame)
    btn_frame.pack(side="right", padx=(6, 0))

    btn_send = ttk.Button(btn_frame, text="Send", width=8)
    btn_send.pack(pady=2)

    btn_stop = ttk.Button(btn_frame, text="Stop", width=8, state="disabled")
    btn_stop.pack(pady=2)

    btn_clear = ttk.Button(btn_frame, text="Clear", width=8)
    btn_clear.pack(pady=2)

    # ── Chat display helpers ──────────────────────────────────────────────

    def _append_chat(role: str, content: str):
        """Append a message to the chat display."""
        chat_text.config(state="normal")
        renderer.render_message(content, role)
        chat_text.config(state="disabled")
        chat_text.see("end")

    def _append_streaming_token(token: str):
        """Append a token during streaming (appends to last assistant message)."""
        chat_text.config(state="normal")
        chat_text.insert("end", token, "msg_assistant")
        chat_text.config(state="disabled")
        chat_text.see("end")

    def _start_assistant_message():
        """Insert the assistant role label for streaming."""
        chat_text.config(state="normal")
        renderer.render_role_label("assistant")
        chat_text.config(state="disabled")
        chat_text.see("end")

    def _load_history():
        """Load persisted chat history for the selected server."""
        sid = current_server_id[0]
        if not sid:
            return
        messages = chat_history.get(sid, [])
        chat_text.config(state="normal")
        chat_text.delete("1.0", "end")
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant", "system"):
                renderer.render_message(content, role)
        chat_text.config(state="disabled")
        chat_text.see("end")

    def _save_message(role: str, content: str):
        """Persist a message to chat history."""
        sid = current_server_id[0]
        if not sid:
            return
        if sid not in chat_history:
            chat_history[sid] = []
        chat_history[sid].append({"role": role, "content": content})
        # Keep last 200 messages
        if len(chat_history[sid]) > 200:
            chat_history[sid] = chat_history[sid][-200:]
        config.set(history_key, chat_history)

    # ── Server connection check + model list ──────────────────────────────

    def _check_server():
        """Quick health check + fetch model list from the selected server."""
        name = v_server.get()
        srv = server_map.get(name)
        if not srv:
            root.after(0, lambda: lbl_status.config(text="○ No server selected", fg="#dc3545"))
            return

        sid = srv["id"]
        state_manager.set_state(sid, State.STARTING)

        def _do():
            if state_manager.get_state(sid) in [State.RUNNING, State.STARTING]:
                health = check_server_health(srv)
                if health.get("result") == "ok":
                    state_manager.set_state(sid, State.RUNNING)
                    _fetch_models(srv)
                else:
                    print(f"Health check failed for {name}: {health.get('message')}")
                    state_manager.set_state(sid, State.ERROR)

        threading.Thread(target=_do, daemon=True).start()

    def _fetch_models(srv: dict):
        """Fetch available models from GET /v1/models."""

        def _do():
            models = get_server_models(srv)

            def _upd():
                cb_model["values"] = models
                if models:
                    cb_model.current(0)

            root.after(0, _upd)

        threading.Thread(target=_do, daemon=True).start()

    def _on_server_change(_event=None):
        name = v_server.get()
        srv = server_map.get(name)
        if srv:
            current_server_id[0] = srv["id"]
            _load_history()
            _check_server()

    cb_server.bind("<<ComboboxSelected>>", _on_server_change)

    # ── Send message ──────────────────────────────────────────────────────

    def _send():
        """Send the user's message and stream the response."""
        if streaming[0]:
            return

        user_msg = input_text.get("1.0", "end").strip()
        if not user_msg:
            return

        name = v_server.get()
        srv = server_map.get(name)
        if not srv:
            messagebox.showwarning("No server", "Select a server first.")
            return

        input_text.delete("1.0", "end")

        # Display and save user message
        _append_chat("user", user_msg)
        _save_message("user", user_msg)

        # Build messages list for API
        sid = current_server_id[0]
        messages = []
        sys_prompt = v_sysprompt.get().strip()
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.extend(chat_history.get(sid, []))

        # Get MCP tools
        mcp_tools = _get_mcp_tools_for_api()

        # Start streaming
        streaming[0] = True
        abort_flag[0] = False
        stop_event.clear()
        btn_send.config(state="disabled")
        btn_stop.config(state="normal")

        # Determine model name for API request
        selected_model = v_model.get() or "local"

        def _stream_completion(messages_to_send):
            """Stream a single completion and handle tool calls."""
            _start_assistant_message()

            # Track tool calls during streaming
            collected_tool_calls = {}  # index -> {id, type, function: {name, arguments}}
            full_response = []

            base_url = build_server_url(srv)
            url = f"{base_url}/v1/chat/completions"
            payload = {
                "model": selected_model,
                "messages": messages_to_send,
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 4096,
            }

            # Include tools if available
            if mcp_tools:
                payload["tools"] = mcp_tools

            data = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers=build_server_headers(srv, True),
                method="POST",
            )

            try:
                resp = urllib.request.urlopen(req, timeout=120)
                buf = b""
                while True:
                    if stop_event.is_set():
                        abort_flag[0] = True
                        break

                    chunk = resp.read(1)
                    if not chunk:
                        break
                    buf += chunk

                    # Process complete lines
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line_str = line.decode("utf-8", errors="replace").strip()

                        if not line_str.startswith("data: "):
                            continue
                        payload_str = line_str[6:]
                        if payload_str == "[DONE]":
                            abort_flag[0] = False  # natural completion
                            break

                        try:
                            obj = json.loads(payload_str)
                            choices = obj.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                # Handle text content
                                content = delta.get("content", "")
                                if content:
                                    full_response.append(content)
                                    root.after(0, _append_streaming_token, content)
                                # Handle tool calls (streamed in pieces)
                                tool_calls = delta.get("tool_calls", [])
                                for tc in tool_calls:
                                    idx = tc.get("index", 0)
                                    if idx not in collected_tool_calls:
                                        collected_tool_calls[idx] = {
                                            "id": tc.get("id", ""),
                                            "type": "function",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    # Update fields (they come incrementally)
                                    if tc.get("id"):
                                        collected_tool_calls[idx]["id"] = tc["id"]
                                    func = tc.get("function", {})
                                    if func.get("name"):
                                        collected_tool_calls[idx]["function"]["name"] = func["name"]
                                    if func.get("arguments"):
                                        collected_tool_calls[idx]["function"]["arguments"] += func["arguments"]
                        except json.JSONDecodeError:
                            pass

                        if abort_flag[0]:
                            break

            except urllib.error.HTTPError as e:
                # Read response body for HTTP errors
                resp_body = ""
                try:
                    resp_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                error_msg = (
                    f"\n\n[HTTP {e.code} {e.reason}]\n"
                    f"URL: {url}\n"
                    f"Headers: {dict(req.headers)}\n"
                    f"Response: {resp_body[:2000]}"
                )
                root.after(0, lambda: _append_streaming_token(error_msg))
                return None, []
            except urllib.error.URLError as e:
                error_msg = f"\n\n[Connection error: {e.reason}]\n" f"URL: {url}\n" f"Headers: {dict(req.headers)}"
                root.after(0, lambda: _append_streaming_token(error_msg))
                return None, []
            except Exception as e:
                error_msg = f"\n\n[Error: {e}]\n" f"URL: {url}\n" f"Headers: {dict(req.headers)}"
                root.after(0, lambda: _append_streaming_token(error_msg))
                return None, []

            # Build assistant message
            assistant_msg = {}
            text_content = "".join(full_response)
            if text_content:
                assistant_msg["role"] = "assistant"
                assistant_msg["content"] = text_content
            elif collected_tool_calls:
                assistant_msg["role"] = "assistant"
                assistant_msg["content"] = None
            else:
                assistant_msg["role"] = "assistant"
                assistant_msg["content"] = ""

            # Sort tool calls by index and add to message
            sorted_tool_calls = [collected_tool_calls[i] for i in sorted(collected_tool_calls.keys())]
            if sorted_tool_calls:
                assistant_msg["tool_calls"] = sorted_tool_calls

            return assistant_msg, sorted_tool_calls

        def _execute_tool_calls(tool_calls):
            """Execute tool calls and return results."""
            results = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}

                # Show tool call in chat
                root.after(0, renderer.render_tool_call, tool_name, arguments)

                # Execute via MCP
                result = _execute_tool_call(tool_name, arguments)

                # Show result in chat
                root.after(0, renderer.render_tool_result, tool_name, result)

                results.append(
                    {
                        "tool_call_id": tc.get("id", ""),
                        "role": "tool",
                        "content": json.dumps(result),
                    }
                )
            return results

        def _do_tool_loop():
            """Main loop: stream response, execute tools, repeat until no more tool calls."""
            sid = current_server_id[0]
            current_messages = list(messages)

            while not abort_flag[0]:
                # Stream completion
                assistant_msg, tool_calls = _stream_completion(current_messages)

                if assistant_msg is None:
                    # Error occurred
                    break

                # Save assistant message
                if assistant_msg.get("content"):
                    _save_message("assistant", assistant_msg["content"])
                if tool_calls:
                    # Save tool_calls in history as part of assistant message
                    chat_history[sid].append(assistant_msg)
                    config.set(history_key, chat_history)

                if not tool_calls:
                    # No tool calls, we're done
                    break

                # Execute tool calls
                tool_results = _execute_tool_calls(tool_calls)

                # Add tool results to messages
                current_messages.append(assistant_msg)
                for result in tool_results:
                    current_messages.append(result)
                    # Save tool result in history
                    chat_history[sid].append(result)
                    config.set(history_key, chat_history)

                # Continue streaming (the model will see the tool results)
                root.after(0, _start_assistant_message)

            # Done
            root.after(0, _stream_done)

        threading.Thread(target=_do_tool_loop, daemon=True).start()

        def _stream_done():
            streaming[0] = False
            btn_send.config(state="normal")
            btn_stop.config(state="disabled")
            # Add separator after response
            chat_text.config(state="normal")
            chat_text.insert("end", "─" * 60 + "\n", "separator")
            chat_text.config(state="disabled")
            chat_text.see("end")

    def _stop():
        """Stop the current streaming response."""
        stop_event.set()

    def _clear():
        """Clear chat history for the current server."""
        sid = current_server_id[0]
        if sid and sid in chat_history:
            if messagebox.askyesno("Clear chat", "Clear conversation history for this server?"):
                chat_history.pop(sid, None)
                config.set(history_key, chat_history)
                chat_text.config(state="normal")
                chat_text.delete("1.0", "end")
                chat_text.config(state="disabled")

    btn_send.config(command=_send)
    btn_stop.config(command=_stop)
    btn_clear.config(command=_clear)

    # Bind Enter to send (Shift+Enter for newline)
    def _on_key(event):
        if event.keysym == "Return" and not event.state & 0x1:
            _send()
            return "break"

    input_text.bind("<Key>", _on_key)

    # ── State manager observer — update status label ──────────────────────
    def _on_server_state_change(server_id, new_state, old_state):
        if server_id != current_server_id[0]:
            return

        def _update():
            if new_state == State.RUNNING:
                lbl_status.config(text="● Connected", fg="#28a745")
            elif new_state == State.ERROR:
                lbl_status.config(text="○ Not reachable", fg="#dc3545")
            elif new_state == State.STARTING:
                lbl_status.config(text="◌ Checking…", fg="#fd7e14")
            else:
                lbl_status.config(text="○ Disconnected", fg="#6c757d")

        root.after(0, _update)

    state_manager.add_observer(_on_server_state_change)

    # ── Cleanup on window close ───────────────────────────────────────────
    def _on_close():
        if _health_timer[0]:
            root.after_cancel(_health_timer[0])
        state_manager.remove_observer(_on_server_state_change)
        mcp_manager.disconnect_all()
        for name in root.tk.call("info", "vars"):
            try:
                root.tk.call("destroy", name)
            except Exception:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    # ── Initial state ─────────────────────────────────────────────────────
    _health_timer = [None]

    def _periodic_health_check():
        """Check server health every 30 seconds (skip if local and not running)."""
        name = v_server.get()
        srv = server_map.get(name)
        if srv and srv.get("is_local", False):
            state = state_manager.get_state(srv["id"])
            if state not in (State.RUNNING, State.STARTING):
                _health_timer[0] = root.after(30000, _periodic_health_check)
                return
        _check_server()
        _health_timer[0] = root.after(30000, _periodic_health_check)

    if server_names:
        cb_server.current(0)
        _on_server_change()
        _periodic_health_check()

    root.mainloop()
