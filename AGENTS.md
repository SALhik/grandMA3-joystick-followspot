# Agent guide

## Purpose and scope

This is a compact Python joystick controller for grandMA3 onPC 2.5, developed
and used on macOS. A Windows launcher (SDL2 input only) exists but is untested.
The intended use is a dedicated front-of-house followspot, with the joystick
connected to the same Mac as onPC. The operator currently uses a PXN-2113 Pro.

Preserve these agreed requirements when maintaining the project:

- Stick X/Y controls movement **speed**, proportional to deflection after a
  radial dead zone. Returning to centre holds the current target position.
- In control mode `marker` (default) the target is one moving grandMA3
  **MArker**; Z is a configurable fixed height. In control mode `pan_tilt`
  the same two stick axes instead drive the pan and tilt percentages of one
  fixture group (OSC only).
- A joystick slider controls absolute brightness through an executor fader.
- An optional separate axis controls zoom/iris fader **speed**, with its own
  centre, dead zone, inversion and maximum speed. `Motion.zoom_level` tracks
  0–100%; centre holds it. MA configures the zoom/iris sequence and Temp fader.
- Buttons have editable press/release command mappings.
- A small Tkinter window lets the operator learn axes/buttons, calibrate,
  change settings, and save them between launches.
- grandMA3 manages physical fixtures, group membership, fixture geometry, and
  XYZ aiming. The script does not compute aim from geometry or maintain a fixture
  list; pan/tilt mode only integrates the stick into pan/tilt percentages.
- Keep installation simple. There are no third-party Python packages and no
  requirement for a signed app or an Apple developer account.

Agents can edit the implementation, tests, and documentation for the user's
requested changes. Read this guide and [README.md](README.md) (which indexes the other docs) first, inspect the
current code and Git state, and preserve unrelated operator changes.

## Code map

| File | Responsibility |
| --- | --- |
| `followspot.py` | Tkinter window, settings editor, device selection/learning, polling, start/stop lifecycle, diagnostic CLI |
| `followspot_ui.py` | Native Live/Setup/Diagnostics views, read-only stage/level previews, draft/readiness feedback, field-error navigation and scroll layout, sections shown for the active control mode / position output, field states |
| `followspot_core.py` | Settings validation/persistence, proportional motion, coordinate conversion, OSC encoding/sending, PSN packet encoders and `PsnStreamer` (background 30 Hz PSN sender), the button edge tracker and output controller, pan/tilt motion and group command |
| `joystick.py` | SDL2 and native macOS HID readers via `ctypes`, normalization and the combined device list |
| `Launch Followspot.command` | Selects a Tk-capable Python and launches the window |
| `Launch Followspot.bat` | Windows equivalent of the launcher; SDL2 only (no native HID), untested on Windows |
| `settings.example.json` | Shareable example configuration; must equal the `Settings` defaults |
| `requirements.txt` | Comment-only: records that there are no third-party packages |
| `.coderabbit.yaml` | Review-bot configuration (docstring check off) |
| `tools/psn_test_sender.py` | Stdlib PSN test sender for onPC; not imported by the app, which has its own `PsnStreamer` (see docs/PSN.md) |
| `diagnostics/ma_plugin_probe/` | Experimental synthetic input, finite OSC movement and direct native-Lua channel probes; single-XML builders and separate offline tests. The OSC package embeds a read-only settings snapshot and app core; the direct probe generates motion frames with the core at build time and uses no Python/network at runtime. Personal XML is ignored. Not part of the app runtime. |
| `ma_plugin/` | Full native grandMA3 plugin: `build.py` embeds Lua UI/output and Python core/input in one XML; `runtime.py` adapts Controller to semantic frames and reliable command events; `worker.py` owns private atomic IPC, lease, lock and PSN lifecycle; `ui.lua` is one native panel with a compact Live strip and an expandable Setup view whose fields, sections and choice labels come from `build.py`'s schema. See docs/PLUGIN.md. |
| `.github/workflows/tests.yml` | Linux/Windows headless and macOS Tk/native CI; GUI skips remain explicit |
| `tests/` | Core behavior, PSN encoder/streamer, device backend, and headless window lifecycle tests; `plugin_harness.py` builds the plugin XML and runs its Lua against MA API doubles for the plugin package, lifecycle and UI tests |
| `README.md` | Short overview: documentation index, quick start, launch, diagnostics |
| `docs/GRANDMA3_SETUP.md` | Operator step-by-step onPC setup with commands, zoom/iris executor, troubleshooting |
| `docs/OPERATING.md` | Operator guide: joystick, buttons, reset lock, zoom/iris, test mode, stop/restart, limitations |
| `docs/PSN.md` | PSN output guide: app and onPC setup, Stop vs Release marker, verified findings, unverified other-computer setup, troubleshooting, packet format, open risks |
| `docs/ACCEPTANCE.md` | Single record/checklist for automated, visual, physical/onPC, long-run PSN and Windows verification |
| `docs/superpowers/` | Original approved design and implementation plan; historical context |

