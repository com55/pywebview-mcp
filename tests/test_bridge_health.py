from pywebview_mcp.bridge import _health


def test_health_without_window():
    body = _health()
    assert body["ok"] is True
    assert body["bridge"] is True
    assert body["has_window"] is False
