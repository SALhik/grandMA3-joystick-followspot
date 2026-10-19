"""Focused startup/UI regressions. All output uses fake transports."""
import struct
import os
import unittest
from unittest.mock import patch

import followspot
import followspot_core as core
import test_window as window_tests


class StartupHardeningTests(unittest.TestCase):
    app = window_tests.WindowTests.app

    def test_first_test_data_uses_test_initial_target_before_thread_runs(self):
        app, _ = self.app(position_output='psn', initial_x=2, initial_y=3)
        app.controller.motion.xyz = [8, -4, 1.5]
        packets = []
        class Socket:
            def sendto(self, packet, destination):
                packets.append(packet)
                if packet[:2] == b'Ug':
                    raise OSError('stop deterministic first-frame schedule')
            def close(self):
                pass
        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
            def join(self, **kwargs):
                pass
            def is_alive(self):
                return False
        def streamer(settings, xyz):
            return core.PsnStreamer(settings, xyz, sock=Socket(), clock=lambda: 0)
        with patch.object(followspot, 'PsnStreamer', side_effect=streamer), patch.object(core.threading, 'Thread', ImmediateThread):
            app.start_output(test=True)
            app.stop_output()
            app.close_streamer()
        data = next(packet for packet in packets if packet[:2] == b'Ug')
        self.assertEqual(struct.unpack('<3f', data[-12:]), (2, 3, 1.5))

    def test_window_release_cancel_preserves_running_stream_accept_releases(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        stream = app.streamer
        app.confirm = False
        self.assertFalse(app.confirm_release_marker())
        self.assertTrue(app.controller.active)
        self.assertIs(app.streamer, stream)
        app.confirm = True
        self.assertTrue(app.confirm_release_marker())
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)
        self.assertTrue(stream.closed)

    def test_mapped_release_stays_immediate_when_window_confirmation_would_cancel(self):
        app, _ = self.app(position_output='psn', buttons={'0': {'action': 'release_marker'}})
        app.start_output()
        app.confirm = False
        app.buttons[0] = True
        app.process_input(0.1)
        self.assertIsNone(app.streamer)
        self.assertFalse(app.controller.active)

    def test_mapped_pan_tilt_reset_skips_deflected_integration_in_same_sample(self):
        app, _ = self.app(control_mode='pan_tilt', reset_locked=False,
                          buttons={'0': {'action': 'reset'}})
        app.start_output()
        app.controller.motion.pan_tilt = [70, 80]
        app.axes = [1, 1, -1]
        app.buttons[0] = True
        app.process_input(0.25)
        self.assertEqual(app.controller.motion.pan_tilt, [50, 50])
        app.process_input(0.1)
        self.assertNotEqual(app.controller.motion.pan_tilt, [50, 50])

    def test_close_failure_during_release_is_visible_and_stops_output(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        def fail():
            raise TimeoutError('sender still alive')
        app.streamer.close = fail
        self.assertFalse(app.release_marker())
        self.assertFalse(app.controller.active)
        self.assertIn('sender still alive', app.faults['psn'])
        self.assertNotIn('released', app.status.get())

    def test_close_failure_during_stream_error_still_stops_output(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.streamer.error = OSError('send failed')
        def fail():
            raise TimeoutError('sender still alive')
        app.streamer.close = fail
        app.check_streamer()
        self.assertFalse(app.controller.active)
        self.assertIn('sender still alive', app.faults['psn'])

    def test_close_failure_during_window_close_keeps_fault_visible(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        destroyed = []
        app.root.destroy = lambda: destroyed.append(True)
        def fail():
            raise OSError('socket close failed')
        app.streamer.close = fail
        app.close()
        self.assertFalse(app.controller.active)
        self.assertEqual(destroyed, [])
        self.assertIn('socket close failed', app.faults['psn'])

    def test_failed_mapped_release_still_beats_simultaneous_start(self):
        app, _ = self.app(position_output='psn', buttons={'0': {'action': 'release_marker'}, '1': {'action': 'start'}})
        app.start_output()
        def fail():
            raise TimeoutError('sender still alive')
        app.streamer.close = fail
        app.buttons[:2] = [True, True]
        app.process_input(0.1)
        self.assertFalse(app.controller.active)
        self.assertEqual(len(self.streamers), 1)
        self.assertIn('sender still alive', app.faults['psn'])

    def test_close_failure_after_failed_start_still_closes_osc(self):
        app, _ = self.app(position_output='psn')
        def streamer(settings, xyz):
            stream = window_tests.FakeStreamer(settings, xyz)
            def fail():
                raise TimeoutError('sender still alive')
            stream.close = fail
            return stream
        with patch.object(followspot, 'PsnStreamer', side_effect=streamer), patch.object(core.Controller, 'start', side_effect=OSError('first OSC failed')):
            app.start_output()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.sender)
        self.assertIn('sender still alive', app.faults['psn'])


@unittest.skipIf(os.environ.get('FOLLOWSPOT_TEST_HEADLESS') == '1', 'Tk disabled by FOLLOWSPOT_TEST_HEADLESS')
class UiHardeningTests(unittest.TestCase):
    open_root = window_tests.RealWindowTests.open_root
    open_app = window_tests.RealWindowTests.open_app

    def held_app(self):
        app = self.open_app(position_output='psn')
        with patch.object(followspot, 'PsnStreamer', window_tests.FakeStreamer):
            app.start_output()
        app.stop_output()
        self.addCleanup(lambda: app.release_marker())
        return app

    def test_held_psn_change_blocks_start_and_test_and_explains_without_joystick(self):
        app = self.held_app()
        app.joystick.close()
        app.values['psn_port'].set('56570')
        self.assertEqual(str(app.start_button['state']), 'disabled')
        self.assertEqual(str(app.test_button['state']), 'disabled')
        self.assertIn('Release', app.view.readiness.get())
        self.assertIn('psn_port', app.view.readiness.get())
        self.assertIn('PSN HOLDING', app.output_label.get())
        app.values['psn_port'].set('56565')
        self.assertEqual(str(app.test_button['state']), 'normal')

    def test_no_joystick_test_blockers_explain_pending_editor_and_invalid_settings(self):
        app = self.open_app()
        app.joystick.close()
        app.press_command.set('Go+')
        self.assertEqual(str(app.test_button['state']), 'disabled')
        self.assertIn('mapping', app.view.readiness.get())
        app.view.discard_editor()
        app.values['port'].set('bad')
        self.assertEqual(str(app.test_button['state']), 'disabled')
        self.assertIn('settings', app.view.readiness.get().lower())

    def test_pending_start_matches_draft_brightness_and_clamped_target_output(self):
        app = self.open_app(zoom_enabled=True)
        app.axes = [0, 0, -1, 0]
        app.joystick.read = lambda: (list(app.axes), list(app.buttons))
        app.controller.motion.xyz = [8, -2, 1.5]
        app.controller.motion.zoom_level = 37.4
        app.values['invert_slider'].set(True)
        app.values['x_max'].set('5')
        app.values['z'].set('2')
        self.assertEqual(app.view.brightness.get(), 0)
        preview = app.view.pending_start.get()
        for text in ('5.00', '-2.00', '2.00', '100.0%', '37.4%'):
            self.assertIn(text, preview)
        self.assertEqual(app.controller.motion.xyz, [8, -2, 1.5])
        app.start_output()
        self.assertEqual(app.controller.motion.xyz, [5, -2, 2])
        self.assertEqual(app.controller.last_brightness, 100)
        self.assertEqual(app.controller.last_zoom, 37.4)

    def test_stage_cache_invalidates_target_geometry_hold_and_color(self):
        app = self.held_app()
        view = app.view
        view.draw_stage()
        unchanged = view.stage.find_all()
        view.draw_stage()
        self.assertEqual(view.stage.find_all(), unchanged)
        for mutate in (lambda: app.controller.motion.xyz.__setitem__(0, 1),
                       lambda: setattr(app.settings, 'x_max', 9),
                       lambda: app.streamer.set_position((2, 0, 1.5)),
                       lambda: setattr(view, 'foreground', '#123456')):
            previous = view.stage.find_all()
            mutate()
            view.draw_stage()
            self.assertNotEqual(view.stage.find_all(), previous)
        view.draw_stage()
        self.assertEqual(view.stage.itemcget(view.stage.find_withtag('target')[0], 'fill'), '#123456')

    def test_table_has_vertical_scroll_and_wheel_does_not_scroll_page(self):
        app = self.open_app(buttons={str(i): {'press': 'Go+'} for i in range(30)})
        table = app.button_table
        body = app.view.mapping_page[2]
        app.notebook.select(1)
        app.view.setup_tabs.select(app.view.mapping_page[1])
        app.root.deiconify()
        app.root.update_idletasks()
        app.view.refresh()
        app.root.update_idletasks()
        self.assertTrue(table.cget('yscrollcommand'))
        self.assertLess(table.yview()[1], 1)
        before = body.scroll_canvas.yview()
        table.event_generate('<MouseWheel>', delta=-120)
        app.root.update_idletasks()
        self.assertGreater(table.yview()[0], 0)
        self.assertEqual(body.scroll_canvas.yview(), before)

    def test_reveal_after_widget_destruction_is_safe(self):
        app = self.open_app()
        body = app.view.field_pages['port'][2]
        widget = app.view.fields['port']
        widget.destroy()
        app.view.reveal(body, widget)

    def test_release_click_confirms_even_while_stopped(self):
        app = self.held_app()
        stream = app.streamer
        with patch.object(app.messagebox, 'askokcancel', return_value=False):
            app.release_button.invoke()
        self.assertIs(app.streamer, stream)
        with patch.object(app.messagebox, 'askokcancel', return_value=True):
            app.release_button.invoke()
        self.assertIsNone(app.streamer)
        self.assertTrue(stream.closed)

    def test_diagnostics_controls_reveal_at_minimum_window_size(self):
        app = self.open_app()
        app.root.geometry('760x660')
        app.root.deiconify()
        app.notebook.select(2)
        app.root.update_idletasks()
        app.view.refresh()
        app.root.update_idletasks()
        body = app.view.diagnostics_page[2]
        app.view.reveal(body, app.test_button)
        top = body.scroll_canvas.canvasy(0)
        y = app.test_button.winfo_rooty() - body.winfo_rooty()
        self.assertGreaterEqual(y, top)
        self.assertLessEqual(y + app.test_button.winfo_height(), top + body.scroll_canvas.winfo_height())
        app.values['initial_zoom'].set('101')
        app.apply_settings()
        self.assertEqual(str(app.view.fields['initial_zoom'].cget('state')), 'disabled')
        self.assertIn('Enable zoom', app.status.get())
        app.root.update_idletasks()

    def test_minimum_window_keeps_footer_visible_and_live_actions_reachable_with_faults(self):
        app = self.held_app()
        app.axes = [0, 0, -1]
        app.values['invert_slider'].set(True)
        app.record_fault('release', 'Release send failed: one\nCheck the held action in onPC.\nAcknowledge in Diagnostics after checking.')
        app.root.geometry('760x660')
        app.root.deiconify()
        for _ in range(3):
            app.root.update_idletasks()
            app.view.refresh()
        root_bottom = app.root.winfo_rooty() + app.root.winfo_height()
        status = next(widget for widget in app.view.footer.master.winfo_children()
                      if widget.winfo_class() == 'TLabel' and str(widget.cget('textvariable')) == str(app.status))
        for widget in (app.save_button, status, app.view.fault):
            self.assertTrue(widget.winfo_ismapped(), str(widget))
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), root_bottom)
        body = app.view.stage.master
        canvas = body.scroll_canvas
        for widget in (app.reset_button, app.release_button):
            widget.focus_force()
            widget.event_generate('<FocusIn>')
            app.root.update_idletasks()
            top = canvas.canvasy(0)
            y = widget.winfo_rooty() - body.winfo_rooty()
            self.assertGreaterEqual(y, top)
            self.assertLessEqual(y + widget.winfo_height(), top + canvas.winfo_height())

    def test_test_help_describes_draft_psn_transport(self):
        app = self.open_app()
        app.values['position_output'].set('psn')
        self.assertIn('PSN', app.view.test_context.get())
        self.assertIn('OSC', app.view.test_context.get())
        app.values['control_mode'].set('pan_tilt')
        self.assertIn('OSC', app.view.test_context.get())
        self.assertNotIn('PSN', app.view.test_context.get())
