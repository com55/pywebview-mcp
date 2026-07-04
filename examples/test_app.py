"""
Minimal pywebview test app for pywebview-mcp integration tests.
"""
from __future__ import annotations

import logging
import sys

import webview

logger = logging.getLogger("test_app")
logging.basicConfig(level=logging.INFO)

HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>pywebview-mcp test</title>
  <style>
    body { font-family: sans-serif; padding: 24px; }
    #status { margin: 12px 0; color: #333; }
    button { padding: 8px 16px; margin-right: 8px; }
    input { padding: 6px; width: 200px; }
  </style>
</head>
<body>
  <h1 id="title">pywebview-mcp test app</h1>
  <p id="status">Waiting for pywebview…</p>
  <input id="name_input" placeholder="Type something…" />
  <button id="btn">Click me</button>
  <button id="greet_btn">Greet</button>
  <script>
    window.addEventListener('pywebviewready', () => {
      document.getElementById('status').textContent = 'pywebview is ready';
    });
    document.getElementById('btn').addEventListener('click', () => {
      const v = document.getElementById('name_input').value || '(empty)';
      document.getElementById('status').textContent = 'Clicked! Input: ' + v;
    });
    document.getElementById('greet_btn').addEventListener('click', () => {
      if (window.pywebview && window.pywebview.api) {
        const name = document.getElementById('name_input').value || 'world';
        window.pywebview.api.say_hello(name).then((r) => {
          document.getElementById('status').textContent = r.message;
        });
      }
    });
  </script>
</body>
</html>
"""


class Api:
    def say_hello(self, name: str) -> dict:
        logger.info("say_hello(%r)", name)
        return {"message": f"Hello, {name}!"}

    def get_state(self) -> dict:
        return {"ok": True, "version": sys.version}


if __name__ == "__main__":
    api = Api()
    window = webview.create_window(
        "pywebview-mcp test",
        html=HTML,
        js_api=api,
        width=480,
        height=360,
    )

    def after_start(win):
        logger.info("GUI ready")

    webview.start(after_start, args=(window,), debug=False)
