import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from scan_batch import scan,heading_at
from target_approach import execute_plan


class ScanRobot:
    def __init__(self):self.heading=0;self.actions=[]
    def execute(self,action):
        self.actions.append(action)
        if action['action']=='turn':self.heading=(self.heading+action['degrees'])%360
        return {'reported_velocity_mm_s':0,'pose':{'x_mm':0,'y_mm':0,'heading_degrees':self.heading}}


class ScanTests(unittest.TestCase):
    def test_heading_interpolation_handles_wrap(self):
        self.assertEqual(heading_at(1,[(0,350),(2,370)]),0)
    @patch('scan_batch.image_info',return_value={'brightness':100})
    @patch('scan_batch.capture_photo',side_effect=lambda *_:{'captured_monotonic':time.monotonic()})
    @patch('scan_batch.config',return_value={'primary':'webcam'})
    def test_moving_scan_uses_two_arcs_and_stops_before_return(self,*_):
        class MovingRobot(ScanRobot):
            def execute(self,action):
                state=super().execute(action)
                if action['action']=='turn':
                    sample={'angle_degrees':action['degrees'],'captured_monotonic':time.monotonic()}
                    zero={'angle_degrees':0,'captured_monotonic':time.monotonic()}
                    return {'sensors_before':sample,'sensor_samples':[],'sensors_after':zero}
                return state
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);robot=MovingRobot()
            frames=scan(robot,SimpleNamespace(root=root),root,time.monotonic()+120,180,continuous=True)
        self.assertEqual([a['degrees'] for a in robot.actions if a['action']=='turn'],[90,90])
        self.assertEqual(frames[-1]['heading_degrees'],180)
        self.assertFalse(frames[-1]['captured_during_scan'])
    @patch('scan_batch.capture',return_value=('fake.jpg',{'brightness':100}))
    def test_batch_tags_each_sample_with_actual_stopped_heading(self,capture):
        with tempfile.TemporaryDirectory() as folder:
            robot=ScanRobot();frames=scan(robot,None,Path(folder),time.monotonic()+120,180)
        self.assertEqual([v['heading_degrees'] for v in frames],[0,30,60,90,120,150,180])
        self.assertEqual(capture.call_count,7)
        self.assertTrue(all(a['action'] in {'turn','status'} for a in robot.actions))
    @patch('scan_batch.capture')
    def test_stop_prevents_scan_motion_and_capture(self,capture):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'STOP').touch();robot=ScanRobot()
            with self.assertRaises(RuntimeError):scan(robot,None,root,time.monotonic()+120)
            self.assertEqual(robot.actions,[]);capture.assert_not_called()
    def test_waypoint_heading_turns_without_driving(self):
        with tempfile.TemporaryDirectory() as folder:
            robot=ScanRobot();result=execute_plan(robot,{'action':'face_heading','heading_degrees':145},Path(folder),time.monotonic()+120)
        self.assertEqual(result['stopped_state']['pose']['heading_degrees'],145)
        self.assertFalse(any(a['action']=='drive' for a in robot.actions))
