"""
mcp_client.py — MCP (Model Protocol) client for llama-tray.

Supports multiple transports:
  - stdio:          JSON-RPC 2.0 over stdin/stdout
  - sse:            Server-Sent Events (GET /sse, POST /message)
  - streamable-http: Streamable HTTP (POST with streaming response)
  - rpc:            TCP JSON-RPC 2.0
"""

import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional


class MCPClient:
    """Base MCP client with transport-specific subclasses."""

    def __init__(self, server_id: str, name: str = ""):
        self.server_id = server_id
        self.name = name or server_id
        self._initialized = False
        self.tools: list[dict] = []

    def start(self, timeout: float = 10.0) -> bool:
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        raise NotImplementedError

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Optional[dict]:
        raise NotImplementedError

    def _send_notification(self, method: str, params: dict):
        raise NotImplementedError


# ── Stdio Transport ──────────────────────────────────────────────────────


class MCPStdioClient(MCPClient):
    """MCP client using stdio (stdin/stdout) JSON-RPC 2.0."""

    def __init__(
        self, server_id: str, command: str, args: list[str] = None, env: dict[str, str] = None, name: str = ""
    ):
        super().__init__(server_id, name)
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None

    def start(self, timeout: float = 10.0) -> bool:
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

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llama-tray", "version": "1.0.0"},
                },
                timeout=timeout,
            )

            if resp is None:
                return False

            self._send_notification("notifications/initialized", {})
            resp = self._send_request("tools/list", {}, timeout=timeout)
            if resp and "tools" in resp:
                self.tools = resp["tools"]

            self._initialized = True
            return True

        except Exception as e:
            print(f"MCP stdio: Failed to start {self.name}: {e}")
            self.stop()
            return False

    def stop(self):
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

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "MCP server not initialized"}
        resp = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
            timeout=timeout,
        )
        if resp is None:
            return {"error": "No response from MCP server"}
        return resp

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Optional[dict]:
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
            print(f"MCP stdio: Failed to send request: {e}")
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)
            return None

        event.wait(timeout=timeout)
        resp = self._responses.pop(req_id, None)
        self._pending.pop(req_id, None)

        if resp is None:
            print(f"MCP stdio: Request {method} timed out")
            return None
        if "error" in resp:
            print(f"MCP stdio: Request {method} error: {resp['error']}")
            return None
        return resp.get("result")

    def _send_notification(self, method: str, params: dict):
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
            except json.JSONDecodeError:
                pass
            except Exception:
                break


# ── SSE Transport ────────────────────────────────────────────────────────


