import unittest,tempfile,time
from pathlib import Path
from unittest.mock import Mock
from target_approach import validate,execute_plan

class TargetTests(unittest.TestCase):
    def plan(self,**changes):
        return dict(action='drive',reason='clear',visibility='good',forward_floor_clear=True,
                    target_visible=False,target_verified=False,close_enough=False,target_box=None,distance_mm=150,**changes)
    def test_short_search_allowed(self):self.assertEqual(validate(self.plan(),80)['distance_mm'],150)
    def test_model_chooses_step_with_visible_target(self):
        p=self.plan();p.update(target_visible=True,target_box=[.3,.2,.6,.6])
        validate(p,80)
        p['distance_mm']=50;validate(p,80)
    def test_verified_target_allows_continuous_50cm_approach(self):
        from oi import validate_motion
        p=self.plan();p.update(target_visible=True,target_verified=True,distance_mm=500)
        validate(p,80)
        validate_motion({'action':'drive','distance_mm':p['distance_mm']})
        p['distance_mm']=1200;validate(p,80,remaining_mm=1500)
        with self.assertRaises(ValueError):validate(p,80,remaining_mm=1000)
    def test_long_move_requires_visible_verified_target(self):
        for visible,verified in [(False,False),(True,False),(False,True)]:
            p=self.plan();p.update(target_visible=visible,target_verified=verified,distance_mm=500)
            with self.assertRaises(ValueError):validate(p,80)
    def test_image_position_does_not_override_model_clearance(self):
        p=self.plan();p.update(target_visible=True,target_box=[.3,.5,.6,.9],distance_mm=20)
        validate(p,80)
    def test_motion_limit_and_declared_obstruction_enforced(self):
        for change in ({'distance_mm':151},{'forward_floor_clear':False},{'visibility':'unusable'}):
            p=self.plan();p.update(change)
            with self.assertRaises(ValueError):validate(p,80)
    def test_action_controls_continuing_approach_not_proximity_flag(self):
        p=self.plan();p.update(close_enough=True,distance_mm=10)
        validate(p,80)
    def test_historical_shirt_confirmation_survives_occlusion(self):
        p=self.plan();p.update(action='turn',degrees=10,target_verified=True);p.pop('distance_mm')
        validate(p,80)
    def test_arrival_requires_shirt(self):
        p=self.plan();p.pop('distance_mm');p.update(action='arrived',target_visible=True,close_enough=True,target_box=[.3,.2,.7,.7])
        with self.assertRaises(ValueError):validate(p,80)
        p['target_verified']=True;validate(p,80)
        p['target_box']=None;validate(p,80)
    def test_unsafe_clearance_rejected(self):
        p=self.plan();p['forward_floor_clear']='true'
        with self.assertRaises(ValueError):validate(p,80)
    def test_scan_and_waypoint_commands_have_strict_bounds(self):
        for action,field,value in [('scan','degrees',180),('face_heading','heading_degrees',145)]:
            p=self.plan();p.pop('distance_mm');p.update(action=action);p[field]=value
            validate(p,80)
            p[field]=361
            with self.assertRaises(ValueError):validate(p,80)
    def test_model_distance_executes_as_bounded_segments(self):
        robot=Mock();robot.execute.return_value={'reported_velocity_mm_s':0}
        with tempfile.TemporaryDirectory() as folder:
            result=execute_plan(robot,{'action':'drive','distance_mm':1200},Path(folder),time.monotonic()+120)
        moves=[c.args[0]['distance_mm'] for c in robot.execute.call_args_list if c.args[0]['action']=='drive']
        self.assertEqual(moves,[500,500,200]);self.assertEqual(len(result['segments']),3)
        speeds=[c.args[0]['speed_mm_s'] for c in robot.execute.call_args_list if c.args[0]['action']=='drive']
        self.assertEqual(speeds,[80,80,60])
    def test_excessive_speed_rejected_by_motor_controller(self):
        from oi import validate_motion
        validate_motion({'action':'drive','distance_mm':500,'speed_mm_s':120})
        with self.assertRaises(ValueError):validate_motion({'action':'drive','distance_mm':500,'speed_mm_s':121})
    def test_stop_between_segments_prevents_remaining_motion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);robot=Mock()
            def execute(command):
                if command['action']=='status':(root/'STOP').touch()
                return {'reported_velocity_mm_s':0}
            robot.execute.side_effect=execute
            with self.assertRaises(RuntimeError):execute_plan(robot,{'action':'drive','distance_mm':1200},root,time.monotonic()+120)
            self.assertEqual(len(robot.execute.call_args_list),2)

if __name__=='__main__':unittest.main()
