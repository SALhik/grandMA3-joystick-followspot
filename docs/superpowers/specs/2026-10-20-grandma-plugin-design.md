# grandMA3 Followspot plugin

The operator has approved building the full plugin after confirming the
synthetic helper, native XYZ output, selection preservation and combined
brightness/XYZ startup in onPC 2.5.1.0. No further feasibility gate is needed.

## Product

One importable `JoystickFollowspot.xml` for macOS grandMA3 onPC 2.5. Python
3.10+ remains installed on the computer; Tk is not needed. Embed the existing
`joystick.py` and `followspot_core.py`. Never write the standalone app's
operator-owned `settings.json`. Default to internal MA output with no OSC
setup. Offer PSN as an optional MArker position mode; native MA faders and
button commands work in either mode. Preserve pan/tilt group mode.

Provide a persistent native MA control panel: Live, Joystick, Target, Levels,
Buttons and Diagnostics. Use native grid, label, edit and button widgets;
paginate long settings pages instead of clipping them. Live shows applied
target, levels, running/test/PSN holding state, faults and input status.
Global Start, Stop, Reset, Release and Save stay accessible. Editors are
disabled during output; settings of inactive paths stay hidden. Show an
explicit real-output Start preview. Test mode is finite and needs no joystick.

Joystick setup includes refresh, explicit selection/open, raw axes/buttons,
axis/button learning, centre calibration, inversion, dead zones and speeds.
Buttons support existing MA press/release commands and local actions. Reset
is locked while running by default. Levels use Master for brightness and
Temp for optional zoom/iris. No show patch, sequence content or In & Out
settings are silently created or changed.

## Runtime boundaries

Python owns device input, core Controller/Motion, button edges and PSN stream.
A narrow Controller adapter produces semantic position/level frames and
reliable ordered MA command events; motion algorithms are not rewritten.
Lua owns native UI and show API calls. Resolve targets without selecting
fixtures, write indexed programmer channels and object faders, and execute
button commands using Cmd. Native output must not call ClearAll or change
the selection for MArker position updates. Pan/tilt retains the existing
selection-based group command through internal Cmd, with its selection effect
explicit in the Live preview. Programmer/Blind/priority limitations
remain explicit. Resolve and validate native targets before Start; invalidate
cached channels if target identity/patch indices change.

Private atomic JSON files connect an owned run folder to its helper. Start
opens no output automatically. Worker runs near 30 Hz; Lua polls near 30 Hz.
Continuous frames use latest state; command events remain queued until Lua
acknowledges execution. Bound queue growth and stop output on failure. Lease
loss stops input/output, releases owned MA buttons where Lua remains alive,
closes PSN and exits. No process searching or killing. A shared lock prevents
two helpers controlling the same station at once. Native/IPC errors stop
output, retain visible faults and require explicit restart.

Stop holds native programmer/fader values and holds an existing PSN stream.
Release ends PSN, with an inline second confirmation; mapped Release remains
immediate. Normal Close with a held stream requires the same deliberate
confirmation. Off Plugin/host teardown is unconditional cleanup: request owned
shutdown and release; lease expiry is the bounded fallback. A crash or host
exit ends PSN and the MArker may return to origin. UI dialogs must not block
lease renewal; use inline controls/confirmation while a helper is alive.

MA settings persist as namespaced UserVars in the current show/user profile;
the operator saves the show to retain them across reload. Python executable
preference is computer-local. Personal generated XML embeds a settings
snapshot and is Git-ignored; a shareable default package is reproducible.

## Verification

Test Python runtime with injected input/streamers: proportional motion,
Start/Stop/reset/held buttons, finite test, PSN seed/hold/release/errors,
settings guards, learning, reliable commands, lease/lock/cleanup. Run actual
Lua and JSON codec offline with MA API doubles; test native targets, faders
(asynchronous readback), UI actions, failure stop and command acknowledgements.
Decode and run the actual packaged XML with the real embedded Python process,
intercepting hardware/network boundaries. Run the existing application suite.
Do not send output to the real show during development. Record operator
verification separately from offline evidence, including remaining physical
joystick, PSN, native layout and long-running behavior.
