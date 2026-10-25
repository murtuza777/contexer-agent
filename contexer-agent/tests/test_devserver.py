"""Start plans and the dev-server lifecycle, against a real Node process tree."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from contexer.appserver import AppStartError, open_app
from contexer.appserver.detect import detect_framework, package_manager, plan_start
from contexer.appserver.devserver import DevServer, DevServerError
from contexer.config.project import AppSettings

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None or shutil.which("npm") is None, reason="node and npm are required")

# A dev server that, like real ones, spawns a long-lived child process and
# writes the child's pid where the test can find it.
SERVER_JS = r"""
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });
fs.writeFileSync("child.pid", String(child.pid));
const port = Number(process.env.PORT);
http.createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html" });
  res.end("<!doctype html><title>Node fixture</title><h1>Hello from node</h1>");
}).listen(port, "127.0.0.1", () => console.log(`listening on http://127.0.0.1:${port}`));
"""


def _node_project(root: Path, script: str = "node server.js") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"name": "fixture", "scripts": {"dev": script}}), encoding="utf-8")
    (root / "server.js").write_text(SERVER_JS, encoding="utf-8")
    (root / "node_modules").mkdir()  # nothing to install
    return root


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        import os

        os.kill(pid, 0)
    except OSError:
        return False
    return True


# -- planning -------------------------------------------------------------------


def test_plan_pins_port_flags_per_framework(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^6"}}), encoding="utf-8"
    )
    plan = plan_start(tmp_path, AppSettings(port=5199))
    assert plan.framework == "vite"
    assert plan.argv[-5:] == ["--port", "5199", "--strictPort", "--host", "127.0.0.1"]
    assert plan.argv[1:4] == ["run", "dev", "--"]  # npm needs the separator
    assert plan.install_argv is not None  # no node_modules yet
    assert plan.url == "http://127.0.0.1:5199/"


def test_plan_respects_a_port_already_in_the_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev -p 4000"}}), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    plan = plan_start(tmp_path)
    assert plan.port == 4000
    assert plan.argv[1:] == ["run", "dev"]  # no duplicate port flags
    assert package_manager(tmp_path, None) == "pnpm"


def test_configured_start_command_substitutes_port(tmp_path: Path) -> None:
    plan = plan_start(tmp_path, AppSettings(start="python -m http.server {port}", port=8123))
    assert "8123" in plan.display
    assert plan.env["PORT"] == "8123"


def test_framework_detection_prefers_the_command() -> None:
    assert detect_framework("next dev --turbopack", {}) == "next"
    assert detect_framework("vite dev", {"dependencies": {"next": "1"}}) == "vite"
    assert detect_framework("node server.js", {"devDependencies": {"@vitejs/plugin-react": "1"}}) == "vite"
    assert detect_framework("node server.js", {}) == "unknown"


def test_no_way_to_start_is_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    with pytest.raises(AppStartError, match="contexer.toml"):
        with open_app(tmp_path):
            pass


# -- lifecycle --------------------------------------------------------------------


@needs_node
def test_dev_server_starts_serves_and_kills_the_whole_tree(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "app")
    log = tmp_path / "server.log"
    with open_app(project, log_path=log) as app:
        assert app.kind == "dev"
        assert "Hello from node" in httpx.get(app.url).text
        child_pid = int((project / "child.pid").read_text())
        assert _pid_alive(child_pid)
        assert "listening on" in app.log_tail()

    deadline = time.monotonic() + 10
    while _pid_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _pid_alive(child_pid), "grandchild process survived stop()"
    assert "listening on" in log.read_text(encoding="utf-8")


@needs_node
def test_server_that_crashes_reports_its_log(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "app", script="node -e \"console.error('boom: missing module'); process.exit(3)\"")
    plan = plan_start(project, AppSettings(ready_timeout=20))
    with pytest.raises(DevServerError) as info:
        DevServer(plan).start()
    assert "exited with code 3" in str(info.value)
    assert "boom: missing module" in info.value.log_tail


def test_a_lockfile_is_installed_exactly_and_never_rewritten(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
    assert plan_start(tmp_path).install_argv[1:] == ["install"]  # type: ignore[index]
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    assert plan_start(tmp_path).install_argv[1:] == ["ci"]  # type: ignore[index]
    (tmp_path / "package-lock.json").unlink()
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert plan_start(tmp_path).install_argv[1:] == ["install", "--frozen-lockfile"]  # type: ignore[index]
    assert plan_start(tmp_path, AppSettings(install=False)).install_argv is None


@needs_node
def test_restart_reinstalls_when_dependencies_changed(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "app")  # node_modules already present
    plan = plan_start(project)
    marker = project / "installs.txt"
    plan.install_argv = [str(NODE), "-e", "require('fs').appendFileSync('installs.txt', 'x')"]
    server = DevServer(plan)
    try:
        server.start()
        assert not marker.exists()  # dependencies were already installed
        server.restart(install=True)
        assert marker.read_text() == "x"
        assert server.is_alive()
    finally:
        server.stop()


@needs_node
def test_ensure_running_restarts_a_dead_server(tmp_path: Path) -> None:
    project = _node_project(tmp_path / "app")
    plan = plan_start(project)
    server = DevServer(plan)
    try:
        url = server.start()
        server.stop()
        assert not server.is_alive()
        assert server.ensure_running() == url
        assert httpx.get(url).status_code == 200
    finally:
        server.stop()
