# Pan/tilt control mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `control_mode` setting (`marker` default, `pan_tilt`) so the two stick axes can drive the pan and tilt percentages of one grandMA3 fixture group at a speed proportional to deflection, sent over OSC.

**Architecture:** `Settings` gains `control_mode` plus the pan/tilt fields. `Motion` keeps a second state, `pan_tilt` (percent), stepped with the same radial dead zone and `MAX_STEP` cap as the marker. `Controller` branches on `control_mode` to build a `ClearSelection; Group N; Attribute ...` command instead of the marker command or a PSN position. `App` and `FollowspotView` follow the applied mode on Live and the draft mode for which Setup fields are editable.

**Tech Stack:** Python 3.10+ standard library only, Tkinter, `unittest`. Tests run with `./.venv/bin/python` (it has Tk; `python3` does not, so the real-window tests skip there).

**Spec:** `docs/superpowers/specs/2026-10-15-pan-tilt-control-design.md` (read it first; it was independently reviewed and passed).

## Global Constraints

- Python 3.10+, no third-party packages, no new dependencies.
- Output starts stopped. Start sends the displayed pan/tilt, the current slider level and the enabled zoom/iris level.
- No idle resend of OSC output: the pan/tilt `/cmd` is sent only when its command list changes (reset forces one resend).
- `ClearSelection` is the only selection clear; never `ClearAll`. Selection and attributes are separate semicolon-separated commands in one `/cmd` string.
- Pan/tilt limits, initial values and `test_pan_tilt_size` are stored and shown as percent 0-100. Do not add them to `PERCENT_FIELDS` in `followspot_ui.py`.
- Validation does not depend on `control_mode`: marker fields, PSN fields and pan/tilt fields are always validated.
- Every new `SettingsError` lists its field keys, and every new field is registered in the view's `fields`/`field_pages`.
- `settings.example.json` must equal the `Settings` defaults.
- Never overwrite or commit the operator's runtime `settings.json`. Tests use temporary files only.
- Settings changes require stopped output; `control_mode` joins the fields refused while a PSN stream is held.
- Existing marker and PSN tests must keep passing unchanged. Never weaken or skip a test to make it pass.
- No emojis in code, docs or commit messages. Commit messages use Conventional Commits and carry no AI attribution.
- Do not commit unless the operator has asked to land the work. The "Commit" step in each task is performed only on that instruction; otherwise leave changes in the working tree and say so.
- Test command for every task: `./.venv/bin/python -m unittest discover -s tests`. Baseline before this plan: 130 tests, OK, none skipped.

## Review Focus

Failure modes the spec implies; each has a test in the task named:

1. A PSN stream is held and the operator switches to pan/tilt: the app must refuse until Release marker (Task 3).
2. Setup fields disabled for the other mode must stay disabled after Stop, not be re-enabled by the running/stopped toggle (Task 4).
3. An invalid value sits in a field disabled by the draft mode: the error must tell the operator how to reach it (Task 4).
4. Settings saved with `position_output = psn` and then run in pan/tilt must open no PSN stream and show no PSN in the summary (Tasks 3 and 4).
5. A stalled poll (huge `dt`) must move pan/tilt by at most one `MAX_STEP`, and the limits must clamp, not wrap (Task 2).
6. An old `settings.json` without the new keys must load as marker control (Task 1).

---

## Before Task 1

- [ ] **Create the working branch** (the repository is on `main`; this is a large change, so it goes on a branch for a PR).

```bash
cd /Users/huang/joystick-followspot
git switch -c feat/pan-tilt-control
```

Expected: `Switched to a new branch 'feat/pan-tilt-control'`. The untracked spec file travels with the branch.

- [ ] **Confirm the baseline**

Run: `./.venv/bin/python -m unittest discover -s tests`
Expected: `Ran 130 tests ... OK`

---

### Task 1: Settings fields, validation and example file

**Files:**
- Modify: `followspot_core.py:21` (`PSN_FIELDS`), `followspot_core.py:83-88` (new fields after `psn_interface`), `followspot_core.py:157-158` and `:177` (validation)
- Modify: `settings.example.json` (regenerate)
- Test: `tests/test_core.py` (append a class before `if __name__ == '__main__':`)

