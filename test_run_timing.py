import unittest
from unittest.mock import patch
from run_timing import RunTiming


class TimingTests(unittest.TestCase):
    @patch('run_timing.time.monotonic',side_effect=[10,11,14,15,16,17])
    def test_failed_operations_are_timed_and_first_milestone_preserved(self,clock):
        timer=RunTiming()
        def fail():raise RuntimeError('test')
        with self.assertRaises(RuntimeError):timer.call('model',fail)
        timer.mark('stopped');timer.mark('stopped')
        summary=timer.summary()
        self.assertEqual(summary['phases']['model'],{'seconds':3,'calls':1})
        self.assertEqual(summary['milestones_s']['stopped'],5)
        self.assertEqual(summary['total_elapsed_s'],7)
