import json
from pathlib import Path

import httpx

from pywebview_mcp.launch import (
    launch_argv,
    launch_error,
    prepare_launch,
    resolve_entry_script,
    validate_project_root,
)
from pywebview_mcp.server import _app_status_from, _should_retry


def test_launch_argv_plug_and_play():
    argv = launch_argv("main.py", ["--after-update"])
    assert argv[:4] == ["uv", "run", "--with", "pywebview-mcp @ git+https://github.com/com55/pywebview-mcp"]
    assert argv[4:8] == ["python", "-m", "pywebview_mcp", "main.py"]
    assert argv[8:] == ["--after-update"]


def test_prepare_launch_requires_cwd():
    result = prepare_launch(cwd=None, script="main.py", app_args=None)
    assert isinstance(result, str)
    body = json.loads(result)
    assert "error" in body
    assert "example" in body
    assert "cwd" in body["hint"]


def test_prepare_launch_rejects_legacy_command_without_cwd():
    result = prepare_launch(
        cwd=None,
        script="main.py",
        app_args=None,
        legacy_command="uv run python -m pywebview_mcp main.py",
    )
    body = json.loads(result)
    assert "deprecated_command" in body
    assert "Do NOT pass command" in body["hint"]


def test_prepare_launch_ok(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "main.py").write_text("print('hi')\n")
    result = prepare_launch(cwd=str(tmp_path), script="main.py", app_args=["--flag"])
    assert isinstance(result, tuple)
    argv, resolved_cwd, resolved_script = result
    assert "--with" in argv
    assert argv[-1] == "--flag"
    assert resolved_script == "main.py"
    assert Path(resolved_cwd) == tmp_path.resolve()


def test_resolve_entry_script_fallback(tmp_path: Path):
    (tmp_path / "app.py").write_text("")
    script, err = resolve_entry_script(str(tmp_path), "main.py")
    assert err is None
    assert script == "app.py"


def test_validate_project_root_missing(tmp_path: Path):
    assert validate_project_root(str(tmp_path)) is not None


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


def test_launch_error_includes_example():
    raw = launch_error("boom", hint="fix it")
    body = json.loads(raw)
    assert body["error"] == "boom"
    assert body["hint"] == "fix it"
    assert "cwd" in body["example"]


def test_script_guide_in_script_not_found_error(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    result = prepare_launch(cwd=str(tmp_path), script="missing.py", app_args=None)
    body = json.loads(result)
    assert "script_guide" in body
    assert any("subfolder" in r for r in body["script_guide"]["rules"])