**Interfaces:**
- Consumes: existing `Settings`, `SettingsError`, `setting_types()`.
- Produces: `Settings.control_mode: str`, `fixture_group: int`, `attribute_pan: str`, `attribute_tilt: str`, `pan_tilt_speed: float`, `pan_min/pan_max/tilt_min/tilt_max: float`, `initial_pan/initial_tilt: float`, `test_pan_tilt_size: float`; `PSN_FIELDS` now also contains `'control_mode'`.

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_core.py`, directly above `if __name__ == '__main__':`:

```python
class PanTiltSettingsTests(unittest.TestCase):
    def test_old_settings_default_to_marker_control(self):
        s = core.Settings.from_dict({'port': 8001})
        self.assertEqual((s.control_mode, s.fixture_group, s.attribute_pan, s.attribute_tilt),
                         ('marker', 1, 'Pan', 'Tilt'))
        self.assertEqual((s.pan_tilt_speed, s.pan_min, s.pan_max, s.tilt_min, s.tilt_max),
                         (25.0, 0.0, 100.0, 0.0, 100.0))
        self.assertEqual((s.initial_pan, s.initial_tilt, s.test_pan_tilt_size), (50.0, 50.0, 10.0))

    def test_invalid_pan_tilt_values_name_their_field(self):
        cases = (({'control_mode': 'zoom'}, 'control_mode'),
                 ({'fixture_group': 0}, 'fixture_group'),
                 ({'fixture_group': 1.5}, 'fixture_group'),
                 ({'attribute_pan': 'Pan Tilt'}, 'attribute_pan'),
                 ({'attribute_tilt': ''}, 'attribute_tilt'),
                 ({'pan_tilt_speed': 0}, 'pan_tilt_speed'),
                 ({'pan_tilt_speed': 1001}, 'pan_tilt_speed'),
                 ({'pan_min': -1}, 'pan_min'),
                 ({'pan_max': 101}, 'pan_max'),
                 ({'pan_min': 60, 'pan_max': 60}, 'pan_min'),
                 ({'pan_min': 60}, 'initial_pan'),
                 ({'tilt_max': 40}, 'initial_tilt'),
                 ({'test_pan_tilt_size': 0}, 'test_pan_tilt_size'),
                 ({'test_pan_tilt_size': 51}, 'test_pan_tilt_size'))
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(core.SettingsError) as caught:
                    core.Settings.from_dict(dict(core.Settings().to_dict(), **changes))
                self.assertIn(field, caught.exception.fields)

    def test_pan_tilt_values_are_validated_even_in_marker_mode(self):
        with self.assertRaises(core.SettingsError):
            core.Settings.from_dict(dict(core.Settings().to_dict(), control_mode='marker', pan_min=60))

    def test_pan_tilt_settings_roundtrip(self):
        s = core.Settings.from_dict(dict(core.Settings().to_dict(), control_mode='pan_tilt', fixture_group=4,
                                         attribute_pan='Pan2', pan_min=10, pan_max=90, initial_pan=20))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            s.save(path)
            self.assertEqual(core.Settings.load(path).to_dict(), s.to_dict())

    def test_control_mode_is_guarded_while_a_psn_stream_is_held(self):
        self.assertIn('control_mode', core.PSN_FIELDS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_core.PanTiltSettingsTests -v`
Expected: FAIL/ERROR (`AttributeError: ... has no attribute 'control_mode'` and `Unknown settings`).

- [ ] **Step 3: Implement**

In `followspot_core.py`, change line 21:

```python
PSN_FIELDS = ('control_mode', 'position_output', 'psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface')
```

Add the fields after `psn_interface: str = '127.0.0.1'` and before `buttons`:

```python
    control_mode: str = 'marker'
    fixture_group: int = 1
    attribute_pan: str = 'Pan'
    attribute_tilt: str = 'Tilt'
    pan_tilt_speed: float = 25.0
    pan_min: float = 0.0
    pan_max: float = 100.0
    tilt_min: float = 0.0
    tilt_max: float = 100.0
    initial_pan: float = 50.0
    initial_tilt: float = 50.0
    test_pan_tilt_size: float = 10.0
```

In `validate`, directly after the `position_output` check (`raise SettingsError('Position output must be osc or psn.', 'position_output')`), add:

```python
        if self.control_mode not in ('marker', 'pan_tilt'):
            raise SettingsError('Control mode must be marker or pan_tilt.', 'control_mode')
        if self.fixture_group < 1:
            raise SettingsError('Fixture group must be positive.', 'fixture_group')
        if not 0 < self.pan_tilt_speed <= 1000:
            raise SettingsError('Pan/tilt speed must be greater than 0 and at most 1000 percentage points/s.', 'pan_tilt_speed')
        for axis in ('pan', 'tilt'):
            lo, hi, initial = getattr(self, f'{axis}_min'), getattr(self, f'{axis}_max'), getattr(self, f'initial_{axis}')
            if not 0 <= lo < hi <= 100 or not lo <= initial <= hi:
                raise SettingsError(f'{axis.capitalize()} limits must be 0-100 with the minimum below the maximum, and contain the initial value.',
                                    f'{axis}_min', f'{axis}_max', f'initial_{axis}')
        if not 0 < self.test_pan_tilt_size <= 50:
            raise SettingsError('Pan/tilt test size must be greater than 0 and at most 50 percentage points.', 'test_pan_tilt_size')
```

Extend the attribute-name loop (`for key in ('attribute_x', 'attribute_y', 'attribute_z'):`) to:

```python
        for key in ('attribute_x', 'attribute_y', 'attribute_z', 'attribute_pan', 'attribute_tilt'):
```

Regenerate the example file so it equals the defaults:

```bash
./.venv/bin/python -c "import followspot_core as c; c.Settings().save('settings.example.json')"
git diff --stat settings.example.json
```

Expected: only added lines (the 12 new keys); no existing line changed. If the diff shows other changes, stop and inspect.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m unittest discover -s tests`
Expected: `OK`, 135 tests (130 + 5), none skipped. In particular `PsnSettingsTests.test_example_file_equals_defaults` passes.

- [ ] **Step 5: Commit (only if the operator has asked to commit)**

```bash
git add followspot_core.py settings.example.json tests/test_core.py
git commit -m "feat(settings): add control mode and pan/tilt settings"
```

---

### Task 2: Pan/tilt motion, command and controller

**Files:**
- Modify: `followspot_core.py` — `Motion.__init__`/`step` (~220-253), new `pan_tilt_commands` and `figure_eight_pan_tilt` (after `marker_commands`/`figure_eight`), `Controller.__init__`, `start`, `_output_position`, `reset_target`, `tick` (~455-567)
- Test: `tests/test_core.py` (new class above `if __name__`)

**Interfaces:**
- Consumes: Task 1 settings fields.
- Produces: `Motion.pan_tilt: list[float]` (`[pan, tilt]`, percent); `pan_tilt_commands(s, pan_tilt) -> list[str]`; `figure_eight_pan_tilt(s, t) -> [pan, tilt]`; `Controller` behaves per `settings.control_mode` and, in `pan_tilt`, needs no `send_position`.

- [ ] **Step 1: Write the failing tests**

Add above `if __name__ == '__main__':` in `tests/test_core.py`:

```python
class PanTiltTests(unittest.TestCase):
    CENTRED = [0, 0, -1]
    HOME = ('ClearSelection; Group 1; Attribute "Pan" At Absolute Percent 50.000000; '
            'Attribute "Tilt" At Absolute Percent 50.000000')

    def settings(self, **changes):
        return core.Settings.from_dict(dict(core.Settings().to_dict(), control_mode='pan_tilt', **changes))

    def controller(self, **changes):
        sent = []
        return core.Controller(self.settings(**changes), lambda a, v: sent.append((a, v))), sent

    def commands(self, sent):
        return [v for a, v in sent if a == '/cmd']

    def test_deflection_sets_pan_tilt_speed_and_centre_holds(self):
        m = core.Motion(self.settings())
        m.step([1, 0, -1], 0.2)
        self.assertAlmostEqual(m.pan_tilt[0], 55)
        self.assertAlmostEqual(m.pan_tilt[1], 50)
        m.step([0.55, 0, -1], 0.2)
        self.assertAlmostEqual(m.pan_tilt[0], 57.5)
        m.step([0.05, 0, -1], 0.2)
        self.assertAlmostEqual(m.pan_tilt[0], 57.5)
        m.step([0, -1, -1], 0.2)
        self.assertAlmostEqual(m.pan_tilt[1], 55)

    def test_inversion_limits_clamp_and_capped_gap(self):
        m = core.Motion(self.settings(invert_x=True))
        m.step([1, 0, -1], 0.2)
        self.assertAlmostEqual(m.pan_tilt[0], 45)
        m = core.Motion(self.settings(pan_max=60, tilt_min=40))
        m.step([1, 0, -1], 10)
        self.assertAlmostEqual(m.pan_tilt[0], 56.25)
        for _ in range(20):
            m.step([1, 0, -1], 0.25)
            m.step([0, 1, -1], 0.25)
        self.assertEqual(m.pan_tilt, [60, 40])

    def test_diagonal_speed_is_capped(self):
        m = core.Motion(self.settings())
        m.step([1, -1, -1], 0.2)
        self.assertAlmostEqual(math.hypot(m.pan_tilt[0] - 50, m.pan_tilt[1] - 50), 5.0)

    def test_each_mode_leaves_the_other_modes_state_alone(self):
        m = core.Motion(self.settings())
        m.step([1, 0, -1], 0.2)
        self.assertEqual(m.xyz, [0.0, 0.0, 1.5])
        m = core.Motion(core.Settings())
        m.step([1, 0, -1], 0.2)
        self.assertEqual(m.pan_tilt, [50.0, 50.0])

    def test_pan_tilt_commands_select_the_group_then_set_percent(self):
        s = self.settings(fixture_group=7)
        self.assertEqual(core.pan_tilt_commands(s, [50, 25.5]),
                         ['ClearSelection', 'Group 7',
                          'Attribute "Pan" At Absolute Percent 50.000000',
                          'Attribute "Tilt" At Absolute Percent 25.500000'])

    def test_pan_tilt_commands_use_attribute_names_and_never_clear_all(self):
        commands = core.pan_tilt_commands(self.settings(attribute_pan='Pan2', attribute_tilt='Tilt2'), [0, 100])
        self.assertIn('Attribute "Pan2" At Absolute Percent 0.000000', commands)
        self.assertIn('Attribute "Tilt2" At Absolute Percent 100.000000', commands)
        self.assertNotIn('ClearAll', ' '.join(commands))

    def test_start_sends_one_group_command_and_suppresses_idle_resends(self):
        c, sent = self.controller()
        c.start(self.CENTRED)
        self.assertEqual(self.commands(sent), [self.HOME])
        c.tick(self.CENTRED, 0.033)
        c.tick(self.CENTRED, 0.033)
        self.assertEqual(len(self.commands(sent)), 1)
        c.tick([1, 0, -1], 0.1)
        self.assertEqual(len(self.commands(sent)), 2)
        self.assertIn('Percent 52.500000', self.commands(sent)[-1])

    def test_needs_no_position_callback_even_when_psn_is_saved(self):
        c, sent = self.controller(position_output='psn')
        c.start(self.CENTRED)
        self.assertEqual(self.commands(sent), [self.HOME])

    def test_stop_then_start_resends_the_displayed_pan_tilt(self):
        c, sent = self.controller()
        c.start(self.CENTRED)
        c.tick([1, 0, -1], 0.2)
        c.stop()
        c.start(self.CENTRED)
        self.assertEqual(self.commands(sent)[-1], '; '.join(core.pan_tilt_commands(c.settings, c.motion.pan_tilt)))
        self.assertIn('Percent 55.000000', self.commands(sent)[-1])

    def test_unlocked_live_reset_resends_home_pan_tilt_and_zoom(self):
        c, sent = self.controller(reset_locked=False, zoom_enabled=True, initial_pan=30, initial_tilt=70)
        c.start([0, 0, -1, 0])
        before = len(self.commands(sent))
        self.assertTrue(c.reset_target())
        self.assertEqual(len(self.commands(sent)), before + 1)
        c.tick([1, 0, -1, 0], 0.2)
        c.motion.zoom_level = 80
        self.assertTrue(c.reset_target())
        self.assertEqual(c.motion.pan_tilt, [30, 70])
        self.assertIn('Percent 30.000000', self.commands(sent)[-1])
        self.assertIn('Percent 70.000000', self.commands(sent)[-1])
        # Sent at start, then again by each of the two forced Reset resends.
        self.assertEqual(sent.count(('/Page1/Fader202', 50.0)), 3)

    def test_locked_live_reset_is_refused_and_stopped_reset_is_local(self):
        c, sent = self.controller()
        c.start(self.CENTRED)
        c.tick([1, 0, -1], 0.2)
        self.assertFalse(c.reset_target())
        self.assertAlmostEqual(c.motion.pan_tilt[0], 55)
        c.stop()
        sent.clear()
        self.assertTrue(c.reset_target())
        self.assertEqual(c.motion.pan_tilt, [50.0, 50.0])
        self.assertEqual(sent, [])

    def test_reset_leaves_the_marker_position_alone(self):
        c, _ = self.controller()
        c.motion.xyz = [3.0, 4.0, 1.5]
        c.reset_target()
        self.assertEqual(c.motion.xyz, [3.0, 4.0, 1.5])

    def test_figure_eight_needs_no_joystick_and_stays_inside_limits(self):
        c, sent = self.controller(pan_min=45, pan_max=55, tilt_min=48, tilt_max=52, test_brightness=40)
        c.start(test=True)
        self.assertEqual(c.motion.pan_tilt, [50.0, 50.0])
        pans, tilts = [], []
        for _ in range(100):
            c.tick((), 0.25)
            pans.append(c.motion.pan_tilt[0])
            tilts.append(c.motion.pan_tilt[1])
        self.assertEqual((min(pans), max(pans)), (45, 55))
        self.assertEqual((min(tilts), max(tilts)), (48, 52))
        self.assertIn(('/Page1/Fader201', 40.0), sent)

    def test_send_failure_stops_output(self):
        def fail(address, value):
            raise OSError('send failed')
        c = core.Controller(self.settings(), fail)
        with self.assertRaises(OSError):
            c.start(self.CENTRED)
        self.assertFalse(c.active)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_core.PanTiltTests -v`
Expected: FAIL/ERROR (`Motion` has no `pan_tilt`; `pan_tilt_commands` undefined).

- [ ] **Step 3: Implement**

In `Motion.__init__` add after `self.xyz = ...`:

```python
        self.pan_tilt = [settings.initial_pan, settings.initial_tilt]
```

In `Motion.step`, replace the block from `radius = math.hypot(x, y)` through `self.xyz[2] = s.z` with:

```python
        radius = math.hypot(x, y)
        pan_tilt = s.control_mode == 'pan_tilt'
        speed = max(0.0, min(1.0, (radius - s.dead_zone) / (1 - s.dead_zone))) * (s.pan_tilt_speed if pan_tilt else s.max_speed)
        if radius and pan_tilt:
            self.pan_tilt[0] = clamp(self.pan_tilt[0] + x / radius * speed * dt, s.pan_min, s.pan_max)
            self.pan_tilt[1] = clamp(self.pan_tilt[1] + y / radius * speed * dt, s.tilt_min, s.tilt_max)
        elif radius:
            self.xyz[0] = clamp(self.xyz[0] + x / radius * speed * dt, s.x_min, s.x_max)
            self.xyz[1] = clamp(self.xyz[1] + y / radius * speed * dt, s.y_min, s.y_max)
        self.xyz[2] = s.z
```

After `figure_eight` add:

```python
def figure_eight_pan_tilt(s, t):
    """Pan/tilt test target: a figure 8 around the initial pan/tilt, kept inside the limits."""
    phase = 2 * math.pi * t / s.test_period
    return [clamp(s.initial_pan + s.test_pan_tilt_size * math.sin(phase), s.pan_min, s.pan_max),
            clamp(s.initial_tilt + s.test_pan_tilt_size / 2 * math.sin(2 * phase), s.tilt_min, s.tilt_max)]
```

After `marker_commands` add:

```python
def pan_tilt_commands(s, pan_tilt):
    # Same shape as marker_commands: ClearSelection isolates the group and keeps programmer values.
    commands = ['ClearSelection', f'Group {s.fixture_group}']
    for attribute, value in zip((s.attribute_pan, s.attribute_tilt), pan_tilt):
        commands.append(f'Attribute "{attribute}" At Absolute Percent {clamp(value, 0, 100):.6f}')
    return commands
```

In `Controller.__init__` change the PSN guard to:

```python
        if settings.control_mode == 'marker' and settings.position_output == 'psn' and send_position is None:
```

In `Controller.start` replace the `if test:` body (`self.motion.xyz = figure_eight(self.settings, 0)`) with `self._set_test_position(0)`.

Add the helper above `_output_position`:

```python
    def _set_test_position(self, t):
        if self.settings.control_mode == 'pan_tilt':
            self.motion.pan_tilt = figure_eight_pan_tilt(self.settings, t)
        else:
            self.motion.xyz = figure_eight(self.settings, t)
```

Replace `_output_position` with:

```python
    def _output_position(self):
        s = self.settings
        if s.control_mode == 'pan_tilt':
            commands = pan_tilt_commands(s, self.motion.pan_tilt)
        elif s.position_output == 'psn':
            # The streamer keeps sending; the selection is never touched.
            self.send_position(tuple(self.motion.xyz))
            return
        else:
            commands = marker_commands(s, self.motion.xyz)
        if commands != self.last_commands:
            # Keep selection and position assignments in one OSC command string.
            # MA does not accept OSC bundles.
            self.send('/cmd', '; '.join(commands))
            self.last_commands = commands
```

In `reset_target` replace `self.motion.xyz = [s.initial_x, s.initial_y, s.z]` with:

```python
        if s.control_mode == 'pan_tilt':
            self.motion.pan_tilt = [s.initial_pan, s.initial_tilt]
        else:
            self.motion.xyz = [s.initial_x, s.initial_y, s.z]
```

In `tick` replace `self.motion.xyz = figure_eight(self.settings, self.test_time)` with `self._set_test_position(self.test_time)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m unittest discover -s tests`
Expected: `OK`, 149 tests (135 + 14), none skipped. All pre-existing marker and PSN tests still pass.

- [ ] **Step 5: Commit (only if the operator has asked to commit)**

```bash
git add followspot_core.py tests/test_core.py
git commit -m "feat(core): drive pan/tilt from the stick over OSC"
```

---

### Task 3: App behaviour in pan/tilt mode

**Files:**
- Modify: `followspot.py` — import (line 13), `begin_learn` (~186), `apply_settings` (~225-255), `start_output` (~283-296), `update_position` (~410-418)
- Modify: `followspot_ui.py` — add `PAN_TILT_AXIS_NAMES` and `axis_name` after `AXIS_NAMES` (line 7-9)
- Test: `tests/test_window.py` (new class after `PsnWindowTests`; imports at the top)

**Interfaces:**
- Consumes: Task 2 `Motion.pan_tilt`, `pan_tilt_commands`, `Controller` pan/tilt behaviour.
- Produces: `followspot_ui.axis_name(key, control_mode) -> str`; `App.apply_settings` carries and clamps both `xyz` and `pan_tilt` and refuses `control_mode` changes while a stream is held; `App.start_output` opens a PSN stream only for `marker` + `psn`; `App.update_position` shows `Pan 50.0%   Tilt 50.0%`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_window.py` change the core import line to:

```python
from followspot_core import ButtonEdges, Controller, Settings, pan_tilt_commands
```

Append after the `PsnWindowTests` class (before `class FakeJoystick`):

```python
class PanTiltWindowTests(unittest.TestCase):
    app = WindowTests.app

    def last_cmd(self, messages):
        return [value for address, value in messages if address == '/cmd'][-1]

    def test_pan_tilt_mode_opens_no_stream_even_with_psn_saved(self):
        app, messages = self.app(control_mode='pan_tilt', position_output='psn')
        app.start_output()
        self.assertTrue(app.controller.active)
        self.assertEqual(self.streamers, [])
        self.assertIsNone(app.streamer)
        self.assertTrue(self.last_cmd(messages).startswith('ClearSelection; Group 1;'))

    def test_control_mode_cannot_change_while_a_stream_is_open(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.values['control_mode'].set('pan_tilt')
        self.assertFalse(app.apply_settings())
        self.assertEqual(app.settings.control_mode, 'marker')
        self.assertIn('control mode', app.faults['settings'])
        app.release_marker()
        self.assertTrue(app.apply_settings())
        self.assertEqual(app.settings.control_mode, 'pan_tilt')

    def test_apply_carries_and_clamps_both_states_across_a_mode_switch(self):
        app, _ = self.app(control_mode='pan_tilt')
        app.controller.motion.pan_tilt = [80.0, 20.0]
        app.controller.motion.xyz = [3.0, 4.0, 1.5]
        app.values['pan_max'].set('60')
        app.values['tilt_min'].set('30')
        self.assertTrue(app.apply_settings())
        self.assertEqual(app.controller.motion.pan_tilt, [60.0, 30.0])
        self.assertEqual(app.controller.motion.xyz, [3.0, 4.0, 1.5])
        app.values['control_mode'].set('marker')
        self.assertTrue(app.apply_settings())
        self.assertEqual(app.controller.motion.pan_tilt, [60.0, 30.0])
        self.assertEqual(app.controller.motion.xyz, [3.0, 4.0, 1.5])

    def test_stop_and_restart_resends_the_displayed_pan_tilt(self):
        app, messages = self.app(control_mode='pan_tilt')
        app.start_output()
        app.controller.tick([1.0, 0, -1], 0.2)
        app.stop_output()
        app.apply_settings()
        app.start_output()
        expected = '; '.join(pan_tilt_commands(app.settings, app.controller.motion.pan_tilt))
        self.assertEqual(self.last_cmd(messages), expected)
        self.assertIn('Percent 55.000000', expected)

    def test_position_text_shows_pan_and_tilt_percent(self):
        app, _ = self.app(control_mode='pan_tilt')
        app.update_position()
        self.assertEqual(app.position_label.get(), 'Pan 50.0%   Tilt 50.0%')

    def test_reset_returns_to_the_initial_pan_tilt(self):
        app, _ = self.app(control_mode='pan_tilt', initial_pan=30.0, initial_tilt=70.0)
        app.controller.motion.pan_tilt = [10.0, 10.0]
        self.assertTrue(app.reset_target())
        self.assertEqual(app.controller.motion.pan_tilt, [30.0, 70.0])
        self.assertIn('Pan 30.0%', app.position_label.get())

    def test_test_mode_traces_pan_and_tilt(self):
        app, messages = self.app(control_mode='pan_tilt')
        app.start_output(test=True)
        self.assertIn('pan and tilt', app.status.get())
        app.controller.tick((), 0.5)
        self.assertGreater(app.controller.motion.pan_tilt[0], 50.0)
        self.assertEqual(len([m for m in messages if m[0] == '/cmd']), 2)

    def test_mapped_release_marker_is_a_no_op_in_pan_tilt(self):
        app, messages = self.app(control_mode='pan_tilt',
                                 buttons={'0': {'action': 'release_marker'}, '1': {'press': 'Down', 'release': 'Up'}})
        app.start_output()
        app.buttons = [False, True, False]
        app.process_input(0.033)
        self.assertEqual(messages[-1], ('/cmd', 'Down'))
        app.buttons = [True, False, False]
        app.process_input(0.033)
        self.assertTrue(app.controller.active)
        self.assertEqual(messages[-1], ('/cmd', 'Up'))
        self.assertFalse(app.release_marker())

    def test_learn_prompt_names_pan_and_tilt_for_the_draft_mode(self):
        app, _ = self.app()
        app.begin_learn('axis_x')
        self.assertIn('left / right control', app.status.get())
        app.learning = None
        app.values['control_mode'].set('pan_tilt')
        app.begin_learn('axis_y')
        self.assertIn('tilt control', app.status.get())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_window.PanTiltWindowTests -v`
Expected: FAIL (no stream guard for `control_mode`, position text is X/Y/Z, `axis_name` missing, a stream would open for psn-saved pan/tilt).

- [ ] **Step 3: Implement**

`followspot_ui.py`, directly after the `AXIS_NAMES` dict add:

```python
PAN_TILT_AXIS_NAMES = {'axis_x': 'pan control (left / right)', 'axis_y': 'tilt control (up / down)'}


def axis_name(key, control_mode):
    """Prompt wording for a learnable control; pan/tilt renames the two stick axes."""
    if control_mode == 'pan_tilt' and key in PAN_TILT_AXIS_NAMES:
        return PAN_TILT_AXIS_NAMES[key]
    return AXIS_NAMES[key]
```

`followspot.py`: change the import to `from followspot_ui import PERCENT_FIELDS, FollowspotView, axis_name, display_value` (`AXIS_NAMES` is no longer used there; check with `rg AXIS_NAMES followspot.py tests` that nothing else references it from outside `followspot_ui.py`).

In `begin_learn` replace the `text = ...` line with:

```python
        text = 'Press the desired button…' if key == 'button' else f'Move only the {axis_name(key, self.values["control_mode"].get())}…'
```

In `apply_settings` change the refusal message to:

```python
                raise SettingsError('Release the PSN marker before changing control mode, position output or PSN settings.', *PSN_FIELDS)
```

After `xyz = self.controller.motion.xyz` add `pan_tilt = self.controller.motion.pan_tilt`, and after the existing `self.controller.motion.xyz = [...]` assignment add:

```python
        self.controller.motion.pan_tilt = [clamp(pan_tilt[0], settings.pan_min, settings.pan_max),
                                           clamp(pan_tilt[1], settings.tilt_min, settings.tilt_max)]
```

In `start_output` replace `if s.position_output == 'psn':` with:

```python
            if s.control_mode == 'marker' and s.position_output == 'psn':
```

and replace the `self.status.set('Test running: ...' if test else ...)` call with:

```python
            marker = s.control_mode == 'marker'
            self.status.set(('Test running: ' + ('the marker traces a figure 8' if marker else 'pan and tilt trace a figure 8') +
                             '; the joystick is ignored. Stop ends it.') if test else
                            'Output running. Centre holds position and zoom/iris. Stop retains tracked levels.')
```

Replace the start of `update_position` (the lines up to and including the `Held at` block, ending before `self.position_label.set(text)`) with:

```python
    def update_position(self):
        if self.settings.control_mode == 'pan_tilt':
            pan, tilt = self.controller.motion.pan_tilt
            text = f'Pan {pan:.1f}%   Tilt {tilt:.1f}%'
        else:
            x, y, z = self.controller.motion.xyz
            text = f'X {x:+.3f} m   Y {y:+.3f} m   Z {z:.3f} m'
            if self.streamer is not None and not self.controller.active:
                hx, hy, hz = self.streamer.position
                text += f'\nHeld at  X {hx:+.3f} m   Y {hy:+.3f} m   Z {hz:.3f} m'
        self.position_label.set(text)
```

(leave the following `self.zoom_label.set(...)` and `self.view.refresh()` lines as they are).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m unittest discover -s tests`
Expected: `OK`, 158 tests (149 + 9), none skipped.

- [ ] **Step 5: Commit (only if the operator has asked to commit)**

```bash
git add followspot.py followspot_ui.py tests/test_window.py
git commit -m "feat(window): run pan/tilt output from the app"
```

---

### Task 4: Setup, Diagnostics and Live views

**Files:**
- Modify: `followspot_ui.py` — constants (top), `__init__` state, `choice`/`build_target`/`build_live`/`build_network` help text/`build_controls` caption keys/`build_diagnostics`, `refresh` (summary, release button, field states), `set_running`, `show_error`, `draw_stage`
- Test: `tests/test_window.py` — add to `RealWindowTests` (these need Tk; they run under `./.venv/bin/python`)

**Interfaces:**
- Consumes: Task 3 `axis_name`, `App.update_position`, Task 1 field names.
- Produces: view constants `MARKER_FIELDS`, `PAN_TILT_FIELDS`, `AXIS_CAPTIONS`; `FollowspotView.apply_field_states()`, `FollowspotView.inapplicable_widgets()`, `FollowspotView.choice(...)`, `FollowspotView.stage_title`.

- [ ] **Step 1: Write the failing tests**

Add these methods inside `RealWindowTests` in `tests/test_window.py` (after `test_setup_is_readable_but_cannot_be_edited_while_running`):

```python
    def test_control_mode_disables_the_other_modes_fields_and_stop_keeps_them_disabled(self):
        app = self.open_app()
        state = lambda key: str(app.view.fields[key]['state'])
        self.assertEqual(state('marker_id'), 'normal')
        self.assertEqual(state('position_output'), 'readonly')
        self.assertEqual(state('pan_min'), 'disabled')
        self.assertEqual(state('control_mode'), 'readonly')
        app.values['control_mode'].set('pan_tilt')
        self.assertEqual(state('marker_id'), 'disabled')
        self.assertEqual(state('max_speed'), 'disabled')
        self.assertEqual(state('test_size'), 'disabled')
        self.assertEqual(state('position_output'), 'disabled')
        self.assertEqual(state('pan_min'), 'normal')
        self.assertEqual(state('test_pan_tilt_size'), 'normal')
        self.assertEqual(state('host'), 'normal')
        app.start_output()
        self.assertEqual(state('pan_min'), 'disabled')
        app.stop_output()
        self.assertEqual(state('marker_id'), 'disabled')
        self.assertEqual(state('pan_min'), 'normal')
        self.assertEqual(state('host'), 'normal')

    def test_axis_captions_follow_the_draft_control_mode(self):
        app = self.open_app()
        caption = app.view.field_captions['axis_x']
        self.assertEqual(str(caption.cget('text')), 'Left / right axis')
        app.values['control_mode'].set('pan_tilt')
        self.assertEqual(str(caption.cget('text')), 'Pan (left / right) axis')
        app.values['control_mode'].set('marker')
        self.assertEqual(str(caption.cget('text')), 'Left / right axis')

    def test_error_in_a_disabled_field_says_how_to_reach_it(self):
        app = self.open_app()
        app.values['control_mode'].set('pan_tilt')
        app.values['marker_id'].set('0')
        self.assertFalse(app.apply_settings())
        self.assertIn('Switch Control to Marker', app.status.get())
        app.values['marker_id'].set('1')
        app.values['pan_min'].set('-5')
        self.assertFalse(app.apply_settings())
        self.assertNotIn('Switch Control', app.status.get())
        app.values['control_mode'].set('marker')
        self.assertFalse(app.apply_settings())
        self.assertIn('Switch Control to Pan-tilt', app.status.get())

    def test_pan_tilt_summary_has_no_psn_and_the_release_button_is_hidden(self):
        app = self.open_app(control_mode='pan_tilt', position_output='psn')
        app.view.refresh()
        self.assertIn('Group 1', app.view.summary.get())
        self.assertNotIn('PSN', app.view.summary.get())
        self.assertNotIn('MArker', app.view.summary.get())
        self.assertFalse(app.release_button.winfo_manager())

    def test_marker_summary_and_release_button_are_unchanged(self):
        app = self.open_app(position_output='psn')
        app.view.refresh()
        self.assertIn('MArker 1', app.view.summary.get())
        self.assertIn('PSN', app.view.summary.get())
        self.assertTrue(app.release_button.winfo_manager())

    def test_live_view_draws_a_pan_tilt_square(self):
        app = self.open_app(control_mode='pan_tilt', pan_min=10.0, pan_max=90.0)
        app.update_position()
        self.assertEqual(app.position_label.get(), 'Pan 50.0%   Tilt 50.0%')
        self.assertEqual(app.view.stage_title.get(), 'Pan / tilt')
        canvas = app.view.stage
        texts = [canvas.itemcget(item, 'text') for item in canvas.find_all() if canvas.type(item) == 'text']
        self.assertIn('Tilt 100%', texts)
        self.assertIn('Pan\n10%', texts)
        self.assertTrue(canvas.find_withtag('target'))
        self.assertFalse(canvas.find_withtag('held'))

    def test_marker_live_view_keeps_its_title_and_labels(self):
        app = self.open_app()
        app.update_position()
        self.assertEqual(app.view.stage_title.get(), 'Tracked target · top view')
        canvas = app.view.stage
        texts = [canvas.itemcget(item, 'text') for item in canvas.find_all() if canvas.type(item) == 'text']
        self.assertIn('Y 10 m', texts)
        self.assertIn('X\n-10 m', texts)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m unittest tests.test_window.RealWindowTests -v 2>&1 | tail -30`
Expected: the new tests FAIL (`KeyError: 'control_mode'` in `view.fields`, etc.). If every real-window test reports `skipped` (Tk or a window is unavailable in this environment), stop: report that the view task cannot be verified here and ask the operator to run it from a normal macOS Terminal. Do not claim it passes.

- [ ] **Step 3: Implement**

**Constants** — in `followspot_ui.py`, after `axis_name`, add:

```python
AXIS_CAPTIONS = {'axis_x': ('Left / right axis', 'Pan (left / right) axis'),
                 'axis_y': ('Upstage / downstage axis', 'Tilt (up / down) axis')}
MARKER_FIELDS = ('marker_id', 'z', 'x_min', 'x_max', 'y_min', 'y_max', 'initial_x', 'initial_y',
                 'space_x_min', 'space_x_max', 'space_y_min', 'space_y_max', 'space_z_min', 'space_z_max',
                 'attribute_x', 'attribute_y', 'attribute_z', 'max_speed', 'position_output',
                 'psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface', 'test_size')
PAN_TILT_FIELDS = ('fixture_group', 'attribute_pan', 'attribute_tilt', 'pan_tilt_speed', 'pan_min', 'pan_max',
                   'tilt_min', 'tilt_max', 'initial_pan', 'initial_tilt', 'test_pan_tilt_size')
```

**`__init__`** — after `self.editing_state = tk.StringVar()` add:

```python
        self.stage_title = tk.StringVar()
        # Last state/text applied per widget, so refresh (every poll) only touches Tk on a change.
        self.field_states, self.caption_texts = {}, {}
```

**`choice` helper** — add below `entry`:

```python
    def choice(self, parent, row, label, key, values):
        caption = self.ttk.Label(parent, text=label)
        caption.grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
        self.field_captions[key] = caption
        box = self.edit(self.ttk.Combobox(parent, textvariable=self.app.values[key], values=values,
                                          state='readonly', width=10), 'readonly')
        box.grid(row=row, column=1, sticky='w', pady=5)
        self.fields[key] = box
        self.field_labels[key] = label
        self.field_pages[key] = self.current_page
        return box
```

**`build_live`** — replace `ttk.Label(live, text='Tracked target · top view').grid(...)` with:

```python
        ttk.Label(live, textvariable=self.stage_title).grid(row=0, column=0, sticky='w', pady=(0, 8))
```

**`build_target`** — replace the whole method with:

```python
    def build_target(self, parent):
        self.choice(parent, 0, 'Control', 'control_mode', ['marker', 'pan_tilt'])
        self.label(parent, text='marker moves one MArker and onPC aims the fixtures at it. pan_tilt drives the pan and tilt of one fixture group directly, over OSC only.').grid(row=1, column=0, columnspan=4, sticky='w', pady=(0, 8))
        self.entry(parent, 2, 'MArker CID', 'marker_id')
        self.entry(parent, 3, 'Z height (m)', 'z')
        self.ttk.Label(parent, text='Operating limits and initial target (m)').grid(row=4, column=0, columnspan=4, sticky='w', pady=(12, 4))
        for row, (key, label) in enumerate([('x_min', 'X minimum'), ('x_max', 'X maximum'),
                                          ('y_min', 'Y minimum'), ('y_max', 'Y maximum'),
                                          ('initial_x', 'Initial / reset X'), ('initial_y', 'Initial / reset Y')], 5):
            self.entry(parent, row, label, key)
        self.ttk.Label(parent, text='MArker movement space (m) · match onPC').grid(row=11, column=0, columnspan=4, sticky='w', pady=(12, 4))
        for row, axis in enumerate('xyz', 12):
            self.entry(parent, row, axis.upper() + ' minimum', f'space_{axis}_min', width=12)
            caption = self.ttk.Label(parent, text='Maximum')
            caption.grid(row=row, column=2, padx=12)
            key = f'space_{axis}_max'
            widget = self.edit(self.ttk.Entry(parent, textvariable=self.app.values[key], width=12))
            widget.grid(row=row, column=3, sticky='w')
            self.fields[key], self.field_pages[key] = widget, self.current_page
            self.field_labels[key] = axis.upper() + ' movement space maximum'
            self.field_captions[key] = caption
        self.label(parent, text='Operating limits fit inside the movement space. Defaults are examples; confirm the actual movement space in onPC.').grid(row=15, column=0, columnspan=4, sticky='w', pady=12)
        self.ttk.Label(parent, text='Pan / tilt (% of the fixture range)', font=self.state_font).grid(row=16, column=0, columnspan=4, sticky='w', pady=(20, 4))
        self.entry(parent, 17, 'Fixture group', 'fixture_group')
        self.entry(parent, 18, 'Pan attribute', 'attribute_pan')
        self.entry(parent, 19, 'Tilt attribute', 'attribute_tilt')
        self.entry(parent, 20, 'Maximum speed (% points/s)', 'pan_tilt_speed')
        for row, (key, label) in enumerate([('pan_min', 'Pan minimum (%)'), ('pan_max', 'Pan maximum (%)'),
                                          ('tilt_min', 'Tilt minimum (%)'), ('tilt_max', 'Tilt maximum (%)'),
                                          ('initial_pan', 'Initial / reset pan (%)'), ('initial_tilt', 'Initial / reset tilt (%)')], 21):
            self.entry(parent, row, label, key)
        self.label(parent, text='Pan/tilt output selects the group, then sets Pan and Tilt as absolute percent, so it takes the console selection while output runs. Limits keep the lights inside a safe range. Confirm the attribute names with List Attribute in onPC.').grid(row=27, column=0, columnspan=4, sticky='w', pady=12)
```

**`build_network`** — append to the help text of the Position output explanation (the `self.label(... 'osc moves the MArker with commands ...')` line) the sentence ` Position output applies to Marker control only; Pan-tilt control always uses OSC.` (place it at the end of the existing string, before the closing quote).

**`build_diagnostics`** — replace the figure-8 field loop, the test button and the following labels so the rows read:

```python
        for row, (key, label) in enumerate([('test_size', 'Figure 8 half-width, marker (m)'),
                                            ('test_pan_tilt_size', 'Figure 8 half-swing, pan/tilt (% points)'),
                                            ('test_period', 'Seconds per lap'),
                                            ('test_brightness', 'Test brightness (%)')], 4):
            self.entry(parent, row, label, key)
        app.test_button = ttk.Button(parent, text='Start test (figure 8)', command=lambda: app.start_output(test=True))
        app.test_button.grid(row=8, column=0, sticky='w', pady=8)
        self.label(parent, text='No joystick needed. Sends OSC around the initial target (marker or pan/tilt, per the applied control mode) at the test brightness; joystick input is ignored. Use Stop output above to end the test.').grid(row=9, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Label(parent, text='OSC reception', font=self.state_font).grid(row=10, column=0, columnspan=3, sticky='w', pady=(20, 8))
        self.label(parent, text='UDP send success does not confirm reception. In onPC, use EchoInput and System Monitor to check incoming commands. Check Input, Receive, Receive Command, Interface/IP, port and prefix.').grid(row=11, column=0, columnspan=3, sticky='w')
```

(these replace the old figure-8 field loop, test button and the two labels after it in `build_diagnostics`; the lines above the loop, from `Input monitor` through the `Figure 8 test · sends real output` heading, stay unchanged.)

**Field states** — add these methods to `FollowspotView` (next to `set_running`), and replace `set_running`:

```python
    def inapplicable_widgets(self):
        """Editors that belong to the other control mode, from the draft selector (not the parsed draft)."""
        mode = self.app.values['control_mode'].get()
        keys = PAN_TILT_FIELDS if mode == 'marker' else MARKER_FIELDS if mode == 'pan_tilt' else ()
        return {self.fields[key] for key in keys if key in self.fields}

    def apply_field_states(self):
        """Disabled = output running, or the field belongs to the other control mode."""
        running = self.app.controller.active
        inapplicable = self.inapplicable_widgets()
        for widget, base in self.editable:
            state = 'disabled' if running or widget in inapplicable else base
            if self.field_states.get(widget) != state:
                widget.configure(state=state)
                self.field_states[widget] = state
        index = 1 if self.app.values['control_mode'].get() == 'pan_tilt' else 0
        for key, texts in AXIS_CAPTIONS.items():
            if self.caption_texts.get(key) != texts[index]:
                self.field_captions[key].configure(text=texts[index])
                self.caption_texts[key] = texts[index]

    def set_running(self, running):
        # refresh() recomputes every editor's state from controller.active and the draft mode.
        self.app.update_button_editor()
        self.refresh()
```

**`refresh`** — directly after `self.resize()` add `self.apply_field_states()`. Replace the summary block (from `s = app.settings` through the `self.summary.set(...)` statement) with:

```python
        s = app.settings
        pan_tilt = s.control_mode == 'pan_tilt'
        target = f'Group {s.fixture_group} pan/tilt' if pan_tilt else f'MArker {s.marker_id}'
        self.summary.set(f'{s.device_name or "No saved joystick"}  ·  {target}  ·  OSC {s.host}:{s.port}' +
                         (f' /{s.prefix}' if s.prefix else '') +
                         (f'  ·  PSN tracker {s.psn_tracker_id} → {s.psn_group}:{s.psn_port} via {s.psn_interface}'
                          if not pan_tilt and s.position_output == 'psn' else ''))
        self.stage_title.set('Pan / tilt' if pan_tilt else 'Tracked target · top view')
```

and change the release-button condition from `if s.position_output == 'psn' or app.streamer is not None:` to:

```python
        if (s.control_mode == 'marker' and s.position_output == 'psn') or app.streamer is not None:
```

**`show_error`** — replace the final two statements (`label = self.field_labels.get(key, 'Button mapping')` and the `self.app.status.set(...)`) with:

```python
            label = self.field_labels.get(key, 'Button mapping')
            text = f'{label}: {error}'
            if key and self.fields[key] in self.inapplicable_widgets():
                text += f' Switch Control to {"Pan-tilt" if key in PAN_TILT_FIELDS else "Marker"} to correct it.'
            self.app.status.set(text)
```

**`draw_stage`** — replace the method with:

```python
    def draw_stage(self):
        canvas, s = self.stage, self.app.settings
        pan_tilt = s.control_mode == 'pan_tilt'
        if pan_tilt:
            x_min, x_max, y_min, y_max = s.pan_min, s.pan_max, s.tilt_min, s.tilt_max
            x_name, y_name, unit = 'Pan', 'Tilt', '%'
            x, y = self.app.controller.motion.pan_tilt
        else:
            x_min, x_max, y_min, y_max = s.x_min, s.x_max, s.y_min, s.y_max
            x_name, y_name, unit = 'X', 'Y', ' m'
            x, y, _ = self.app.controller.motion.xyz
        width, height = max(160, canvas.winfo_width()), max(130, canvas.winfo_height())
        scale = min((width - 90) / (x_max - x_min), (height - 65) / (y_max - y_min))
        stage_width, stage_height = (x_max - x_min) * scale, (y_max - y_min) * scale
        left, top = (width - stage_width) / 2, (height - stage_height) / 2
        right, bottom = left + stage_width, top + stage_height
        canvas.delete('all')
        color = self.foreground
        canvas.create_rectangle(left, top, right, bottom, outline=color, tags='limits')
        canvas.create_text((left+right)/2, top-14, text=f'{y_name} {y_max:g}{unit}', fill=color)
        canvas.create_text((left+right)/2, bottom+14, text=f'{y_name} {y_min:g}{unit}', fill=color)
        canvas.create_text(left-8, (top+bottom)/2, text=f'{x_name}\n{x_min:g}{unit}', anchor='e', fill=color)
        canvas.create_text(right+8, (top+bottom)/2, text=f'{x_name}\n{x_max:g}{unit}', anchor='w', fill=color)
        px = left + (clamp(x, x_min, x_max) - x_min) * scale
        py = bottom - (clamp(y, y_min, y_max) - y_min) * scale
        canvas.create_oval(px-5, py-5, px+5, py+5, fill=color, outline=color, tags='target')
        if not pan_tilt and self.app.streamer is not None and not self.app.controller.active:
            hx, hy, _ = self.app.streamer.position
            hpx = left + (clamp(hx, x_min, x_max) - x_min) * scale
            hpy = bottom - (clamp(hy, y_min, y_max) - y_min) * scale
            canvas.create_oval(hpx-8, hpy-8, hpx+8, hpy+8, outline=color, dash=(3, 2), tags='held')
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m unittest discover -s tests`
Expected: `OK`, 165 tests (158 + 7), none skipped. In particular the existing `test_setup_is_readable_but_cannot_be_edited_while_running` and all PSN window tests still pass.

Then run the visible-window startup test in isolation to confirm the real backend still starts:

Run: `./.venv/bin/python -m unittest tests.test_window.RealWindowTests.test_visible_window_with_real_backend_starts_and_polls_without_aborting -v`
Expected: `ok` (or `skipped` with a Tk/window reason; report which).

- [ ] **Step 5: Commit (only if the operator has asked to commit)**

```bash
git add followspot_ui.py tests/test_window.py
git commit -m "feat(ui): add control selector, pan/tilt fields and live preview"
```

---

### Task 5: Documentation and agent guide

**Files:**
- Modify: `README.md`, `docs/OPERATING.md`, `docs/GRANDMA3_SETUP.md`, `docs/PSN.md`, `AGENTS.md`

Documentation changes need no new tests. Keep each fact in one place and link rather than duplicate.

- [ ] **Step 1: README.md**

Replace the first paragraph's second sentence group and the "All physical fixture assignment" line. Change:

`The stick moves one virtual MArker across X/Y: further deflection means faster movement; releasing it holds the position.`

to:

`The stick moves one virtual MArker across X/Y, or optionally drives the pan and tilt of one fixture group directly: further deflection means faster movement; releasing it holds the position.`

Change `All physical fixture assignment and XYZ aiming stay in grandMA3. This tool does not calculate pan/tilt or manage a fixture list.` to:

`All physical fixture assignment and aiming stay in grandMA3. This tool does not compute aim from stage geometry or manage a fixture list; in pan/tilt mode it only integrates the stick into pan and tilt percentages.`

In the documentation table, append to the OPERATING.md row's contents: `, marker or pan/tilt control` (after "Joystick configuration").

- [ ] **Step 2: docs/OPERATING.md**

Add a new section after "Configure the joystick" (before "## Buttons"):

```markdown
## Control mode: marker or pan/tilt

**Setup → Target / stage → Control** chooses what the stick drives. The choice applies when you click **Save settings** (or Start).

- **marker** (default): the stick moves one MArker; onPC aims the fixtures at it. Position output (OSC or PSN, Setup → OSC) applies to this mode only.
- **pan_tilt**: the X axis drives pan and the Y axis drives tilt of one fixture group, as a percentage of the fixture's range. Deflection sets the speed in percentage points per second (**Maximum speed**, default 25, so full deflection crosses the range in about 4 seconds); the centre dead zone, calibration and inversion are the same as for the marker. Centre holds the current value. Pan and tilt stop at their **minimum / maximum** limits (default 0-100). **Initial / reset pan / tilt** (default 50) are where output starts and what Reset returns to. If the lights tilt the wrong way, tick **Invert** beside the Y axis.

Pan/tilt output is OSC only. Each change sends `ClearSelection; Group <n>; Attribute "Pan" At Absolute Percent <p>; Attribute "Tilt" At Absolute Percent <t>`, so it takes the console selection while output runs, as the OSC marker does. See [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md#optional-pantilt-control) for the group and attribute setup. Fields that belong to the other mode are greyed out; if a save reports an error in a greyed field, switch Control back to correct it. The figure 8 test in Diagnostics uses **half-swing, pan/tilt** in this mode (tilt swings half as far). Brightness, zoom / iris and buttons behave the same in both modes. The marker's position and the pan/tilt values are both kept when you switch, and Release marker does nothing in pan/tilt mode.

Pan/tilt mode has not been confirmed on a real console yet; see the checklist in the setup guide.
```

In "## Settings file", add after the sentence about the five position-output settings: `The control mode adds twelve more (control_mode, fixture_group, attribute_pan, attribute_tilt, pan_tilt_speed, pan_min, pan_max, tilt_min, tilt_max, initial_pan, initial_tilt, test_pan_tilt_size); a missing one takes its default (marker control). A settings file saved by this version is refused by an older checkout, which rejects unknown settings.`

In "## Limitations", add a bullet: `- Pan/tilt control sends the group selection with every change, so, like the OSC marker, it takes the console selection while output runs and the encoders are expected to be unusable; this is inferred from the marker behaviour and not yet observed. Percent maps to the fixture's full pan/tilt range as MA defines it for the attribute.`

- [ ] **Step 3: docs/GRANDMA3_SETUP.md**

Insert before "## References":

```markdown
## Optional: pan/tilt control

Use this instead of Steps 2-5 when you want the stick to drive pan and tilt directly rather than a MArker. Brightness (Step 6), OSC (Step 8) and the optional zoom / iris executor are still needed.

1. Make a group that contains exactly the fixtures to move, and note its number (for example Group 1). All fixtures in the group receive the same pan and tilt percentage.
2. Run `List Attribute` and confirm the pan and tilt attribute names in your fixture library (normally `Pan` and `Tilt`).
3. In the tool, open **Setup → Target / stage**, set **Control** to `pan_tilt`, and enter the **Fixture group**, the attribute names, the pan/tilt limits and the initial pan / tilt. Click **Save settings**.
4. Run the figure 8 test (Step 10). In pan/tilt mode the lights should swing in a small figure 8 around the initial pan / tilt, within the limits.
5. Connect the joystick (Step 11). Pushing the stick right should increase pan and pushing it forward should increase tilt; tick **Invert** beside an axis if a direction is wrong.

Each update sends `ClearSelection; Group <n>; Attribute "Pan" At Absolute Percent <p>; Attribute "Tilt" At Absolute Percent <t>`. The installed MA 2.5 files support the pieces: `resource/attribute_definitions.xml` defines `Pan` and `Tilt` with a physical (degree) readout, which is why the command uses `At Absolute Percent`; the system tests use `Attribute 'Pan' At Relative Percent 10` and select a group by name followed by a semicolon. That OSC accepts this exact string and moves the lights is **not yet confirmed**.

Check on a test show, and tell the maintainers what you see: the lights move; 0-100% covers the fixture's full pan/tilt range; the default tilt direction; what happens to fixtures that were following a MArker when you switch modes; and whether the encoder wheels really are unusable while output runs.
```

- [ ] **Step 4: docs/PSN.md**

Add one sentence at the end of the Status paragraph (line 3): `PSN applies only to the marker control mode; pan/tilt control (Setup → Target / stage → Control) is OSC only and opens no PSN stream.`

- [ ] **Step 5: AGENTS.md**

Make these exact edits.

1. Replace the bullet `- The target is one moving grandMA3 **MArker**. Z is a configurable fixed height.` with:

```markdown
- In control mode `marker` (default) the target is one moving grandMA3
  **MArker**; Z is a configurable fixed height. In control mode `pan_tilt`
  the same two stick axes instead drive the pan and tilt percentages of one
  fixture group (OSC only).
```

2. Replace the line `  XYZ aiming. The script does not compute pan/tilt or maintain a fixture list.` (two leading spaces; it is the second line of the bullet that starts `- grandMA3 manages physical fixtures`) with:

```markdown
  XYZ aiming. The script does not compute aim from geometry or maintain a fixture
  list; pan/tilt mode only integrates the stick into pan/tilt percentages.
```

3. In the Code map table, extend the `followspot_core.py` row's responsibility with `, pan/tilt motion and group command` and the `followspot_ui.py` row's with `, control-mode field states`.

4. Insert this contract before the line beginning `- Test mode (`Controller.start(test=True)`)`:

```markdown
- Control mode (`control_mode` = `marker` default or `pan_tilt`). `pan_tilt` is
  OSC only: `Controller` sends `ClearSelection; Group <fixture_group>; Attribute
  "Pan" At Absolute Percent <p>; Attribute "Tilt" At Absolute Percent <t>` only
  when the values change (no idle resend; Reset forces one resend), needs no
  `send_position`, and no `PsnStreamer` is created. `Motion.pan_tilt` (percent,
  clamped to `pan_min/max`, `tilt_min/max`) and `Motion.xyz` are both kept; only
  the active mode is stepped, and Save/apply carries and clamps both. `axis_x`
  drives pan and `axis_y` tilt with the existing centre, dead zone and inversion;
  speed is `pan_tilt_speed` percentage points per second with the same
  `MAX_STEP` cap. `position_output` and the `psn_*` fields are saved and
  validated but ignored in this mode, and validation never depends on the mode.
  `control_mode` is in `PSN_FIELDS`, so it cannot change while a PSN stream is
  held. In Setup the draft selector (`app.values['control_mode']`) decides which
  editors are enabled (`FollowspotView.apply_field_states`, recomputed in
  `refresh`, never stored as the widget's base state); Live follows the applied
  settings.
```

5. In "Handoff status and change workflow", add a paragraph after the "Added since then" paragraph:

```markdown
Pan/tilt control mode was added on 2026-10-15 (branch `feat/pan-tilt-control`)
and is covered by automated tests only. Not verified: that onPC accepts the
`Group <n>; Attribute "Pan"/"Tilt" At Absolute Percent` command over OSC and
moves the lights, that 0-100% spans the full fixture range, the default tilt
direction, how fixtures that followed a MArker behave after a mode switch, and
the Setup / Live layout in the real window. See docs/GRANDMA3_SETUP.md,
Optional: pan/tilt control, for the operator checklist.
```

- [ ] **Step 6: Verify**

Run each and report the actual output:

```bash
./.venv/bin/python -m unittest discover -s tests
./.venv/bin/python followspot.py --settings settings.example.json --check-settings
git diff --check
rg -n "AXIS_NAMES" followspot.py
git status --short
```

Expected: `OK` with 165 tests; `Settings valid: settings.example.json`; no `git diff --check` output; no `AXIS_NAMES` match in `followspot.py`; only the intended files modified, `settings.json` absent from the list.

- [ ] **Step 7: Commit (only if the operator has asked to commit)**

```bash
git add README.md docs/OPERATING.md docs/GRANDMA3_SETUP.md docs/PSN.md AGENTS.md
git commit -m "docs: document pan/tilt control mode"
```

---

## Final verification and handoff

- [ ] Run `./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5` and report the actual counts.
- [ ] Also run the suite with `python3 -m unittest discover -s tests` and report that the real-window tests skip there (no Tk), separately from code results.
- [ ] State plainly what was **not** verified: OSC acceptance and fixture movement in onPC, the full pan/tilt range mapping, tilt direction, the real-window layout on screen, the Windows launcher.
- [ ] If the operator wants the work landed: open a PR from `feat/pan-tilt-control` (large change), with the verification evidence above; do not push without being asked.
