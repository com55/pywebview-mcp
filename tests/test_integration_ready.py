import json
import os
import subprocess
import sys
import time

import httpx
import pytest

EXAMPLE = "examples/test_app.py"


def _env() -> dict[str, str]:
    return os.environ.copy()


def _free_cdp_port() -> int:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ready(base: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base}/ready", timeout=1)
            if r.status_code == 200:
                last = r.json()
                if last.get("ready"):
                    return last
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise AssertionError(f"bridge never reported ready: {last}")


@pytest.mark.integration
def test_ready_endpoint_reports_ready(free_port):
    cdp = _free_cdp_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "pywebview_mcp", EXAMPLE],
        env={
            **_env(),
            "PYWEBVIEW_MCP_PORT": str(free_port),
            "PYWEBVIEW_MCP_CDP_PORT": str(cdp),
        },
    )
    base = f"http://127.0.0.1:{free_port}"
    try:
        body = _wait_ready(base)
        assert body.get("pywebview_ready") is True
        assert body.get("dom_ready") is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.integration
def test_dom_tree_returns_elements(free_port):
    cdp = _free_cdp_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "pywebview_mcp", EXAMPLE],
        env={
            **_env(),
            "PYWEBVIEW_MCP_PORT": str(free_port),
            "PYWEBVIEW_MCP_CDP_PORT": str(cdp),
        },
    )
    base = f"http://127.0.0.1:{free_port}"
    try:
        _wait_ready(base)
        dom = httpx.get(f"{base}/dom", timeout=5).json()
        assert "elements" in dom
        assert dom["elements"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _call_launch_app(
    server,
    *,
    port: int,
    cwd: str | None = None,
    script: str = EXAMPLE,
    timeout: int = 45,
) -> str:
    fn = getattr(server.launch_app, "fn", server.launch_app)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return fn(cwd=cwd or root, script=script, port=port, timeout=timeout)


def _call_stop_app(server, port: int) -> str:
    fn = getattr(server.stop_app, "fn", server.stop_app)
    return fn(port=port)


@pytest.mark.integration
def test_launch_app_tool_waits_for_ready(free_port, monkeypatch):
    cdp = _free_cdp_port()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg_path = root.replace("\\", "/")
    monkeypatch.setenv("PYWEBVIEW_MCP_PORT", str(free_port))
    monkeypatch.setenv("PYWEBVIEW_MCP_CDP_PORT", str(cdp))
    monkeypatch.setenv("PYWEBVIEW_MCP_PACKAGE", f"pywebview-mcp @ file:///{pkg_path}")

    import importlib

    import pywebview_mcp.server as server

    importlib.reload(server)

    result = _call_launch_app(server, port=free_port, timeout=45)
    data = json.loads(result)
    try:
        assert data.get("ok") is True, data
        assert data["ready"]["ready"] is True
    finally:
        _call_stop_app(server, port=free_port)


@pytest.mark.integration
def test_call_api_via_bridge(free_port):
    cdp = _free_cdp_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "pywebview_mcp", EXAMPLE],
        env={
            **_env(),
            "PYWEBVIEW_MCP_PORT": str(free_port),
            "PYWEBVIEW_MCP_CDP_PORT": str(cdp),
        },
    )
    base = f"http://127.0.0.1:{free_port}"
    try:
        _wait_ready(base)
        r = httpx.post(
            f"{base}/api",
            json={"method": "get_state", "args": [], "kwargs": {}},
            timeout=5,
        )
        body = r.json()
        assert body.get("result", {}).get("ok") is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)
