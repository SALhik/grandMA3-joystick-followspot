# PSN: moving the MArker without taking the selection

Status: available as an optional output in the app (Setup → Output → Position output). Verified in onPC 2.5.0.3 with the test sender; not yet checked with the real joystick or a real show. The default output still moves the MArker through OSC (see [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md)). This page records what was found on 2026-10-14 and how to configure both sides. PSN applies only to the marker control mode; pan/tilt control (Setup → Target → Control) is OSC only and opens no PSN stream.

## Why

The OSC command `ClearSelection; MArker 1; Attribute ...` replaces the operator's selection on every position update, so the encoder wheels cannot be used while output runs. `Attribute` needs a selection, and no documented Lua call writes programmer values without one. Other ideas (a separate OSC user, a second station) were not tested; the OSC row has no user column.

PosiStageNet (PSN) moves a MArker directly from a tracker, with no command line and no selection involved.

## What was verified

Tested in onPC 2.5.0.3 on macOS with `tools/psn_test_sender.py`, observed by the operator:

- **Selection and encoders are untouched.** With a light selected and the Focus tab open, nothing changed while the MArker moved.
- **Movement shows in the 3D window** and in the PSN row's Position columns.
- **Axes are MA stage axes** with the default Map X/Y/Z: sent x is left/right, y is front/back, z is up/down. No swap is needed. A tracker at (3, 2, 1.5) matched in the 3D window, and (0, 0, 1.5) put the MArker 1.5 m up. Positions appear to be absolute stage metres, so a PSN mode would not need the OSC percent conversion. Offsets other than the tested points were not checked against the MArker's Movement Space.
- **Fixture Sheet and MArker encoders do not show the PSN position.** They stayed 0, 0, 0. This is a display quirk, not a failure to move.
- **The MArker snaps back to 0, 0, 0 shortly after packets stop.** A PSN mode must keep streaming, including while the stick is idle. The exact timeout was not measured.

Not verified: PSN with the real joystick, use in a real theatre show, how a stopped or crashed app behaves on stage (it drops to 0, 0, 0 by the point above), the app's own PSN stream received by onPC, and the Windows case.

## Transport that worked

| Setting | Value |
| --- | --- |
| Destination | multicast `236.10.10.10`, UDP port `56565` |
| onPC PSN Interface | `lo0` (127.0.0.1), when the sender runs on the same Mac |
| Sender multicast interface | `IP_MULTICAST_IF` = 127.0.0.1, TTL 1 |

Unicast to `127.0.0.1` and to the Mac's LAN IP did not register (the tracker stayed red, Position 0). Multicast via the LAN interface failed with "No route to host" on a Mac whose default multicast route went through a VPN tunnel. `netstat -gn` showed onPC joining `236.10.10.10` on `lo0`. The interface can be changed without restarting onPC. The row's **Sender IP** field could not be edited and showed "No Cable"; this looked cosmetic.

## Configure onPC

Menu paths are from MA's [PSN help](https://help.malighting.com/grandMA3/2.5/HTML/remote_inputs_psn.html) (also in `~/MALightingTechnology/gma3_2.5.0/shared/language/HTML/remote_inputs_psn.html`).

1. **Menu → In & Out → PSN.** Enable **Input** at the top and set the **Interface** to `lo0` (127.0.0.1) for onPC on the same Mac. Set multicast IP `236.10.10.10` and port `56565`.
2. Insert a tracker row under the system. Set **Tracker ID** to the ID the sender uses (1 in the test) and **MArker ID** to the MArker's CID (1 in the example). The tracker name is red until packets arrive.
3. Set **Requested** to Yes for the tracker.
4. **Menu → Patch → DMX Universes:** on the universe that holds the MArker, set **Merge Mode** to **Prio**. A row whose merge mode reads "no marker" has no MArker ID yet.
5. Run the sender and watch the 3D window. The tracker name turns from red once data arrives.

