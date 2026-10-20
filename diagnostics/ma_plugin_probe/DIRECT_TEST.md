# Stage 3: direct output inside MA

This finite research test checks whether MA's `SetProgPhaser()` API can move
the configured MArker without changing the operator's fixture selection or
encoder context. See the [reason for this test](DIRECT_OUTPUT_RESEARCH.md).
This is not the finished followspot plugin.

The operator has confirmed direct movement in onPC 2.5.1.0; selection/grid and
encoder context were retained in the report. They also observed the lights
reach 100% from a 0% Master, exposing an early readback check: the old probe
read 0% immediately and aborted before XYZ started. Version **0.3.1.0** waits
up to one second for brightness readback, then starts the full motion cycle.
The operator confirmed the combined one-press run with that timing fix. See
[the recorded results](../../docs/ACCEPTANCE.md).

Import only [FollowspotDirectTest.xml](FollowspotDirectTest.xml). It contains
all its Lua and motion frames. No Python process, joystick, OSC or PSN is used
at runtime. The builder uses the existing app's `figure_eight()` to generate
the frames from a read-only settings snapshot.

The current personal package targets **MArker 1**, one **10-second** cycle,
**X −15 to +15 m**, **Y −7.5 to +7.5 m**, **Z 1.5 m**. An optional separate
choice sets the **Master to 100% on Page 1 / Executor 201**. Zoom/iris, mapped
buttons and pan/tilt are outside this probe.

## Run in a test show

1. Stop the followspot app output and **Release marker** if a PSN stream is
   holding. Stop any standalone PSN sender. In MA, disable **In & Out → OSC →
   Enable Input** for this test. This proves that any movement comes from the
   direct Lua path. The plugin does not change OSC or PSN configuration itself.
2. Use the already working show with its existing moving MArker 1. Keep
   **Blind and Preview off**, and **Program Time off**. Do not run patch or
   programmer changes during the test. The plugin does not alter those modes,
   create fixtures or assign lights to the MArker.
3. Import `FollowspotDirectTest.xml` into an unused Plugins pool cell, as with
   the previous movement test. Its pool name is **Followspot Direct Test**.
   After updating the XML, re-import it: copying a file does not update an
   already imported pool object. New reports include `probe_version=0.3.1.0`.
4. Select an unrelated fixture and an encoder feature such as Focus. Remember
   the selection and feature. Open the 3D view, tap the plugin and choose
   **Run XYZ only**. Watch the MArker and check that selection and encoder
   context stay unchanged. Do not deliberately change them while it runs:
   the probe treats a change as a reason to stop. This choice leaves brightness
   untouched; it can be checked even with the lights dark.
5. After the cycle, the summary reports the exit reason, selection/encoder
   preservation and programmer readback. **`reason=completed` means the API
   and readback completed; visible movement still needs your observation.**
   The final target is approximately the initial (0, 0, 1.5) m.

The essential result is: **does the MArker move with OSC disabled, while the
unrelated fixture selection and encoder feature remain unchanged?** A second
run with no fixtures selected checks startup without any selection.

## Other choices and Stop

- **Inspect only** resolves the MArker, XYZ channel indices and existing
  programmer data and saves a report. It sends no output. Use this if Run
  reports a missing target, channel or API.
- **Run XYZ + brightness** additionally resolves the saved page/executor's
  assigned object and sets its `FaderMaster` directly. Its level must read back
  correctly before XYZ motion starts. The probe sends the level once and polls
  for up to one second, yielding to let MA apply it. Stop or a changed target
  during this wait prevents XYZ from starting; a timeout reports the requested
  and last observed brightness. Settling does not shorten the figure eight or
  skip its initial target. This checks brightness separately from XYZ-only
  mode; the executor must already be configured for brightness.
- **Cancel** sends nothing and creates no report folder.
- To test early Stop, start a cycle, then execute
  `Off Plugin "Followspot Direct Test"`. The report should say
  **`reason=requested_stop`**, and movement should stop. Real MA cleanup
  dispatch remains unverified until this is observed.

Completion, Stop and errors retain the last written XYZ and optional
brightness. There is no automatic restore, blackout or programmer clear. The
probe writes only the MArker's three XYZ channels and, when explicitly chosen,
the brightness object's Master. Existing data on those XYZ channels may be
replaced or merged by MA's API; the report records their before/after data.
Use a test show. It does not remove unrelated programmer values or restore a
selection changed by the operator or host API.

## Reports and interpretation

Each accepted run creates a new folder:

```text
~/MALightingTechnology/gma3_library/followspot_direct_tests/run.<unique-id>/
```

- `report.txt`: exact onPC/Lua version, target and channel resolution, existing
  XYZ programmer data, last readback, exit reason, selection and encoder
  comparisons, and optional brightness request/readback/wait duration. Total
  elapsed time includes brightness settling; the motion timestamps below start
  when XYZ begins.
- `writes.tsv`: elapsed time, XYZ in metres and the percentages written.
  Present only when a motion run reached output setup.

`readback_matches=pending` means the most recent frame has not been fully
verified (for example, Stop or a write failure interrupted it). Earlier
`last_readback` entries are not confirmation of that partial frame.

Missing APIs/targets or a readback mismatch produce **`reason=error`** and a
specific error. A selection/grid or encoder-context change also stops further
writes. The target handle, subfixture index and channel indices are checked
between updates to avoid continuing after a patch change. A scheduling gap
over 0.25 s produces **`reason=timing_gap`** rather than jumping to a later
position. These checks do not make Lua a real-time control system.

If readback matches but 3D does not move, record that distinction and the
report. Check the existing MArker patch, movement space, Blind/Preview/timing
and competing playback/PSN input; do not assume a transport failure. This
probe uses the saved Movement Space bounds for percent conversion, as the
working OSC test did. It does not yet resolve those bounds automatically.

## Build and offline verification

```sh
python3 diagnostics/ma_plugin_probe/build_direct.py --settings settings.json
python3 -m unittest discover -s diagnostics/ma_plugin_probe -p 'test_*.py' -v
```

The personal XML is ignored by Git and the source settings are never written.
The builder refuses to overwrite its input, including through an alias.
The tests decode the actual XML and run its real Lua/coroutine in a stock Lua
interpreter. Only MA's host APIs are doubled. They cannot establish MA API
semantics, physical beam behavior or MA's actual cleanup dispatch.

Executed checks and pending operator observations belong in
[ACCEPTANCE.md](../../docs/ACCEPTANCE.md).
