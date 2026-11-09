"""Check that the explanation follows outcomes instead of promising a winner."""
import contextlib
import io
import tempfile
import unittest
from presentation import comparison_lesson

class ExplanationTests(unittest.TestCase):
    def explain(self, static_time, dynamic_time, static_ok=True, case='normal'):
        rows=[dict(policy=policy,trial=trial,ok=ok,server=server,response_s=seconds,throughput_mbps=1)
              for trial in [1,2] for policy,seconds,ok,server in [
                  ('static',static_time,static_ok,'srv1'),('dynamic',dynamic_time,True,'srv3')]]
        output=io.StringIO()
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(output):
            comparison_lesson(rows,root,case)
        return output.getvalue()

    def test_static_can_win_without_claiming_cause(self):
        text=self.explain(1,2)
        self.assertIn('FASTER SUCCESSFUL DOWNLOADS: STATIC',text)
        self.assertIn('did not isolate the cause',text)

    def test_server_outage_compares_success_not_failed_timing(self):
        text=self.explain(.01,2,False,'server-failure')
        self.assertIn('MORE FILES DELIVERED: DYNAMIC',text)
        self.assertIn('SPEED: Cannot compare',text)
        self.assertNotIn('FASTER SUCCESSFUL DOWNLOADS: STATIC',text)

    def test_fixed_server_does_not_mean_fixed_routes(self):
        self.assertIn('BOTH can take another road',self.explain(1,1,case='link-failure'))
