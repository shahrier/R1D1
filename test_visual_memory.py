import math
import unittest
import cv2
import numpy as np
from pose_graph import optimize, relative
from visual_memory import Features
from calibrate_camera import diverse


class VisualMemoryTests(unittest.TestCase):
    def test_pose_graph_anchor_and_loop_reduce_drift(self):
        poses = [[0,0,0],[1,0,math.pi/2],[1,1,math.pi],[0,1,-math.pi/2],[.15,.12,0]]
        edges = [{'from':i,'to':i+1,'measurement':relative(poses[i],poses[i+1]).tolist(),
                  'sigma':[.08,.08,.08]} for i in range(4)]
        edges.append({'from':0,'to':4,'measurement':[0,0,0],'sigma':[.02,.02,.02]})
        result = optimize(poses, edges)
        self.assertEqual(result[0], [0,0,0])
        self.assertLess(math.hypot(result[-1][0],result[-1][1]), .05)

    def test_odometry_graph_without_revisit_does_not_invent_correction(self):
        poses = [[0,0,0],[.1,0,0],[.2,0,.2]]
        edges = [{'from':i,'to':i+1,'measurement':relative(poses[i],poses[i+1]).tolist()} for i in range(2)]
        self.assertTrue(np.allclose(optimize(poses,edges),poses))

    def test_blank_images_are_not_places(self):
        features = Features(); blank = features.extract(np.zeros((480,640),np.uint8))
        self.assertFalse(features.compare(blank,blank)['matched'])

    def test_geometric_match_rejects_unrelated_texture(self):
        rng = np.random.default_rng(12)
        first = rng.integers(0,256,(480,640),dtype=np.uint8)
        second = rng.integers(0,256,(480,640),dtype=np.uint8)
        features = Features()
        self.assertFalse(features.compare(features.extract(first),features.extract(second))['matched'])

    def test_geometric_matching_survives_small_view_change(self):
        rng = np.random.default_rng(4)
        image = np.zeros((480,640),np.uint8)
        for _ in range(140):
            x,y = rng.integers([20,20],[620,460]); radius=int(rng.integers(3,13))
            cv2.circle(image,(int(x),int(y)),radius,int(rng.integers(80,255)),-1)
        transformed=cv2.warpPerspective(image,np.array([[1.,.01,8.],[0,1.,5.],[0,0,1.]]),(640,480))
        features=Features(); match=features.compare(features.extract(image),features.extract(transformed))
        self.assertTrue(match['matched']);self.assertGreater(match['inliers'],50)

    def test_calibration_requires_view_diversity(self):
        self.assertFalse(diverse([np.array([.5,.5,.3,0]) for _ in range(25)]))
        features=[np.array([.2+i*.03,.3+i*.02,.25+i*.01,i*.02]) for i in range(20)]
        self.assertTrue(diverse(features))

    def test_calibrated_rotation_is_distinct_from_scene_translation(self):
        rng=np.random.default_rng(7)
        image=rng.integers(0,256,(480,640),dtype=np.uint8)
        image=cv2.GaussianBlur(image,(3,3),0)
        k=np.array([[630.,0,320],[0,630.,240],[0,0,1.]])
        angle=math.radians(10)
        rotation=np.array([[math.cos(angle),0,math.sin(angle)],[0,1,0],[-math.sin(angle),0,math.cos(angle)]])
        query=cv2.warpPerspective(image,k@rotation@np.linalg.inv(k),(640,480))
        features=Features({'image_size':[640,480],'matrix':k.tolist(),'distortion':[0,0,0,0,0]})
        match=features.compare(features.extract(image),features.extract(query))
        self.assertTrue(match['matched'])
        self.assertAlmostEqual(match['visual_yaw_degrees'],10,delta=1.5)
        self.assertTrue(match['same_location_candidate'])


if __name__=='__main__':unittest.main()
