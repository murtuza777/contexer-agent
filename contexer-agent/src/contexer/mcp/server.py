"""Official GitHub MCP Server runner and environment configurator.

Resolves, configures, and launches the official GitHub MCP Server
(https://github.com/github/github-mcp-server) strictly in read-only mode.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import platform
import shutil
from typing import Optional
import urllib.request
import zipfile

from contexer.config.settings import ContexerConfig
from contexer.mcp.client import MCPClient

logger = logging.getLogger(__name__)

OFFICIAL_GITHUB_MCP_REPO = "github/github-mcp-server"
DEFAULT_RELEASE_VERSION = "v1.12.1"


class GitHubMCPServerRunner:
    """Configures and resolves the official GitHub MCP Server process."""

    def __init__(self, config: Optional[ContexerConfig] = None) -> None:
        self.config = config or ContexerConfig()

    @property
    def token(self) -> Optional[str]:
        """Retrieve GitHub Personal Access Token from config, environment, or git credentials."""
        if self.config.github_token:
            return self.config.github_token
        raw = (
            os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
        )
        if raw and raw.strip():
            return raw.strip()

        # Local developer fallback: query git credential manager
        try:
            import subprocess

            proc = subprocess.run(
                ["git", "credential", "fill"],
                input="protocol=https\nhost=github.com\n",
                text=True,
                capture_output=True,
                timeout=2.0,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    if line.startswith("password="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        except Exception:
            pass

        return None

    @property
    def read_only(self) -> bool:
        """Return whether read-only mode is enforced (always True for MVP)."""
        return bool(self.config.github_mcp_read_only)

    @property
    def toolsets(self) -> str:
        """Return configured toolsets (defaults to repos,issues)."""
        return self.config.github_mcp_toolsets or "repos,issues"

    def resolve_executable(self, workspace_root: Optional[Path | str] = None) -> Optional[tuple[str, list[str]]]:
        """Find the official github-mcp-server executable or container runner.

        Returns:
            Tuple of (command, args) or None if no runner is available.
        """
        # 1. User-configured custom command
        if self.config.github_mcp_command:
            parts = self.config.github_mcp_command.split()
            return parts[0], parts[1:]

        # 2. Workspace-local or home-dir cached binary (.contexer/bin/github-mcp-server)
        roots = []
        if workspace_root:
            roots.append(Path(workspace_root))
        roots.append(Path.cwd())
        try:
            roots.append(Path.home())
        except (RuntimeError, OSError):
            pass

        bin_name = "github-mcp-server.exe" if platform.system() == "Windows" else "github-mcp-server"
        for root in roots:
            candidate = root / ".contexer" / "bin" / bin_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate), ["stdio"]

        # 3. System PATH
        on_path = shutil.which("github-mcp-server") or shutil.which(bin_name)
        if on_path:
            return on_path, ["stdio"]

        # 4. Docker runner if docker is present
        docker_bin = shutil.which("docker")
        if docker_bin:
            return docker_bin, [
                "run",
                "-i",
                "--rm",
                "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e", "GITHUB_READ_ONLY=true",
                "-e", f"GITHUB_TOOLSETS={self.toolsets}",
                "ghcr.io/github/github-mcp-server",
                "stdio",
            ]

        return None

    def check_availability(self, workspace_root: Optional[Path | str] = None) -> tuple[bool, str]:
        """Diagnose configuration and readiness without leaking credentials."""
        if not self.config.github_mcp_enabled:
            return False, "GitHub MCP integration is disabled in configuration."

        if not self.token:
            return (
                False,
                "GitHub Personal Access Token is missing. Set GITHUB_PERSONAL_ACCESS_TOKEN "
                "in your environment or .env file (with repo read permissions).",
            )

        runner = self.resolve_executable(workspace_root)
        if not runner:
            return (
                False,
                "Official GitHub MCP Server is not found. Please install 'github-mcp-server' "
                "or ensure Docker Desktop is running.",
            )

        cmd, _ = runner
        return True, f"GitHub MCP Server runner ready ({Path(cmd).name})."

    def create_client(self, workspace_root: Optional[Path | str] = None) -> MCPClient:
        """Construct an MCPClient configured for the official GitHub MCP server."""
        available, reason = self.check_availability(workspace_root)
        if not available:
            raise RuntimeError(reason)

        token = self.token
        if not token:
            raise RuntimeError("Missing GitHub Personal Access Token.")

        resolved = self.resolve_executable(workspace_root)
        if not resolved:
            raise RuntimeError("Could not resolve github-mcp-server executable.")

        cmd, base_args = resolved

        # Prepare arguments: enforce read-only and toolsets
        extra_args: list[str] = []
        if not cmd.lower().endswith("docker") and not cmd.lower().endswith("docker.exe"):
            if "--read-only" not in base_args:
                extra_args.append("--read-only")
            if "--toolsets" not in base_args:
                extra_args.extend(["--toolsets", self.toolsets])

        final_args = list(base_args) + extra_args

        # Set environment variables for the subprocess
        env = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
            "GITHUB_READ_ONLY": "true",
            "GITHUB_TOOLSETS": self.toolsets,
        }

        return MCPClient(
            command=cmd,
            args=final_args,
            env=env,
            cwd=workspace_root,
            timeout=45.0,
        )

    @classmethod
    def download_official_binary(cls, dest_dir: Path) -> Path:
        """Download official GitHub MCP server binary from GitHub releases.

        Supports Windows x86_64, Darwin (arm64/x86_64), and Linux (x86_64/arm64).
        """
        sys_name = platform.system()
        machine = platform.machine().lower()

        if sys_name == "Windows":
            arch = "x86_64"
            asset_name = f"github-mcp-server_Windows_{arch}.zip"
            bin_name = "github-mcp-server.exe"
        elif sys_name == "Darwin":
            arch = "arm64" if "arm" in machine or "aarch64" in machine else "x86_64"
            asset_name = f"github-mcp-server_Darwin_{arch}.tar.gz"
            bin_name = "github-mcp-server"
        elif sys_name == "Linux":
            arch = "arm64" if "arm" in machine or "aarch64" in machine else "x86_64"
            asset_name = f"github-mcp-server_Linux_{arch}.tar.gz"
            bin_name = "github-mcp-server"
        else:
            raise RuntimeError(f"Unsupported operating system: {sys_name}")

        download_url = (
            f"https://github.com/{OFFICIAL_GITHUB_MCP_REPO}/releases/download/"
            f"{DEFAULT_RELEASE_VERSION}/{asset_name}"
        )
        logger.info("Downloading official GitHub MCP server binary from %s", download_url)

        dest_dir.mkdir(parents=True, exist_ok=True)
        final_binary = dest_dir / bin_name

        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Contexer-Agent/0.1.0"},
        )
        with urllib.request.urlopen(req) as resp:
            data = resp.read()

        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    if member.endswith(bin_name) or member == bin_name:
                        with zf.open(member) as source, open(final_binary, "wb") as target:
                            shutil.copyfileobj(source, target)
                        break
        else:
            import tarfile

            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if member.name.endswith(bin_name) or member.name == bin_name:
                        f = tf.extractfile(member)
                        if f:
                            with open(final_binary, "wb") as target:
                                shutil.copyfileobj(f, target)
                        break

        if not final_binary.exists():
            raise RuntimeError(f"Could not extract {bin_name} from release asset {asset_name}")

        try:
            os.chmod(final_binary, 0o755)
        except OSError:
            pass

        logger.info("Successfully installed official GitHub MCP server to %s", final_binary)
        return final_binary
