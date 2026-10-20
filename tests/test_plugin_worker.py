import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'Plugin helper requires POSIX file locking')
class WorkerTests(unittest.TestCase):
    def test_real_worker_handshake_requests_stop_and_lease_expiry(self):
        self.assertTrue((ROOT/'ma_plugin/worker.py').exists(), 'Worker not implemented')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            run = base/'run'; run.mkdir()
            (run/'config.json').write_text(json.dumps({'settings': {}, 'output_mode': 'direct'}))
            (run/'lease').write_text('owner:0')
            process = subprocess.Popen([sys.executable, str(ROOT/'ma_plugin/worker.py'), str(run),
                'owner', '--base', str(base)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(lambda: process.poll() is None and process.kill())
            end = time.monotonic()+4
            status = None
            counter = 0
            while time.monotonic()<end:
                counter += 1
                (run/'lease').write_text(f'owner:{counter}')
                if (run/'status.json').exists():
                    status=json.loads((run/'status.json').read_text())
                    if status.get('ready'): break
                time.sleep(.02)
            self.assertTrue(status and status['ready'])
            self.assertFalse(status['running'])
            duplicate = base/'duplicate'; duplicate.mkdir()
            (duplicate/'config.json').write_text((run/'config.json').read_text())
            (duplicate/'lease').write_text('other:0')
            second = subprocess.run([sys.executable,str(ROOT/'ma_plugin/worker.py'),str(duplicate),
                'other','--base',str(base)],capture_output=True,text=True,timeout=3)
            self.assertEqual(second.returncode,73,second.stderr)
            self.assertEqual(json.loads((duplicate/'status.json').read_text())['exit_reason'],'busy')
            request=dict(token='owner',id=1,action='test',payload={})
            (run/'request.json').write_text(json.dumps(request))
            for _ in range(30):
                counter+=1; (run/'lease').write_text(f'owner:{counter}')
                time.sleep(.02)
                status=json.loads((run/'status.json').read_text())
                if status['request_id']==1: break
            self.assertTrue(status['running'])
            self.assertEqual(status['frame']['target']['kind'], 'marker')
            initial=status['frame']
            time.sleep(.12)
            self.assertEqual(json.loads((run/'status.json').read_text())['frame'],initial,
                             'Motion advanced before MA acknowledged the initial frame')
            (run/'ack.json').write_text(json.dumps(dict(token='owner',event_id=0,frame_id=initial['seq'])))
            for _ in range(20):
                time.sleep(.02)
                status=json.loads((run/'status.json').read_text())
                if status['frame']['seq']>initial['seq']: break
            self.assertGreater(status['frame']['seq'],initial['seq'])
            # A cancelled Start request cannot restart output after urgent Stop.
            (run/'request.json').write_text(json.dumps(dict(request,id=2,action='start')))
            (run/'urgent.json').write_text(json.dumps(dict(token='owner',id=1,
                action='stop',cancel_through=2)))
            for _ in range(10):
                counter+=1; (run/'lease').write_text(f'owner:{counter}')
                time.sleep(.02)
            status=json.loads((run/'status.json').read_text())
            self.assertFalse(status['running'])
            process.communicate(timeout=5)
            self.assertEqual(process.returncode,0)
            final=json.loads((run/'status.json').read_text())
            self.assertEqual(final['exit_reason'],'lease_expired')


if __name__=='__main__': unittest.main()
