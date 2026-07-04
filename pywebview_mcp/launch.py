"""Launch helpers for launch_app — validation, argv building, agent-friendly errors."""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT_PACKAGE = "pywebview-mcp @ git+https://github.com/com55/pywebview-mcp"
_COMMON_ENTRIES = ("main.py", "app.py", "run.py")

LAUNCH_EXAMPLE: dict = {
    "cwd": "/absolute/path/to/your-pywebview-project",
    "script": "main.py",
    "app_args": [],
    "timeout": 45,
}

# Agent-facing guide — included in MCP instructions, errors, and get_launch_help().
SCRIPT_GUIDE: dict = {
    "rules": [
        "cwd = REQUIRED absolute path to the project root (folder with pyproject.toml).",
        "script = path to the entry .py file, RELATIVE to cwd (never absolute).",
        "cwd is NOT the folder where the .py lives — keep cwd at project root even if script is in a subfolder.",
        "Omit script (or leave default main.py) when the entry file is main.py at project root.",
        "If default main.py is missing, auto-detect tries app.py and run.py at cwd root only (not subfolders).",
    ],
    "when_to_set_script": [
        "Entry file is not named main.py → set script to that filename, e.g. app.py",
        "Entry file is in a subfolder → set script to a relative path, e.g. src/run.py or backend/gui.py",
        "Unsure which file → list cwd or read pyproject.toml, then set script explicitly",
    ],
    "examples": [
        {
            "cwd": "/abs/my-project",
            "note": "main.py at project root — script can be omitted",
        },
        {
            "cwd": "/abs/my-project",
            "script": "app.py",
            "note": "different filename at project root",
        },
        {
            "cwd": "/abs/my-project",
            "script": "src/run.py",
            "note": "entry inside src/ subfolder; cwd stays project root",
        },
        {
            "cwd": "/abs/my-project",
            "script": "backend/gui.py",
            "app_args": ["--verbose"],
            "note": "entry in backend/ + CLI flags via app_args",
        },
    ],
}


def mcp_package_spec() -> str:
    return os.environ.get("PYWEBVIEW_MCP_PACKAGE", _DEFAULT_PACKAGE)


def _use_with_launch() -> bool:
    """Opt-in slow path: fetch pywebview-mcp via ``uv run --with`` on every launch."""
    return os.environ.get("PYWEBVIEW_MCP_USE_WITH", "").lower() in ("1", "true", "yes")


def bridge_package_root() -> str | None:
    """
    Directory containing the ``pywebview_mcp`` package from the running MCP server install.
    Used for PYTHONPATH injection — avoids a git fetch on every launch.
    """
    try:
        import pywebview_mcp
    except ImportError:
        return None
    return str(Path(pywebview_mcp.__file__).resolve().parent.parent)


def launch_argv(script: str = "main.py", app_args: list[str] | None = None) -> list[str]:
    """
    Build argv for plug-and-play launch.

    Default: ``uv run python -m pywebview_mcp`` with bridge on PYTHONPATH (fast).
    Set PYWEBVIEW_MCP_USE_WITH=1 to use ``uv run --with pywebview-mcp@git`` instead (slow).
    """
    if _use_with_launch():
        return [
            "uv",
            "run",
            "--with",
            mcp_package_spec(),
            "python",
            "-u",
            "-m",
            "pywebview_mcp",
            script,
            *(app_args or []),
        ]
    return [
        "uv",
        "run",
        "python",
        "-u",
        "-m",
        "pywebview_mcp",
        script,
        *(app_args or []),
    ]


def launch_env_overrides() -> dict[str, str]:
    """Env vars merged into the app subprocess (unbuffered stdout + bridge PYTHONPATH)."""
    overrides: dict[str, str] = {"PYTHONUNBUFFERED": "1"}
    if _use_with_launch():
        return overrides
    root = bridge_package_root()
    if root is None:
        return overrides
    sep = os.pathsep
    existing = os.environ.get("PYTHONPATH", "")
    overrides["PYTHONPATH"] = f"{root}{sep}{existing}" if existing else root
    return overrides


def launch_error(message: str, *, hint: str | None = None, **extra: object) -> str:
    body: dict = {"error": message, "example": LAUNCH_EXAMPLE}
    if hint:
        body["hint"] = hint
    body.update(extra)
    return json.dumps(body, indent=2)


def validate_project_root(cwd: str) -> str | None:
    root = Path(cwd)
    if not root.is_dir():
        return f"cwd is not a directory: {cwd}"
    if not (root / "pyproject.toml").exists() and not (root / ".venv").exists():
        return f"cwd does not look like a project root (no pyproject.toml or .venv): {root}"
    return None


def resolve_entry_script(cwd: str, script: str) -> tuple[str, str | None]:
    root = Path(cwd)
    if (root / script).is_file():
        return script, None
    if script != "main.py":
        return script, f"Entry script not found: {root / script}"
    for name in _COMMON_ENTRIES:
        if (root / name).is_file():
            return name, None
    return script, f"No entry script in {root} (tried: {', '.join(_COMMON_ENTRIES)})"


def prepare_launch(
    *,
    cwd: str | None,
    script: str,
    app_args: list[str] | None,
    legacy_command: str | None = None,
) -> tuple[list[str], str, str, dict[str, str]] | str:
    """
    Validate inputs and return (argv, resolved_cwd, resolved_script, env_overrides)
    or an error JSON string.
    """
    if not cwd or not str(cwd).strip():
        extra: dict = {}
        if legacy_command:
            extra["deprecated_command"] = legacy_command
        return launch_error(
            "Missing required parameter: cwd",
            hint=(
                "Pass cwd as the ABSOLUTE path to the project root (folder with pyproject.toml). "
                "Do NOT pass command= — launch_app runs "
                "'uv run python -m pywebview_mcp <script>' with the bridge on PYTHONPATH."
            ),
            **extra,
        )

    resolved_cwd = str(Path(cwd).expanduser().resolve())
    root_err = validate_project_root(resolved_cwd)
    if root_err:
        return launch_error(
            root_err,
            hint="cwd must be the directory you would cd into before running uv run python main.py",
        )

    resolved_script, script_err = resolve_entry_script(resolved_cwd, script)
    if script_err:
        return launch_error(
            script_err,
            hint=(
                "Set script= to the entry .py path relative to cwd. "
                "Examples: script='app.py' (root), script='src/run.py' (subfolder). "
                "See script_guide in this response."
            ),
            script_guide=SCRIPT_GUIDE,
        )

    argv = launch_argv(resolved_script, app_args)
    env_overrides = launch_env_overrides()
    if not _use_with_launch() and bridge_package_root() is None:
        return launch_error(
            "Cannot locate pywebview_mcp package for PYTHONPATH launch",
            hint="Set PYWEBVIEW_MCP_USE_WITH=1 on the MCP server to use uv --with git fallback.",
        )
    return argv, resolved_cwd, resolved_script, env_overrides


TIMEOUT_HINTS = [
    "Another instance may already be running — close it or call stop_app() first.",
    "Call get_app_output() to read stdout/stderr from the failed launch.",
    "If the log is empty for a long time, the app may be stuck before webview.start — check for native dialogs.",
    "Increase timeout to 60–90 for cold starts (large mod scans, first uv sync).",
]
