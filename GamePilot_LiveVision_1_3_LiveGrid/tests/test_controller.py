import unittest
from gamepilot.controller import Brain, InputBridge, Mode, Observation
from gamepilot.config import Settings
from gamepilot.mapping import WorldMap

class TestController(unittest.TestCase):
    def test_armed_requires_enable(self):
        events=[]
        brain=Brain(Settings(),WorldMap(),InputBridge(),events.append)
        brain.arm()
        self.assertEqual(brain.mode,Mode.IDLE)

    def test_disarm_ensures_false(self):
        bridge=InputBridge()
        bridge.enabled=True
        bridge.disarm()
        self.assertFalse(bridge.enabled)

    def test_uncertainty_halts(self):
        cfg=Settings(max_position_uncertainty_px=20)
        wm=WorldMap(uncertainty=25)
        bridge=InputBridge();bridge.enabled=True
        bridge._window_focused=lambda: True  # isolate uncertainty check from foreground-window gate
        brain=Brain(cfg,wm,bridge,lambda _:None);brain.mode=Mode.SEARCH
        brain.tick(Observation(800,600,1.,[],now=50))
        self.assertEqual(brain.mode,Mode.HELP)
        self.assertFalse(bridge.enabled)
