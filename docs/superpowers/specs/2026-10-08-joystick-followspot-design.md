# Joystick followspot controller

## Purpose and agreed scope

A compact Python tool on the show Mac reads the connected PXN-2113 Pro joystick and controls a dedicated FOH followspot through grandMA3 onPC 2.5 on the same Mac. A small settings window allows changes without editing code. No Apple developer account or packaged native app is required.

The tool controls one moving MArker target, rather than individual lights. Fixture assignment, XYZ enablement, real-world position/orientation calibration, and multi-fixture aiming belong in grandMA3. Brightness is routed through an executor configured in grandMA3.

## Controls

- Main stick: X/Y velocity. Greater deflection means greater speed. Returning to centre stops movement and holds the target's position.
- Apply a configurable centre dead zone, rescale the remaining travel, and use a linear speed response initially. Limit the combined X/Y speed so diagonals do not exceed the configured maximum. Default maximum speed: 1 metre per second.
- Integrate velocity using elapsed monotonic time. Suspend movement after a long processing gap rather than advancing by the entire gap.
- Z: a fixed height editable in settings; default 1.5 metres.
- Slider: absolute 0–100% brightness, with configurable axis selection and inversion.
- Buttons: editable grandMA3 command strings for press and release. Send once per transition, not continuously while held. Empty mappings do nothing.

## Window and saved settings

Use Python with Tkinter for the window and a joystick library selected after a hardware compatibility check. Show device connection, live axes/buttons, current target XYZ, brightness, output state, and errors.

Settings include joystick selection; X/Y/slider axis mapping and inversion; centre calibration and dead zone; maximum speed; MArker CID; XYZ bounds; initial XYZ position; executor page and number; OSC host, port, and optional prefix; and button press/release commands. Save validated settings as JSON beside the script. Provide a short input-learning flow for axis and button mapping.

Start with output disabled. Provide Start, Stop, and an explicit target reset to the configured initial position. Changing routing or calibration requires stopped output. Applying settings must not silently enable output.

## grandMA3 connection

Recommended implementation: OSC over UDP for MArker attribute commands, executor fader values, and mapped button commands. Default destination is localhost with configurable host/port because the interface MA binds to must be verified on the actual system. No automatic showfile edits or plugin are required.

Configure one moving MA Lighting MArker with MArker IDType and a CID. Fixtures are configured to aim at that MArker through their MArker attribute; do not parent the physical fixtures underneath it to make them move.

MArker X/Y/Z attributes are mapped into its configured Movement Space. Settings express coordinates and speed in metres. The configured XYZ minimum/maximum values must match that space in onPC; convert coordinates to its 0–100% attribute range explicitly, without relying on the console's current readout units. Confirm the marker attribute names and address syntax against an actual test show before live use.

Use the configured executor's fader for brightness, leaving fixture membership and playback setup in grandMA3. Enable OSC input and Receive Command for command messages. Include clear setup instructions and sample commands for button mappings.

Alternative considered: PSN for the XYZ target and OSC for brightness/buttons. PSN offers dedicated tracking input, but introduces another protocol and setup. Start with OSC and validate smoothness and console interaction before considering PSN.

## Runtime behaviour and limitations

Poll inputs and schedule output at approximately 30 Hz. Send changed positions and fader values, suppress unnecessary repeated commands, and keep the UI responsive. Clamp XYZ to the configured bounds.

The displayed XYZ is the script's target, not feedback from grandMA3. Start sends that displayed target and the current slider level; the operator must review them before enabling. Stop retains the software target for resuming. Restarting the script restores the configured initial target and leaves output disabled.

OSC attribute commands write MArker values into the programmer. During testing, verify that addressing the MArker does not disrupt the intended console workflow; document any selection/programmer effects. The controller is for dedicated followspot operation and does not implement automatic cue takeover.

Joystick disconnect, input failure, or transport errors disable output and require explicit Start after recovery. Stop/disconnect/window close send mapped releases for buttons the tool previously pressed when transport remains available; they do not clear the programmer or change brightness automatically. UDP transmission alone does not confirm reception, and lost releases remain a documented limitation.

## Delivery and verification

Deliver a small script, dependency list, JSON settings, and a concise README with launch and onPC setup instructions. Keep the script runnable directly in a local Python virtual environment.

Verify real joystick axes/buttons without emitting lighting commands. Test dead zone, proportional velocity, time integration, bounds, settings validation, button transitions, and OSC packet encoding with focused automated checks. Exercise the window and receive output locally to confirm the transmitted target and fader values. Verify aiming, brightness, responsiveness, and programmer interaction in an available grandMA3 2.5 test show; clearly identify any checks that cannot be completed here.

## Approval status

The user approved the in-chat design and explicitly confirmed proportional speed on 2026-10-08. This written specification is awaiting review before implementation planning.
