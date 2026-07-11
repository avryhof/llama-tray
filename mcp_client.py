"""
mcp_client.py — Simple MCP (Model Context Protocol) client for llama-tray.

Connects to MCP servers via stdio transport using JSON-RPC 2.0.
Discovers tools and executes tool calls for use in the chat interface.
"""

import json
import subprocess
import threading
import time
from typing import Any, Optional


class MCPClient:
    """Simple MCP client that communicates with a server over stdio."""

    def __init__(self, server_id: str, command: str, args: list[str] = None,
                 env: dict[str, str] = None, name: str = ""):
        self.server_id = server_id
        self.name = name or server_id
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._initialized = False
        self.tools: list[dict] = []

    def start(self, timeout: float = 10.0) -> bool:
        """Start the MCP server process and initialize."""
        try:
            import os
            full_env = os.environ.copy()
            full_env.update(self.env)

            self._process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                bufsize=0,
            )

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Initialize
            resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "llama-tray",
                    "version": "1.0.0"
                }
            }, timeout=timeout)

            if resp is None:
                return False

            # Send initialized notification
            self._send_notification("notifications/initialized", {})

            # Fetch tools
            resp = self._send_request("tools/list", {}, timeout=timeout)
            if resp and "tools" in resp:
                self.tools = resp["tools"]

            self._initialized = True
            return True

        except Exception as e:
            print(f"MCP: Failed to start {self.name}: {e}")
            self.stop()
            return False

    def stop(self):
        """Stop the MCP server process."""
        self._initialized = False
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any],
                  timeout: float = 30.0) -> dict[str, Any]:
        """Call an MCP tool and return the result."""
        if not self._initialized:
            return {"error": "MCP server not initialized"}

        resp = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, timeout=timeout)

        if resp is None:
            return {"error": "No response from MCP server"}

        return resp

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict,
                      timeout: float = 10.0) -> Optional[dict]:
        """Send a JSON-RPC request and wait for response."""
        req_id = self._next_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        event = threading.Event()
        self._pending[req_id] = event
        self._responses[req_id] = None

        try:
            data = json.dumps(message) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            self._process.stdin.flush()
        except Exception as e:
            print(f"MCP: Failed to send request: {e}")
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)
            return None

        # Wait for response
        event.wait(timeout=timeout)
        resp = self._responses.pop(req_id, None)
        self._pending.pop(req_id, None)

        if resp is None:
            print(f"MCP: Request {method} timed out")
            return None

        if "error" in resp:
            print(f"MCP: Request {method} error: {resp['error']}")
            return None

        return resp.get("result")

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            data = json.dumps(message) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            self._process.stdin.flush()
        except Exception:
            pass

    def _read_loop(self):
        """Read JSON-RPC responses from stdout."""
        while self._process and self._process.poll() is None:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if not line:
                    continue

                msg = json.loads(line)
                req_id = msg.get("id")

                if req_id is not None and req_id in self._pending:
                    self._responses[req_id] = msg
                    self._pending[req_id].set()
                else:
                    # Notification or unknown message - ignore
                    pass

            except json.JSONDecodeError:
                pass
            except Exception:
                break


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.Lock()

    @property
    def all_tools(self) -> list[dict]:
        """Get all tools from all connected MCP servers."""
        tools = []
        with self._lock:
            for client in self._clients.values():
                if client._initialized:
                    for tool in client.tools:
                        # Add server prefix to tool name to avoid collisions
                        prefixed = dict(tool)
                        prefixed["name"] = f"{client.server_id}__{tool['name']}"
                        prefixed["_mcp_server"] = client.server_id
                        prefixed["_mcp_original_name"] = tool["name"]
                        tools.append(prefixed)
        return tools

    def connect_server(self, server_id: str, command: str, args: list[str] = None,
                       env: dict[str, str] = None, name: str = "",
                       timeout: float = 10.0) -> bool:
        """Connect to an MCP server."""
        with self._lock:
            # Stop existing connection if any
            if server_id in self._clients:
                self._clients[server_id].stop()

            client = MCPClient(
                server_id=server_id,
                command=command,
                args=args,
                env=env,
                name=name,
            )

            if client.start(timeout=timeout):
                self._clients[server_id] = client
                return True
            return False

    def disconnect_server(self, server_id: str):
        """Disconnect from an MCP server."""
        with self._lock:
            client = self._clients.pop(server_id, None)
            if client:
                client.stop()

    def disconnect_all(self):
        """Disconnect from all MCP servers."""
        with self._lock:
            for client in self._clients.values():
                client.stop()
            self._clients.clear()

    def call_tool(self, full_tool_name: str, arguments: dict,
                  timeout: float = 30.0) -> dict[str, Any]:
        """Call a tool by its prefixed name (server_id__tool_name)."""
        parts = full_tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool name format: {full_tool_name}"}

        server_id, tool_name = parts
        with self._lock:
            client = self._clients.get(server_id)

        if not client:
            return {"error": f"MCP server not connected: {server_id}"}

        return client.call_tool(tool_name, arguments, timeout=timeout)

    def get_server(self, server_id: str) -> Optional[MCPClient]:
        """Get a connected MCP client."""
        with self._lock:
            return self._clients.get(server_id)

    def is_connected(self, server_id: str) -> bool:
        """Check if an MCP server is connected."""
        with self._lock:
            client = self._clients.get(server_id)
            return client is not None and client._initialized