Runtime `settings.json` is operator-owned and ignored by Git. Do not overwrite
it during development or commit it. Share configuration changes through the
example file and maintain compatibility or document a migration. `.venv/`,
`.superpowers/`, logs, and Python caches are also ignored.

## Run and verify

Use Python 3.10+; the GUI needs Tkinter. The launcher checks for a Tk-capable
Python, including a local `.venv` if present. Some Homebrew Python installations
can run the CLI but lack Tk. SDL2 is optional for native Mac input, but the SDL
virtual-device test requires an installed SDL2 library with virtual joystick
support. `FOLLOWSPOT_SDL2` can specify the library path.

```sh
zsh 'Launch Followspot.command'
python3 followspot.py --list-devices
python3 followspot.py --monitor 10
python3 followspot.py --settings settings.example.json --check-settings
python3 -m unittest discover -s tests -v
git diff --check
```

Device listing and monitoring do not transmit OSC. Monitoring opens the unique
device matching the saved name. If a local environment exists, substitute
`./.venv/bin/python` for `python3`. Keep meaningful regression tests for changes
to motion, packet contents, device handling, and output lifecycle. Documentation
changes do not need new tests. Report environment failures separately from code
failures; never report skipped or blocked hardware checks as passing.

## Integration contracts

- Output starts stopped. Start applies settings and sends the target, current slider
  level and enabled zoom/iris shown in the pending Start preview. Live retains applied
  settings; pending mode, bounds, Z and brightness mapping changes are explicit in the
  separate preview. There is no position or fader feedback from MA.
- Normal polling is approximately 30 Hz. Suppress duplicate output; there is no
  idle resend of OSC output (it would retake the console selection and fader; PSN streaming
  is the exception below). A long sample
  gap moves at most one `MAX_STEP` (0.25 s) of motion; diagonal speed is capped.
- Stop retains target/brightness and attempts releases for buttons this
  controller pressed. Held-at-Start buttons must not produce a new press or
  release. Read/send failure stops output; there is no automatic resume.
- `poll` owns failure classification. A joystick read failure stops output and
  closes the device. Any failure while processing input or sending OSC stops
  output and keeps the device open; unexpected exception types are re-raised
  after stopping so the window never shows running output the controller stopped.
