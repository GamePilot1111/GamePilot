import tempfile
import unittest
from pathlib import Path
from gamepilot.mapping import WorldMap


class TestWorldMap(unittest.TestCase):
    def test_motion_camera_opposite(self):
        w=WorldMap()
        w.update_motion(-30,12,.8)
        self.assertEqual((w.player_x,w.player_y),(30,-12))
        self.assertIn(w.cell(30,-12),w.visited)

    def test_resource_dedup(self):
        w=WorldMap()
        a=w.add_observation(200,100,400,400,.5,.5,now=3)
        b=w.add_observation(205,98,400,400,.5,.5,now=4)
        self.assertEqual(a.id,b.id)
        self.assertEqual(len(w.resources),1)

    def test_forbidden_exit(self):
        w=WorldMap()
        w.set_exit(152,0)
        self.assertFalse(w.passable((2,0)))
        self.assertFalse(w.passable((4,0)))
        self.assertTrue(w.passable((-2,0)))

    def test_planner_goes_around_block(self):
        w=WorldMap(cell_px=50)
        w.blocked.add((1,0))
        path=w.plan((200,0))
        self.assertTrue(path)
        self.assertNotIn((50,0),path)

    def test_save_load(self):
        w=WorldMap();w.set_exit(150,0);w.update_motion(-80,-30,.7)
        w.add_observation(210,130,400,300,.5,.5,True,now=8)
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'map.json';w.save(p);copy=WorldMap.load(p)
        self.assertEqual(w.exits,copy.exits)
        self.assertEqual(w.player_x,copy.player_x)
        self.assertEqual(len(w.resources),len(copy.resources))

    def test_frontier(self):
        w=WorldMap()
        w.visited.add((0,0))
        self.assertIsNotNone(w.frontier())


if __name__=='__main__':unittest.main()