class MCPSSEClient(MCPClient):
    """MCP client using Server-Sent Events (SSE) transport.

    GET  /sse   — receives SSE stream with JSON-RPC messages
    POST /message — sends JSON-RPC requests
    """

    def __init__(self, server_id: str, url: str, headers: dict[str, str] = None, name: str = ""):
        super().__init__(server_id, name)
        self.url = url
        self.headers = {"User-Agent": "LlamaTray/1.0"}
        if headers:
            self.headers.update(headers)
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, Any] = {}
        self._sse_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._message_url: Optional[str] = None

    def start(self, timeout: float = 10.0) -> bool:
        try:
            self._stop_event.clear()

            # Start SSE listener thread
            self._sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
            self._sse_thread.start()

            # Wait for message URL to be discovered
            deadline = time.time() + timeout
            while time.time() < deadline and self._message_url is None:
                if self._stop_event.is_set():
                    return False
                time.sleep(0.05)

            if self._message_url is None:
                print(f"MCP SSE: Timed out waiting for endpoint from {self.url}")
                return False

            # Initialize
            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llama-tray", "version": "1.0.0"},
                },
                timeout=timeout,
            )

            if resp is None:
                return False

            self._send_notification("notifications/initialized", {})
            resp = self._send_request("tools/list", {}, timeout=timeout)
            if resp and "tools" in resp:
                self.tools = resp["tools"]

            self._initialized = True
            return True

        except Exception as e:
            print(f"MCP SSE: Failed to start {self.name}: {e}")
            self.stop()
            return False

    def stop(self):
        self._initialized = False
        self._stop_event.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2)

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "MCP server not initialized"}
        resp = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
            timeout=timeout,
        )
        if resp is None:
            return {"error": "No response from MCP server"}
        return resp

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Optional[dict]:
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
            data = json.dumps(message).encode("utf-8")
            req = urllib.request.Request(
                self._message_url,
                data=data,
                headers={**self.headers, "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            print(f"MCP SSE: Failed to send request: {e}")
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)
            return None

        event.wait(timeout=timeout)
        resp = self._responses.pop(req_id, None)
        self._pending.pop(req_id, None)

        if resp is None:
            print(f"MCP SSE: Request {method} timed out")
            return None
        if "error" in resp:
            print(f"MCP SSE: Request {method} error: {resp['error']}")
            return None
        return resp.get("result")

    def _send_notification(self, method: str, params: dict):
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            data = json.dumps(message).encode("utf-8")
            req = urllib.request.Request(
                self._message_url,
                data=data,
                headers={**self.headers, "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    def _sse_loop(self):
        """Read SSE stream from GET /sse endpoint."""
        try:
            req = urllib.request.Request(
                self.url,
                headers=self.headers,
            )
            resp = urllib.request.urlopen(req, timeout=30)
            buf = ""
            event_type = ""
            event_data = ""

            while not self._stop_event.is_set():
                line = resp.readline()
                if not line:
                    break
                line = line.decode("utf-8").rstrip("\n\r")

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    event_data = line[5:].strip()
                elif line == "":
                    # End of event
                    if event_type == "endpoint" and event_data:
                        # Build full URL if relative
                        if event_data.startswith("/"):
                            self._message_url = f"{self.url}{event_data}"
                        else:
                            self._message_url = event_data
                    elif event_type == "message" and event_data:
                        try:
                            msg = json.loads(event_data)
                            req_id = msg.get("id")
                            if req_id is not None and req_id in self._pending:
                                self._responses[req_id] = msg
                                self._pending[req_id].set()
                        except json.JSONDecodeError:
                            pass
                    event_type = ""
                    event_data = ""

        except Exception as e:
            if not self._stop_event.is_set():
                print(f"MCP SSE: Stream error: {e}")


# ── Streamable HTTP Transport ────────────────────────────────────────────


class MCPHTTPClient(MCPClient):
    """MCP client using Streamable HTTP transport.

    POST /mcp — sends JSON-RPC, receives streaming or single response.
    """

    def __init__(self, server_id: str, url: str, headers: dict[str, str] = None, name: str = ""):
        super().__init__(server_id, name)
        self.url = url
        self.headers = {"User-Agent": "LlamaTray/1.0"}
        if headers:
            self.headers.update(headers)
        self._request_id = 0
        self._lock = threading.Lock()

    def start(self, timeout: float = 10.0) -> bool:
        try:
            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llama-tray", "version": "1.0.0"},
                },
                timeout=timeout,
            )

            if resp is None:
                return False

            self._send_notification("notifications/initialized", {})
            resp = self._send_request("tools/list", {}, timeout=timeout)
            if resp and "tools" in resp:
                self.tools = resp["tools"]

            self._initialized = True
            return True

        except Exception as e:
            print(f"MCP HTTP: Failed to start {self.name}: {e}")
            return False

    def stop(self):
        self._initialized = False

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "MCP server not initialized"}
        resp = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
            timeout=timeout,
        )
        if resp is None:
            return {"error": "No response from MCP server"}
        return resp

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Optional[dict]:
        req_id = self._next_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(message).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            content_type = resp.headers.get("Content-Type", "")

            if "text/event-stream" in content_type:
                # Streaming response — collect events
                result = self._collect_sse_response(resp, req_id, timeout)
                return result
            else:
                # Single JSON response
                body = resp.read().decode("utf-8").strip()
                if body:
                    msg = json.loads(body)
                    if "error" in msg:
                        print(f"MCP HTTP: Request {method} error: {msg['error']}")
                        return None
                    return msg.get("result")
                return None

        except Exception as e:
            print(f"MCP HTTP: Request {method} failed: {e}")
            return None

    def _collect_sse_response(self, resp, expect_id: int, timeout: float) -> Optional[dict]:
        """Parse SSE stream and collect the response for expect_id."""
        deadline = time.time() + timeout
        event_data = ""
        event_type = ""

        while time.time() < deadline:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8").rstrip("\n\r")

            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                event_data = line[5:].strip()
            elif line == "":
                if event_type == "message" and event_data:
                    try:
                        msg = json.loads(event_data)
                        if msg.get("id") == expect_id:
                            if "error" in msg:
                                print(f"MCP HTTP: SSE error: {msg['error']}")
                                return None
                            return msg.get("result")
                    except json.JSONDecodeError:
                        pass
                event_type = ""
                event_data = ""

        return None

    def _send_notification(self, method: str, params: dict):
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            data = json.dumps(message).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


# ── TCP RPC Transport ────────────────────────────────────────────────────


