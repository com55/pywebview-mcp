import httpx

from pywebview_mcp.server import _app_status_from, _launch_argv, _should_retry


def test_launch_argv_plug_and_play():
    argv = _launch_argv("main.py", ["--after-update"])
    assert argv[:4] == ["uv", "run", "--with", "pywebview-mcp @ git+https://github.com/com55/pywebview-mcp"]
    assert argv[4:8] == ["python", "-m", "pywebview_mcp", "main.py"]
    assert argv[8:] == ["--after-update"]


def test_should_retry_connect_error():
    assert _should_retry(httpx.ConnectError("boom")) is True


def test_should_retry_read_error():
    assert _should_retry(httpx.ReadError("boom")) is True


def test_should_not_retry_http_status_error():
    request = httpx.Request("GET", "http://127.0.0.1/x")
    response = httpx.Response(500, request=request)
    exc = httpx.HTTPStatusError("err", request=request, response=response)
    assert _should_retry(exc) is False


def test_status_running_and_responsive():
    s = _app_status_from(proc_alive=True, exit_code=None, bridge_ok=True, timed_out=False)
    assert s["running"] is True
    assert s["bridge_responsive"] is True
    assert s["likely_native_dialog_block"] is False


def test_status_alive_but_bridge_timed_out():
    s = _app_status_from(proc_alive=True, exit_code=None, bridge_ok=False, timed_out=True)
    assert s["likely_native_dialog_block"] is True
