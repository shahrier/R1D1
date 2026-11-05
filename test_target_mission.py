"""Mission lifecycle checks with fake API, camera, sound and serial controller."""
import contextlib,io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import target_approach as mission
from inspect_demo import Store


class MissionTests(unittest.TestCase):
    def brain(self):
        return Mock(model='muse-wonder-1.0',estimated_usd=0,deadline=time.monotonic()+120)

    def run_stages(self,second_action):
        with tempfile.TemporaryDirectory() as folder:
            brain=self.brain();brain.last={}
            plan={'action':'arrived','reason':'verified close target','visibility':'good',
                  'forward_floor_clear':True,'target_visible':True,'target_verified':True,
                  'close_enough':True,'target_box':None}
            brain.ask.side_effect=[json.dumps(plan),json.dumps({**plan,'action':second_action})]
            robot=Mock();robot.execute.return_value={'pose':{'x_mm':0,'y_mm':0,'heading_degrees':0},
                'travelled_mm':0,'reported_velocity_mm_s':0}
            with patch.object(mission,'__file__',str(Path(folder)/'target_approach.py')), \
                 patch.object(mission,'Brain',return_value=brain),patch.object(mission,'Robot',return_value=robot), \
                 patch.object(mission,'scan',return_value=[]) as scan, \
                 patch.object(mission,'capture',return_value=('fake.jpg',{'brightness':100})), \
                 patch.object(mission,'send_report',return_value={'simulated':True}), \
                 patch('sound_effects.play_stopped',return_value={'simulated':True}), \
                 contextlib.redirect_stdout(io.StringIO()):
                robot.execute.return_value['effect']='simulated'
                mission.main(['--target','black Roomba','--then','I heart AI doll'])
            result=json.loads(next((Path(folder)/'runtime').glob('target-*/result.json')).read_text())
            descriptions=[call.args[1]['target_description'] for call in brain.ask.call_args_list]
            self.assertEqual(descriptions,['black Roomba','I heart AI doll'])
            self.assertEqual(scan.call_count,2)
            self.assertTrue((Path(folder)/'runtime/STOP').exists())
            return result

    def test_two_targets_complete_in_order(self):
        result=self.run_stages('arrived')
        self.assertTrue(result['goal_reported_reached']);self.assertEqual(len(result['stages']),2)

    def test_second_target_failure_does_not_report_whole_mission_success(self):
        result=self.run_stages('blocked')
        self.assertFalse(result['goal_reported_reached']);self.assertEqual(len(result['stages']),1)

    def test_api_failure_never_opens_serial_and_leaves_stop_latched(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=self.brain();brain.preflight.side_effect=RuntimeError('simulated auth error')
            with patch.object(mission,'__file__',str(Path(folder)/'target_approach.py')), \
                 patch.object(mission,'Brain',return_value=brain), \
                 patch.object(mission,'Robot') as robot, \
                 patch.object(mission,'capture',return_value=('fake.jpg',{})), \
                 patch.object(mission,'send_report',return_value={'simulated':True}), \
                 patch('sound_effects.play_stopped',return_value={'simulated':True}), \
                 contextlib.redirect_stdout(io.StringIO()):
                mission.main([])
            robot.assert_not_called()
            self.assertTrue((Path(folder)/'runtime/STOP').exists())
            self.assertTrue((Path(folder)/'runtime/run-benchmarks.jsonl').exists())

    def test_mission_lock_precedes_latch_reset_or_serial_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'runtime';store=Store(root);(root/'STOP').touch()
            with store.locked(),patch.object(mission,'__file__',str(Path(folder)/'target_approach.py')), \
                 patch.object(mission,'Brain',return_value=self.brain()), \
                 patch.object(mission,'Robot') as robot:
                with self.assertRaises(RuntimeError):mission.main([])
                robot.assert_not_called();self.assertTrue((root/'STOP').exists())
