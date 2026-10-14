# grandMA3 setup, step by step

Follow these in order on a **test show**. Each step says what to do and how to check it. Stage geometry, patching and executor storage are done in onPC; this tool only sends OSC.

Commands in `code blocks` are typed on the onPC command line. `Group 1`, `MArker 1`, `Sequence 201` and `Executor 1.201` are examples: use your own IDs, and keep the same numbers in the tool's window.

## Step 1. Patch the real lights

1. **Patch → Fixture Types → Edit**: for each followspot fixture type, set **XYZ = Yes** for the DMX mode you use.
2. Patch the lights and enter their **real positions and rotations** in the stage. Accurate geometry is what makes the beam land on the target.
3. Put the followspots in a group, for example `Group 1`.

Check: the 3D view shows the lights where they really hang.

## Step 2. Patch the MArker

1. Add one **MA Lighting MArker**, mode **Moving**, with **IDType = MArker** and **CID = 1**.
2. Give it a DMX address in an **unused virtual universe**. Do not output that universe to any hardware.
3. Keep its patch position and rotation at 0.

Check: `List Attribute` shows `XYZ_X`, `XYZ_Y`, `XYZ_Z` for the MArker.

## Step 3. Read the MArker's Movement Space

1. **Patch → Stages → Edit → Spaces**: find the MArker's **Movement Space**.
2. Write down its X, Y and Z **minimum and maximum**.
3. Later you will type these into the tool's **Setup → Target / stage → MArker movement space** fields (Step 9). The tool converts metres to the 0–100 % attribute value with them, so they must match exactly. This is not the stage box and not the Target Space. The tool's defaults are an example 200 m cube centred on the origin, not measured geometry.
4. For the first version use an unrotated stage and space.

## Step 4. Set a small Target Space

Create or edit a **Target Space** around the marker that contains the origin, for example **−1 to +1 m** on X, Y and Z. It sets how far the lights may aim from the marker, not how far the marker travels.

## Step 5. Point the followspots at the MArker

Select only your followspots and enter these, one line at a time:

```text
Group 1
Attribute "XYZ_MArker" At Absolute Natural 1
Attribute "XYZ_X" At Absolute Physical 0
Attribute "XYZ_Y" At Absolute Physical 0
Attribute "XYZ_Z" At Absolute Physical 0
At 100
```

Replace `Group 1` with your group and the `1` in the second line with the MArker's CID. Do not parent the lights to the marker.

Check: the 3D view beams point at the marker. Moving the marker by hand should move the beams:

```text
ClearSelection
MArker 1
Attribute "XYZ_X" At Absolute Percent 60
```

## Step 6. Store the followspot cue on an executor

1. With the setup from Step 5 still in the programmer, store it as a cue and put it on an executor with a **Master** fader. The example uses Page 1, Executor 201:

```text
Store Sequence 201 Cue 1
Assign Sequence 201 At Executor 1.201
```

2. Set that executor's fader type to **Master** in the executor's settings. If the exact command differs in your onPC version, store and assign with the GUI instead.
3. Run the sequence, then clear the programmer so the executor, not the programmer, owns the dimmer:

```text
ClearAll
Go+ Sequence 201
```

Check: moving the executor's fader by hand changes the lights' brightness. Grand master, blackout, parked values and other dimmer overrides also affect brightness.

## Step 7. Turn Programmer Time off

Turn **Programmer Time off** so the marker follows the joystick without fade lag. The tool writes marker coordinates to the programmer, and programmer fades would add lag.

In the master controls menu, tap **Prog Time** until its green marker disappears (or press Off on an executor assigned to the Program Time master). This is from MA's [Time Control help](https://help.malighting.com/grandMA3/2.2/HTML/masters_grand_time.html) for 2.2; check the 2.5 wording on your console.

## Step 8. Enable OSC input

1. **Menu → In & Out → OSC**.
2. Enable **Input** at the top.
3. Add a row with:

| Field | Value |
| --- | --- |
| Protocol | UDP |
| Port | 8000 |
| Receive | Yes |
| Receive Command | Yes |
| FaderRange | 100 |
| Prefix | empty |

4. Choose the **Interface** that onPC listens on. The tool's default host is `127.0.0.1`. If onPC uses your Mac's Ethernet or Wi-Fi address, put **that IP** in the tool's **Setup → OSC → onPC host / IP** field. Do not assume loopback works.
5. Leave outgoing echo and command transmission off unless you need them. The row's Destination IP only affects OSC that onPC sends out.
6. **In an existing show, check the other OSC rows first.** A show that already has an OSC row (for example row 1, set up for another controller) can stop this tool from working even though a blank test show works: MA showed the incoming messages and reported no error, but the marker never moved. The cause is probably that the older row handled the messages with its own settings, but this is not verified. Removing the old row fixed it in one theatre show. Delete or disable any other row that uses the same port (8000), or make it match the table above, and keep only one row for this tool.

