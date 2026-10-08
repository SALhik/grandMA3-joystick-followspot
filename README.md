# Joystick Followspot

A small Python controller for grandMA3 onPC 2.5 on the same Mac. The stick moves one virtual MArker across X/Y: further deflection means faster movement; releasing it holds the position. Z is set in the window. The slider controls an executor's brightness fader. Buttons send editable commands on press/release.

All physical fixture assignment and XYZ aiming stay in grandMA3. This tool does not calculate pan/tilt or manage a fixture list.

## Launch

Double-click **Launch Followspot.command** in this folder. It selects a Python with Tk support and opens the settings window. Output starts **stopped** every time.

On this Mac, Python 3.12 with Tk and SDL2 are installed. No Apple developer account, Python package installation, or app signing is needed. The reader uses native macOS HID if SDL does not find the joystick. If macOS opens the launcher as text, run it from Terminal:

```sh
cd ~/joystick-followspot
zsh 'Launch Followspot.command'
```

For another Mac, use Python 3.10+ with Tkinter (the python.org macOS installer includes it). Native HID works without SDL2; SDL2 can optionally be installed for the SDL backend:

```sh
brew install sdl2
```

SDL2 is found in the standard Homebrew or framework locations. A custom library path can be supplied through `FOLLOWSPOT_SDL2`. No virtual environment is required.

### Joystick detection or access errors

If SDL does not list the joystick, the reader automatically lists controller devices through macOS HID and opens only the selected joystick. Keyboard/mouse interfaces are excluded. This avoids confusing an SDL detection failure with a disconnected USB device.

If the window says **macOS denied input access**, the controller was detected but could not be opened. Check **System Settings → Privacy & Security → Input Monitoring** for the app launching Python (for example Terminal, iTerm, or Python), then quit/relaunch that app if you choose to permit access. The script does not change permissions or bypass a denial. A restricted/sandboxed terminal may still be unable to read the device. Do not grant permissions solely for an empty list; use the explicit error to identify an access failure.

## Configure onPC

Use a test show first. The script does not edit your showfile automatically.

1. Patch the real lights and enter their accurate positions and orientations in the stage. Enable **XYZ = Yes** for the fixture type's used DMX mode in **Patch → Fixture Types → Edit**. Accurate patch geometry is necessary for physical aiming.
2. Patch one **MA Lighting MArker**, mode **Moving**, with **IDType = MArker** and **CID = 1** (or your chosen ID). Give the MArker a DMX address in an unused virtual universe; MA requires a patched address for its movement to be visible. Do not output that virtual universe to hardware.
3. In the patch, identify this MArker's **Movement Space**. In **Patch → Stages → Edit → Spaces**, read that space's X/Y/Z minimum and maximum values. Copy these into the tool's **Target / stage → MArker movement space** fields. They define how metre coordinates map to 0–100% attribute values. The defaults in the tool are an example 200 m cube centred at the origin; they must match the actual configured space, not just the visible 3D stage box. Use an unrotated stage/space for the first version, and keep the MArker's patch position/rotation at the origin/zero so these coordinates correspond to the stage axes.
4. Configure a small **Target Space** around the marker that contains the origin, for example min/max **−1/+1 metres for X, Y and Z**. This controls the offset of the lights' aiming point relative to the MArker, rather than the MArker's travel.
5. Select the followspot fixtures or their group. Set their **MArker** attribute to the chosen MArker CID and their X/Y/Z target offsets to **0 metres**. Use physical/natural notation explicitly, e.g. for CID 1:

   ```text
   Group 1
   Attribute "XYZ_MArker" At Absolute Natural 1
   Attribute "XYZ_X" At Absolute Physical 0
   Attribute "XYZ_Y" At Absolute Physical 0
   Attribute "XYZ_Z" At Absolute Physical 0
   At 100
   ```

   Replace `Group 1` with your followspot group. Check the 3D view and physical aiming before continuing. These commands affect the current selection, so enter them with only the intended lights selected. Keep the physical fixtures in their real patch positions; do not make them children of the moving MArker.
6. Store the lights' marker assignment, XYZ offsets, and full dimmer in a dedicated followspot cue/sequence. Assign it to an executor, such as **Page 1, Executor 201**, with a **Master** fader. Run that sequence. Clear its stored setup from the programmer so its dimmer can be controlled by the executor fader. Other dimmer overrides, parked values, grand master, or blackout can affect brightness.
7. Turn **Programmer Time off** for responsive MArker updates. The script writes MArker coordinates to the programmer; programmer fades could introduce lag.
8. Open **Menu → In & Out → OSC**. Enable **Input**. Add a row with **UDP**, **Port 8000**, **Receive = Yes**, **Receive Command = Yes**, **FaderRange = 100**, and an empty **Prefix**. Select the interface on which onPC receives OSC. The tool defaults to `127.0.0.1`; if onPC is bound to your Mac's Ethernet/Wi-Fi IP, put that IP in the tool instead. An OSC destination IP controls outgoing OSC and does not replace the input-interface choice. Disable outgoing echo/command transmission unless you need it.

