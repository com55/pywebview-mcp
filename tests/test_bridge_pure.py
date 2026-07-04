from pywebview_mcp.bridge import _ready_from


def test_ready_from_requires_all_conditions():
    assert _ready_from(True, True, True, 600, 500) is True


def test_ready_from_false_when_not_idle():
    assert _ready_from(True, True, True, 200, 500) is False


def test_ready_from_false_when_dom_not_ready():
    assert _ready_from(False, True, True, 600, 500) is False


def test_ready_from_false_when_no_pywebview():
    assert _ready_from(True, True, False, 600, 500) is False


def test_ready_from_false_when_empty_page():
    assert _ready_from(True, False, True, 600, 500) is False
