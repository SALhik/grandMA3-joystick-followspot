# Acceptance record

Use a test show with no live hardware output for initial console checks. Then use the normal launcher and a controlled fixture setup for physical aiming checks. Record actual observations; packet encoding or successful UDP sends do not establish console reception.

## Recorded evidence

| Date | Environment | Check | Result and limit |
| --- | --- | --- | --- |
| 2026-10-14 | macOS, onPC 2.5.0.3, standalone PSN test sender | PSN marker motion, axis mapping, selection and encoder isolation, Stop snap-back | Operator observed success at several points; app's own stream and exact snap-back timeout not tested. Details in [PSN.md](PSN.md#what-was-verified). |
| 2026-10-16 | macOS, Python 3.12.10, Tk-capable local environment | Pre-change full automated suite | 182 tests passed with window access; sandbox Tk creation aborted. No end-to-end onPC/physical movement established. |
| 2026-10-16 | macOS, Python 3.12.10, Tk and local UDP access, review fixes | Integrated automated suite | 229 tests run: 228 passed, 1 Windows-only batch execution test skipped. Real Tk workflows, visible startup, minimum-size/footer/focus geometry and local UDP receiver checks ran. No onPC reception or physical aiming established. |
| 2026-10-16 | Local checkout | Supporting checks | Example settings validation, macOS launcher syntax, whitespace check and workflow YAML parsing passed. Independent integration review found no remaining actionable issue after fixes. Remote CI has not run. |
| 2026-10-16 | Fake input/output, temporary settings, macOS light appearance | Minimum-size visual screenshot | Applied 0% and pending 100% brightness were readable. Screenshot exposed a clipped footer; corrected layout passes visible geometry/focus regressions. The computer-use service stalled, so no final screenshot or full manual keyboard/dark-appearance pass was completed. |

New automated, visual and operator results belong here after execution. CI configuration alone is not a recorded CI pass.

On 2026-10-16 the operator requested that console checks remain pending. Development verification uses fake output and local loopback receivers; it does not transmit to onPC.

## Console and physical input

All rows below are **pending** until an operator records a result.

| Check | Expected observation | Record |
| --- | --- | --- |
| OSC marker | Corrected semicolon-separated commands appear in EchoInput/System Monitor and move the marker and beams. | Pending |
| App PSN figure 8 | The app's own stream moves the marker from the configured initial target; console selection and encoders stay free. | Pending |
| Stop / Release | Stop holds the marker. Window Release asks; Cancel preserves the hold; Confirm resets it to origin. Mapped Release remains immediate. | Pending |
| Real PXN axes | Centre holds; calibrated/inverted directions and proportional speed agree with setup; diagonal speed stays capped. | Pending |
| Brightness / zoom / buttons | Real executors respond; a held MA action releases on Stop; zoom/iris holds at centre. Review the Start preview after a mapping/inversion edit. | Pending |
| Disconnect / recovery | Pulling the joystick stops output and retains PSN hold; reconnect requires Refresh and explicit Start. | Pending |
| Pan/tilt | Group commands are accepted over OSC; 0–100% spans the fixture's range; inversion gives the desired tilt direction. | Pending |
| Mode switch | Test marker → pan/tilt → marker; record programmer overrides, fixture behavior and selection/encoder effects. | Pending |
| Close / Cmd-Q | With a held stream, both ask before ending it. Cancel preserves output. Also check Quit during invalid-settings and close-confirmation dialogs. | Pending |
| Mixed controllers / hotplug | Adding/removing SDL and native devices cannot substitute another controller for the selected one. Identically named devices require explicit selection. | Pending |

Record for each run: date, OS, Python/Tk/SDL versions, onPC version, joystick name, control/position mode, relevant settings, show/fixture identifiers, observed result, and any console errors. Keep operator settings private; share a sanitized configuration if needed.

## Long-running PSN and timeout

1. Record the PSN interface, group, tracker and onPC version. Hold a nonzero target with the app, then Stop while retaining the stream.
2. Observe for at least 30 minutes in the foreground, then 30 minutes with another app in front. Record any snap-back, fault, CPU load or responsiveness change. A background sender thread alone is not proof against App Nap.
3. On a test show, record the time between the last received DATA packet and the marker resetting to origin. Repeat and record the observed minimum/maximum. Do not infer this from the app's 30 Hz setting.
4. Exercise Release and restart after the long hold. Repeat on another computer/network only if that environment is intended for use.

Status: **pending**. No timeout or long-run immunity has been established.

## Visual and keyboard operation

Check the real window at its minimum 760×660 and default 860×740 size in available light/dark appearances. Use temporary settings and fake transports for developer visual checks; no real output is needed.

- Live: applied target and levels, pending Start preview, PSN HOLDING state, held marker, multiline faults and accessible Start/Stop/Release controls.
- Setup: each control/output mode, hidden sections, long button lists with vertical scrolling, field-error navigation and disabled-editor readability.
- Diagnostics: raw inputs, joystick-free test blockers and selected-transport wording.
- Keyboard: tab through visible controls, activate Start/Stop/confirmation with the keyboard, cancel Release, navigate mappings and reach invalid fields. Verify readable focus indication and text contrast.

Status: **partial**, as recorded above. A complete manual pass in both available appearances remains pending. Automated widget geometry and focus/reveal checks remain separate evidence.

## Windows and other computers

Windows launcher with Python/Tk and SDL2.dll, real joystick input, onPC reception and fixture output: **pending**. The Linux/Windows headless and macOS Tk/native CI jobs must also be observed running remotely; local macOS results do not establish those jobs passed.

Cross-computer PSN multicast routing, interface selection and OSC reception: **pending**; follow [PSN.md](PSN.md#script-on-a-different-computer-unverified).
