"""
Launcher: run any pywebview app with the bridge pre-installed.

Usage:
    python -m pywebview_mcp myapp.py [args...]
    python -m pywebview_mcp -m mypackage.module [args...]
    uv run python -m pywebview_mcp main.py
"""
from __future__ import annotations

import os
import runpy
import sys

from pywebview_mcp.cdp_env import ensure_webview2_cdp_flags


def _patch_webview() -> None:
    ensure_webview2_cdp_flags()
    import webview

    from pywebview_mcp.bridge import install_bridge, register_window

    bridge_port = int(os.environ.get("PYWEBVIEW_MCP_PORT", "7891"))
    cdp_port = int(os.environ.get("PYWEBVIEW_MCP_CDP_PORT", "9222"))

    _orig_create = webview.create_window
    _orig_start = webview.start

    def _patched_create_window(*args, **kwargs):
        win = _orig_create(*args, **kwargs)
        register_window(win, js_api=kwargs.get("js_api"))
        return win

    def _patched_start(func=None, args=None, **kwargs):
        webview.settings["REMOTE_DEBUGGING_PORT"] = cdp_port

        def _wrapped(*wrapped_args):
            win = wrapped_args[0] if wrapped_args else None
            if win is None and args is not None:
                win = args[0] if isinstance(args, tuple) else args
            if win is None and webview.windows:
                win = webview.windows[0]
            if win is None:
                win = webview.active_window()
            install_bridge(port=bridge_port, window=win, cdp_port=cdp_port)
            if func is None:
                return None
            if args is not None:
                if isinstance(args, tuple):
                    return func(*args)
                return func(args)
            if wrapped_args:
                return func(*wrapped_args)
            return func()

        if func is not None:
            return _orig_start(_wrapped, args, **kwargs)
        return _orig_start(_wrapped, args, **kwargs)

    webview.create_window = _patched_create_window
    webview.start = _patched_start


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: python -m pywebview_mcp <script.py> [args...]")
        print("       python -m pywebview_mcp -m <module> [args...]")
        sys.exit(1)

    _patch_webview()

    if argv[0] == "-m":
        if len(argv) < 2:
            print("Error: -m requires a module name")
            sys.exit(1)
        sys.argv = argv[1:]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = argv
        runpy.run_path(argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
