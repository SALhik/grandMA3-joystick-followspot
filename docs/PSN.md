# PSN: moving the MArker without taking the selection

Status: **researched and verified with a test sender; not yet an output mode in the app.** Today the app moves the MArker only through OSC (see [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md)). This page records what was found on 2026-10-14 so a PSN output option can be built and configured from it.

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

Not verified: PSN with the real joystick, use in a real theatre show, how a stopped or crashed app behaves on stage (it drops to 0, 0, 0 by the point above), and the Windows case.

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

## Test sender

`tools/psn_test_sender.py` is stdlib-only and sends no OSC. Run it on the same Mac as onPC:

```sh
python3 tools/psn_test_sender.py --iface 127.0.0.1 --pattern axes --seconds 30
```

Patterns: `static` (hold `--home X Y Z`, default 0 0 1.5), `circle`, and `axes` (6 s hold, then x, y and z swept by `--radius` for 6 s each, to tell the axes apart). Other options: `--dest`, `--port`, `--tracker`, `--rate` (default 30 Hz), `--seconds`.

## Packet format (for the implementation)

PSN v2.03, UDP, little-endian chunks. A chunk header is a uint32: `id | (data_length << 16) | (has_subchunks << 31)`.

- **DATA** packet `0x6755`: header chunk `0x0000` (uint64 timestamp in microseconds, version high 2, version low 0, frame id, frame packet count), then tracker list `0x0001` containing one chunk per tracker (chunk id = tracker id) with a POS chunk `0x0000` of three float32 values in metres.
- **INFO** packet `0x6756`: header `0x0000`, system name `0x0001`, tracker list `0x0002` containing name chunks `0x0000`. The test sender repeats it at 1 Hz.

The encoder was cross-checked by decoding its packets with the PSN-CPP reference library.

## Open decisions for an app output mode

- Keep brightness and zoom/iris on OSC faders; PSN would carry position only.
- PSN needs continuous sending (about 30 Hz) even when the stick is idle, which reverses the OSC rule of no idle resend. Stopping output stops the stream and the MArker returns to 0, 0, 0 unless Stop keeps sending the held position.
- AGENTS.md (integration contracts), the setup guide and the settings example would change with it.
