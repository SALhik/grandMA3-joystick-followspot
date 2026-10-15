# Pan/tilt control mode: design

Date: 2026-10-15. Status: draft for operator review, revised after an independent review.

## Goal

Add a second way to control the lights. Today the stick moves one MArker in stage space and grandMA3 aims the fixtures at it. The new **pan/tilt** mode drives the pan and tilt attributes of a fixture group directly from the same two stick axes. Stick deflection sets speed, as for the marker: a large push moves fast, a small push moves slowly, and centre holds the current value.

"Calculate the necessary pan and tilt values" means integrating the stick into pan/tilt percentages, not computing aim from a stage position. The script still has no fixture list or geometry, and grandMA3 still owns physical aiming.

## Requirement changes (requested by the operator; confirmed together with this spec)

AGENTS.md currently says "The target is one moving grandMA3 MArker" and "the script does not compute pan/tilt", and its `/cmd` contract describes only `MArker`. This feature amends those lines with the operator's approval. The amended wording is: the target is either one moving MArker (control mode `marker`) or the pan/tilt of one fixture group (`pan_tilt`); the script still does not compute aim from geometry; the position `/cmd` contract gains the group form below. Also updated: the Purpose bullets, the Code map and the Integration contracts (control mode, Reset, Start) in AGENTS.md, and a line in docs/PSN.md that PSN applies only in marker mode.

## Scope

In scope: a `control_mode` setting, pan/tilt motion, the OSC command, controller and window changes, tests, and documentation.

Out of scope: pan/tilt over PSN (PSN carries a position only), per-fixture pan/tilt, computing aim from geometry, driving pan/tilt without taking the selection, changes to brightness, zoom/iris or buttons.

## Settings

All new fields have defaults, so existing `settings.json` files load unchanged as `marker`. `settings.example.json` must equal the `Settings` defaults. A file saved by the new version is refused by an older checkout, because `Settings.from_dict` rejects unknown keys; that is accepted and noted in the docs.

| Field | Default | Validation |
| --- | --- | --- |
| `control_mode` | `marker` | `marker` or `pan_tilt` |
| `fixture_group` | 1 | integer, positive (grandMA3 group number) |
| `attribute_pan` | `Pan` | MA attribute library name (same pattern as `attribute_x`) |
| `attribute_tilt` | `Tilt` | same |
| `pan_tilt_speed` | 25.0 | greater than 0, at most 1000 (percentage points per second) |
| `pan_min`, `pan_max` | 0.0, 100.0 | within 0-100, min below max |
| `tilt_min`, `tilt_max` | 0.0, 100.0 | within 0-100, min below max |
| `initial_pan`, `initial_tilt` | 50.0 | inside its own min/max |
| `test_pan_tilt_size` | 10.0 | greater than 0, at most 50 (percentage points) |

Rules:

- `position_output` and the `psn_*` fields are unchanged and apply only when `control_mode` is `marker`. In `pan_tilt` mode they are ignored but still saved and validated, so switching back keeps the PSN choice.
- Validation does not change with the mode: the marker fields (limits, Movement Space, `marker_id`, Z) must stay valid even when unused, as in PSN mode, so switching modes never turns a saved file invalid.
- Pan/tilt limits, initial values and `test_pan_tilt_size` are stored and displayed as percent (0-100). They are not added to `PERCENT_FIELDS` in `followspot_ui.py`, which converts fractions to percent for the dead zones only.
- Every new `SettingsError` lists the offending field keys, and every new field is registered in the view's `fields` and `field_pages`, so field-error navigation works.
- `fixture_group` is used instead of a pan-prefixed name to avoid confusion with `psn_group`, the multicast address.

## Behavior

**Axes and motion.** `axis_x` drives pan and `axis_y` drives tilt, with the existing centre, dead zone and inversion settings (`centre_x/y`, `dead_zone`, `invert_x/y`). The radial dead zone and proportional speed work as in marker mode, with `pan_tilt_speed` in place of `max_speed`; diagonal speed is capped. `Motion.pan_tilt` holds `[pan, tilt]` in percent and clamps at the pan/tilt limits (no wraparound). The same `MAX_STEP` cap applies to a long sample gap. Z, `max_speed` and the marker limits are not used in this mode. Tilt direction follows `invert_y` (default true, so pushing forward increases tilt); the operator inverts it if their fixtures move the other way. `Motion` keeps both `xyz` and `pan_tilt`; only the active mode's state is stepped.

**Output.** One OSC `/cmd` string, sent only when the values change, with no idle resend (the same rule as the marker):

```text
ClearSelection; Group 1; Attribute "Pan" At Absolute Percent 50.000000; Attribute "Tilt" At Absolute Percent 50.000000
```

