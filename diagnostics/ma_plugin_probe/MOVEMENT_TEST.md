# Stage 2: visible MArker movement

`FollowspotMovementTest.xml` is a separate **real-output test** for grandMA3
onPC 2.5 on macOS. It launches its embedded Python helper and runs one figure
eight using the followspot app's controller and OSC encoder. No joystick,
Tkinter or SDL2 is required. Python 3.10+ is required, as in the synthetic test.

The operator's successful movement result and remaining checks are recorded in
the [acceptance record](../../docs/ACCEPTANCE.md#recorded-evidence).

The package contains a snapshot read from the project's `settings.json` when
built. It does not reread that file when imported or run, and never edits it.
Device identity and button mappings are excluded. The personal XML is ignored
by Git; rebuild and reimport after changing settings.

This stage supports the saved **MArker + OSC** path. The builder rejects PSN
or pan/tilt settings and periods longer than 30 seconds. Zoom/iris and joystick
buttons are not exercised. It does not patch fixtures, create an executor or
change the show's fixture-to-MArker assignments.

## Import and run

1. Stop output in the followspot app. Use a test show with your existing MArker,
   fixture-following assignments and brightness executor. Follow the
   [MA setup guide](../../docs/GRANDMA3_SETUP.md) if these are not ready.
2. Enable the configured OSC input as described in
   [Step 8](../../docs/GRANDMA3_SETUP.md#step-8-enable-osc-input). Turn on
   **EchoInput** and open **System Monitor**, plus a **3D** window where the
   MArker and lights are visible.
3. Import `FollowspotMovementTest.xml` from the internal drive into an unused
   Plugins pool cell, using the same import procedure as the
   [synthetic diagnostic](README.md#import-and-run). The file belongs in:

   ```text
   ~/MALightingTechnology/gma3_library/datapools/plugins/
   ```

4. Tap **Followspot Movement Test**. Read the preview: it shows the actual
   MArker ID, OSC address, path limits, height, duration and brightness executor
   embedded in this package. Keep the Python path that worked in stage 1.
5. Choose **Run movement test**. It sends the initial target and saved test
   brightness, then moves the target at about 30 Hz for one figure-eight cycle.
   The current operator package uses **MArker 1**, OSC **127.0.0.1:8000**, X
   **−15 to +15 m**, Y **−7.5 to +7.5 m**, **Z 1.5 m**, **10 seconds**, and
   **100% on Page 1 / Fader 201**. Movement-space conversion uses the saved
   bounds, so these must match the actual MArker Movement Space in MA.
6. Watch all three boundaries: changing X/Y in the plugin's monitor messages,
   incoming `/cmd` messages from **EchoInput**, and visible MArker/beam movement
   in **3D**. The final **SENT** summary proves only that the helper completed
   its sends. It does not prove MA received or accepted them.

Normal completion ends at the configured initial X/Y, at the fixed Z height.
MA retains the final target and brightness; the test does not restore the
previous programmer state or blackout the executor. To stop early, use:

```text
Off Plugin "Followspot Movement Test"
```

The cleanup function requests a stop. If MA stops dispatching the plugin
without cleanup, the helper stops after its 1.2-second lease expires. Every
helper also has a finite runtime limit. Real MA cancellation dispatch remains
an operator check; a stopped test retains its last target and brightness.

## If nothing moves

- **No changing plugin samples / no helper ready:** inspect `reader.log` in the
  report folder. This is a helper/startup boundary.
- **Samples change but no incoming EchoInput:** inspect the OSC interface,
  destination IP, port and duplicate rows in
  [Step 8](../../docs/GRANDMA3_SETUP.md#step-8-enable-osc-input). Successful UDP
  sends alone cannot establish reception.
- **EchoInput arrives but MA rejects commands:** record the exact error and
  command in System Monitor. `sent.jsonl` records every successfully sent
  address/value; do not change unrelated fixture setup to fix reception.
- **Commands are accepted but the MArker is static or moves incorrectly:**
  compare the configured ID, XYZ attribute names and Movement Space with
  [Steps 2–4](../../docs/GRANDMA3_SETUP.md#step-2-patch-the-marker).
- **MArker moves but beams do not:** check
  [fixture following](../../docs/GRANDMA3_SETUP.md#step-5-point-the-followspots-at-the-marker)
  and the [brightness executor](../../docs/GRANDMA3_SETUP.md#step-6-store-the-followspot-cue-on-an-executor).

Each run prints its report folder:

```text
~/MALightingTechnology/gma3_library/followspot_movement_tests/run.<unique-id>/
```

`report.txt` is the MA-side summary; `helper-report.txt` / `result.json` contain
the exit reason and successful-send count. `sent.jsonl` contains the sent OSC
commands and fader value. `reader.log` contains startup errors. The run's
`settings.json` is the embedded snapshot, not the operator's source file.

Record the onPC version, report folder, any System Monitor error, and whether
the MArker, beams and fader each moved in the
[acceptance record](../../docs/ACCEPTANCE.md#console-and-physical-input).

## Rebuild and offline checks

From the project root:

```sh
python3 diagnostics/ma_plugin_probe/build_movement.py --settings settings.json
python3 -m unittest discover -s diagnostics/ma_plugin_probe -p 'test_*.py' -v
```

Copy the rebuilt XML to the import folder and reimport it. Importing only the
XML is sufficient; it contains Lua, the Python helper, the app core and the
settings snapshot. Offline movement checks intercept every network send and
cannot establish real onPC reception or movement.