MA's references: [XYZ activation](https://help.malighting.com/grandMA3/2.5/HTML/xyz_activate.html), [MArkers](https://help.malighting.com/grandMA3/2.5/HTML/xyz_marker.html), [spaces](https://help.malighting.com/grandMA3/2.5/HTML/patch_stage.html), [OSC](https://help.malighting.com/grandMA3/2.5/HTML/remote_inputs_osc.html), [Percent input](https://help.malighting.com/grandMA3/2.5/HTML/keyword_percent_word.html).

## Configure the joystick

1. In **Controls**, select the PXN joystick. Click **Refresh** after connecting/reconnecting it.
2. Use **Learn** beside X, Y, and Brightness. Move only the intended control after clicking. Axis numbers start at zero. The initial 0/1/2 mappings are placeholders; a flight stick's slider may be axis 3 rather than 2.
3. Release the stick and click **Calibrate centre**. Set inversion, dead zone and maximum speed. Default speed is 1 m/s; a half deflection beyond the dead zone moves at half the maximum speed. Diagonal travel has the same maximum speed as horizontal/vertical travel.
4. In **Target / stage**, enter the MArker CID, Z height, operating limits and initial X/Y. Operating limits restrict your joystick travel and may be smaller than the full movement space. **Reset target** changes the script's displayed position while stopped; it sends that position when you next Start.
5. In **OSC**, set the host/port/prefix and brightness executor page/number. Default marker attribute library names are `XYZ_X`, `XYZ_Y`, `XYZ_Z`; confirm using `List Attribute` if your fixture library differs.
6. In **Buttons**, click **Learn button**, press the desired button, enter commands, and click **Set mapping**. Then **Save / apply settings**. Examples:

   | Action | Press | Release |
   | --- | --- | --- |
   | Run next cue | `Go+ Sequence 10` | empty |
   | Run a macro | `Go+ Macro 5` | empty |
   | Held flash | `Flash On Executor 1.202` | `Flash Off Executor 1.202` |

   Commands execute as entered. Buttons fire once per transition. A button already held when you Start is ignored until it is released and pressed again. Default button mappings are empty.
7. Save/apply. Check **Live** for the target and slider level, then click **Start output**. Start also applies/saves the currently displayed settings. It immediately sends the displayed target and current brightness; it does not read the fixture's existing position or fader level from onPC.

Settings are saved to `settings.json` beside the script. To share an example configuration, use `settings.example.json`; it is not loaded automatically. Stop before editing settings. While output runs, settings tabs are disabled.

## Stop and restart

**Stop** sends release commands for buttons this tool pressed, stops transmitting, and keeps the current target in memory. It does not clear the programmer, release the MArker, blackout the lights, or move them home. Resume with Start. Closing the window attempts button releases and stops output.

On disconnect or read/send failure, output stops and does not resume automatically. Reconnect, Refresh, then Start. Relaunching the script restores your saved initial X/Y and Z; review those before enabling.

The script uses best-effort UDP OSC with no acknowledgement or position feedback. The status means packets were sent, not that onPC received or accepted them. It sends changed coordinates at approximately 30 Hz and suppresses duplicate values. If a packet is lost, a held target may remain at the previous received position until another position is sent; press Stop/Start to resend the displayed target. Lost button-release packets may require a manual release command in onPC.

MArker command input uses the programmer and can change the console's selection/attribute context. Each position update sends separate commands in one OSC string: `ClearSelection; MArker <CID>; Attribute "XYZ_X" At Absolute Percent <value>; ...`. Selection must be separate from attribute assignment; combining them as `MArker 1 Attribute ...` is rejected by onPC. During dedicated followspot operation, avoid concurrent programmer work that relies on preserving the selection. Buttons that affect selection are followed by explicit MArker targeting on the next position update. If you need independent programming alongside followspot operation, a later PSN implementation or separate onPC station/user may be more suitable.

## Diagnostics and tests

Read input without transmitting any lighting commands:

```sh
python3 followspot.py --list-devices
python3 followspot.py --monitor 10
python3 followspot.py --check-settings
python3 -m unittest discover -s tests -v
```

The CLI input monitor does not need Tk. The normal Homebrew Python can run it even if it lacks `_tkinter`.

Development verification: core motion/configuration/OSC-packet tests, simulated SDL joystick input/disconnect tests, native HID discovery/fallback tests, and headless window lifecycle tests pass. The updated native detector lists the connected **PXN-2113 Pro** in this session; its device-open call reports **0xe00002e2 (not permitted)** inside the sandbox. MA's installed 2.5 system tests confirm the `XYZ_X`, `XYZ_Y`, `XYZ_Z`, and `XYZ_MArker` attribute names. The agent sandbox cannot create a native Tk window, bind UDP loopback sockets, or read the physical joystick. Physical input, visual UI layout, OSC reception, movement smoothness and real fixture aiming therefore require a normal macOS launch and an onPC test show before show use.