`ClearSelection` is the only selection clear (never `ClearAll`), and the selection and the attributes are separate semicolon-separated commands. This copies the form of the MArker command, whose separator fix is covered by regression tests but whose movement is still awaiting operator confirmation (see the AGENTS.md handoff status). Evidence from the installed MA 2.5 files (root `~/MALightingTechnology/gma3_2.5.0/shared/`) supports the pieces: `resource/attribute_definitions.xml` defines `Pan` and `Tilt` with a physical readout (degrees), so the explicit `At Absolute Percent` is needed; `resource/lib_plugins/systemtests/db/system_test_cue_update.lua` uses `Attribute 'Pan' At Relative Percent 10`; `resource/lib_plugins/systemtests/db/system_test_prog_readout.lua` uses `group "DIM"; At Absolute PercentFine 0`, a group selected by name and followed by a semicolon (not `Group 1`). None of these proves that OSC accepts this exact string. As with the marker over OSC, each update is expected to retake the console selection, which is why the encoders are expected to be unusable while output runs; this is inferred from the marker behavior, not observed for pan/tilt. Brightness, zoom/iris and buttons are unchanged and stay on OSC.

**Lifecycle.**

- *Start* sends the displayed pan/tilt, the current slider level and the enabled zoom/iris level.
- *Stop* retains pan/tilt, xyz and brightness and releases buttons as before.
- *Save/apply* carries both `xyz` and `pan_tilt` across, each clamped to its own new limits, so a mode switch loses nothing.
- *Reset* in `pan_tilt` mode sets pan/tilt to `initial_pan`/`initial_tilt` and zoom/iris to `initial_zoom`, and leaves `xyz` untouched (marker-mode Reset likewise leaves pan/tilt untouched). Unlocked live Reset forces a resend of pan/tilt even when already at home, and of the enabled zoom/iris level, like the marker. A locked Reset while running is refused, and a mapped Reset skips pan/tilt and zoom integration for that sample.
- *Test mode* runs a figure 8 around the initial pan/tilt: pan swings by `test_pan_tilt_size`, tilt by half of it (the same 2:1 shape as the existing figure 8), over `test_period`, clamped to the limits, at `test_brightness`.
- Failures stop output exactly as in the existing contracts.

**PSN interaction.** No `PsnStreamer` is created in `pan_tilt` mode and `Controller` needs no position callback. `control_mode` joins the fields that `apply_settings` refuses to change while a PSN stream is held (the guard tuple gains it, and the message names the control mode), so the operator cannot switch to pan/tilt while onPC is still being fed a marker stream; they press Release marker first. The `release_marker` button action does nothing with no stream open, so it is a no-op in `pan_tilt` mode.

## Window

Which mode decides what: the **draft** Control selector decides which Setup fields are editable; the **applied** `settings.control_mode` decides everything on Live (preview, position text, summary, Release marker button), matching how Live uses applied settings today.

