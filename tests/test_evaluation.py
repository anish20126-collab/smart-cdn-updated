"""Check comparison statistics, failure accounting, and missing-data handling."""
import tempfile
import unittest
from evaluation import summarize

class ComparisonTests(unittest.TestCase):
    def test_trial_means_and_failures(self):
        rows=[dict(policy='static',trial=1,ok=True,server='srv1',response_s=2,throughput_mbps=8),
              dict(policy='static',trial=1,ok=False,server='',response_s=20,throughput_mbps=0),
              dict(policy='static',trial=2,ok=True,server='srv1',response_s=4,throughput_mbps=4),
              dict(policy='dynamic',trial=1,ok=False,server='',response_s=20,throughput_mbps=0)]
        with tempfile.TemporaryDirectory() as root:
            summary,distribution=summarize(rows,root)
        static,dynamic=summary
        self.assertEqual(static['successes'],2)
        self.assertEqual(static['failures'],1)
        self.assertEqual(static['mean_response_s'],3)
        self.assertAlmostEqual(static['std_response_s'],2**.5)
        self.assertEqual(dynamic['mean_response_s'],'')
        self.assertEqual(dynamic['failures'],1)
        self.assertEqual(distribution['static','srv1'],2)

    def test_old_runs_do_not_become_comparisons(self):
        with tempfile.TemporaryDirectory() as root:
            summary,_=summarize([dict(ok=True,scenario='normal')],root)
        self.assertEqual(summary,[])
