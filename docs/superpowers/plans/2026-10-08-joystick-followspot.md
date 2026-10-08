# Joystick Followspot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a compact joystick-to-grandMA3 controller with editable settings.

**Architecture:** Separate the control/OSC logic, SDL joystick adapter, and Tkinter window. Use the SDL2 library already installed on this Mac through Python ctypes, avoiding an extra Python package. Use Python 3.12, which includes Tk bindings; native GUI creation is unavailable in the agent shell.

**Tech Stack:** Python standard library, Tkinter, SDL2.

**Spec:** `docs/superpowers/specs/2026-10-08-joystick-followspot-design.md`

## Global Constraints

- grandMA3 onPC 2.5 on the same Mac; fixture assignment remains in onPC.
- Greater joystick deflection means greater X/Y speed; centre holds position.
- Configurable Z; absolute brightness slider; editable button press/release commands.
- Approximately 30 Hz; output disabled initially and after device/input failure.
- No silent output enablement, automatic showfile edits, or Apple developer account.

## Review Focus

- Invalid/nonfinite settings must not reach output.
- A processing stall must not cause a large target jump.
- A button held during Start must not trigger a new action.
- Disconnect/reconnect must not resume output automatically.
- Marker movement-space bounds must be distinct from optional smaller operating limits.

### Task 1: Control model, configuration, OSC

**Files:** `followspot_core.py`, `tests/test_core.py`

**Interfaces:** `Settings.from_dict(data)`, `Settings.validate()`, `Motion(settings).step(axes, dt)`, `Controller(settings, sender).start/stop/tick`, `OscSender(host, port, prefix).send(address, value)`.

- [ ] Write unittest cases for proportional velocity, dead zone, diagonal cap, centre correction, slider endpoints, clamp/stall behaviour, settings roundtrip/rejection, explicit-percent MArker commands, and button lifecycle.
- [ ] Run `python3 -m unittest discover -s tests -v`; expect missing implementation failure.
- [ ] Implement validated JSON settings, time-based motion, OSC encoding, explicit `At Absolute Percent` commands, and output lifecycle.
- [ ] Run the same suite; expect all tests passing. Add a loopback UDP check where the sandbox permits sockets.
- [ ] Commit the tested core.

### Task 2: Joystick adapter and settings window

**Files:** `joystick.py`, `followspot.py`, `tests/test_joystick.py`

**Interfaces:** `Joystick.devices() -> list[tuple[int, str]]`, `Joystick.open(index)`, `Joystick.read() -> (list[float], list[bool])`, `Joystick.close()`; consumes Task 1's validated settings/controller.

- [ ] Write tests for signed-axis normalization, axis learning, and simulated SDL virtual-device input/disconnect when available.
- [ ] Run tests and observe missing adapter failure.
- [ ] Implement SDL loading, background input, device selection, state sampling, attachment checks, and clean closure.
- [ ] Implement the window's live view, stopped-only settings, calibration/learn controls, button editor, Start/Stop/reset, and error recovery. Use headless logic tests plus a manual GUI smoke check if the environment allows one.
- [ ] Run the suite and read the real joystick without OSC output; commit.

### Task 3: Launch, setup guide, final verification

**Files:** `Launch Followspot.command`, `README.md`, `requirements.txt`, `settings.example.json`

- [ ] Provide a launcher selecting a Tk-capable Python; document SDL2 installation only if missing.
- [ ] Document exact MA setup, marker movement-space conversion, executor brightness, button examples, startup/stop behaviour, and UDP/programmer limitations.
- [ ] Run all tests, compile all modules, and perform available device/OSC/UI checks; report integration checks that require the user's onPC show.
- [ ] Review the finished implementation against the approved spec and commit delivery files.

## Execution decision

The user's instruction “Approved. Please start implementing” authorizes execution in this session. Proceed inline without a further approval handoff. This is a new, isolated project directory, on its own feature branch; no existing checkout needs a worktree.
