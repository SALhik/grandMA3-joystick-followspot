# PSN position output: design

Date: 2026-10-14. Status: draft, revised after an independent review. Background and verified findings: [docs/PSN.md](../../PSN.md).

## Goal

Let the operator keep their console selection and encoder wheels while the followspot runs. In OSC mode the app sends `ClearSelection; MArker <id>; Attribute ...` on every position update, which replaces the selection. A new selectable position output sends the MArker position as PosiStageNet (PSN) instead, which onPC maps to the MArker without a command line.

## Scope

In scope:

- A `position_output` setting (`osc` default, `psn`).
- PSN encoder and a streaming sender in `followspot_core.py`.
- Stop/Release behavior, window controls, a local `release_marker` button action.
- Tests and documentation, including the same-Mac setup and an unverified section for onPC on another computer.

Out of scope: brightness, zoom/iris and button commands (they stay on OSC), PSN input, multiple trackers, unicast PSN (it did not register in onPC), Windows verification.

## Facts the design depends on

Verified in onPC 2.5.0.3 (see docs/PSN.md): multicast `236.10.10.10:56565` on interface `lo0` moves a MArker mapped by Tracker ID and MArker ID; selection and encoders are unaffected; axes are MA stage axes (x left/right, y front/back, z up/down); sent positions looked like absolute stage metres at the points tested; the MArker returns to 0, 0, 0 shortly after packets stop (timeout not measured). Not verified: real joystick use, a real show, behavior on another computer, Windows.

## Settings

New fields, all with defaults so existing `settings.json` files load unchanged:

| Field | Default | Validation |
| --- | --- | --- |
| `position_output` | `osc` | `osc` or `psn` |
| `psn_tracker_id` | 1 | integer 1-65535 |
| `psn_group` | `236.10.10.10` | IPv4 multicast address (224.0.0.0/4) |
| `psn_port` | 56565 | integer 1-65535 |
| `psn_interface` | `127.0.0.1` | IPv4 address |