Check with `lsof -nP -iUDP:56565` that onPC listens. The System Monitor shows OSC, not PSN, so it does not help here.

## Configure the app

1. Stop output and open **Setup → Output**.
2. Set **Position output** to **PSN stream** (saved as `psn`). The PSN fields appear below it; the MArker attribute names, which only OSC commands use, are hidden. Leave the PSN tracker ID, multicast group, port and interface at their defaults when onPC runs on this Mac (tracker 1, `236.10.10.10`, `56565`, interface `127.0.0.1`), and match the tracker ID to the PSN row in onPC.
3. **Save settings**, then Start. The Live view shows a **Release marker** button while PSN is selected or a stream is open.

What changes in PSN mode: the app no longer sends `ClearSelection; MArker ...`, so your selection and encoders stay free. Brightness, zoom / iris and buttons still go over OSC, so the OSC setup in [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md) is still needed. The MArker is chosen by the PSN row in onPC, so the app's MArker CID and movement space are not used for conversion in PSN mode, but they must still be valid settings. The PSN fields are checked only while PSN is selected, and the MArker attribute names only while OSC commands are selected.

**Stop and Release marker.** PSN has no hold: if packets stop, onPC resets the MArker to 0, 0, 0. So **Stop keeps sending the last position** and the output state shows **PSN HOLDING**; **Release marker** ends the stream, and the MArker then resets to 0, 0, 0. Release marker also stops output if it is running. The Live button asks for confirmation whenever a stream is open; cancelling keeps output and streaming unchanged. A button mapped to "Release PSN marker" remains immediate. Closing the window (or Cmd-Q on macOS) also asks first when a stream is open. A joystick disconnect or an OSC failure stops output but keeps the stream holding.

**Warning:** quitting the app, closing the Terminal that launched it, a crash, or the computer sleeping all stop the stream, and the MArker then resets to 0, 0, 0 mid-show. Quitting and a crash end the stream because the process ends; closing the Terminal and sleep should do the same but were not tested.

The PSN selector and fields can still be edited while a stream is held and output is stopped, but Save settings and the stopped Reset button refuse to apply a changed PSN setting, or a changed control mode, until you Release marker. Readiness explains that blocker and disables Start and testing until you Release or revert those edits. While a stream is held and output is stopped, the Live position shows a second "Held at" line, because the applied target (changed by Reset or settings) may differ from what onPC is holding; the separate Start preview shows what pending settings will send. A stream failure (for example a socket error) closes the stream, stops output if it was running, and shows a PSN fault that stays until the next successful Start (Release marker cannot clear it, because the failed stream is already closed); the MArker resets in onPC.

PSN positions and operating bounds must fit finite float32 values, as required by the packet format. A figure-8 test's first DATA packet starts at its initial target, even after the tracked target has moved. Socket sends are bounded so a stalled network send cannot indefinitely hold up stream shutdown.

The Fixture Sheet and the MArker encoders do not show the PSN position (they read 0, 0, 0); use the 3D view or the PSN row.

## Script on a different computer (unverified)

Not tested. The same-Mac setup above is the only verified one. In principle:

1. Put both computers on the same network segment. PSN is multicast UDP, so the switch or Wi-Fi must pass multicast (IGMP snooping misconfigured, or Wi-Fi multicast filtering, are common causes of silence).
2. In onPC, set the PSN **Interface** to onPC's network interface instead of `lo0`, and keep the multicast group and port.
3. In the app, set **PSN interface** to this computer's IPv4 address on that same network (not `127.0.0.1`).
4. OSC still needs its own setup: set **onPC host / IP** and the OSC Interface as in [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md) Step 8.
5. A VPN can take the default multicast route. On the test Mac, sending multicast through the LAN interface failed with "No route to host" because the default multicast route went through the VPN tunnel; disconnect the VPN or add a multicast route for the interface.

Check with `lsof -nP -iUDP:56565` on the onPC computer and watch the tracker in the PSN menu.

## Troubleshooting