class MCPRPCClient(MCPClient):
    """MCP client using TCP JSON-RPC 2.0 transport."""

    def __init__(self, server_id: str, url: str, headers: dict[str, str] = None, name: str = ""):
        super().__init__(server_id, name)
        # url format: host:port
        self.url = url
        self.headers = headers or {}
        self._request_id = 0
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, timeout: float = 10.0) -> bool:
        try:
            host, port_str = self.url.rsplit(":", 1)
            port = int(port_str)

            self._sock = socket.create_connection((host, port), timeout=timeout)
            self._sock.settimeout(timeout)
            self._stop_event.clear()

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            resp = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llama-tray", "version": "1.0.0"},
                },
                timeout=timeout,
            )

            if resp is None:
                return False

            self._send_notification("notifications/initialized", {})
            resp = self._send_request("tools/list", {}, timeout=timeout)
            if resp and "tools" in resp:
                self.tools = resp["tools"]

            self._initialized = True
            return True

        except Exception as e:
            print(f"MCP RPC: Failed to start {self.name}: {e}")
            self.stop()
            return False

    def stop(self):
        self._initialized = False
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if not self._initialized:
            return {"error": "MCP server not initialized"}
        resp = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
            timeout=timeout,
        )
        if resp is None:
            return {"error": "No response from MCP server"}
        return resp

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> Optional[dict]:
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
            self._sock.sendall(data.encode("utf-8"))
        except Exception as e:
            print(f"MCP RPC: Failed to send request: {e}")
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)
            return None

        event.wait(timeout=timeout)
        resp = self._responses.pop(req_id, None)
        self._pending.pop(req_id, None)

        if resp is None:
            print(f"MCP RPC: Request {method} timed out")
            return None
        if "error" in resp:
            print(f"MCP RPC: Request {method} error: {resp['error']}")
            return None
        return resp.get("result")

    def _send_notification(self, method: str, params: dict):
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            data = json.dumps(message) + "\n"
            self._sock.sendall(data.encode("utf-8"))
        except Exception:
            pass

    def _read_loop(self):
        buf = ""
        while not self._stop_event.is_set():
            try:
                self._sock.settimeout(1.0)
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    req_id = msg.get("id")
                    if req_id is not None and req_id in self._pending:
                        self._responses[req_id] = msg
                        self._pending[req_id].set()
            except socket.timeout:
                continue
            except Exception:
                break


# ── Factory ──────────────────────────────────────────────────────────────

MCP_TRANSPORT_MAP = {
    "stdio": MCPStdioClient,
    "sse": MCPSSEClient,
    "streamable-http": MCPHTTPClient,
    "rpc": MCPRPCClient,
}


def create_mcp_client(
    server_id: str,
    transport: str,
    name: str = "",
    command: str = "",
    args: list[str] = None,
    env: dict[str, str] = None,
    url: str = "",
    headers: dict[str, str] = None,
) -> Optional[MCPClient]:
    """Create an MCP client for the given transport type."""
    cls = MCP_TRANSPORT_MAP.get(transport)
    if cls is None:
        print(f"MCP: Unknown transport '{transport}'")
        return None

    if transport == "stdio":
        return cls(server_id=server_id, command=command, args=args, env=env, name=name)
    else:
        return cls(server_id=server_id, url=url, headers=headers, name=name)


# ── Manager ──────────────────────────────────────────────────────────────


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.Lock()

    @property
    def all_tools(self) -> list[dict]:
        tools = []
        with self._lock:
            for client in self._clients.values():
                if client._initialized:
                    for tool in client.tools:
                        prefixed = dict(tool)
                        prefixed["name"] = f"{client.server_id}__{tool['name']}"
                        prefixed["_mcp_server"] = client.server_id
                        prefixed["_mcp_original_name"] = tool["name"]
                        tools.append(prefixed)
        return tools

    def connect_server(
        self,
        server_id: str,
        transport: str = "stdio",
        command: str = "",
        args: list[str] = None,
        env: dict[str, str] = None,
        url: str = "",
        headers: dict[str, str] = None,
        name: str = "",
        timeout: float = 10.0,
    ) -> bool:
        with self._lock:
            if server_id in self._clients:
                self._clients[server_id].stop()

            client = create_mcp_client(
                server_id=server_id,
                transport=transport,
                name=name,
                command=command,
                args=args,
                env=env,
                url=url,
                headers=headers,
            )

            if client is None:
                return False

            if client.start(timeout=timeout):
                self._clients[server_id] = client
                return True
            return False

    def disconnect_server(self, server_id: str):
        with self._lock:
            client = self._clients.pop(server_id, None)
            if client:
                client.stop()

    def disconnect_all(self):
        with self._lock:
            for client in self._clients.values():
                client.stop()
            self._clients.clear()

    def call_tool(self, full_tool_name: str, arguments: dict, timeout: float = 30.0) -> dict[str, Any]:
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
        with self._lock:
            return self._clients.get(server_id)

    def is_connected(self, server_id: str) -> bool:
        with self._lock:
            client = self._clients.get(server_id)
            return client is not None and client._initialized
