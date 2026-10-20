# Experimental MA plugin diagnostic

For the separate real-output stage, see [Stage 2: visible MArker movement](MOVEMENT_TEST.md).
For the next test without OSC, see [Stage 3: direct output inside MA](DIRECT_TEST.md).
For the finished plugin's output architecture investigation, see
[Direct show output research](DIRECT_OUTPUT_RESEARCH.md).

This is a **synthetic-input research diagnostic for grandMA3 onPC 2.5 on macOS**.
Import only `FollowspotDiagnostic.xml`. The XML includes its Lua code and Python
emulator; the other files are for development. Python 3.10+ must already be
installed. Tk, SDL2 and a joystick are not needed.

The diagnostic generates axis, slider, zoom-axis and button samples in its own
helper process. It sends **no OSC, PSN, fixture, fader or button commands**, opens
no input devices and does not read or change the followspot app's settings. It
does not create an OS-level virtual joystick or establish real HID permissions.

Executed offline and operator checks, including their limits, are recorded in
the [acceptance record](../../docs/ACCEPTANCE.md#recorded-evidence). This is not
the followspot application converted into a plugin.

## Import and run

1. Copy [FollowspotDiagnostic.xml](FollowspotDiagnostic.xml) into:

   ```text
   ~/MALightingTechnology/gma3_library/datapools/plugins/
   ```

2. Launch MA normally and use an empty test show. No fixture patch or OSC/PSN
   configuration is needed. Do not use the earlier experimental startup flags.
3. Open **Add Window → More → System Monitor** to see the synthetic samples.
4. Open a Plugins pool. Edit an unused plugin cell, choose **Import**, select
   the internal drive and `FollowspotDiagnostic.xml`, and import it. Close the
   editor and tap **Followspot Diagnostic** in the pool. A separate `.lua` file
   is not required. See [MA's import instructions](https://help.malighting.com/grandMA3/2.5/HTML/plugins.html).
5. Choose **1 Run emulation**. The Python executable field is prefilled from
   common python.org/Homebrew locations. If needed, enter the full executable
   path, for example `/opt/homebrew/bin/python3`.
6. Watch System Monitor for **helper ready**, followed by changing `X`, `Y`,
   `slider`, `zoom` and `buttons`. After about four seconds of samples, expect a
   summary with **PASS: normal** and **reason=completed**. MA/import or startup
   failures may instead produce an error or a FAIL summary; report that result.

The generated input follows this sequence; the buttons are data only:

| Approximate helper time | X / Y | Slider | Zoom axis | Button mask |
| --- | --- | --- | --- | --- |
| 0–1 s | 0 / 0 | 25% | 0 | 0 |
| 1–2 s | +0.75 / −0.50 | 60% | +0.50 | 1 |
| 2–3 s | 0 / 0, centre held | 60% | 0 | 0 |
| 3–4 s | −0.75 / +0.50 | 80% | −0.50 | 2 |

No light or on-screen MArker is expected to move during these tests.

## Additional checks

Tap the plugin again for each test:

- **2 Watchdog test:** Lua deliberately stops renewing the helper's lease. A
  PASS summary should report `reason=lease_expired`, usually within a few seconds.
- **3 Reader fault test:** The emulator deliberately fails. A PASS summary
  should report `reason=injected_fault`; PASS means the expected failure was
  observed, not that real hardware was tested.
- **MA cancellation:** Start **1 Run emulation**, then execute
  `Off Plugin "Followspot Diagnostic"` while samples are running. In the latest
  run folder, `helper-report.txt` should show `reason=requested_stop`. A
  `lease_expired` result instead shows the watchdog worked, but MA's cleanup
  callback was not established. This manual check has not been verified.

Every helper has a maximum run duration of eight seconds; the UI uses about four
seconds. The watchdog and stop files apply only to the helper's own run token.
The diagnostic never searches for or kills other processes.

**This shutdown policy is for synthetic tests only.** A future real PSN helper
must distinguish Stop from Release and preserve the existing held stream.

## Reports and troubleshooting

Each run prints its report folder in System Monitor and in its final pop-up:

```text
~/MALightingTechnology/gma3_library/followspot_diagnostics/run.<unique-id>/
```

- `report.txt`: MA-side result, observed updates and runtime capabilities.
- `helper-report.txt` / `result.json`: helper's actual exit reason and sample count.
- `reader.log`: Python/shell startup errors.
- `capabilities.txt`: Lua version, host and process/library-loading capabilities.

The diagnostic creates these files and leaves them available for inspection. It
does not alter existing MA configuration. Deleting the pool object does not
delete the report folders. A cancelled run may leave `report.txt` saying STOP
REQUESTED; use the helper's report to confirm its actual exit.

If an import fails, the component turns red, or no starting pop-up appears,
record MA's exact message and version. If Python fails to launch, inspect
`reader.log` and check the executable path. This emulation should not require
Input Monitoring access; do not change privacy settings for this diagnostic.

## Build and offline verification

From the project root:

```sh
python3 diagnostics/ma_plugin_probe/build.py
python3 -m unittest discover -s diagnostics/ma_plugin_probe -p 'test_*.py' -v
```

The process tests run real Python subprocesses, including stop, lease expiry,
injected failure and duplicate rejection. With a local Lua interpreter, the
package check decodes the XML and executes its included Lua and Python from a
temporary folder. Only MA's platform and pop-up APIs are doubled in that check;
it cannot establish real MA behavior. Lua absence produces an explicit skip.