**Setup.** The **Control** selector (Marker / Pan-tilt) sits at the top of the **Target / stage** tab. That tab also gets a new **Pan / tilt** section below the marker fields, holding `fixture_group`, `attribute_pan`, `attribute_tilt`, `pan_tilt_speed`, the limits and the initial values. The existing Position output selector and PSN fields stay on the **OSC** tab, where they are, and apply to Marker only; there is no output choice for Pan-tilt, because pan/tilt is OSC only (the OSC tab's help text says so).

The field sets are explicit:

- *Marker-only:* `marker_id`, `z`, `x_min`, `x_max`, `y_min`, `y_max`, `initial_x`, `initial_y`, `space_*`, `attribute_x/y/z`, `max_speed`, `position_output`, the `psn_*` fields and `test_size`.
- *Pan/tilt-only:* `fixture_group`, `attribute_pan`, `attribute_tilt`, `pan_tilt_speed`, `pan_min/max`, `tilt_min/max`, `initial_pan`, `initial_tilt` and `test_pan_tilt_size`.
- Everything else (joystick, brightness, zoom/iris, OSC host/port/prefix, `test_period`, `test_brightness`, buttons) applies to both.

Fields not applicable to the draft control mode are disabled, not hidden. This covers the Diagnostics test fields too (`test_size` vs `test_pan_tilt_size`) and `max_speed` on the Joystick tab. The learn prompt and axis captions (`AXIS_NAMES`) follow the draft mode, like the other Setup input previews.

The disabled state is "running, or not applicable to the draft control mode", recomputed in `refresh()`. The draft mode is read directly from `app.values['control_mode'].get()`, not from the parsed draft `Settings`, which is `None` whenever any unrelated field fails to parse. The state is not stored as the widget's base state in `edit()`, because `set_running` restores that base state on Stop and would re-enable the fields. Because `refresh()` runs on every poll (about 30 Hz) and every keystroke, it calls `configure(state=...)` only when a widget's computed state differs from the last one it applied (as `resize()` caches `wrap_widths`), to keep Tk work minimal. A `SettingsError` that names a disabled field appends "switch Control to Marker (or Pan-tilt) to correct it", so the operator is never stuck on a field they cannot edit.

**Diagnostics.** `test_pan_tilt_size` is placed next to the existing `test_size` and `test_period` fields. The figure-8 label and note say "marker" or "pan/tilt" according to the applied mode.

**Live.** The position line reads `Pan 50.0%   Tilt 50.0%` instead of X/Y/Z metres. The stage preview becomes a pan/tilt square (pan horizontal, tilt vertical) with the limits, titled "Pan / tilt" instead of "Tracked target · top view". The Release marker button is shown only in Marker mode with PSN selected or a stream open. The summary names `Group <n>` instead of the MArker, and its PSN suffix is shown only in marker mode.

**Wording that must follow the mode:** the test-running status text ("the marker traces a figure 8"), the Diagnostics test labels, the axis-learning prompts and captions (`AXIS_NAMES`: "left / right control" and "upstage / downstage control" become pan / tilt in pan/tilt mode), the OSC tab help text, and the PSN-guard refusal message.

## Components touched

- `followspot_core.py`: settings fields and validation; `Motion.pan_tilt` and its step; `pan_tilt_commands`; pan/tilt figure 8; `Controller` mode branches in construction (the PSN-callback guard), start, output, reset and tick.
- `followspot.py`: opening a stream only for marker + PSN; `apply_settings` guard and clamping of both states; position text; reset; status and learn-prompt wording.
- `followspot_ui.py`: Setup selector and fields, mode-aware disabling in `refresh()`, Diagnostics field, Live position and preview, summary, Release marker visibility, wording.
- `settings.example.json`, tests, README, `docs/OPERATING.md`, `docs/GRANDMA3_SETUP.md`, `docs/PSN.md`, `AGENTS.md`.

## Testing

Automated, in the existing test files:

- Settings: defaults equal the example file; old files load as `marker`; each new field's validation and the field keys in each error.
- Motion: speed proportional to deflection, dead zone, centre holds, limits clamp (no wrap), diagonal speed cap, long gap capped at `MAX_STEP`, inversion.
- Command: exact `pan_tilt_commands` string, duplicate suppression, no `ClearAll`.
- Controller: pan/tilt mode needs no position callback and sends no PSN; start/stop; Stop then Start preserves pan/tilt and the first `/cmd` equals the displayed values; unlocked Reset forces a resend and resets zoom/iris, and locked Reset is refused; the pan/tilt figure 8 stays inside its limits; a failure stops output.
- Window (headless, stubbed view): `control_mode` change refused while a PSN stream is held; with saved `position_output='psn'` in `pan_tilt`, `start_output` opens no stream; Save/apply carries and clamps both `pan_tilt` and `xyz` across a mode switch; a mapped `release_marker` is a no-op in `pan_tilt`; button priority unchanged.
- Window (real Tk via `open_app`, skipped without Tk): Setup fields disabled by mode stay disabled after Stop; an invalid value in a disabled field is reported with the switch hint; the summary has no "PSN" and the Release button is hidden in `pan_tilt`; the Live position text and the preview.
- Existing marker and PSN tests must pass unchanged.

Not automatable, to be recorded as unverified until the operator confirms in a test show: that MA accepts `Group N; Attribute "Pan"/"Tilt" At Absolute Percent` over OSC and moves the lights; that 0-100% maps to the full pan/tilt range for the fixture type; the default tilt direction; how pan/tilt programmer values interact with fixtures that were following the MArker before a mode switch; whether the encoders really are unusable while output runs. The Live and Setup layout also needs a visual check in the real window.

## Open points for review

1. Inapplicable fields are disabled, not hidden. Hiding them would match "under marker" more literally but needs show/hide handling the layout code does not have, and layout code on macOS is fragile (see AGENTS.md). Say if you prefer hiding.
2. `max_speed` (metres per second) is not reused for pan/tilt because the units differ; there is a separate `pan_tilt_speed`.
3. Position output stays on the OSC tab rather than moving next to the Control selector, to keep the diff small. It is disabled in Pan-tilt mode. Say if you want it moved under the selector.
4. One group drives both pan and tilt. Separate groups per axis are not needed for the stated goal and are not included.
