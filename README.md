# pywebview-mcp

Playwright-style MCP server for pywebview apps — lets AI assistants see, control, and debug your Python desktop web UI without modifying your app's source code.

```
AI assistant → MCP tools → pywebview-mcp server → HTTP bridge → pywebview app
```

## Features

- **Screenshot** the webview page via CDP (edgechromium/qt)
- **Inspect** the full DOM tree (tag, id, role, text, bounds)
- **Click, type, scroll, press keys** — full page interaction
- **Find elements** by CSS selector, text, role, or tag
- **call_api** — invoke `js_api` methods directly from Python (skip DOM when the app exposes an API)
- **eval_js / eval_python** — run code in the page or app process
- **Read Python logs** captured from the app
- **Launch and stop** the app directly from Claude

Zero changes to your app's source code required.

## Requirements

- Python 3.11+
- pywebview 6.0+
- [uv](https://docs.astral.sh/uv/) (recommended)
- Windows (tested with WebView2), Linux/macOS (should work with supported renderers)

## Installation

| Component | Where it runs | Needs pywebview? |
|-----------|---------------|------------------|
| **MCP server** (`pywebview-mcp`) | AI client's MCP process | No |
| **Bridge** (via `launch_app`) | Inside your pywebview app | Uses project's existing pywebview |

**No changes to the target project.** `launch_app(cwd=…)` runs
`uv run --with pywebview-mcp@git python -m pywebview_mcp main.py` — the bridge
is injected at runtime; nothing is added to `pyproject.toml`.

### MCP server — Cursor

Add to `%USERPROFILE%\.cursor\mcp.json` or project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "pywebview": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/com55/pywebview-mcp", "pywebview-mcp"]
    }
  }
}
```

Local development:

```json
{
  "mcpServers": {
    "pywebview": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/pywebview-mcp", "pywebview-mcp"]
    }
  }
}
```

Optional custom port:

```json
"env": { "PYWEBVIEW_MCP_PORT": "7891", "PYWEBVIEW_MCP_CDP_PORT": "9222" }
```

### MCP server — Claude Code

```bash
claude mcp add -s user pywebview -- uvx --from git+https://github.com/com55/pywebview-mcp pywebview-mcp
```

Or install the plugin (MCP + skill):

```bash
claude plugin install github:com55/pywebview-mcp
```

## Running your app with the bridge

**From MCP (recommended — zero project setup):**

```
launch_app(cwd="/path/to/project")                              # main.py at root
launch_app(cwd="/path/to/project", script="app.py")             # other name at root
launch_app(cwd="/path/to/project", script="backend/gui.py")   # entry in subfolder
get_launch_help()                                               # full script decision guide
```

`cwd` is the project root (`pyproject.toml`). `script` is the entry `.py` **relative to cwd**.

**Manual equivalent:**

```bash
cd your-pywebview-project
uv run --with "pywebview-mcp @ git+https://github.com/com55/pywebview-mcp" \
  python -m pywebview_mcp main.py
```

## Standard workflow

1. `launch_app(cwd="/path/to/project")`
2. `screenshot()` + `get_dom_tree()`
3. Interact via `click`, `type_text`, or `call_api("get_ui_state")`
4. `get_logs()` / `get_app_output()` to debug

## Ports

| Env var | Default | Purpose |
|---------|---------|---------|
| `PYWEBVIEW_MCP_PORT` | 7891 | HTTP bridge (differs from pyside6-mcp's 7890) |
| `PYWEBVIEW_MCP_CDP_PORT` | 9222 | Chrome DevTools for screenshots |

## Limitations

- **Screenshots** require `edgechromium` or `qt` renderer (CDP). Set automatically by the launcher.
- **Native file dialogs** block automation — use `call_api` to set paths instead.
- **Element IDs reset** on every app restart — call `get_dom_tree()` again.
- **uvx cache** — after updating the package, clear uv cache or use a local path.

## Architecture

- `pywebview_mcp/server.py` — FastMCP stdio server (no pywebview dependency)
- `pywebview_mcp/bridge.py` — in-process HTTP bridge
- `pywebview_mcp/__main__.py` — monkey-patches `webview.start` for zero-config injection

## License

MIT
