# Joystick Followspot — grandMA3 plugin

One importable XML brings the controller into **grandMA3 onPC on macOS 2.5**.
It embeds the project's Python input/motion code and opens a native MA control
panel. Python **3.10+** must be installed on the same Mac; Tk, signing and
third-party Python packages are unnecessary. The Windows standalone app is
separate; this plugin's launcher is macOS only.

The native output APIs and combined brightness/XYZ startup were confirmed by
the operator in onPC **2.5.1.0** with the direct diagnostic. The complete
plugin is covered offline; physical joystick input from the MA-launched
helper, actual PSN from this package, native layout and long-running operation
still require operator acceptance. See [ACCEPTANCE.md](ACCEPTANCE.md).

## Import and first run

The prepared personal file is in MA's usual import folder:
`~/MALightingTechnology/gma3_library/datapools/plugins/JoystickFollowspot.xml`.

1. Import **JoystickFollowspot.xml** into an unused Plugins pool object. Its
   name is **Joystick Followspot**. Only the XML is needed; embedded source
   files are extracted automatically. After a package update, re-import into
   that object; copying a new XML does not update an existing pool object.
2. Tap the plugin. Output always starts **stopped**. The helper starts in the
   background; no separate Tk window opens. If Python cannot launch, open
   **Diagnostics**, enter its full executable path and click **Reconnect helper**.
   The path is remembered on this Mac. The python.org installer normally gives
   `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`.
3. In **Target**, choose **MArker** and **direct**. The personal package is
   seeded from the existing app configuration. Confirm the MArker CID, fixed
   height, initial/reset position, travel limits and Movement Space bounds.
   **Read MA movement space** copies the configured MArker's space bounds into
   the draft when MA exposes them; it does not edit the patch. Review and Save.
