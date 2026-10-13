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
3. Later you will type these into the tool's **Target / stage → MArker movement space** fields (Step 8). The tool converts metres to the 0–100 % attribute value with them, so they must match exactly. This is not the stage box and not the Target Space.

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

Turn **Programmer Time off** so the marker follows the joystick without fade lag. The tool writes marker coordinates to the programmer.

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

4. Choose the **Interface** that onPC listens on. The tool's default host is `127.0.0.1`. If onPC uses your Mac's Ethernet or Wi-Fi address, put **that IP** in the tool's **OSC → onPC host / IP** field. Do not assume loopback works.
5. Leave outgoing echo and command transmission off unless you need them. The row's Destination IP only affects OSC that onPC sends out.

Check in Terminal: `lsof -nP -iUDP:8000` should show onPC listening.

## Step 9. Enter the values in the tool

Open the tool (`Launch Followspot.command`) and fill in these tabs. Click **Save / apply settings** when done.

| Tab | Fields |
| --- | --- |
| Target / stage | MArker CID, Z height, operating limits, initial X/Y, **movement space min/max from Step 3** |
| OSC | host/IP, port 8000, empty prefix, brightness executor page and number (1 and 201 in the example) |

## Step 10. Test without the joystick (figure 8)

1. In the tool, open **Live** and click **Start test (figure 8)**.
2. The marker traces a figure 8 around the initial target, and the executor fader is held at the test brightness (100 % by default). Tune size, lap time and brightness on the **Test** tab.
3. Watch the 3D view, the beams, and the executor fader moving in onPC.
4. Click **Stop output** to end the test. The marker stays where it stopped.

If nothing moves:

1. Enable **EchoInput** in the OSC row and open **System Monitor**: incoming `/cmd` text should appear. If not, check the port, the Interface/IP (Step 8) and that **Receive Command** is on.
2. If the commands appear but are rejected, read the error text in System Monitor. The tool sends `ClearSelection; MArker 1; Attribute "XYZ_X" At Absolute Percent 50; ...`.
3. If the commands are accepted but the beams do not move, recheck Steps 2, 3 and 5.
4. If the marker moves but the fader does not, recheck Step 6 (Master fader, **FaderRange = 100**, correct executor page and number).

## Step 11. Connect the joystick

1. Go to **Controls**, select the PXN joystick and click **Refresh** if it is missing.
2. Click **Learn** beside X, Y and Brightness, then move only that control. Axis numbers start at 0.
3. Release the stick and click **Calibrate centre**. Set inversion, dead zone and maximum speed.
4. Optional: map buttons on the **Buttons** tab (see the README).
5. **Save / apply settings**, then **Start output**.
