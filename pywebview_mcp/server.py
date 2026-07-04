"""
FastMCP server for pywebview-mcp.

Run as MCP server:
    pywebview-mcp                          # default port 7891
    PYWEBVIEW_MCP_PORT=8000 pywebview-mcp # custom port
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO

import httpx
from fastmcp import FastMCP
from fastmcp.utilities.types import Image

PORT = int(os.environ.get("PYWEBVIEW_MCP_PORT", "7891"))
CDP_PORT = int(os.environ.get("PYWEBVIEW_MCP_CDP_PORT", "9222"))
BRIDGE = f"http://127.0.0.1:{PORT}"

_DEFAULT_PACKAGE = "pywebview-mcp @ git+https://github.com/com55/pywebview-mcp"


def _mcp_package_spec() -> str:
    """PyPI/git spec passed to ``uv run --with`` (override via PYWEBVIEW_MCP_PACKAGE)."""
    return os.environ.get("PYWEBVIEW_MCP_PACKAGE", _DEFAULT_PACKAGE)


def _launch_argv(
    script: str = "main.py",
    app_args: list[str] | None = None,
) -> list[str]:
    """
    Build argv for plug-and-play launch: project deps from ``uv run`` + bridge via ``--with``.
    No pywebview-mcp entry in the target project's pyproject.toml required.
    """
    return [
        "uv",
        "run",
        "--with",
        _mcp_package_spec(),
        "python",
        "-m",
        "pywebview_mcp",
        script,
        *(app_args or []),
    ]

_client: httpx.Client | None = None
_procs: dict[int, subprocess.Popen] = {}
_proc_logs: dict[int, IO] = {}


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            base_url=BRIDGE,
            timeout=10,
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )
    return _client


def _app_log_path(port: int) -> str:
    return os.path.join(tempfile.gettempdir(), f"pywebview-mcp-app-{port}.log")


def _read_log_tail(port: int, n: int) -> str:
    fh = _proc_logs.get(port)
    if fh is not None:
        try:
            fh.flush()
        except (ValueError, OSError):
            pass
    path = _app_log_path(port)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[-n:]) if n > 0 else "".join(lines)


mcp = FastMCP(
    "pywebview-mcp",
    instructions=(
        "Controls and inspects a running pywebview application, like Playwright for web UIs.\n\n"
        "PREFERRED WAY TO START THE APP: call launch_app(cwd='/path/to/project'). "
        "It uses ``uv run --with pywebview-mcp`` so the target project needs NO extra "
        "dependencies or source changes. The bridge is injected by monkey-patching "
        "webview.start. Do NOT add pywebview-mcp to the user's pyproject.toml.\n\n"
        "If the app is already running and reachable, you can skip launch_app(). "
        "After the app is up, always start with screenshot() + get_dom_tree() to orient "
        "yourself, then use element IDs from the tree for subsequent operations.\n\n"
        "For apps with js_api, prefer call_api() to query state or trigger "
        "actions without DOM clicks. Use eval_js() for arbitrary page JavaScript."
    ),
)


def _bridge_unreachable_error() -> RuntimeError:
    return RuntimeError(
        f"Cannot reach bridge on port {PORT}. "
        "Start the app with the launch_app() tool — it injects the bridge automatically, "
        "with no changes needed to the app's source code."
    )


def _bridge_http_error(exc: httpx.HTTPStatusError) -> RuntimeError:
    detail = None
    try:
        detail = exc.response.json().get("error")
    except Exception:
        detail = exc.response.text.strip() or None
    suffix = f": {detail}" if detail else ""
    return RuntimeError(f"Bridge returned {exc.response.status_code}{suffix}")


_TRANSIENT_EXC = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


def _should_retry(exc: Exception) -> bool:
    return isinstance(exc, _TRANSIENT_EXC)


def _app_status_from(proc_alive: bool, exit_code, bridge_ok: bool, timed_out: bool) -> dict:
    return {
        "running": bool(proc_alive),
        "exit_code": exit_code,
        "bridge_responsive": bool(bridge_ok),
        "likely_native_dialog_block": bool(proc_alive and timed_out and not bridge_ok),
    }


_RETRY_BACKOFFS = (0.1, 0.3, 0.6)


def _request_with_retry(method: str, path: str, **kwargs) -> httpx.Response:
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(len(_RETRY_BACKOFFS) + 1):
        try:
            r = client.request(method, path, **kwargs)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _should_retry(exc) or attempt == len(_RETRY_BACKOFFS):
                break
            time.sleep(_RETRY_BACKOFFS[attempt])
    assert last_exc is not None
    raise last_exc


def _get(path: str, **params) -> dict:
    try:
        r = _request_with_retry(
            "GET", path, params={k: v for k, v in params.items() if v is not None}
        )
        return r.json()
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.RemoteProtocolError):
        raise _bridge_unreachable_error()
    except httpx.HTTPStatusError as exc:
        raise _bridge_http_error(exc)


def _post(path: str, data: dict) -> dict:
    try:
        r = _request_with_retry("POST", path, json=data)
        return r.json()
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.RemoteProtocolError):
        raise _bridge_unreachable_error()
    except httpx.HTTPStatusError as exc:
        raise _bridge_http_error(exc)


def _kill_proc_tree(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform != "win32":
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
            proc.wait(timeout=timeout)


def _bridge_gone(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout))


def _request_app_quit(port: int, timeout: float = 5.0) -> dict:
    bridge_url = f"http://127.0.0.1:{port}"
    try:
        r = httpx.post(f"{bridge_url}/quit", timeout=5)
        r.raise_for_status()
    except httpx.ConnectError:
        return {"bridge_reachable": False}
    except httpx.HTTPError as exc:
        if _bridge_gone(exc):
            return {"bridge_reachable": True, "bridge_stopped": True}
        return {"bridge_reachable": True, "quit_error": str(exc)}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{bridge_url}/app", timeout=0.5)
        except httpx.ReadTimeout:
            time.sleep(0.2)
            continue
        except httpx.HTTPError as exc:
            if _bridge_gone(exc):
                return {"bridge_reachable": True, "bridge_stopped": True, "quit": r.json()}
            raise
        time.sleep(0.2)
    return {"bridge_reachable": True, "bridge_stopped": False, "quit": r.json()}


# ---------------------------------------------------------------------------
# Visual / inspection
# ---------------------------------------------------------------------------


@mcp.tool()
def screenshot(element_id: str | None = None) -> Image:
    """
    Capture a screenshot of the webview page (or a specific element by ID).
    Uses CDP (edgechromium/qt renderer). Call this first to orient yourself.
    """
    import base64

    data = _get("/screenshot", element_id=element_id)
    return Image(data=base64.b64decode(data["image"]), format="png")


@mcp.tool()
def get_dom_tree() -> str:
    """
    Get the DOM tree of the page as JSON.
    Each element has: id, tag, html_id, class, role, text, visible, bounds, children.
    Use element IDs from this tree in other tools.
    """
    return json.dumps(_get("/dom"), indent=2)


@mcp.tool()
def get_element_info(element_id: str) -> str:
    """Get detailed properties of a specific DOM element by MCP id."""
    return json.dumps(_get(f"/element/{element_id}"), indent=2)


@mcp.tool()
def get_app_state() -> str:
    """Get app-level state: page title, URL, focus element, pywebview platform."""
    return json.dumps(_get("/app"), indent=2)


@mcp.tool()
def find_element(
    selector: str | None = None,
    tag: str | None = None,
    html_id: str | None = None,
    role: str | None = None,
    text: str | None = None,
    visible: bool | None = None,
) -> str:
    """
    Search DOM elements by CSS selector, tag, html id, ARIA role, text, or visibility.
    Examples:
      find_element(selector="#launch-btn")
      find_element(text="Launch")
      find_element(role="button")
    """
    body: dict = {}
    if selector is not None:
        body["selector"] = selector
    if tag is not None:
        body["tag"] = tag
    if html_id is not None:
        body["html_id"] = html_id
    if role is not None:
        body["role"] = role
    if text is not None:
        body["text"] = text
    if visible is not None:
        body["visible"] = visible
    return json.dumps(_post("/find", body), indent=2)


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------


@mcp.tool()
def click(
    element_id: str | None = None,
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
) -> str:
    """
    Click an element or page coordinate.
    - element_id only: clicks the center of that element
    - element_id + x/y: clicks at offset within element bounds
    - x/y only: clicks at viewport coordinates
    """
    if element_id:
        body: dict = {"button": button}
        if x is not None:
            body["x"] = x
        if y is not None:
            body["y"] = y
        return json.dumps(_post(f"/element/{element_id}/click", body))
    return json.dumps(_post("/click", {"x": x, "y": y, "button": button}))


@mcp.tool()
def double_click(element_id: str, x: int | None = None, y: int | None = None) -> str:
    """Double-click an element."""
    body: dict = {"button": "left", "double": True}
    if x is not None:
        body["x"] = x
    if y is not None:
        body["y"] = y
    return json.dumps(_post(f"/element/{element_id}/click", body))


@mcp.tool()
def type_text(text: str, element_id: str | None = None) -> str:
    """Type text into an input element (focuses it first)."""
    if element_id:
        return json.dumps(_post(f"/element/{element_id}/type", {"text": text}))
    state = _get("/app")
    fw = state.get("focus_element")
    if fw:
        return json.dumps(_post(f"/element/{fw}/type", {"text": text}))
    return json.dumps({"error": "No focused element. Provide element_id."})


@mcp.tool()
def press_key(key: str) -> str:
    """
    Press a key on the focused element.
    Named keys: enter, escape, tab, backspace, delete, arrows, space, home, end, f1–f6.
    """
    return json.dumps(_post("/key", {"key": key}))


@mcp.tool()
def scroll(dy: int, element_id: str | None = None, dx: int = 0) -> str:
    """Scroll the page or an element. dy > 0 scrolls down."""
    body: dict = {"dy": dy, "dx": dx}
    if element_id:
        body["element_id"] = element_id
    return json.dumps(_post("/scroll", body))


# ---------------------------------------------------------------------------
# Debugging
# ---------------------------------------------------------------------------


@mcp.tool()
def get_logs(n: int = 50) -> str:
    """Get the last n Python logging records from the app."""
    return json.dumps(_get("/logs", n=n), indent=2)


@mcp.tool()
def get_app_output(port: int = 7891, n: int = 200) -> str:
    """
    Get the last n lines of the launched app's stdout/stderr.
    Only works for apps started via launch_app on this server.
    """
    if not os.path.exists(_app_log_path(port)):
        return json.dumps({
            "error": f"No captured output for port {port}. "
                     "The app must be started via launch_app for output capture."
        })
    return json.dumps({"port": port, "output": _read_log_tail(port, n)}, indent=2)


@mcp.tool()
def eval_python(code: str) -> str:
    """
    Evaluate Python in the app process.
    Context: window, webview, api (js_api object).
    WARNING: debugging only.
    """
    return json.dumps(_post("/eval", {"code": code}), indent=2)


@mcp.tool()
def eval_js(code: str) -> str:
    """Execute JavaScript in the webview page and return the result."""
    return json.dumps(_post("/js", {"code": code}), indent=2)


@mcp.tool()
def call_api(method: str, args: list | None = None, kwargs: dict | None = None) -> str:
    """
    Call a js_api method directly on the Python object exposed to the page.
    Example: call_api("get_state") when the app exposes state via js_api.
    """
    body: dict = {"method": method, "args": args or [], "kwargs": kwargs or {}}
    return json.dumps(_post("/api", body), indent=2)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@mcp.tool()
def launch_app(
    cwd: str | None = None,
    port: int = 7891,
    timeout: int = 45,
    script: str = "main.py",
    app_args: list[str] | None = None,
    command: str | None = None,
) -> str:
    """
    Launch a pywebview app with the MCP bridge pre-injected, then wait until ready.

    Plug-and-play: uses ``uv run --with pywebview-mcp@git`` in ``cwd`` so the target
    project needs no pywebview-mcp dependency. Only ``cwd`` is required in most cases:

      launch_app(cwd="/path/to/your-project", app_args=["--verbose"])

    ``command`` overrides the auto-built argv (advanced use only).
    timeout defaults to 45s for slow cold starts (heavy startup work, large mod lists, etc.).
    """
    bridge_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "PYWEBVIEW_MCP_PORT": str(port),
        "PYWEBVIEW_MCP_CDP_PORT": str(CDP_PORT),
    }

    log_path = _app_log_path(port)
    log_file = open(log_path, "w", encoding="utf-8")
    _proc_logs.pop(port, None)
    _proc_logs[port] = log_file

    if command is not None:
        argv = shlex.split(command, posix=(sys.platform != "win32"))
    else:
        if cwd is None:
            return json.dumps({"error": "Provide cwd (project root with pyproject.toml or venv)"})
        argv = _launch_argv(script, app_args)

    popen_kwargs: dict = {
        "args": argv,
        "cwd": cwd,
        "env": env,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(**popen_kwargs)
    _procs[port] = proc

    deadline = time.monotonic() + timeout
    last_ready: dict | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return json.dumps({
                "error": f"App exited early with code {proc.returncode}",
                "pid": proc.pid,
                "log_file": log_path,
                "output": _read_log_tail(port, 50),
            })
        try:
            r = httpx.get(f"{bridge_url}/ready", timeout=1)
            if r.status_code == 200:
                last_ready = r.json()
                if last_ready.get("ready"):
                    return json.dumps({
                        "ok": True,
                        "pid": proc.pid,
                        "log_file": log_path,
                        "argv": argv,
                        "ready": last_ready,
                    })
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError):
            pass
        time.sleep(0.4)

    if last_ready is not None:
        return json.dumps({
            "error": f"App started but UI not ready within {timeout}s",
            "pid": proc.pid,
            "log_file": log_path,
            "ready": last_ready,
            "output": _read_log_tail(port, 50),
        })
    _kill_proc_tree(proc)
    return json.dumps({
        "error": f"Bridge did not start within {timeout}s",
        "pid": proc.pid,
        "log_file": log_path,
        "output": _read_log_tail(port, 50),
    })


@mcp.tool()
def wait_until_ready(timeout: int = 30, quiet_ms: int = 500) -> str:
    """Wait until DOM is ready and pywebview API is available."""
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        try:
            last = _get("/ready", quiet_ms=quiet_ms)
            if last.get("ready"):
                return json.dumps({"ok": True, "ready": last})
        except RuntimeError:
            pass
        time.sleep(0.3)
    return json.dumps({"ok": False, "error": f"UI not ready within {timeout}s", "ready": last})


@mcp.tool()
def wait_for_idle(timeout: float = 5.0, quiet_ms: int = 300) -> str:
    """Wait until the page has been quiet (no DOM mutations) for quiet_ms."""
    deadline = time.monotonic() + timeout
    last_idle = 0.0
    while time.monotonic() < deadline:
        try:
            last_idle = float(_get("/idle").get("idle_ms", 0.0))
        except RuntimeError:
            break
        if last_idle >= quiet_ms:
            return json.dumps({"ok": True, "idle_ms": last_idle})
        time.sleep(0.1)
    return json.dumps({"ok": False, "idle_ms": last_idle, "timeout": timeout})


@mcp.tool()
def get_app_status(port: int = 7891) -> str:
    """Report process + bridge health; detect likely native dialog blocks."""
    proc = _procs.get(port)
    proc_alive = proc is not None and proc.poll() is None
    exit_code = None if proc is None else proc.poll()

    bridge_ok = False
    timed_out = False
    bridge_url = f"http://127.0.0.1:{port}"
    try:
        r = httpx.get(f"{bridge_url}/app", timeout=2)
        bridge_ok = r.status_code == 200
    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        timed_out = True
    except httpx.HTTPError:
        bridge_ok = False

    status = _app_status_from(proc_alive, exit_code, bridge_ok, timed_out)
    if status["likely_native_dialog_block"]:
        status["hint"] = (
            "The main thread appears blocked — likely a native file dialog or OS modal. "
            "Close the dialog or use call_api/eval_python to bypass."
        )
    status["output"] = _read_log_tail(port, 30)
    return json.dumps(status, indent=2)


@mcp.tool()
def list_actions() -> str:
    """List clickable buttons, links, and role=button elements."""
    return json.dumps(_get("/actions"), indent=2)


@mcp.tool()
def trigger_action(name: str | None = None, text: str | None = None) -> str:
    """Click a button/link by html id (name) or visible text without DOM traversal."""
    body: dict = {}
    if name is not None:
        body["name"] = name
    if text is not None:
        body["text"] = text
    return json.dumps(_post("/action", body))


@mcp.tool()
def stop_app(port: int = 7891) -> str:
    """Stop a previously launched app (started via launch_app)."""
    result: dict = {"ok": True, "port": port}
    quit_status = _request_app_quit(port)
    result["quit"] = quit_status

    proc = _procs.pop(port, None)
    if proc is not None:
        _kill_proc_tree(proc)
        result["pid"] = proc.pid
        result["returncode"] = proc.returncode

    log_file = _proc_logs.pop(port, None)
    if log_file is not None:
        try:
            log_file.close()
        except OSError:
            pass
        result["log_file"] = _app_log_path(port)
    elif not quit_status.get("bridge_stopped"):
        if not quit_status.get("bridge_reachable"):
            return json.dumps({"error": f"No app tracked on port {port} and bridge unreachable"})
        return json.dumps({"error": f"App on port {port} did not stop after quit request", **result})

    return json.dumps(result)


def main() -> None:
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
