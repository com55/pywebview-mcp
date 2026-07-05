"""
In-app bridge for pywebview-mcp.

Usage (add to your app before webview.start returns):
    from pywebview_mcp import install_bridge
    install_bridge(window)
"""
from __future__ import annotations

import base64
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from pywebview_mcp import dom_scripts

logger = logging.getLogger("pywebview_mcp.bridge")

_log_records: list[dict] = []
_window: Any | None = None
_js_api: Any | None = None
_cdp_port: int | None = None
_installed = False

# ---------------------------------------------------------------------------
# Readiness helpers (pure — testable without pywebview)
# ---------------------------------------------------------------------------


def _ready_from(dom_ready: bool, has_content: bool, pywebview_ready: bool, idle_ms: float, quiet_ms: float) -> bool:
    """Ready when DOM is complete, page has content, pywebview API is up, and UI is quiet."""
    return bool(dom_ready and has_content and pywebview_ready and idle_ms >= quiet_ms)


# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------


class _LogCapture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _log_records.append({
            "time": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        })
        if len(_log_records) > 500:
            _log_records.pop(0)


# ---------------------------------------------------------------------------
# JS evaluation
# ---------------------------------------------------------------------------


def _eval_js(script: str, timeout: float = 5.0) -> Any:
    """Run JavaScript in the webview page."""
    if _window is None:
        raise RuntimeError("No pywebview window registered")

    try:
        return _window.evaluate_js(script)
    except Exception as direct_exc:
        result: list[Any] = []
        error: list[Exception] = []
        done = threading.Event()

        def _run() -> None:
            try:
                result.append(_window.evaluate_js(script))
            except Exception as exc:  # noqa: BLE001
                error.append(exc)
            finally:
                done.set()

        threading.Thread(target=_run, daemon=True).start()
        if not done.wait(timeout):
            raise TimeoutError(
                f"evaluate_js timed out after {timeout} s — the main thread may be "
                "blocked by a native dialog (file picker, message box). "
                "Close the dialog or use call_api/eval_python instead."
            ) from direct_exc
        if error:
            raise error[0]
        return result[0]


# ---------------------------------------------------------------------------
# CDP screenshot
# ---------------------------------------------------------------------------


def _cdp_screenshot(cdp_port: int, url_hint: str | None = None, clip: dict | None = None) -> bytes:
    import httpx
    from websocket import create_connection

    targets = httpx.get(f"http://127.0.0.1:{cdp_port}/json", timeout=3).json()
    target = None
    for item in targets:
        if item.get("type") != "page":
            continue
        page_url = item.get("url") or ""
        if url_hint and url_hint not in page_url and "http" in page_url:
            continue
        target = item
        if url_hint and url_hint in page_url:
            break
    if target is None:
        pages = [t for t in targets if t.get("type") == "page"]
        target = pages[0] if pages else None
    if target is None:
        raise RuntimeError(
            f"No CDP page target on port {cdp_port}. "
            "Ensure REMOTE_DEBUGGING_PORT is set (edgechromium/qt renderer)."
        )

    ws = create_connection(
        target["webSocketDebuggerUrl"],
        timeout=5,
        header=["Origin: http://127.0.0.1"],
    )
    try:
        msg_id = 1
        params: dict[str, Any] = {"format": "png"}
        if clip:
            params["clip"] = clip
        ws.send(json.dumps({"id": msg_id, "method": "Page.captureScreenshot", "params": params}))
        while True:
            raw = ws.recv()
            if not raw:
                continue
            resp = json.loads(raw)
            if resp.get("id") != msg_id:
                continue
            if "error" in resp:
                raise RuntimeError(resp["error"])
            return base64.b64decode(resp["result"]["data"])
    finally:
        ws.close()


