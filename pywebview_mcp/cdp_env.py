"""WebView2 / CDP environment helpers."""
from __future__ import annotations

import os

_REMOTE_ALLOW = "--remote-allow-origins=*"


def ensure_webview2_cdp_flags() -> None:
    """
    WebView2 blocks CDP WebSocket clients (403) unless this flag is set
    before the WebView2 environment is created.
    """
    key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
    existing = os.environ.get(key, "")
    if _REMOTE_ALLOW not in existing:
        os.environ[key] = f"{existing} {_REMOTE_ALLOW}".strip()
