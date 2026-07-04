---
name: pywebview-mcp
description: >
  How to use the pywebview-mcp MCP server to see, control, and debug a running pywebview
  Python desktop app — like Playwright but for web UIs. Use when the user wants to inspect
  or interact with their pywebview app: screenshot, click, type, read logs, call js_api,
  launch the app from Claude. Trigger for pywebview desktop app UI development and debugging.
---

# pywebview-mcp — Playwright for pywebview

## Overview

`pywebview-mcp` lets Claude see and control a running pywebview app via an HTTP bridge injected into the app process. No source code changes required.

```
Claude → MCP tools → pywebview-mcp server → HTTP bridge (port 7891) → pywebview app
```

> **Never edit the user's source code to add `install_bridge()`.**
> Start the app with `launch_app()` — it monkey-patches `webview.start` automatically.

## Prerequisites

Only the MCP server config in Cursor/Claude — **no install in the target app**.
The target project must already use pywebview and be runnable via `uv run` in its directory.

## Standard Workflow

### 1. Launch the app

**Required:** `cwd` (absolute project root).  
**Optional:** `script` (entry `.py` relative to cwd), `app_args`, `timeout`.

| Entry location | Call |
|----------------|------|
| `main.py` at project root | `launch_app(cwd="/abs/project")` |
| other name at root, e.g. `app.py` | `launch_app(cwd="/abs/project", script="app.py")` |
| in subfolder, e.g. `backend/gui.py` | `launch_app(cwd="/abs/project", script="backend/gui.py")` |

`cwd` is always the project root (where `pyproject.toml` lives), **not** the folder containing the `.py` file.

If unsure, call `get_launch_help()` first or list the project root before launching.

```
launch_app(cwd="/absolute/path/to/your-project")
launch_app(cwd="/absolute/path/to/your-project", script="src/run.py", app_args=["--verbose"], timeout=60)
```

Do not pass `command=` or shell strings.

### 2. Orient yourself

```
screenshot()
get_dom_tree()
```

### 3. Interact

```python
find_element(selector="#submit-btn")
click(element_id="5")
type_text("hello", element_id="2")
call_api("get_state")  # faster than DOM clicks when js_api exposes state
```

### 4. Verify

```
screenshot()
get_logs(n=20)
get_app_output(n=50)
```

## Tool Reference

| Tool | What it does |
|------|-------------|
| `get_launch_help()` | How to set cwd, script, app_args before launch |
| `launch_app(cwd, script?, app_args?, port?, timeout?)` | Spawn app via `uv run --with` — no project install needed |
| `stop_app(port)` | Stop a previously launched app |
| `screenshot(element_id?)` | Capture page or element via CDP |
| `get_dom_tree()` | Full DOM hierarchy with element IDs |
| `get_element_info(element_id)` | Detailed element properties |
| `get_app_state()` | Title, URL, focus element |
| `find_element(selector?, tag?, html_id?, role?, text?)` | Search DOM |
| `click(element_id?, x?, y?, button?)` | Mouse click |
| `double_click(element_id, x?, y?)` | Double click |
| `type_text(text, element_id?)` | Keyboard input |
| `press_key(key)` | Named key press |
| `scroll(dy, element_id?, dx?)` | Scroll page or element |
| `call_api(method, args?, kwargs?)` | Call js_api Python method directly |
| `eval_js(code)` | Run JavaScript in the page |
| `eval_python(code)` | Run Python in app process (context: window, webview, api) |
| `get_logs(n?)` | Python logging records |
| `get_app_output(port?, n?)` | Raw stdout/stderr from launch_app |
| `list_actions()` | List clickable buttons/links |
| `trigger_action(name?, text?)` | Click by html id or label |
| `wait_until_ready(timeout?, quiet_ms?)` | Wait for DOM + pywebviewready |
| `wait_for_idle(timeout?, quiet_ms?)` | Wait for DOM quiet period |
| `get_app_status(port?)` | Process + bridge health |

## Common patterns

| Goal | Approach |
|------|----------|
| Find a button | `find_element(selector="#submit-btn")` or `find_element(text="Save")` |
| Read app state | `call_api("get_state")` if exposed via `js_api` |
| Bypass native file dialog | `call_api(...)` or `eval_python(...)` to set paths directly |

Example — bypass a native file picker:

```python
call_api("set_config_path", kwargs={"path": "/path/to/file"})
eval_python("api.config_path = '/path/to/file'")
```

## Gotchas

- **Element IDs reset on every restart** — call `get_dom_tree()` again after `launch_app`
- **Native dialogs block tools** — use `call_api` / `eval_python` instead
- **Screenshots need CDP** — launcher sets `REMOTE_DEBUGGING_PORT` automatically
- **Slow cold start** — increase `timeout` (e.g. 45–60s) on first launch
- **Ports** — bridge 7891 (not 7890 — that's pyside6-mcp)