def _page_screenshot(element_id: str | None = None) -> str:
    if _cdp_port is None:
        raise RuntimeError("CDP port not configured — screenshot requires edgechromium/qt renderer")

    url_hint = None
    if _window is not None:
        url_hint = getattr(_window, "real_url", None) or getattr(_window, "original_url", None)

    clip = None
    if element_id:
        info = _eval_js(dom_scripts.ELEMENT_INFO % json.dumps(element_id))
        if isinstance(info, dict) and "bounds" in info:
            b = info["bounds"]
            clip = {
                "x": b["x"],
                "y": b["y"],
                "width": max(b["w"], 1),
                "height": max(b["h"], 1),
                "scale": 1,
            }

    png = _cdp_screenshot(_cdp_port, url_hint=url_hint, clip=clip)
    return base64.b64encode(png).decode()


# ---------------------------------------------------------------------------
# DOM / app operations
# ---------------------------------------------------------------------------


def _dom_tree() -> dict:
    return _eval_js(dom_scripts.DOM_TREE)


def _element_info(element_id: str) -> dict:
    return _eval_js(dom_scripts.ELEMENT_INFO % json.dumps(element_id))


def _find(body: dict) -> dict:
    return _eval_js(dom_scripts.FIND_ELEMENTS % json.dumps(body))


def _click_element(element_id: str, body: dict) -> dict:
    opts = {"x": body.get("x"), "y": body.get("y"), "button": body.get("button", "left"), "double": False}
    return _eval_js(dom_scripts.CLICK_ELEMENT % (json.dumps(element_id), json.dumps(opts)))


def _double_click_element(element_id: str, body: dict) -> dict:
    opts = {"x": body.get("x"), "y": body.get("y"), "button": body.get("button", "left"), "double": True}
    return _eval_js(dom_scripts.CLICK_ELEMENT % (json.dumps(element_id), json.dumps(opts)))


def _click_coord(body: dict) -> dict:
    return _eval_js(dom_scripts.CLICK_COORD % json.dumps(body))


def _type_text(element_id: str, body: dict) -> dict:
    return _eval_js(
        dom_scripts.TYPE_TEXT % (json.dumps(element_id), json.dumps(body.get("text", "")))
    )


def _press_key(body: dict) -> dict:
    return _eval_js(dom_scripts.PRESS_KEY % json.dumps(body.get("key", "")))


def _scroll(body: dict) -> dict:
    opts = {
        "dx": int(body.get("dx", 0)),
        "dy": int(body.get("dy", 0)),
        "element_id": body.get("element_id"),
    }
    return _eval_js(dom_scripts.SCROLL % json.dumps(opts))


def _list_actions() -> dict:
    return _eval_js(dom_scripts.LIST_ACTIONS)


def _trigger_action(body: dict) -> dict:
    return _eval_js(dom_scripts.TRIGGER_ACTION % json.dumps(body))


def _readiness(quiet_ms: float) -> dict:
    data = _eval_js(dom_scripts.READY_STATE % int(quiet_ms))
    if not isinstance(data, dict):
        return {"ready": False, "error": "unexpected readiness response"}
    data["ready"] = _ready_from(
        bool(data.get("dom_ready")),
        bool(data.get("has_content")),
        bool(data.get("pywebview_ready")),
        float(data.get("idle_ms", 0)),
        quiet_ms,
    )
    return data


def _idle() -> dict:
    return _eval_js(dom_scripts.IDLE_STATE)


def _app_info() -> dict:
    info = _eval_js(dom_scripts.APP_STATE)
    if _window is not None:
        info["window_title"] = getattr(_window, "title", None)
        info["real_url"] = getattr(_window, "real_url", None)
    return info


def _health() -> dict:
    """Instant liveness probe — no evaluate_js (safe while the UI thread is busy)."""
    return {
        "ok": True,
        "bridge": True,
        "has_window": _window is not None,
    }


def _quit() -> dict:
    if _window is None:
        return {"error": "No window"}
    _window.destroy()
    return {"ok": True}


def _py_eval(body: dict) -> dict:
    import webview

    code = body.get("code", "")
    ctx: dict[str, Any] = {
        "window": _window,
        "webview": webview,
        "api": _js_api,
    }
    try:
        result = eval(code, ctx)  # noqa: S307
        return {"result": repr(result)}
    except SyntaxError:
        exec(code, ctx)  # noqa: S102
        return {"result": "executed"}


