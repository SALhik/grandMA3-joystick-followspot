# Operating guide

How to configure the joystick and run the tool once onPC is set up (see [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md)). Settings are saved to `settings.json` beside the script; `settings.example.json` is a shareable example and is not loaded automatically.

## Window layout

**Live** shows the tracked target on a read-only top view of the applied operating limits, its X/Y/Z coordinates, brightness and zoom/iris. Positive Y is at the top; the drawing keeps the same scale on both axes. It is not a fixture view or feedback from MA. While stopped, brightness is a preview of the current slider; during output it shows the last level sent. Start sends the current slider level, which may differ from MA's fader.

**Setup** contains Joystick, Target / stage, Brightness / zoom, OSC and Buttons. These remain readable during output, with editing disabled. Scroll a page to see additional settings. **Diagnostics** contains raw input readings, the figure 8 test and OSC reception guidance. Input readings are ignored during a test.

Start/Stop and the output state remain visible in every view. Start is disabled when no joystick is selected, mappings are unusable, learning is active or edits are invalid/incomplete. The explanation appears beside the output state. Figure 8 testing needs no joystick.

## Configure the joystick

1. In **Setup → Joystick**, select the PXN joystick. Click **Refresh** after connecting or reconnecting it.
2. Use **Learn** beside X, Y and Brightness. Move only the intended control after clicking. Axis numbers start at zero. The initial 0/1/2 mappings are placeholders; a flight stick's slider may be axis 3 rather than 2.
3. Release the stick and click **Calibrate stick centre**. Set inversion, centre dead zone (shown as a percentage; default 10%) and maximum speed. Input previews use the draft axis mappings, and learning/calibration feedback appears beside the control. Captured offsets are under **Advanced calibration offsets**. Default speed is 1 m/s; a half deflection beyond the dead zone moves at half the maximum speed. Diagonal travel has the same maximum speed as horizontal/vertical travel.
4. In **Setup → Target / stage**, enter the MArker CID, Z height, operating limits and initial X/Y. Operating limits restrict joystick travel and may be smaller than the full movement space.
5. In **Setup → OSC**, set the host, port and prefix. In **Setup → Brightness / zoom**, set the brightness executor page/number. The default marker attribute names are `XYZ_X`, `XYZ_Y`, `XYZ_Z`; confirm them with `List Attribute` if your fixture library differs.
6. Optionally configure buttons and zoom/iris (below), click **Save settings**, check **Live**, then click **Start output**.

Start also applies and saves the displayed settings. It immediately sends the displayed target, the current brightness and the enabled zoom/iris level. It does not read the fixture's position or fader levels from onPC.

## Buttons

In **Setup → Buttons**, click **Learn button**, press the desired button, and choose **Action on press**. Choose **MA command** to enter press/release commands, or **Start output**, **Stop output**, **Toggle output** or **Reset target** to control this program. Click **Add / update mapping**, then **Save settings**. The editor explains when either step remains pending. Save/Start and selecting another mapping cannot discard unfinished editor changes; use **Discard editor changes** to revert the editor deliberately. Default mappings are empty. MA command examples:

| Action | Press | Release |
| --- | --- | --- |
| Run next cue | `Go+ Sequence 10` | empty |
| Run a macro | `Go+ Macro 5` | empty |
| Held flash | `Flash On Executor 1.202` | `Flash Off Executor 1.202` |

Commands execute as entered. MA commands are sent only while output runs. Each mapping chooses one action; local actions do not also send MA commands, and they fire once per press. Stop performs the same button-release cleanup as the window button.

Priority and held-button rules:

- For simultaneous local presses, Stop takes priority. While stopped, Start takes priority over Reset.
- Start is ignored when already running. Toggle acts as Stop when running and Start when stopped.
- Reset obeys the same Live lock as the window button (see below).
- A button already held when you connect, apply settings or Start is ignored until it is released and pressed again, including after a failed Start.
- Learning suppresses local actions, including the press that completes learning.

## Reset and the Live lock

**Reset target + zoom/iris** returns to the initial X/Y, the configured Z and the initial zoom/iris level. While stopped, this is local; Start sends those values. The window button first saves and applies edited settings. A joystick button mapped to Reset uses the last applied settings and never saves edits.

In **Live**, **Lock reset while running** is enabled by default. Uncheck it to allow an immediate reset during output; brightness is retained and output keeps running. The lock can be changed while running and is saved immediately, without applying other settings drafts. Centre both controls to hold the reset values; deflected controls continue changing them on later polls.