- PSN position output (`position_output` = `osc` default or `psn`, with `psn_tracker_id`,
  `psn_group`, `psn_port`, `psn_interface`; details in docs/PSN.md). In PSN mode
  `Controller` calls `send_position` instead of building `/cmd` marker commands, and
  `App` owns one `PsnStreamer` whose thread streams the latest position at 30 Hz
  (INFO at 1 Hz). This streaming is the exception to "no idle resend": onPC resets
  the MArker to 0, 0, 0 when packets stop. Brightness, zoom/iris and buttons stay
  on OSC with the existing rules. Lifecycle: Start opens the stream (a failed Start
  closes only a stream it created); Stop, joystick read failure and OSC failure
  stop output but hold the stream; the stream closes only on Release marker, a
  confirmed window close (on macOS also Cmd-Q, routed through `::tk::mac::Quit`; the command's
  existence is tested but a real Quit event is not), or a stream error. Release marker (Live button or local
  button action `release_marker`) stops output if running and closes the stream;
  in the same sample it acts with Stop and beats Start and Reset, and is a no-op
  with no stream open. `App.check_streamer` runs first in every poll, so a held
  stream's send error is surfaced even with no joystick open: it closes the
  stream, stops output if running and records fault kind `psn`, which persists
  until the next successful Start (the stream is already closed, so Release marker
  cannot clear it). PSN fields stay editable while a stream
  is held and output is stopped, but `apply_settings` refuses a changed PSN field
  until Release. Validation follows the active path (see Control mode): with PSN the
  `psn_*` fields are range-checked and `attribute_x/y/z` are not; with OSC the reverse.
  `marker_id` and the Movement Space are still checked in PSN mode even though PSN
  does not use them for conversion.
  The window Release button confirms whenever a stream is open; mapped Release remains
  immediate. Stopped output with an open stream is prominently labelled PSN HOLDING.
  Readiness and apply share the held-stream settings guard, so changed PSN fields block
  normal and test Start until released or reverted. A new figure-8 stream is seeded with
  the test's initial target before its worker can send DATA.
- Control mode (`control_mode` = `marker` default or `pan_tilt`). `pan_tilt` is
  OSC only: `Controller` sends `ClearSelection; Group <fixture_group>; Attribute
  "Pan" At Absolute Percent <p>; Attribute "Tilt" At Absolute Percent <t>` only
  when the values change (no idle resend; Reset forces one resend), needs no
  `send_position`, and no `PsnStreamer` is created. `Motion.pan_tilt` (percent,
  clamped to `pan_min/max`, `tilt_min/max`) and `Motion.xyz` are both kept; only
  the active mode is stepped, and Save/apply carries and clamps both. `axis_x`
  drives pan and `axis_y` tilt with the existing centre, dead zone and inversion;
  speed is `pan_tilt_speed` percentage points per second with the same
  `MAX_STEP` cap. Only the active path is range-checked:
  `followspot_core.inactive_fields(control_mode, position_output)` names the
  settings of the other control mode and the other position output
  (`MARKER_FIELDS`, `PAN_TILT_FIELDS`, `OSC_POSITION_FIELDS`, `PSN_POSITION_FIELDS`).
  They are still saved, type-checked and parsed from the window (a non-number
  cannot be saved), so an inactive value may be out of range until its path is
  selected; code must not use inactive fields. Switching back re-validates them.
  `control_mode` is in `PSN_FIELDS`, so it cannot change while a PSN stream is
  held. In Setup the draft selectors (`app.values['control_mode']` and
  `['position_output']`) decide which sections are shown
  (`FollowspotView.apply_sections`, called from `apply_field_states` in `refresh`);
  the hidden fields equal `inactive_fields` (a real Tk test pins this). Editors are
  disabled only while running, for a loaded local button action, or for zoom/iris
  while the draft leaves it off (zoom/iris is still validated); states are recomputed
  in `refresh`, never stored as the widget's base state. The selectors show labels
  (MArker / Pan / tilt, OSC commands / PSN stream) and store the raw values.
  `show_error` names the selector to switch for an error in a hidden field. Live
  follows the applied settings.
- Test mode (`Controller.start(test=True)`) needs no joystick: a figure 8 around the initial X/Y (`figure_eight`) or, in pan/tilt mode, the initial pan/tilt (`figure_eight_pan_tilt`) and fixed `test_brightness`. `poll` skips joystick reads and button processing while a test runs; failures stop output like normal.
- Settings changes require stopped output. Release commands must be attempted
  before closing the sender, and release failures must remain visible.
- Setup and Diagnostics stay readable while running; disable editors, not tabs.
  Dead zones display as percentages but persist as fractions. Incomplete button
  editor changes must be added/updated or discarded before saving/starting.
  Faults are separate from routine status; release warnings require acknowledgement.
- On macOS, SDL enumeration can dispatch Tk drawing events outside `_tkinter`'s
  call boundary. Do not use Python Configure or scrollbar callbacks for layout:
  update layout from normal polling and use native Tcl widget commands for scrollbars.
  The visible-window subprocess test exercises the real backend without sending OSC.