def _run_js(body: dict) -> dict:
    code = body.get("code", "")
    result = _eval_js(code)
    return {"result": result}


def _call_api(body: dict) -> dict:
    method = body.get("method", "")
    args = body.get("args") or []
    kwargs = body.get("kwargs") or {}
    if _js_api is None:
        return {"error": "No js_api registered on this window"}
    fn = getattr(_js_api, method, None)
    if fn is None or not callable(fn):
        return {"error": f"js_api has no method {method!r}"}
    result = fn(*args, **kwargs)
    return {"result": result}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: ARG002
        pass

    def _send(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):  # noqa: N802
        p = urlparse(self.path)
        qs = parse_qs(p.query)
        path = p.path
        try:
            if path == "/screenshot":
                eid = qs.get("element_id", [None])[0]
                self._send({"image": _page_screenshot(eid)})
            elif path == "/dom":
                self._send(_dom_tree())
            elif path.startswith("/element/"):
                eid = path.split("/")[2]
                self._send(_element_info(eid))
            elif path == "/logs":
                n = int(qs.get("n", ["50"])[0])
                self._send({"logs": _log_records[-n:]})
            elif path == "/app":
                self._send(_app_info())
            elif path == "/health":
                self._send(_health())
            elif path == "/ready":
                quiet = float(qs.get("quiet_ms", ["500"])[0])
                self._send(_readiness(quiet))
            elif path == "/idle":
                self._send(_idle())
            elif path == "/actions":
                self._send(_list_actions())
            else:
                self._send({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._send({"error": str(exc)}, 500)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        body = self._body()
        try:
            parts = path.split("/")
            if len(parts) >= 4 and parts[1] == "element" and parts[3] == "click":
                eid = parts[2]
                if body.get("double"):
                    self._send(_double_click_element(eid, body))
                else:
                    self._send(_click_element(eid, body))
            elif len(parts) >= 4 and parts[1] == "element" and parts[3] == "type":
                eid = parts[2]
                self._send(_type_text(eid, body))
            elif path == "/click":
                self._send(_click_coord(body))
            elif path == "/key":
                self._send(_press_key(body))
            elif path == "/scroll":
                self._send(_scroll(body))
            elif path == "/find":
                self._send(_find(body))
            elif path == "/eval":
                self._send(_py_eval(body))
            elif path == "/js":
                self._send(_run_js(body))
            elif path == "/api":
                self._send(_call_api(body))
            elif path == "/quit":
                self._send(_quit())
            elif path == "/action":
                self._send(_trigger_action(body))
            else:
                self._send({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._send({"error": str(exc)}, 500)


class _ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_window(window: Any, *, js_api: Any | None = None) -> None:
    """Record window/js_api references (called from launcher monkey-patch)."""
    global _window, _js_api
    _window = window
    if js_api is not None:
        _js_api = js_api


def install_bridge(
    port: int = 7891,
    *,
    window: Any | None = None,
    js_api: Any | None = None,
    cdp_port: int | None = None,
) -> None:
    """
    Start the pywebview-mcp bridge inside your app.
    Normally injected automatically by `python -m pywebview_mcp`.
    """
    global _installed, _window, _js_api, _cdp_port
    if _installed:
        return
    _installed = True

    if window is not None:
        _window = window
    if js_api is not None:
        _js_api = js_api
    _cdp_port = cdp_port

    logging.root.addHandler(_LogCapture())

    # Prime DOM helpers before serving requests.
    try:
        _eval_js(dom_scripts.INIT_SCRIPT)
    except Exception:
        logger.debug("INIT_SCRIPT deferred until page is ready", exc_info=True)

    server = _ThreadedHTTP(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("pywebview-mcp bridge started on port %d", port)
    print(
        f"[pywebview-mcp] Bridge listening on http://127.0.0.1:{port}",
        file=sys.stderr,
    )


def reset_for_tests() -> None:
    """Reset module state between tests."""
    global _installed, _window, _js_api, _cdp_port, _log_records
    _installed = False
    _window = None
    _js_api = None
    _cdp_port = None
    _log_records.clear()
