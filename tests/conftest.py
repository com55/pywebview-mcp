"""Shared pytest fixtures for pywebview-mcp tests."""
import socket

import pytest


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def free_port() -> int:
    """An OS-assigned free TCP port for an isolated bridge instance."""
    return _free_port()
