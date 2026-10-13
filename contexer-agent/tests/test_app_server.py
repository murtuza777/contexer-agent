"""Tests for the static app server used to observe static projects over HTTP."""

from pathlib import Path

import httpx
import pytest

from contexer.workflow.app_server import StaticAppServer


def test_serves_files_created_after_start_without_caching(tmp_path: Path) -> None:
    with StaticAppServer(tmp_path) as server:
        assert server.url.startswith("http://127.0.0.1:")
        (tmp_path / "index.html").write_text("<h1>v1</h1>", encoding="utf-8")
        first = httpx.get(server.url)
        (tmp_path / "index.html").write_text("<h1>v2</h1>", encoding="utf-8")
        second = httpx.get(server.url)

    assert first.status_code == 200 and "v1" in first.text
    assert "v2" in second.text
    assert first.headers["cache-control"] == "no-store"


def test_stop_releases_the_port(tmp_path: Path) -> None:
    server = StaticAppServer(tmp_path)
    url = server.start()
    server.stop()
    # Refused on POSIX; Windows loopback may time out instead. Either way nothing answers.
    with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
        httpx.get(url, timeout=1)
    with pytest.raises(RuntimeError):
        _ = server.url