- The saved `reset_locked` flag defaults to true. Its Live toggle is available
  while running and saves only that flag, leaving other settings drafts unapplied.
  Stopped Reset is local; unlocked live Reset immediately resends initial X/Y/Z
  and enabled initial zoom/iris level without changing brightness or stopping
  output. Deflected input resumes motion on following polls.
- Zoom/iris is disabled in old settings by default; only enabled mappings require
  a fourth, distinct axis and an executor different from brightness. Start sends
  its tracked level; changed levels send at 0.1% resolution with no idle resend.
  Save/apply and Stop/Start preserve the tracked level, even if initial_zoom is
  edited; Reset/relaunch use initial_zoom. The same MAX_STEP caps integration.
  A mapped Reset uses applied settings and skips both X/Y and zoom integration
  for that sample. Brightness is never reset.
- Button mappings default to MA commands when `action` is absent. Local actions
  (`start`, `stop`, `toggle`, `reset`) fire on press and cannot include MA commands.
  The window's single `ButtonEdges` tracker runs whether or not output is active;
  it routes presses to local actions and passes press/release edges to
  `Controller.tick`, which owns MA presses. Any joystick read outside `poll` goes
  through `App.read_snapshot`, which reseeds the tracker so held buttons stay
  unobserved. Learning samples reseed without acting. Priority and held-button
  rules are specified for operators in docs/OPERATING.md (Buttons); keep them. A mapped Reset
  never applies settings drafts; the window Reset button applies them while stopped.
- Coordinates are in metres in the script. Convert to percent using the actual
  MArker **Movement Space** bounds, which differ from operating limits and the
  MArker **Target Space**. Defaults are examples, not measured stage geometry.
- MA receives a single OSC message, not an OSC bundle. OSC position output uses
  `/cmd` (PSN mode streams the position instead) with an OSC string containing semicolon-separated commands. Clear only the
  selection, select the configured MArker, then set its attributes (in `pan_tilt`
  control mode the selected object is the fixture group and the attributes are
  Pan/Tilt; see the Control mode bullet):

  ```text
  ClearSelection; MArker 1; Attribute "XYZ_X" At Absolute Percent 50; Attribute "XYZ_Y" At Absolute Percent 50; Attribute "XYZ_Z" At Absolute Percent 50.75
  ```

  `MArker 1 Attribute ...` without a separator was rejected as **Not implemented**.
  `At Absolute Percent` itself is supported. Never replace `ClearSelection`
  with `ClearAll`, which would discard programmer values.
- Brightness sends a float in 0–100 to `/Page<page>/Fader<executor>`; MA's
  `FaderRange` must be 100 and the executor's fader must be a Master.
- Zoom/iris uses the same OSC fader address format with its own page/number;
  the operator configures a zoom-only or iris-only sequence with a Temp fader.
  Actual zoom/iris movement still requires operator confirmation in a test show.
- An optional prefix is applied consistently to all OSC addresses.
- UDP send success does not prove reception or command acceptance. In MA,
  enable global **Input**, row **Receive** and **Receive Command**, and use
  **EchoInput** plus System Monitor for reception checks. EchoOutput concerns
  MA's outgoing data. The row's Destination IP is for outgoing OSC; reception
  uses the selected top-level Interface. A pre-existing OSC row on the same port
  made a theatre show ignore the tool's commands with no error (typed commands
  and a blank show worked); removing it fixed it. See docs/GRANDMA3_SETUP.md,
  Step 8 item 6. Match the script's destination to that
  interface. Do not assume `127.0.0.1` is available merely because both programs
  run on the same Mac. `lsof -nP -iUDP:8000` in a normal Terminal helps inspect
  listeners.

## Device and environment caveats

SDL did not enumerate the physical PXN on the operator's Mac. Native HID lists
it, and the operator confirmed live input responds. The device list combines
SDL controllers with native HID controllers that SDL did not list, so a second
controller visible to SDL no longer hides the PXN. SDL2 exposes no physical
identity to match HID records against, so HID records are matched by name
count: when HID sees more controllers with a name than SDL lists, every HID
record with that name is listed, accepting a duplicate entry so none becomes
unreachable. Identical controllers then need explicit selection. The combined listing
has fake-backend tests but has not yet been checked with mixed physical devices.

