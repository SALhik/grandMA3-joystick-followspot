# Joystick Followspot

A small Python controller for grandMA3 onPC 2.5, running on the same computer as onPC (macOS, with an untested Windows launcher). The stick moves one virtual MArker across X/Y, or optionally drives the pan and tilt of one fixture group directly: further deflection means faster movement; releasing it holds the position. Z is set in the window. The slider controls an executor's brightness fader. An optional extra axis changes a zoom or iris executor's fader at a proportional speed and holds its tracked level at centre. Buttons send editable commands on press/release or control output locally.

All physical fixture assignment and aiming stay in grandMA3. This tool does not compute aim from stage geometry or manage a fixture list; in pan/tilt mode it only integrates the stick into pan and tilt percentages.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/GRANDMA3_SETUP.md](docs/GRANDMA3_SETUP.md) | Step-by-step onPC setup with every command, the figure-8 test, troubleshooting |
| [docs/OPERATING.md](docs/OPERATING.md) | Joystick configuration, marker or pan/tilt control, buttons, reset lock, zoom/iris, test mode, stop/restart, settings file, limitations |
| [docs/PSN.md](docs/PSN.md) | Optional PSN position output that moves the MArker without taking the console selection: app and onPC setup, Stop vs Release marker, findings, test sender, packet format (checked with the test sender only) |
| [AGENTS.md](AGENTS.md) | For AI agents and contributors: code map, workflow, integration contracts, verification limits |

## Quick start

1. Set up onPC on a test show by following [docs/GRANDMA3_SETUP.md](docs/GRANDMA3_SETUP.md). The script does not edit your showfile.
2. Launch the tool (below). Output starts **stopped** every time.
3. In **Diagnostics**, check the setup with **Start test (figure 8)**; no joystick is needed. This sends real OSC output.
4. Connect and calibrate the joystick, then start output, as described in [docs/OPERATING.md](docs/OPERATING.md).

## Launch

### macOS

Double-click **Launch Followspot.command** in this folder. It selects a Python with Tk support and opens the settings window. If macOS opens the launcher as text, run it from Terminal:

```sh
cd ~/joystick-followspot
zsh 'Launch Followspot.command'
```

No Apple developer account, Python package installation, or app signing is needed. The joystick is read through SDL2 if available, plus native macOS HID for controllers SDL does not list. For another Mac, use Python 3.10+ with Tkinter (the python.org installer includes it). SDL2 is optional on macOS:

```sh
brew install sdl2
```

SDL2 is found in the standard Homebrew or framework locations. A custom library path can be supplied through `FOLLOWSPOT_SDL2`. No virtual environment is required.

### Windows

Double-click **Launch Followspot.bat**. It picks a Python with Tk (a local `.venv`, then `python`, then the `py` launcher) and opens the same window. Install Python 3.10+ from python.org with "tcl/tk and IDLE" ticked.

Windows has no native HID fallback, so the joystick is read through SDL2, which is **required** there. Download the SDL2 runtime (`SDL2.dll`, 64-bit to match Python) from the SDL releases page and put it in this folder, next to the launcher, or point `FOLLOWSPOT_SDL2` at it. The launcher uses a `SDL2.dll` beside it automatically. The Windows launcher has not been tested on a Windows machine with onPC or a physical joystick.

### Joystick detection or access errors

The joystick list combines SDL controllers with macOS HID controllers that SDL does not list, and opens only the selected joystick. Keyboard/mouse interfaces are excluded. This avoids confusing an SDL detection failure with a disconnected USB device.

If the window says **macOS denied input access**, the controller was detected but could not be opened. Check **System Settings → Privacy & Security → Input Monitoring** for the app launching Python (for example Terminal, iTerm, or Python), then quit and relaunch that app if you choose to permit access. The script does not change permissions or bypass a denial. A restricted or sandboxed terminal may still be unable to read the device. Do not grant permissions solely for an empty list; use the explicit error to identify an access failure.

## Diagnostics and tests

None of these transmit OSC:

```sh
python3 followspot.py --list-devices
python3 followspot.py --monitor 10
python3 followspot.py --settings settings.example.json --check-settings
python3 -m unittest discover -s tests -v
```

- `--monitor` opens the saved device, so a `settings.json` naming exactly one connected device is required (select and save it in the window first).
- `--check-settings` fails if the settings file does not exist; pass `--settings` to check another file such as the example.
- The CLI commands do not need Tk, so Homebrew Python works even without `_tkinter`. The real-window tests skip when Tk is unavailable.

Automated tests cannot prove end-to-end operation; see the limitations in [docs/OPERATING.md](docs/OPERATING.md) and the development checks in [AGENTS.md](AGENTS.md).
