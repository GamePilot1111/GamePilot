"""Tests for additional navigation and input fail-closed guarantees."""
import math
from unittest.mock import patch
from gamepilot.controller import InputBridge, Navigator, Brain, Mode, Observation
from gamepilot.mapping import WorldMap
from gamepilot.config import Settings

def test_focus_empty_fails_closed():
    assert InputBridge()._window_focused() is False

def test_no_click_without_explicit_target_title():
    bridge=InputBridge()
    bridge.enabled=True
    bridge.configure_monitor(0,0,800,600)
    assert bridge.click(100,100,0) is False

def test_frontier_exclusions():
    wm=WorldMap(cell_px=50)
    a=wm.frontier()
    assert a is not None
    b=wm.frontier(excluded={wm.cell(*a)})
    assert b is not None and a!=b

def test_navigation_does_not_click_through_blocked_cell():
    wm=WorldMap(cell_px=50)
    cfg=Settings(cell_px=50,click_interval_seconds=0)
    nav=Navigator(wm,cfg)
    wm.set_blocked(50,0)
    nav.set_goal((200,0))
    bridge=InputBridge()
    bridge.enabled=True
    bridge.configure_monitor(0,0,800,600)
    bridge.window_title_contains='test'
    calls=[]
    bridge.click=lambda x,y,minimum_interval=0: calls.append((x,y)) or True
    for i in range(3):
        nav.tick(bridge,800,600,100+i)
    assert all(wm.line_passable((wm.player_x,wm.player_y),
          (wm.player_x+x-400,wm.player_y+y-312)) for x,y in calls)

def test_frontier_failure_quarantine():
    wm=WorldMap(cell_px=50)
    cfg=Settings(cell_px=50,auto_explore=True)
    bridge=InputBridge()
    brain=Brain(cfg,wm,bridge,lambda _:None)
    first=brain._frontier()
    assert first is not None
    brain.explore_failures[wm.cell(*first)]=float('inf')
    assert brain._frontier()!=first
