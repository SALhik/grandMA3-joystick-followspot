# Implementation ledger — 2026-10-20-grandma-plugin

Spec and plan are in docs/superpowers. The user explicitly approved implementation
after the final combined native brightness/XYZ test succeeded.

Decisions: implement inline in the existing checkout, adding isolated plugin modules
and preserving all existing uncommitted diagnostic work. No Git commits or branch
changes requested. Use native inline editing/confirmation so modal dialogs cannot
starve the helper heartbeat. Keep the standalone app unchanged.

Preflight: runtime snapshot is the Lua output/UI input; builder embeds both with a
single protocol version. Requests and output command events each have independent
monotonic IDs and owner tokens. Latest position frames do not replace command events.

Task 1: complete — runtime tests and real-worker lease/request tests pass.
Task 2: complete — real Lua JSON/native output tests pass with MA boundary doubles.
Task 3: implementation complete; package tests passed for direct and PSN modes.
Real packaged Lua launches the real Python worker, drives native UI callbacks,
preserves half-typed fields, saves/reloads settings, holds PSN on Stop and requires
two-click Release; network sends intercepted at socket boundary.

Ruling: pan/tilt retains the existing core-generated Group/Attribute command
through internal Cmd; MArker output alone guarantees selection preservation.
This preserves the existing optional mode without guessing an unverified group
membership API. Cost: pan/tilt takes the operator selection, as the standalone app does.

Final verification: 253 tests, 207 passed / 46 explicit environment/platform
skips; all 41 diagnostic checks passed. The 24 plugin tests include real XML
execution, startup-failure recovery, stale-frame Stop protection, initial-frame
acknowledgement, duplicate lock ownership, and distinct press/release ownership.
Regression checks were observed failing before their respective fixes.

Independent final review was requested with fresh context via
`review_full_plugin`; the worker returned a usage-limit error before reviewing.
Deviation: completed a local failure-path audit instead of claiming an independent
verdict. Fixed Reset resend, persistent release warnings, cancelled-press releases,
identical command text ownership and partial panel construction cleanup.
Hardware/API semantics, native visual layout and long-run performance were set
aside as operator acceptance checks; offline doubles cannot establish them.

Personal and default packages reproduce byte-for-byte; embedded config/core/input
match their sources. Personal v1.0.0.0 SHA-256:
`06a72fcdea71841d4a521ba1970366875fe614a11b95a46eba759fb18d9d6c91`.
Operator settings retain their original SHA-256. Documentation is complete.
Copied with filesystem approval into
`~/MALightingTechnology/gma3_library/datapools/plugins/JoystickFollowspot.xml`;
the installed bytes, XML version/name and SHA-256 match the verified build.
No MA pool object was imported or executed; the operator's first full-package
onPC run remains the next acceptance step. The operator subsequently requested
a local commit of all edits; no remote push was requested.
