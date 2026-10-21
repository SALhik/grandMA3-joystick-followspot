import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from followspot_core import Settings


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'ma_plugin'))
import runtime as plugin_runtime  # noqa: E402
if os.name == 'posix':  # worker imports fcntl
    import worker  # noqa: E402


class FakeStream:
    def __init__(self, settings, xyz):
        self.position = tuple(xyz)
        self.closed = False
        self.error = None

    def set_position(self, xyz):
        self.position = tuple(xyz)

    def poll_error(self):
        value, self.error = self.error, None
        return value

    def close(self):
        self.closed = True


class LeaseSim:
    """Drives worker.run on a fake clock; lease renewal is decided per step."""

    def __init__(self, test, output_mode='psn', end=40.0):
        self.test, self.end, self.now = test, end, 0.0
        self.folder = tempfile.TemporaryDirectory()
        test.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.root = self.base/'run'
        self.root.mkdir()
        config = dict(output_mode=output_mode, settings=Settings(test_period=600).to_dict())
        (self.root/'config.json').write_text(json.dumps(config))
        (self.root/'lease').write_text('tok:0')
        self.runtime = None
        self.ticks = []
        self.counter = 0
        self.statuses = []
        self.renew = lambda t: True
        self.on_step = lambda t: None
        self.request_id = 0

    def factory(self, config):
        self.runtime = plugin_runtime.PluginRuntime(config, stream_factory=FakeStream)
        real_tick = self.runtime.tick
        def tick(dt):
            self.ticks.append(self.now)
            return real_tick(dt)
        self.runtime.tick = tick
        return self.runtime

    def request(self, action):
        self.request_id += 1
        (self.root/'request.json').write_text(json.dumps(
            dict(token='tok', id=self.request_id, action=action, payload={})))

    def urgent(self, action, ident=1):
        (self.root/'urgent.json').write_text(json.dumps(dict(token='tok', id=ident, action=action)))

    def sleep(self, seconds):
        self.statuses.append((self.now, json.loads((self.root/'status.json').read_text())))
        self.now += 1/30
        if self.renew(self.now):
            self.counter += 1
            (self.root/'lease').write_text(f'tok:{self.counter}')
        if self.runtime and self.runtime.frame:
            (self.root/'ack.json').write_text(json.dumps(
                dict(token='tok', event_id=0, frame_id=self.runtime.frame['seq'])))
        self.on_step(self.now)
        if self.now >= self.end:
            self.urgent('shutdown', ident=99)

    def run(self):
        code = worker.run(self.root, 'tok', self.base, runtime_factory=self.factory,
                          clock=lambda: self.now, sleep=self.sleep)
        self.final = json.loads((self.root/'status.json').read_text())
        return code

    def status_at(self, t):
        return min(self.statuses, key=lambda item: abs(item[0]-t))[1]


@unittest.skipUnless(os.name == 'posix', 'Plugin helper requires POSIX file locking')
class RequestErrorTests(unittest.TestCase):
    def test_settings_errors_report_the_fields_to_highlight(self):
        sim = LeaseSim(self, output_mode='direct', end=1.0)
        bad = dict(output_mode='direct', settings=dict(Settings().to_dict(), marker_id=0))
        def on_step(t):
            if t > .2 and not (sim.root/'request.json').exists():
                (sim.root/'request.json').write_text(json.dumps(
                    dict(token='tok', id=1, action='configure', payload=dict(config=bad))))
        sim.on_step = on_step
        sim.run()
        reply = next(status for _, status in sim.statuses if status.get('request_id') == 1)
        self.assertEqual(reply['request_error'], 'IDs must be positive.')
        self.assertEqual(reply['request_error_fields'], ['marker_id'])