Check in Terminal: `lsof -nP -iUDP:8000` should show onPC listening.

To keep the console selection free, use PSN position output: see [PSN.md](PSN.md). Brightness, zoom / iris and buttons still need this OSC setup.

## Step 9. Enter the values in the tool

Open the tool (`Launch Followspot.command`) and fill in these pages under **Setup**. Click **Save settings** when done.

| Tab | Fields |
| --- | --- |
| Target / stage | MArker CID, Z height, operating limits, initial X/Y, **movement space min/max from Step 3** |
| OSC | host/IP, port 8000, empty prefix |
| Brightness / zoom | brightness executor page and number (1 and 201 in the example); optional zoom/iris axis and executor (1 and 202); see the last section |

## Step 10. Test without the joystick (figure 8)

1. In the tool, open **Diagnostics** and click **Start test (figure 8)**. This sends real output.
2. The marker traces a figure 8 around the initial target, and the executor fader is held at the test brightness (100 % by default). Tune size, lap time and brightness in Diagnostics before starting.
3. Watch the 3D view, the beams, and the executor fader moving in onPC.
4. Click **Stop output** to end the test. The marker stays where it stopped.

If nothing moves:

1. Enable **EchoInput** in the OSC row and open **System Monitor**: incoming `/cmd` text should appear. If not, check the port, the Interface/IP (Step 8) and that **Receive Command** is on.
2. If the commands appear but nothing happens and there is no error, look for a second OSC row on the same port (Step 8, item 6). Typing the same commands by hand works in this case, so the command syntax is not the problem.
3. If the commands appear but are rejected, read the error text in System Monitor. The tool sends `ClearSelection; MArker 1; Attribute "XYZ_X" At Absolute Percent 50; ...`.
4. If the commands are accepted but the beams do not move, recheck Steps 2, 3 and 5.
5. If the marker moves but the fader does not, recheck Step 6 (Master fader, **FaderRange = 100**, correct executor page and number).

## Step 11. Connect the joystick

1. Go to **Setup → Joystick**, select the PXN joystick and click **Refresh** if it is missing.
2. Click **Learn** beside X, Y and Brightness, then move only that control. Axis numbers start at 0.
3. Release the stick and click **Calibrate stick centre**. Set inversion, dead zone (%) and maximum speed.
4. Optional: map buttons in **Setup → Buttons**, and enable zoom/iris (see below and [OPERATING.md](OPERATING.md)).
5. **Save settings**, then **Start output**.

## Optional: zoom / iris executor

Do this after the brightness executor works. The tool controls only a fader level; the cue and playback you set up here decide what that does to zoom or iris.

1. Create a separate sequence that contains **only zoom or only iris** values for the followspots, and assign it to its own executor, for example Page 1, Executor 202. It must differ from the brightness executor.
2. In **Assign → Handle** set that executor's fader function to **Temp**. A Temp fader crossfades the cue on and off (see MA's [fader functions](https://help.malighting.com/grandMA3/2.5/HTML/executor_assign.html)).
3. Establish the desired underlying value for the low end of the fader, and store the desired high-end value in the Temp cue.
4. Clear those values from the programmer, then move the fader by hand through its full travel and confirm the zoom or iris behaves as expected.
5. Keep **FaderRange = 100** on the OSC row (Step 8).
6. In the tool open **Setup → Brightness / zoom**, enable the axis, enter the executor page and number, then learn and calibrate the axis (see [OPERATING.md](OPERATING.md#optional-zoom--iris-control)).

Check: a figure-8 test with the axis enabled sends the initial zoom/iris level once but does not move it, because the joystick is ignored in a test. Confirm zoom/iris movement with the joystick.

## References

MA's help: [XYZ activation](https://help.malighting.com/grandMA3/2.5/HTML/xyz_activate.html), [MArkers](https://help.malighting.com/grandMA3/2.5/HTML/xyz_marker.html), [stages and spaces](https://help.malighting.com/grandMA3/2.5/HTML/patch_stage.html), [OSC](https://help.malighting.com/grandMA3/2.5/HTML/remote_inputs_osc.html), [Percent input](https://help.malighting.com/grandMA3/2.5/HTML/keyword_percent_word.html).
