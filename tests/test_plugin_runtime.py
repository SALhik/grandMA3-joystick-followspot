import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from followspot_core import Settings


ROOT = Path(__file__).resolve().parents[1]


class Input:
    def __init__(self):
        self.handle = None
        self.axes = [0, 0, -1, 0]
        self.buttons = [False, False, False]
        self.fail = False
    def devices(self): return [(0, 'Test stick')]
    def open(self, index): self.handle = index + 1
    def read(self):
        if self.fail: raise OSError('unplugged')
        return self.axes[:], self.buttons[:]
    def close(self): self.handle = None
    def shutdown(self): self.close()


class Stream:
    def __init__(self, settings, xyz):
        self.seed = tuple(xyz)
        self.position = tuple(xyz)
        self.closed = False
        self.error = None
    def set_position(self, xyz): self.position = tuple(xyz)
    def poll_error(self):
        value, self.error = self.error, None
        return value
    def close(self): self.closed = True


class PluginRuntimeTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'ma_plugin/runtime.py'
        self.assertTrue(path.exists(), 'Plugin runtime is not implemented')
        spec = importlib.util.spec_from_file_location('plugin_runtime', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.input = Input()
        self.now = 0.0
        self.config = dict(output_mode='direct', settings=Settings(max_speed=2,
            invert_y=False, test_period=2).to_dict())
        self.runtime = module.PluginRuntime(self.config, input_factory=lambda: self.input,
                                           stream_factory=Stream, clock=lambda: self.now)

    def connect(self):
        self.runtime.command('refresh')
        self.runtime.command('select', {'index': 0, 'name': 'Test stick'})

    def test_starts_stopped_and_motion_reuses_proportional_core(self):
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertIsNone(self.runtime.snapshot()['frame'])
        self.connect()
        self.runtime.command('start')
        self.input.axes[0] = 1
        self.runtime.tick(0.1)
        frame = self.runtime.snapshot()['frame']
        self.assertEqual(frame['target']['xyz'], [0.2, 0, 1.5])
        for got, expected in zip(frame['target']['percent'], [50.1, 50, 50.75]):
            self.assertAlmostEqual(got, expected)
        self.input.axes[0] = 0
        self.runtime.tick(0.1)
        self.assertEqual(self.runtime.snapshot()['frame']['target']['xyz'], [0.2, 0, 1.5])

    def test_finite_test_needs_no_joystick_and_holds_at_completion(self):
        self.runtime.command('test')
        for _ in range(21): self.runtime.tick(0.1)
        status = self.runtime.snapshot()
        self.assertFalse(status['running'])
        self.assertAlmostEqual(status['frame']['target']['xyz'][0], 0)
        self.assertEqual(status['frame']['brightness'], 100)

    def test_button_commands_are_ordered_and_retained_until_acknowledged(self):
        self.config['settings']['buttons'] = {'0': {'press': 'Flash On Executor 1.202',
                                                   'release': 'Flash Off Executor 1.202'}}
        self.runtime.command('configure', {'config': self.config})
        self.connect()
        self.runtime.command('start')
        self.input.buttons[0] = True
        self.runtime.tick(.1)
        self.runtime.command('stop')
        events = self.runtime.snapshot()['events']
        self.assertEqual([e['command'] for e in events],
                         ['Flash On Executor 1.202', 'Flash Off Executor 1.202'])
        self.runtime.acknowledge(events[0]['id'])
        self.assertEqual(self.runtime.snapshot()['events'], [events[1]])
        self.runtime.acknowledge(events[1]['id'])
        self.assertEqual(self.runtime.snapshot()['events'], [])

    def test_held_at_start_is_not_owned_and_cannot_emit_a_release(self):
        self.config['settings']['buttons'] = {'0': {'press': 'On Sequence 4', 'release': 'Off Sequence 4'}}
        self.runtime.command('configure', {'config': self.config})
        self.connect()
        self.input.buttons[0] = True
        self.runtime.command('start')
        self.input.buttons[0] = False
        self.runtime.tick(.1)
        self.runtime.command('stop')
        self.assertEqual(self.runtime.snapshot()['events'], [])

    def test_psn_seed_stop_hold_guard_and_release(self):
        self.config['output_mode'] = 'psn'
        self.runtime.command('configure', {'config': self.config})
        self.runtime.command('test')
        stream = self.runtime.stream
        self.assertEqual(stream.seed, (0, 0, 1.5))
        self.runtime.tick(.2)
        self.runtime.command('stop')
        self.assertFalse(stream.closed)
        self.assertTrue(self.runtime.snapshot()['holding'])
        changed = copy.deepcopy(self.config)
        changed['settings']['psn_tracker_id'] = 2
        with self.assertRaisesRegex(ValueError, 'Release'):
            self.runtime.command('configure', {'config': changed})
        self.runtime.command('release')
        self.assertTrue(stream.closed)
        self.assertFalse(self.runtime.snapshot()['holding'])

    def test_stream_error_stops_output_and_closes_stream(self):
        self.config['output_mode'] = 'psn'
        self.runtime.command('configure', {'config': self.config})
        self.runtime.command('test')
        stream = self.runtime.stream
        stream.error = OSError('network failed')
        self.runtime.tick(.1)
        self.assertTrue(stream.closed)
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertIn('network failed', self.runtime.snapshot()['fault'])

    def test_check_stream_surfaces_error_without_ticking_output(self):
        self.config['output_mode'] = 'psn'
        self.runtime.command('configure', {'config': self.config})
        self.runtime.command('test')
        stream = self.runtime.stream
        self.assertFalse(self.runtime.check_stream())
        stream.error = OSError('network failed')
        self.assertTrue(self.runtime.check_stream())
        self.assertTrue(stream.closed)
        self.assertIsNone(self.runtime.stream)
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertEqual(self.runtime.fault, 'PSN: network failed')

    def test_hold_after_lease_loss_stops_output_but_keeps_stream(self):
        self.config['output_mode'] = 'psn'
        self.runtime.command('configure', {'config': self.config})
        self.runtime.command('test')
        stream = self.runtime.stream
        self.runtime.hold_after_lease_loss()
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertFalse(stream.closed)
        self.assertIs(self.runtime.stream, stream)
        self.assertIn('MA heartbeat lost', self.runtime.fault)

    def test_input_failure_stops_and_closes_device_without_resuming(self):
        self.connect()
        self.runtime.command('start')
        self.input.fail = True
        self.runtime.tick(.1)
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertFalse(self.runtime.snapshot()['device_open'])
        self.assertIn('unplugged', self.runtime.snapshot()['fault'])

    def test_axis_learning_suppresses_actions_and_only_returns_a_draft_change(self):
        self.connect()
        self.runtime.command('learn', {'key': 'axis_x'})
        self.input.axes[2] = 1
        self.runtime.tick(.1)
        status = self.runtime.snapshot()
        self.assertEqual(status['learned']['values'], {'axis_x': 2})
        self.assertEqual(status['config']['settings']['axis_x'], 0)
        self.assertFalse(status['running'])

    def test_reset_lock_and_zoom_temp_level_tracking(self):
        self.config['settings']['zoom_enabled'] = True
        self.runtime.command('configure', {'config': self.config})
        self.connect()
        self.runtime.command('start')
        self.input.axes[0], self.input.axes[3] = 1, 1
        self.runtime.tick(.1)
        frame = self.runtime.snapshot()['frame']
        self.assertEqual(frame['zoom'], 55)
        self.runtime.command('reset')
        self.assertEqual(self.runtime.snapshot()['frame']['target']['xyz'], frame['target']['xyz'])
        self.runtime.command('reset_lock', {'locked': False})
        self.runtime.command('reset')
        self.assertEqual(self.runtime.snapshot()['frame']['target']['xyz'], [0, 0, 1.5])
        self.assertEqual(self.runtime.snapshot()['frame']['zoom'], 50)

    def test_save_preserves_tracked_position_and_rejects_running_edits(self):
        self.connect()
        self.runtime.command('start')
        self.input.axes[0] = 1
        self.runtime.tick(.1)
        with self.assertRaisesRegex(ValueError, 'Stop'):
            self.runtime.command('configure', {'config': self.config})
        self.runtime.command('stop')
        self.runtime.command('configure', {'config': self.config})
        self.input.axes[0] = 0
        self.runtime.command('start')
        self.assertEqual(self.runtime.snapshot()['frame']['target']['xyz'], [0.2, 0, 1.5])

    def test_inactive_pan_limits_are_not_used_while_marker_mode_is_applied(self):
        self.config['settings'].update(pan_min=200,pan_max=-10)
        self.runtime.command('configure',{'config':self.config})
        self.assertEqual(self.runtime.snapshot()['preview']['pan_tilt'],[50,50])

    def test_start_read_failure_closes_input_immediately(self):
        self.connect();self.input.fail=True
        with self.assertRaisesRegex(OSError,'unplugged'): self.runtime.command('start')
        self.assertFalse(self.runtime.snapshot()['device_open'])

    def test_command_events_distinguish_release_from_cancelled_press(self):
        self.config['settings']['buttons']={'0':{'press':'Flash On Exec 201','release':'Flash Off Exec 201'}}
        self.runtime.command('configure',{'config':self.config});self.connect();self.runtime.command('start')
        self.input.buttons[0]=True;self.runtime.tick(.1);self.runtime.command('stop')
        events=self.runtime.snapshot()['events']
        self.assertFalse(events[0].get('release'))
        self.assertTrue(events[1].get('release'))
        self.assertEqual(events[0]['generation'],events[1]['generation'])

    def test_reset_forces_one_position_resend_even_at_home_without_resetting_brightness(self):
        self.connect();self.runtime.command('start')
        self.runtime.command('reset_lock',{'locked':False})
        before=self.runtime.snapshot()['frame']
        self.runtime.command('reset')
        after=self.runtime.snapshot()['frame']
        self.assertGreater(after['seq'],before['seq'])
        self.assertEqual(after['brightness'],before['brightness'])
        self.assertTrue(after['force_position'])

    def test_identical_press_and_release_text_keeps_distinct_button_ownership(self):
        self.config['settings']['buttons']={'0':{'press':'Toggle Exec 201','release':'Toggle Exec 201'}}
        self.runtime.command('configure',{'config':self.config});self.connect();self.runtime.command('start')
        self.input.buttons[0]=True;self.runtime.tick(.1)
        self.input.buttons[0]=False;self.runtime.tick(.1)
        press,release=self.runtime.snapshot()['events']
        self.assertFalse(press['release'])
        self.assertTrue(release['release'])
        self.assertEqual(press['owner'],release['owner'])
        self.assertTrue(release['paired'])

    def test_queue_failure_keeps_release_warning_after_explicit_restart(self):
        self.config['settings']['buttons']={'0':{'press':'Flash On Exec 201','release':'Flash Off Exec 201'}}
        self.runtime.command('configure',{'config':self.config});self.connect();self.runtime.command('start')
        for _ in range(33):
            self.input.buttons[0]=True;self.runtime.tick(.01)
            self.input.buttons[0]=False;self.runtime.tick(.01)
        self.assertFalse(self.runtime.snapshot()['running'])
        self.assertIn('Release',self.runtime.snapshot()['warning'])
        self.runtime.acknowledge(self.runtime.event_seq)
        self.runtime.command('start')
        self.assertIn('Release',self.runtime.snapshot()['warning'])
        self.runtime.command('ack_warning')
        self.assertEqual(self.runtime.snapshot()['warning'],'')


if __name__ == '__main__': unittest.main()
