"""Orchestration checks with mocked processes, not live Mininet evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
try:
    import experiment
except ModuleNotFoundError:
    experiment=None

@unittest.skipIf(experiment is None,'Run pairing test with system Python (Mininet imports)')
class PairingTests(unittest.TestCase):
    def test_busy_workload_restarts_for_each_mode_and_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'content').mkdir(); (root/'content/document.pdf').write_bytes(b'test fixture')
            demo=experiment.Demo.__new__(experiment.Demo)
            demo.output=root
            demo.health=Mock(return_value={str(i):dict(healthy=True,active=0) for i in range(4)})
            demo.wait_for=lambda predicate,*args:self.assertTrue(predicate())
            demo.controller=Mock(return_value={'down_links':[]})
            demo.background=Mock(return_value=['mock process'])
            demo.stop_processes=Mock()
            order=[]
            def batch(scenario,**options):
                order.append(options['policy'])
                return [dict(ok=True,server='srv1',response_s=1,throughput_mbps=1,
                             policy=options['policy'],trial=options['trial'],case=options['case'])]
            demo.batch=Mock(side_effect=batch)
            with patch.object(experiment,'ROOT',root),patch.object(experiment.time,'sleep'),patch.object(experiment,'stage'),patch.object(experiment,'say'),patch.object(experiment,'comparison_lesson'):
                demo.paired_test('congestion',trials=2,busy=True)
            self.assertEqual(order,['static','dynamic','dynamic','static'])
            self.assertEqual(demo.background.call_count,4)
            self.assertEqual(demo.stop_processes.call_count,4)
            self.assertTrue((root/'comparison_cases/congestion/method.json').exists())

    def test_mixed_batch_preserves_client_file_assignments_in_both_modes(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            demo=experiment.Demo.__new__(experiment.Demo)
            demo.output=Path(directory); demo.rows=[]; demo.events=[]
            demo.processes=[]; demo.previous_servers={}
            assigned=[]
            def launch(command,**kwargs):
                assigned.append(command[4])
                return Mock(communicate=Mock(return_value=(json.dumps(dict(
                    ok=True,server='srv1',response_s=1,throughput_mbps=1)),'')))
            demo.net={f'c{i}':Mock(popen=Mock(side_effect=launch)) for i in range(1,7)}
            with patch.object(experiment,'say'),patch.object(experiment,'show_request'),patch.object(experiment,'batch_summary'):
                static=demo.batch('normal-static',name=None,policy='static',address='10.0.0.11')
                dynamic=demo.batch('normal-dynamic',name=None,policy='dynamic')
            self.assertEqual(assigned,list(experiment.MIXED_FILES)*2)
            self.assertEqual([row['content'] for row in static],[row['content'] for row in dynamic])
            self.assertEqual(len(set(assigned)),4)