`settings.example.json` must equal the `Settings` defaults. In PSN mode the app does not use `marker_id` or the Movement Space to convert coordinates (the MArker is chosen in onPC's PSN row), but validation is unchanged: the operating limits, initial position and Z must still fit inside the Movement Space and `marker_id` must still be positive. This keeps one set of rules for both modes and avoids a settings file that becomes invalid when the mode is switched.

## Components

**PSN encoder** (`followspot_core.py`, pure functions). `psn_data_packet(tracker_id, xyz, timestamp_us, frame)` and `psn_info_packet(system_name, tracker_id, tracker_name, timestamp_us, frame)` produce PSN v2.03 packets (little-endian chunks; chunk header `id | length << 16 | has_subchunks << 31`; DATA `0x6755`, INFO `0x6756`; details in docs/PSN.md). Positions are float32 metres.

**PsnStreamer** (`followspot_core.py`). Opens a UDP socket with `IP_MULTICAST_IF = psn_interface` and TTL 1. One background thread sends a DATA packet at 30 Hz with the latest position and an INFO packet at 1 Hz. API: `PsnStreamer(settings, xyz)` (the initial position is required, so the first packet always has a valid value), `set_position(xyz)`, `poll_error()` (returns and clears a stored exception), `close()`. The position is a lock-protected tuple; a send error is stored, the thread stops, and nothing is raised into Tk. `close()` joins the thread with a timeout and closes the socket. The socket and clock are injectable for tests. INFO and DATA share one frame counter, as in the verified test sender (whether PSN wants separate counters was not checked).

**Controller** (`followspot_core.py`). `Controller(settings, send, send_position=None)`; constructing one in PSN mode without `send_position` raises. `App` builds a `Controller` in two places (init and every `apply_settings`); both pass the callback. In PSN mode `_output_position` calls `send_position(xyz)` instead of building `marker_commands`; there is no duplicate suppression for PSN because the streamer already sends continuously. Brightness, zoom/iris and button handling are unchanged and still use `send`. `marker_commands` and OSC mode are unchanged.

**App** (`followspot.py`). Owns the streamer. The streamer outlives Stop; the lifecycle table below says when it closes.

## Behavior

- **Start (PSN mode):** applies settings, creates the streamer with the displayed target if none is open, starts the controller. A failed Start closes a streamer it created and leaves a pre-existing held stream alone.
- **Running:** each controller output calls `streamer.set_position`. The streamer keeps sending at 30 Hz when the stick is idle (this reverses the OSC rule of no idle resend, per mode).
- **Stop:** the controller stops as today (button releases attempted, brightness and zoom OSC stop). The streamer keeps sending the last position, so the lights stay put.
- **Stopped Reset and settings edits:** these change the displayed target but not the held stream. While a stream is open, the stage preview and position label show the held position separately ("Held at X, Y, Z") so the display never claims a target onPC is not holding. The next Start sends the displayed target.
- **Release marker:** closes the streamer, and onPC resets the MArker to 0, 0, 0. The Live button is shown in PSN mode and enabled whenever a stream is open (keyed to the stream, not to the draft or applied mode). The local button action is `release_marker`, to keep it distinct from the existing button release commands, the `release` fault kind and the release-warning acknowledgement. Releasing while output runs also stops output. Priority among simultaneous local presses: Stop, then Release marker, then Start, then Reset.
- **Close window while holding:** asks for confirmation, because closing resets the MArker mid-show. An app crash cannot ask; the stream stops and the MArker resets.
- **Settings while a stream is open:** changes to `position_output` or any `psn_*` field are refused until the marker is released (the status explains). Other settings apply as today. Switching to OSC mode therefore requires a released stream, so a held PSN stream never coexists with OSC position output.
- **Test mode (figure 8) in PSN mode:** works the same, driving the streamer.

### Stream lifecycle by event

| Event | Output | Stream |
| --- | --- | --- |
| Stop | stops | holds |
| Release marker | stops if running | closes |
| Window close (confirmed) | stops | closes |
| Joystick read failure (`input_lost`) | stops | holds, so a cable pull does not drop the spot; the fault tells the operator to Release if wanted |
| OSC send failure (brightness, buttons) | stops | holds |
| Start failure | stopped | closes only if this Start created it |
| Streamer send error | stops if running | closes (it is already dead); recorded as its own fault kind |

## Errors

- A streamer send error is stored by the thread. `poll` checks `poll_error()` first, outside the test and joystick branches, so a held stream with no joystick open still surfaces it. It stops output if running, closes the streamer and records a fault.
- Start fails with the error text if the socket cannot be opened or the interface is invalid. A multicast route failure ("No route to host") points the operator to the interface advice in docs/PSN.md.
- Read failures and OSC send failures keep their existing handling; the stream behavior is in the lifecycle table.
- No automatic resume.

## UI

Setup → Network gets a "Position output" selector and the PSN fields, editable only while stopped and not holding. The Live summary keeps the OSC host (brightness and zoom still use OSC) and adds a PSN line. The Live view gets the Release marker button. The button editor lists `release_marker` among local actions. Local actions cannot include MA commands (existing rule).

## Tests

- Encoder: exact bytes for fixed inputs (header chunk, tracker list, POS, INFO name chunks), including a negative coordinate and a tracker ID above 255. The layout was cross-checked against the PSN-CPP reference decoder during the investigation, but the decoder is not in the repo.
- Streamer with an injected socket and clock: packet counts and contents (no wall-clock rate assertions), `set_position` changes the value sent, `close()` stops sending, a failing socket is reported through `poll_error()` without raising. One real loopback UDP test skips when the sandbox denies UDP.
- Controller: PSN mode sends no `/cmd` position commands and calls `send_position`; brightness, zoom/iris and button OSC unchanged; OSC mode byte-for-byte unchanged.
- Settings: defaults equal the example file (a new test; none exists today), old files load, each validation rule, unknown value of `position_output` rejected.
- Window (headless): Stop keeps the stream; Release closes it; settings change refused while holding; `input_lost` and OSC failure hold; a streamer error with no joystick still stops output and records a fault; a failed Start closes the streamer it created; `release_marker` works from a mapped button and ranks after Stop and before Start; closing while holding asks for confirmation.
- Not testable here: real onPC reception, a real joystick, behavior on a second computer, timing against MA's snap-back timeout.

## Documentation

- `docs/PSN.md`: becomes the PSN setup guide (same-Mac setup, Release/Stop behavior, reset-on-stop warning, troubleshooting, packet format).
- Section for onPC on another computer, labelled unverified: set onPC's PSN Interface to its network interface and `psn_interface` in the app to this computer's address on the same network; keep the multicast group; check that switches/Wi-Fi pass multicast and the VPN does not take the default multicast route (observed on this Mac).
- `docs/GRANDMA3_SETUP.md`, `docs/OPERATING.md` (Stop vs Release marker, priority rules, limitations), `README.md`, `AGENTS.md` (code map, integration contracts: PSN streaming exception to "no idle resend", thread, Release), and `settings.example.json`.

## Open risks

- macOS App Nap or background throttling could delay the sender thread beyond MA's snap-back timeout; the thread is not proven immune, and the Live view should be kept in front during shows.
- Whether PSN wants separate frame counters for INFO and DATA, and whether onPC applies its Map or offset to the received metres, were not checked.
- The MArker snap-back timeout was not measured; a UI stall is mitigated by the sender thread but a frozen process still resets the marker mid-show.
- Absolute-metre positions were checked at a few points only; the Movement Space bounds may still matter at extremes.
- Fixture Sheet and encoders do not show PSN positions, so the operator cannot read the marker position there.