@unittest.skipUnless(os.name == 'posix', 'Plugin helper requires POSIX file locking')
class TwoStageLeaseTests(unittest.TestCase):
    def sim_with_running_psn(self, stall_from=1.0, renew_again=None, **kwargs):
        sim = LeaseSim(self, **kwargs)
        sim.renew = lambda t: t < stall_from or (renew_again is not None and t >= renew_again)
        started = []
        def on_step(t):
            if t > .3 and not started:
                started.append(t)
                sim.request('test')
        sim.on_step = on_step
        return sim

    def test_no_stream_exits_when_lease_is_older_than_stop_threshold(self):
        sim = LeaseSim(self, output_mode='direct')
        sim.renew = lambda t: t < 1.0
        self.assertEqual(sim.run(), 0)
        self.assertEqual(sim.final['exit_reason'], 'lease_expired')
        self.assertGreater(sim.now, 1.0 + worker.LEASE_STOP_SECONDS)
        self.assertLess(sim.now, 1.0 + worker.LEASE_STOP_SECONDS + .2)

    def test_open_stream_stops_output_and_holds_until_hold_threshold(self):
        sim = self.sim_with_running_psn()
        sim.run()
        self.assertEqual((worker.LEASE_STOP_SECONDS, worker.LEASE_HOLD_SECONDS), (3, 15))
        before = sim.status_at(2.5)
        self.assertTrue(before['running'])
        self.assertFalse(before['lease_lost'])
        lost = sim.status_at(8.0)
        self.assertTrue(lost['lease_lost'])
        self.assertFalse(lost['running'])
        self.assertTrue(lost['holding'])
        self.assertEqual(lost['fault'], 'MA heartbeat lost; output stopped and PSN held. Start again when MA responds.')
        # No tick while MA is silent after the stop threshold.
        silent_from = 1.0 + worker.LEASE_STOP_SECONDS
        self.assertFalse([t for t in sim.ticks if t > silent_from + .1])
        # Exit only after the hold threshold, closing the stream.
        self.assertEqual(sim.final['exit_reason'], 'lease_expired')
        self.assertGreater(sim.now, 1.0 + worker.LEASE_HOLD_SECONDS)
        self.assertLess(sim.now, 1.0 + worker.LEASE_HOLD_SECONDS + .2)
        self.assertTrue(sim.runtime.closed)

    def test_hold_expiry_reports_that_the_stream_was_released(self):
        sim = self.sim_with_running_psn()
        sim.run()
        self.assertEqual(sim.final['exit_reason'], 'lease_expired')
        self.assertFalse(sim.final['holding'])
        self.assertEqual(sim.final['fault'], 'MA heartbeat lost for 15 s; PSN released and helper stopped. '
                                             'Reconnect to continue.')

    def test_stream_stays_open_while_lost(self):
        sim = self.sim_with_running_psn()
        streams = []
        original = sim.on_step
        def watch(t):
            original(t)
            if sim.runtime and sim.runtime.stream and 4.0 < t < 14.0:
                streams.append(sim.runtime.stream.closed)
        sim.on_step = watch
        sim.run()
        self.assertTrue(streams)
        self.assertFalse(any(streams))

    def test_stop_is_applied_once_not_every_loop(self):
        sim = self.sim_with_running_psn()
        calls = []
        original = sim.factory
        def factory(config):
            runtime = original(config)
            real = runtime.hold_after_lease_loss
            runtime.hold_after_lease_loss = lambda: (calls.append(sim.now), real())[1]
            return runtime
        sim.factory = factory
        sim.run()
        self.assertEqual(len(calls), 1)

    def test_renewal_while_lost_resumes_ticks_without_restarting_output(self):
        sim = self.sim_with_running_psn(renew_again=8.0)
        sim.end = 12.0
        sim.run()
        self.assertEqual(sim.final['exit_reason'], 'shutdown')
        after = sim.status_at(10.0)
        self.assertFalse(after['lease_lost'])
        self.assertFalse(after['running'])
        self.assertTrue(after['holding'])
        self.assertIn('MA heartbeat lost', after['fault'])
        self.assertTrue([t for t in sim.ticks if t > 8.0])
        self.assertTrue([t for t in sim.ticks if t < 1.0 + worker.LEASE_STOP_SECONDS])

    def test_stream_error_while_lost_is_surfaced(self):
        sim = self.sim_with_running_psn()
        def on_step(t):
            if 5.0 < t < 5.1 and sim.runtime.stream:
                sim.runtime.stream.error = OSError('network failed')
        sim.on_step = lambda t: (self.sim_started(sim, t), on_step(t))
        sim.run()
        # Surfaced while the lease was still lost, well before the hold threshold.
        self.assertEqual(sim.status_at(5.5)['fault'], 'PSN: network failed')
        self.assertFalse(sim.status_at(5.5)['holding'])
        self.assertEqual(sim.final['fault'], 'PSN: network failed')
        self.assertFalse(sim.final['holding'])

    @staticmethod
    def sim_started(sim, t):
        if t > .3 and sim.request_id == 0:
            sim.request('test')

    def test_urgent_release_while_lost_closes_stream(self):
        sim = self.sim_with_running_psn()
        stream = []
        original = sim.on_step
        def on_step(t):
            original(t)
            if sim.runtime and sim.runtime.stream and not stream:
                stream.append(sim.runtime.stream)
            if 6.0 < t < 6.1:
                sim.urgent('release')
        sim.on_step = on_step
        sim.run()
        self.assertTrue(stream[0].closed)
        self.assertFalse(sim.status_at(7.0)['holding'])
        self.assertLess(sim.now, 1.0 + worker.LEASE_HOLD_SECONDS)

    def test_urgent_shutdown_while_lost_exits(self):
        sim = self.sim_with_running_psn()
        sim.on_step = lambda t: (self.sim_started(sim, t), t > 6.0 and sim.urgent('shutdown'))
        sim.run()
        self.assertEqual(sim.final['exit_reason'], 'shutdown')



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