Native discovery filters controller usages and excludes keyboard/mouse
interfaces. Without a scheduled HID run loop, Refresh must reapply matching to
discover hotplug/reconnect. Open only the chosen device non-exclusively, retain
the required CoreFoundation objects, and release them during cleanup. Respect
macOS access denials; do not treat an empty SDL list as proof that Input
Monitoring permission is missing.

Some agent sandboxes abort the interpreter during native Tk window creation, and
some Python installs (for example Homebrew's default `python3`) lack `_tkinter`.
Use `FOLLOWSPOT_TEST_HEADLESS=1` to explicitly skip real-window tests in a restricted
environment; this is a test-only flag. Missing Tk or recoverable Tcl window errors
also produce explicit skips. CI probes macOS Tk in a subprocess before the suite.
Sandboxes may also deny physical HID reads, process
inspection, UDP operations, or network/GitHub access. Automated tests and packet
encoding checks cannot establish end-to-end operation. Use a normal macOS
Terminal and a test show for manual input, OSC reception, marker movement,
brightness, and button checks. Preserve these distinctions in completion reports.

## Handoff status and change workflow

As of 2026-10-08, the operator has observed MA receiving OSC and rejecting the
old combined selection/attribute commands. The separator fix has regression
coverage; the 2026-10-20 operator movement confirmation through the imported
OSC test plugin is recorded in docs/ACCEPTANCE.md. An earlier “Select and open a joystick first” report was not
reproduced. One plausible cause was fixed on 2026-10-09: an OSC send failure
used to close the joystick, so the next Start showed that message. Do not
claim the report is resolved without operator evidence.

Also on 2026-10-20, the operator confirmed MArker movement through the direct
native-Lua probe in onPC 2.5.1.0, with unrelated selection/grid and encoder
context retained in its report. They subsequently observed actual brightness
reach 100% from a 0% Master on Page 1 / Executor 201 (Sequence 901). The old
probe immediately read back 0% and aborted before XYZ; its new 0.3.1.0 version
waits up to one second for the asynchronous readback before starting the full
motion cycle. The operator confirmed combined one-press success with that fix;
report `run.LSVdY780` records 0% → 100% settling in about 0.040 s followed by
226 XYZ frames, with empty selection and encoder context retained. This probe
does not establish the finished plugin's input/helper lifecycle.

The full plugin was added on 2026-10-20, reusing core/input without changing
the standalone app runtime. Native MArker channel writes preserve selection;
pan/tilt deliberately retains the selection-based core command via internal
Cmd. Faders use the assigned object's Master/Temp, not OSC. Config is a
namespaced show/user UserVar; the Python executable preference is local.
One shared helper lock, private owner token and a two-stage lease bound
orphan lifetime: three seconds without renewal stops output (and exits with no
PSN stream); a held PSN stream survives up to fifteen seconds, without ticking
input, so a Lua stall does not snap the MArker to origin. Lua treats a helper
with no heartbeat for five seconds as finished, so Close and Reconnect never
wait on a helper that did not start. Plugin arguments (`start`, `stop`,
`toggle`, `test`, `reset`, `release`, `show`) act only on an open panel. Stop cancels pending presses/frames, releases owned commands
and retains PSN; Release/normal Close require inline confirmation for a hold.
Off Plugin is unconditional cleanup. Do not introduce blocking UI dialogs
while renewing the lease. Packaged Lua/Python tests run offline with MA,
input and socket boundaries intercepted; the full native layout, MA-launched
physical joystick, actual package PSN and long runs remain operator checks.

On 2026-10-14 the operator verified in onPC 2.5.0.3 that PSN packets move a
MArker without touching the console selection or encoders (multicast
236.10.10.10:56565 on lo0; MArker returns to 0, 0, 0 when packets stop).
PSN position output was implemented on 2026-10-14 (branch `feat/psn-output`) and
is covered by automated tests only. It is not verified with the real joystick,
a real show, onPC receiving the app's own stream, onPC on another computer or
Windows, and the Live view and Setup layout were not checked visually by the
operator; see docs/ACCEPTANCE.md for recorded evidence and the pending operator checks.

Added since then: proportional zoom/iris axis, the figure-8 test mode with the
step-by-step setup guide, and the Windows launcher. The imported plugin exercises
the shared figure-8 controller; the app's GUI test mode, zoom/iris movement in a
test show and the Windows launcher on real hardware remain unverified.

Pan/tilt control mode was added on 2026-10-15 (branch `feat/pan-tilt-control`)
and is covered by automated tests only. Not verified: that onPC accepts the
`Group <n>; Attribute "Pan"/"Tilt" At Absolute Percent` command over OSC and
moves the lights, that 0-100% spans the full fixture range, the default tilt
direction, how fixtures that followed a MArker behave after a mode switch, and
the Setup / Live layout in the real window. See docs/GRANDMA3_SETUP.md,
Optional: pan/tilt control, for the operator checklist.

Also on 2026-10-15 (branch `feat/conditional-setup-sections`), Setup was reorganised:
tabs Target and Output (was Target / stage and OSC), only the active control mode's and
position output's sections are shown, one speed / figure-8 size row switches with the
mode, zoom/iris editors are disabled while it is off, and the selectors show labels.
Validation now skips the inactive path (see Control mode). Covered by automated tests
only; the real window layout has not been checked visually by the operator.

Review hardening on 2026-10-16 adds SDL instance identity checks, bounded PSN sends,
active-path numeric representability checks, diagnostic argument validation, a shared
preflight/Start preview and deliberate window Release. UI drawing avoids unchanged
repaints, command-entry states have one owner, and delayed reveal callbacks are guarded.
The operator changes and remaining environment checks are documented in OPERATING.md,
PSN.md and ACCEPTANCE.md rather than repeated here.

Design choices retained: first pan/tilt use sends 50 / 50 to the whole group at full
speed; one group and one pair serve all fixtures; older checkouts reject newer settings
keys. Release with no open stream still reports "No PSN stream is open." Historical
plans describe their original version and should not be rewritten to match later work.

Automated coverage: core motion/configuration/OSC-packet tests, simulated SDL
input/disconnect and hotplug identity, native HID discovery and ownership/failure tests
with doubles, PSN encoder (pinned bytes), streamer (injected sockets and bounded shutdown),
local UDP receiver tests and controller tests, headless window lifecycle tests (including
zoom/iris, test mode and PSN stream hold/release/close, faults and button priority), real Tk
workflow tests, pan/tilt coverage in each layer (core motion, validation and OSC-string tests;
headless window tests; real Tk tests for the selectors, hidden sections matching `inactive_fields`, captions and error labels), and a visible startup test with the real backend. Tk tests skip
when Tk is missing or cannot open a window. The
launcher Python/Tk probes have automated coverage; actual Windows launcher/runtime and
physical operation remain unverified until recorded. MA's installed 2.5 system tests
confirm the `XYZ_X`, `XYZ_Y`, `XYZ_Z`, and `XYZ_MArker` attribute names.

Keep changes compact and follow existing style. Update README,
docs/OPERATING.md or docs/GRANDMA3_SETUP.md for operator-facing changes (keep
each fact in one place and link rather than duplicate), and this guide when
architecture, workflows, or known limitations change.
Consult official MA 2.5 documentation or the matching installed MA system tests
before changing console command syntax. The original plan is not proof that a
command works. Diagnose the failing boundary before changing unrelated setup.

Before committing, inspect the diff, run applicable checks, and state what was
actually verified. Inspect the current branch/remotes rather than assuming a
branch name. Distinguish local changes, local commits, and successful remote pushes
in reports. Preserve the working directory and operator configuration.

Useful MA references: [MArker keyword](https://help.malighting.com/grandMA3/2.5/HTML/keyword_marker.html),
[Percent syntax](https://help.malighting.com/grandMA3/2.5/HTML/keyword_percent_word.html),
[MArker fixtures](https://help.malighting.com/grandMA3/2.5/HTML/xyz_marker.html),
[OSC](https://help.malighting.com/grandMA3/2.5/HTML/remote_inputs_osc.html).