4. In **Levels**, confirm the brightness page/executor. The current personal
   mapping is Page 1 / Executor 201, whose assigned object in the test show
   was Sequence 901. The executor number and sequence number need not match.
   The brightness object must have a running cue containing the followspots'
   dimmer values. The plugin controls its **Master**. Optional zoom/iris uses
   a separate object's **Temp** fader; configure its cue as in
   [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md#optional-zoom--iris-executor).
5. Use **Test figure eight** on Live or Diagnostics. No joystick is required.
   It sends real output for one configured cycle and then stops/holds. Test
   brightness is fixed; normal Start uses the live joystick slider. Check
   the Live Start preview before either action.
6. Open **Joystick**, click **Refresh**, cycle the device button to the desired
   entry and click **Open chosen device**. Refresh closes the old input before
   enumeration. Choose explicitly even for identically named controllers.
   Use Learn beside each axis, move only that control, then Save. Release the
   stick before **Calibrate X / Y**. Raw axes/buttons appear in the status area.
7. Save settings, review Live, and **Start output**. Returning the stick to
   centre holds the tracked position. All MA fixture assignments, geometry,
   patch and aiming remain in the show.

Direct MArker position uses indexed programmer channels without selecting the
MArker. Brightness, zoom/iris and mapped MA commands use internal MA APIs.
**No OSC input row, host, port, prefix or FaderRange setup is required.**
Fader changes are asynchronous: the plugin sends changed levels without an
immediate readback assertion. It does not repeatedly resend idle levels.

## Pages and settings

- **Live:** tracked target and requested levels, applied output state, pending
  Start information, input readiness and PSN hold. These are controller targets,
  not measured fixture/beam positions.
- **Joystick:** axis learning, inversions, radial dead zone, proportional speed
  and centre offsets. Dead zones display as percentages and persist as fractions.
- **Target:** MArker or pan/tilt group, direct or PSN position output, operating
  bounds and initial values. Inactive settings are hidden. Use **Next settings
  page** for additional fields. Movement Space and operating limits differ.
- **Levels:** brightness Master, optional zoom/iris speed axis, its dead zone,
  centre, initial level and Temp executor. Centre holds the zoom/iris level.
- **Buttons:** learn/index a button, choose MA press/release commands or a local
  action, then **Add / update**. **Load mapping**, **Remove mapping** and
  **Discard editor** manage the editor explicitly. Uncommitted editor changes
  block Save/Start. A saved mapping list appears below the editor.
- **Diagnostics:** finite test size/period/brightness, reset lock, Python path,
  helper reconnect and release-warning acknowledgement. Faults remain visible
  independently of routine messages.

Setup remains readable during output. Editing, Save, learning and calibration
require Stop. Start validates/applies the whole draft; invalid input remains
available for correction. Reset is locked while running by default. The Live
reset-lock toggle saves only the lock, preserving other draft edits. Reset
uses applied settings to return target and enabled zoom/iris to their initial
values, leaving brightness. Save edited initial values before using Reset.

Settings live in a namespaced **UserVar in the current MA show/user profile**.
Save the MA show to preserve them across reload. They do not overwrite the
standalone app's `settings.json`. A newly imported package seeds defaults only
when that user variable does not exist. Python path preference stays on the
computer. Changing MA show/user context ends this helper; reopen the plugin.

Mapped local actions follow the standalone app's priority: Stop/Release beat
Start and Reset; Start beats stopped Reset. Held-at-Start buttons do not become
new presses. Learning suppresses actions. MA commands remain ordered and
queued until Lua processes them; Stop cancels pending presses and attempts
releases for owned actions. Failed releases stay visible; clear the action in
MA before acknowledging the warning.

## Optional PSN

Set Target → position output to **psn**. Only XYZ uses PSN; faders and button
commands stay internal. The existing same-Mac defaults are tracker 1,
multicast `236.10.10.10:56565`, sender interface `127.0.0.1`. MA still needs its
PSN input/interface, tracker-to-MArker mapping and priority/merge setup; follow
[PSN.md → Configure onPC](PSN.md#configure-onpc). The plugin does not silently
change In & Out settings or create patch objects.

**Stop holds the last PSN position** by keeping the existing background stream
open. Live shows **PSN HOLDING**, including the actual held XYZ separately from
the pending target. **Release PSN** requires two clicks: first arms the inline
confirmation, second closes the stream. Cancel confirmation leaves it held.
Mapped Release is immediate. Closing with a held stream uses the same inline
two-click confirmation. Changed PSN/control-mode fields cannot be applied until
the held stream is released; other stopped edits remain possible.

`Off Plugin "Joystick Followspot"`, forced host/UI teardown, a helper crash or
lease expiry ends streaming. MA may then return the MArker to origin. The
normal UI Close/Release confirmation does not protect an unconditional Off or
host crash. A joystick disconnect stops input but preserves an existing hold;
an actual PSN send error closes the failed stream and stays visible.

## Pan / tilt and programmer limitations

Pan/tilt preserves the existing group-based behavior, using internal MA
`ClearSelection; Group ...; Attribute ...` commands. It **changes selection**;
Live makes this explicit. PSN applies only to MArkers. Pan/tilt syntax/range,
fixture mode switching, and its real-show behavior remain operator checks.

Direct MArker writes preserve selection but still use the programmer. Blind,
Clear, Program Time, Store, relative/phaser data and playback priorities affect
those values. Do not use the controller as an isolated playback engine. Set up
the show deliberately; the plugin never clears unrelated programmer data or
changes those global modes. A late input sample integrates at most the existing
quarter-second cap. Lua/UI scheduling is not a real-time guarantee.

## Reports, updates and development

The helper owns a unique folder under:

```text
~/MALightingTechnology/gma3_library/joystick_followspot/run.<id>/
```

`reader.log` contains Python startup errors. `status.json` contains the latest
owner/version, configuration, raw input, output state, faults and exit reason.
The panel prints the run folder in System Monitor. A shared lock prevents two
helpers from running on this computer for the same plugin data directory.
No process search or blanket process-kill commands are used. With no MA
heartbeat for about three seconds the helper closes its resources and exits.
Button releases cannot be guaranteed after a host crash; inspect held actions.

Build from the project folder (Python settings are read only):

```sh
python3 ma_plugin/build.py --settings settings.json
python3 -m unittest discover -s tests -p 'test_plugin_*.py' -v
```

The generated personal XML is Git-ignored. Build with `settings.example.json`
for shareable defaults. Verification intercepts network/device boundaries;
it must not transmit output to the operator's real show. The complete plugin's
MA layout, physical joystick, PSN reception/hold/release and long-running
reliability remain explicit operator checks in [ACCEPTANCE.md](ACCEPTANCE.md).
