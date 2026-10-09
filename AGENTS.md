# Agent guide

## Purpose and scope

This is a compact Python joystick controller for grandMA3 onPC 2.5 on macOS.
The intended use is a dedicated front-of-house followspot, with the joystick
connected to the same Mac as onPC. The operator currently uses a PXN-2113 Pro.

Preserve these agreed requirements when maintaining the project:

- Stick X/Y controls movement **speed**, proportional to deflection after a
  radial dead zone. Returning to centre holds the current target position.
- The target is one moving grandMA3 **MArker**. Z is a configurable fixed height.
- A joystick slider controls absolute brightness through an executor fader.
- Buttons have editable press/release command mappings.
- A small Tkinter window lets the operator learn axes/buttons, calibrate,
  change settings, and save them between launches.
- grandMA3 manages physical fixtures, group membership, fixture geometry, and
  XYZ aiming. The script does not compute pan/tilt or maintain a fixture list.
- Keep installation simple. There are no third-party Python packages and no
  requirement for a signed app or an Apple developer account.

Agents can edit the implementation, tests, and documentation for the user's
requested changes. Read this guide and [README.md](README.md) first, inspect the
current code and Git state, and preserve unrelated operator changes.

## Code map

| File | Responsibility |
| --- | --- |
| `followspot.py` | Tkinter window, settings editor, device selection/learning, polling, start/stop lifecycle, diagnostic CLI |
| `followspot_core.py` | Settings validation/persistence, proportional motion, coordinate conversion, OSC encoding/sending, the button edge tracker and output controller |
| `joystick.py` | SDL2 and native macOS HID readers via `ctypes`, normalization and the combined device list |
| `Launch Followspot.command` | Selects a Tk-capable Python and launches the window |
| `settings.example.json` | Shareable example configuration |
| `tests/` | Core behavior, device backend, and headless window lifecycle tests |
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

- Output starts stopped. Start applies settings and sends the displayed target
  and current slider level. There is no position or fader feedback from MA.
- Normal polling is approximately 30 Hz. Suppress duplicate output; there is no
  idle resend (it would retake the console selection and fader). A long sample
  gap moves at most one `MAX_STEP` (0.25 s) of motion; diagonal speed is capped.
- Stop retains target/brightness and attempts releases for buttons this
  controller pressed. Held-at-Start buttons must not produce a new press or
  release. Read/send failure stops output; there is no automatic resume.
- `poll` owns failure classification. A joystick read failure stops output and
  closes the device. Any failure while processing input or sending OSC stops
  output and keeps the device open; unexpected exception types are re-raised
  after stopping so the window never shows running output the controller stopped.
- Settings changes require stopped output. Release commands must be attempted
  before closing the sender, and release failures must remain visible.
- The saved `reset_locked` flag defaults to true. Its Live toggle is available
  while running and saves only that flag, leaving other settings drafts unapplied.
  Stopped Reset is local; unlocked live Reset immediately resends initial X/Y/Z
  without changing brightness or stopping output. Deflected input resumes motion
  on following polls.
- Button mappings default to MA commands when `action` is absent. Local actions
  (`start`, `stop`, `toggle`, `reset`) fire on press and cannot include MA commands.
  The window's single `ButtonEdges` tracker runs whether or not output is active;
  it routes presses to local actions and passes press/release edges to
  `Controller.tick`, which owns MA presses. Any joystick read outside `poll` goes
  through `App.read_snapshot`, which reseeds the tracker so held buttons stay
  unobserved. Learning samples reseed without acting. Priority and held-button
  rules are specified for operators in README step 6; keep them. A mapped Reset
  never applies settings drafts; the window Reset button applies them while stopped.
- Coordinates are in metres in the script. Convert to percent using the actual
  MArker **Movement Space** bounds, which differ from operating limits and the
  MArker **Target Space**. Defaults are examples, not measured stage geometry.
- MA receives a single OSC message, not an OSC bundle. Movement uses `/cmd`
  with an OSC string containing semicolon-separated commands. Clear only the
  selection, select the configured MArker, then set its attributes:

  ```text
  ClearSelection; MArker 1; Attribute "XYZ_X" At Absolute Percent 50; Attribute "XYZ_Y" At Absolute Percent 50; Attribute "XYZ_Z" At Absolute Percent 50.75
  ```

  `MArker 1 Attribute ...` without a separator was rejected as **Not implemented**.
  `At Absolute Percent` itself is supported. Never replace `ClearSelection`
  with `ClearAll`, which would discard programmer values.
- Brightness sends a float in 0–100 to `/Page<page>/Fader<executor>`; MA's
  `FaderRange` must be 100 and the executor's fader must be a Master.
- An optional prefix is applied consistently to both OSC addresses.
- UDP send success does not prove reception or command acceptance. In MA,
  enable global **Input**, row **Receive** and **Receive Command**, and use
  **EchoInput** plus System Monitor for reception checks. EchoOutput concerns
  MA's outgoing data. The row's Destination IP is for outgoing OSC; reception
  uses the selected top-level Interface. Match the script's destination to that
  interface. Do not assume `127.0.0.1` is available merely because both programs
  run on the same Mac. `lsof -nP -iUDP:8000` in a normal Terminal helps inspect
  listeners.

## Device and environment caveats

SDL did not enumerate the physical PXN on the operator's Mac. Native HID lists
it, and the operator confirmed live input responds. The device list combines
SDL controllers with native HID controllers whose names SDL did not list, so a
second controller visible to SDL no longer hides the PXN. The combined listing
has fake-backend tests but has not yet been checked with mixed physical devices.

Native discovery filters controller usages and excludes keyboard/mouse
interfaces. Without a scheduled HID run loop, Refresh must reapply matching to
discover hotplug/reconnect. Open only the chosen device non-exclusively, retain
the required CoreFoundation objects, and release them during cleanup. Respect
macOS access denials; do not treat an empty SDL list as proof that Input
Monitoring permission is missing.

Some agent sandboxes deny native Tk window creation (the real-window test then
skips itself), physical HID reads, process
inspection, UDP operations, or network/GitHub access. Automated tests and packet
encoding checks cannot establish end-to-end operation. Use a normal macOS
Terminal and a test show for manual input, OSC reception, marker movement,
brightness, and button checks. Preserve these distinctions in completion reports.

## Handoff status and change workflow

As of 2026-10-08, the operator has observed MA receiving OSC and rejecting the
old combined selection/attribute commands. The separator fix has regression
coverage, but successful movement with the corrected syntax still needs operator
confirmation. An earlier “Select and open a joystick first” report was not
reproduced. One plausible cause was fixed on 2026-10-09: an OSC send failure
used to close the joystick, so the next Start showed that message. Do not
claim the report is resolved without operator evidence.

Automated coverage: core motion/configuration/OSC-packet tests, simulated SDL
input/disconnect, native HID discovery and combined-list tests with doubles,
headless window lifecycle tests, and one real Tk window test that skips when Tk
cannot open a window. MA's installed 2.5 system tests confirm the `XYZ_X`,
`XYZ_Y`, `XYZ_Z`, and `XYZ_MArker` attribute names.

Keep changes compact and follow existing style. Update README for operator-facing
changes and this guide when architecture, workflows, or known limitations change.
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
