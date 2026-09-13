"""Model Context Protocol (MCP) async stdio client for Contexer.

Implements JSON-RPC 2.0 transport over standard I/O according to the
Model Context Protocol specification (2024-11-05).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    """Base exception for all MCP-related errors."""


class MCPConnectionError(MCPError):
    """Raised when connecting or launching the MCP server process fails."""


class MCPProtocolError(MCPError):
    """Raised when an MCP protocol violation or JSON-RPC error occurs."""


class MCPTimeoutError(MCPError):
    """Raised when an MCP request times out."""


@dataclass(frozen=True)
class MCPTool:
    """Discovered tool exposed by an MCP server."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Async stdio client for communicating with an MCP server."""

    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[Path | str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.command = command
        self.args = args or []
        self.custom_env = env or {}
        self.cwd = str(cwd) if cwd else None
        self.timeout = timeout

        self._process: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self._pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None
        self._closing = False

        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self.protocol_version: Optional[str] = None
        self.stderr_lines: list[str] = []

    @property
    def is_connected(self) -> bool:
        """Return True if the subprocess is currently running and initialized."""
        return (
            self._process is not None
            and self._process.returncode is None
            and not self._closing
        )

    async def start(self) -> None:
        """Spawn the MCP server process and complete the initialize handshake."""
        if self.is_connected:
            return

        merged_env = dict(os.environ)
        merged_env.update(self.custom_env)

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
                cwd=self.cwd,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise MCPConnectionError(
                f"Failed to start MCP server '{self.command}': {exc}"
            ) from exc

        self._closing = False
        self._reader_task = asyncio.create_task(self._stdout_reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_reader_loop())

        # Perform initialize handshake
        try:
            init_response = await self._send_request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "contexer",
                        "version": "0.1.0",
                    },
                },
            )
            self.protocol_version = init_response.get("protocolVersion")
            self.server_capabilities = init_response.get("capabilities", {})
            self.server_info = init_response.get("serverInfo", {})

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})
            logger.info(
                "Connected to MCP server '%s' (%s)",
                self.server_info.get("name", self.command),
                self.server_info.get("version", "unknown"),
            )
        except Exception:
            await self.close()
            raise

    async def list_tools(self) -> list[MCPTool]:
        """Query the MCP server for available tools via tools/list."""
        response = await self._send_request("tools/list", {})
        raw_tools = response.get("tools", [])
        tools: list[MCPTool] = []
        for t in raw_tools:
            if not isinstance(t, dict) or "name" not in t:
                continue
            name = str(t["name"])
            desc = str(t.get("description") or "")
            schema = t.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            tools.append(MCPTool(name=name, description=desc, input_schema=schema))
        return tools

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """Invoke a tool on the MCP server and return output as a string."""
        params = {
            "name": name,
            "arguments": arguments or {},
        }
        response = await self._send_request("tools/call", params)
        content_items = response.get("content", [])
        is_error = bool(response.get("isError", False))

        text_parts: list[str] = []
        for item in content_items:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(str(item["text"]))
                elif "data" in item:
                    text_parts.append(str(item["data"]))
            elif isinstance(item, str):
                text_parts.append(item)

        output = "\n".join(text_parts) if text_parts else json.dumps(response, default=str)
        if is_error:
            if not output.startswith("Error:"):
                return f"Error: {output}"
        return output

    async def close(self) -> None:
        """Gracefully shut down the MCP server process and reader tasks."""
        self._closing = True

        # Cancel pending futures with connection error
        for req_id, future in list(self._pending_requests.items()):
            if not future.done():
                future.set_exception(MCPConnectionError("MCP connection closed"))
        self._pending_requests.clear()

        # Cancel reader tasks first
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

        if self._process is not None:
            if self._process.stdin and not self._process.stdin.is_closing():
                try:
                    self._process.stdin.close()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self._process.wait(), timeout=1.0)
            except Exception:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=1.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass

            for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                if stream is not None:
                    trans = getattr(stream, "_transport", None)
                    if trans is not None:
                        try:
                            trans.close()
                        except Exception:
                            pass

            proc_trans = getattr(self._process, "_transport", None)
            if proc_trans is not None:
                try:
                    proc_trans.close()
                except Exception:
                    pass

        self._process = None

    async def __aenter__(self) -> MCPClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the matching response."""
        if not self.is_connected or self._process is None or self._process.stdin is None:
            raise MCPConnectionError("MCP client is not connected")

        req_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        message = json.dumps(payload) + "\n"
        try:
            self._process.stdin.write(message.encode("utf-8"))
            await self._process.stdin.drain()
        except (OSError, ConnectionResetError) as exc:
            self._pending_requests.pop(req_id, None)
            raise MCPConnectionError(f"Failed to write to MCP server: {exc}") from exc

        try:
            return await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            self._pending_requests.pop(req_id, None)
            raise MCPTimeoutError(
                f"MCP request '{method}' (id={req_id}) timed out after {self.timeout}s"
            ) from exc

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a fire-and-forget JSON-RPC notification."""
        if not self.is_connected or self._process is None or self._process.stdin is None:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        message = json.dumps(payload) + "\n"
        try:
            self._process.stdin.write(message.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as exc:
            logger.debug("Failed to send MCP notification '%s': %s", method, exc)

    async def _stdout_reader_loop(self) -> None:
        """Continuously read newline-delimited JSON-RPC messages from server stdout."""
        if not self._process or not self._process.stdout:
            return

        while not self._closing:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8").strip()
                if not decoded:
                    continue

                try:
                    msg = json.loads(decoded)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON line from MCP server stdout: %s", decoded)
                    continue

                if isinstance(msg, dict):
                    self._handle_incoming_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._closing:
                    logger.warning("Error reading from MCP server stdout: %s", exc)
                break

        # Process closed or terminated
        if not self._closing:
            returncode = self._process.returncode if self._process else None
            logger.info("MCP server stdout closed (exit code=%s)", returncode)
            # Fail any still pending requests
            for req_id, future in list(self._pending_requests.items()):
                if not future.done():
                    future.set_exception(
                        MCPConnectionError(
                            f"MCP server exited unexpectedly with code {returncode}"
                        )
                    )
            self._pending_requests.clear()

    async def _stderr_reader_loop(self) -> None:
        """Continuously capture server stderr for diagnostic inspection."""
        if not self._process or not self._process.stderr:
            return

        while not self._closing:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    self.stderr_lines.append(decoded)
                    if len(self.stderr_lines) > 200:
                        self.stderr_lines.pop(0)
                    logger.debug("[MCP stderr] %s", decoded)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    def _handle_incoming_message(self, msg: dict[str, Any]) -> None:
        """Route responses to pending request futures."""
        req_id = msg.get("id")
        if req_id is not None and isinstance(req_id, int):
            future = self._pending_requests.pop(req_id, None)
            if future is not None and not future.done():
                if "error" in msg:
                    err_info = msg["error"]
                    err_msg = (
                        err_info.get("message")
                        if isinstance(err_info, dict)
                        else str(err_info)
                    )
                    future.set_exception(
                        MCPProtocolError(f"MCP server error ({req_id}): {err_msg}")
                    )
                else:
                    future.set_result(msg.get("result", {}))
