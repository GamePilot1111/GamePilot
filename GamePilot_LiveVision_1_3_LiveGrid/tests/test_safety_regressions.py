"""Regression tests for disallowed exits, input gates, and editable safety zones."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

from gamepilot.controller import InputBridge, Navigator
from gamepilot.config import Settings
from gamepilot.mapping import WorldMap


def test_click_rejected_at_forbidden_zone():
    bridge = InputBridge()
    bridge.enabled = True
    bridge.configure_monitor(0, 0, 800, 600)
    bridge.point_allowed = lambda x, y: x < 300
    with patch.dict(sys.modules, {'pyautogui': SimpleNamespace(click=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('unexpected click')))}):
        assert bridge.click(400, 200) is False


def test_hover_rejected_at_forbidden_zone():
    bridge = InputBridge()
    bridge.enabled = True
    bridge.configure_monitor(0, 0, 800, 600)
    bridge.point_allowed = lambda x, y: x < 300
    with patch.dict(sys.modules, {'pyautogui': SimpleNamespace(moveTo=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('unexpected hover')))}):
        assert bridge.hover(400, 200) is False


def test_click_permitted_when_safe():
    clicked = []
    bridge = InputBridge()
    bridge._window_focused=lambda: True
    bridge.enabled = True
    bridge.configure_monitor(120, 40, 800, 600)
    bridge.point_allowed = lambda x, y: x < 300
    with patch.dict(sys.modules, {'pyautogui': SimpleNamespace(click=lambda x, y: clicked.append((x, y)))}):
        assert bridge.click(200, 200, 0) is True
    assert clicked == [(320, 240)]


def test_exit_removal_rebuilds_forbidden_area():
    wm = WorldMap(cell_px=50)
    wm.set_exit(150, 50)
    wm.set_exit(450, 50)
    assert not wm.passable((3, 1))
    assert not wm.passable((9, 1))
    wm.erase(150, 50)
    assert wm.passable((3, 1))
    assert not wm.passable((9, 1))
    assert len(wm.exits) == 1


def test_navigation_cannot_target_marked_exit():
    wm = WorldMap(cell_px=50)
    wm.set_exit(150, 50)
    navigator = Navigator(wm, Settings(cell_px=50))
    navigator.set_goal((150, 50))
    bridge = InputBridge()
    bridge.enabled = True
    assert navigator.tick(bridge, 800, 600, 100) == 'failed'