## Optional zoom / iris control

In MA, assign a separate sequence containing only zoom or only iris values for your followspot fixtures to an executor. Set its fader function to **Temp**. The full MA-side steps are in [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md#optional-zoom--iris-executor).

In the tool, while stopped, open **Setup → Brightness / zoom**, enable the axis and use **Learn** while moving only the intended control. It must be separate from X, Y and brightness. Release it and click **Calibrate zoom / iris centre**. Set **Invert** if needed, its dead zone (in percent), maximum speed and executor page/number. The executor must differ from the brightness executor, and OSC **FaderRange** remains **100**.

The default initial/reset level is **50%** and the default maximum speed is **50 percentage points/s**. Full deflection changes the tracked level by 50 points per second; half deflection beyond the dead zone changes it by 25. Centre holds the current level. The tool clamps it to 0–100%, sends changes rounded to 0.1%, and limits delayed samples to a quarter-second of change. **Live** displays the tracked level. Save/apply and Stop/Start keep that level; changing the initial setting takes effect on Reset or relaunch. Manual MA fader moves do not update the tracked value.

## Test mode (no joystick)

To check onPC without a joystick, open **Diagnostics**, set size, seconds per lap and test brightness, then click **Start test (figure 8)** (`test_size`, `test_period`, `test_brightness` in `settings.json`). The marker traces a figure 8 around the initial target, stays inside the operating limits, and the brightness executor is held at the test brightness. The joystick is ignored during a test. **Stop output** ends it and keeps the last position. The test is labeled **sends real output** because it sends real OSC to onPC like normal output.

## Stop and restart

**Stop** sends release commands for buttons this tool pressed, stops transmitting, and keeps the current target and zoom/iris level in memory. It does not clear the programmer, release the MArker, blackout the lights or move them home. Resume with Start. Closing the window attempts button releases and stops output.

On a joystick disconnect or read failure, output stops and the joystick is closed: reconnect, Refresh, then Start. On an OSC send failure, output stops but the joystick stays selected: correct the network problem shown in the status, then Start. Output never resumes automatically. Relaunching restores your saved initial X/Y, Z and zoom/iris level; review those before enabling.

Faults stay visible below the views and in Diagnostics, independently of routine status messages. Successful reconnect, settings save or output restart clears the corresponding fault. Failed button releases remain visible even after restarting: check and release the held actions in onPC, then use **Acknowledge release warning** in Diagnostics.

## Settings file

Existing settings load without migration: a missing `zoom_enabled` defaults to `false`, a missing `reset_locked` to `true`, and button mappings without `action` remain MA commands. Local mappings use an action, for example `"0": {"action": "toggle"}`; valid actions are `command`, `start`, `stop`, `toggle` and `reset`.

Stop output before editing settings. **Unsaved changes** marks drafts, including unfinished button editor changes; **Settings saved** means the displayed settings match the applied configuration. **Save settings** validates, saves and applies them. Invalid fields are marked and their page is opened. A failed save preserves the saved configuration. Start and the stopped window Reset also save/apply drafts. The live reset lock remains available during output and saves only its own flag.

Existing settings need no migration for the percentage display: dead zones still use fractions in JSON (for example `0.1` for 10%).

## Limitations

- OSC is best-effort UDP with no acknowledgement or position feedback. The status means packets were sent, not that onPC received or accepted them.
- Changed coordinates are sent at approximately 30 Hz and duplicates are suppressed. There is deliberately no idle resend: each resend would reselect the MArker and force the executor fader back to the slider level.
- If the window's updates are delayed (for example by a modal dialog or macOS throttling a background app), each late update moves at most a quarter-second of travel instead of jumping.
- If a packet is lost, a held target may stay at the previous received position until another position is sent; press Stop then Start to resend the displayed target. Lost button-release packets may need a manual release command in onPC.
- MArker input uses the programmer and can change the console's selection context. Each position update sends, in one OSC string: `ClearSelection; MArker <CID>; Attribute "XYZ_X" At Absolute Percent <value>; ...`. Selection must be separate from attribute assignment; `MArker 1 Attribute ...` is rejected by onPC. Avoid concurrent programmer work that relies on the selection during followspot operation; for independent programming, a separate onPC station or user (or a future PSN implementation) may suit better.
- Automated tests cannot prove end-to-end operation. Before show use, check physical input, OSC reception, movement smoothness and real fixture aiming from a normal macOS launch with an onPC test show.
