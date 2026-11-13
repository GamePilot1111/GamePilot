import unittest
import numpy as np
import cv2
from gamepilot.vision import estimate_camera_shift,match_template,progress_bar_visible

class TestVision(unittest.TestCase):
    def test_shift_static_features(self):
        rng=np.random.default_rng(11)
        frame=np.zeros((480,640,3),dtype=np.uint8)
        for x,y in rng.integers([60,70],[580,390],size=(100,2)):
            cv2.circle(frame,(int(x),int(y)),2,(230,230,230),-1)
        matrix=np.float32([[1,0,-12],[0,1,8]])
        moved=cv2.warpAffine(frame,matrix,(640,480))
        motion=estimate_camera_shift(frame,moved)
        self.assertGreater(motion.confidence,.4)
        self.assertAlmostEqual(motion.dx,-12,delta=2)
        self.assertAlmostEqual(motion.dy,8,delta=2)

    def test_match_template(self):
        rng=np.random.default_rng(4)
        patch=rng.integers(0,255,(28,28,3),dtype=np.uint8)
        frame=np.zeros((180,220,3),dtype=np.uint8)
        frame[75:103,90:118]=patch
        det=match_template(frame,patch,threshold=.95)
        self.assertTrue(det)
        self.assertAlmostEqual(det[0].x,104,delta=2)

    def test_progress_roi(self):
        frame=np.zeros((150,300,3),dtype=np.uint8)
        frame[110:125,25:140]=(30,210,70)
        self.assertTrue(progress_bar_visible(frame,(20,105,150,25)))
        self.assertFalse(progress_bar_visible(frame,(20,10,150,25)))