- **Tracker stays red:** check the PSN Interface in onPC against the app's PSN interface, that the tracker ID matches the app's PSN tracker ID, that the row's MArker ID is the MArker's CID, and that **Input** is enabled. Confirm the app is streaming (Start, or a held stream after Stop).
- **The MArker moves, then jumps to 0, 0, 0:** the stream stopped. Release marker was pressed, the window was closed, the app stopped, or a PSN fault was shown in Diagnostics.
- **Nothing moves although the tracker is not red:** check **Requested** on the tracker and that the universe's **Merge Mode** is **Prio**.
- **A PSN fault reports "No route to host" or the stream fails right after Start:** the multicast route for the chosen interface is wrong (the send happens on the stream thread, so this appears as a PSN fault just after Start, not as a Start error); see the VPN note in the previous section. Start itself reports an error only if the socket cannot be opened or the interface address is invalid.
- **The Live "Held at" position changed after a failed Start:** Start sends the position before the OSC brightness send, so a Start that fails on OSC can move the held position. The stream stays open and "Held at" shows the current position; Release marker if that is not wanted.

## Test sender

`tools/psn_test_sender.py` is stdlib-only and sends no OSC. Run it on the same Mac as onPC:

```sh
python3 tools/psn_test_sender.py --iface 127.0.0.1 --pattern axes --seconds 30
```

Patterns: `static` (hold `--home X Y Z`, default 0 0 1.5), `circle`, and `axes` (6 s hold, then x, y and z swept by `--radius` for 6 s each, to tell the axes apart). Other options: `--dest`, `--port`, `--tracker`, `--rate` (default 30 Hz), `--seconds`. Invalid addresses, ports, tracker IDs, durations, rates or non-finite/unrepresentable coordinates are rejected before opening a socket or sending any packets.

## Packet format (for the implementation)

PSN v2.03, UDP, little-endian chunks. A chunk header is a uint32: `id | (data_length << 16) | (has_subchunks << 31)`.

- **DATA** packet `0x6755`: header chunk `0x0000` (uint64 timestamp in microseconds, version high 2, version low 0, frame id, frame packet count), then tracker list `0x0001` containing one chunk per tracker (chunk id = tracker id) with a POS chunk `0x0000` of three float32 values in metres.
- **INFO** packet `0x6756`: header `0x0000`, system name `0x0001`, tracker list `0x0002` containing name chunks `0x0000`. The test sender repeats it at 1 Hz.

The app's encoder produces the same bytes as the verified `tools/psn_test_sender.py` for the fixed inputs pinned in `tests/test_psn.py`. (The test sender's layout was cross-checked against the PSN-CPP reference decoder during the investigation; the app itself was not decoded with it.)

## Open risks

- The MArker snap-back timeout was not measured, so how long a stalled app can go without the marker resetting is unknown.
- macOS App Nap or background throttling could delay the sender thread beyond that timeout; the thread is not proven immune. Keep the Live view in front during shows.
- Whether PSN wants separate frame counters for INFO and DATA (the app and the test sender share one), and whether onPC applies its Map or offset to the received metres, were not checked.
- Absolute-metre positions were checked at a few points only; the Movement Space bounds may still matter at extremes.

## Remaining work

The app is covered by automated tests, including Release-button visibility and PSN-field error navigation. The default position output is OSC, as stated above. Automated coverage does not establish onPC reception, fixture movement or long-run/background reliability.

The [acceptance record](ACCEPTANCE.md) is the single checklist for the app's own stream, physical joystick, Stop/Release/close and Cmd-Q, Setup → Output and Live visuals, long-running/background streaming, snap-back timing, another-computer setup and Windows. The verified test-sender findings above remain separate from those pending app checks.

Remaining behavior to keep in mind: a mapped Release press with no stream replaces routine status text; PSN group validation accepts any IPv4 multicast address. Cmd-Q during a failed-settings dialog and reentrant close-confirmation behavior still need explicit checks in the acceptance record.
