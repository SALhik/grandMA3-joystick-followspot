# grandMA3 Followspot plugin implementation plan

> Execute inline, task by task, with regression tests and a final independent review.

**Goal:** One importable plugin with native MA controls, reused Python input/motion,
direct show output and optional PSN.

**Architecture:** Embedded Python runtime publishes semantic output frames and
acknowledged command events through owned atomic JSON files. Lua applies native
MA output and presents configuration pages. The existing app remains intact.

**Tech stack:** Python 3.10+ standard library; MA Lua 5.5/API; single XML package.

**Spec:** `docs/superpowers/specs/2026-10-20-grandma-plugin-design.md`.

## Global constraints

- macOS onPC 2.5; Python 3.10+; no third-party Python packages or Tk dependency.
- Never overwrite operator settings.json or send real MA output in verification.
- Native position output preserves selection; brightness Master, zoom/iris Temp.
- Stop holds PSN; Release closes it; cleanup/lease loss exits the helper.
- No commits/pushes or worktree changes requested; preserve existing uncommitted work.

## Review focus

- Lost or duplicate input/action events must not leave owned buttons held.
- Stale frames, delayed acknowledgements and show/patch changes must stop safely.
- PSN hold/settings changes/lease expiry must have explicit, bounded semantics.
- Long/invalid/non-ASCII settings and command text must round-trip without code execution.
- Native pages must retain drafts and remain readable while editors are disabled.

## Task 1 — Python runtime and private protocol

Files: `ma_plugin/runtime.py`, `ma_plugin/worker.py`, `tests/test_plugin_runtime.py`.
Interfaces: `PluginRuntime(config, input_factory, stream_factory, clock)`,
`command(action, payload)`, `tick(dt)`, `snapshot()`; worker owns atomic IO/lock/lease.

- [x] Write failing runtime tests for semantic frames, motion, reliable command
  events, held buttons, finite test, configuration, learning, PSN hold/release.
- [x] Implement a Controller subclass/adapter using core Settings/Motion and Joystick.
- [x] Implement owned atomic requests/status, command acknowledgement, lease and lock.
- [x] Run runtime tests with fake hardware/streams and real filesystem subprocess checks.

## Task 2 — Lua codec and native output

Files: `ma_plugin/json.lua`, `ma_plugin/output.lua`, `tests/test_plugin_lua.py`.
Interfaces: JSON `encode/decode`; `Output.new(config)`, `apply(frame)`, `commands(events)`.

- [x] Write failing executed-Lua tests for JSON round-trip/invalid input and native
  channel/fader targets, command failures, stale/replaced targets and no selection calls.
- [x] Implement codec and native adapter; fader readback is observed after yielding,
  not asserted synchronously. Cache target identity, not current selection.
- [x] Run real Lua tests with MA doubles and no network.

## Task 3 — Native UI, launcher and package

Files: `ma_plugin/ui.lua`, `ma_plugin/main.lua`, `ma_plugin/build.py`,
`tests/test_plugin_package.py`, `docs/PLUGIN.md`.
Interfaces: UI events queue commands; main owns lease/output and config persistence;
builder embeds modules, Python, schema/default settings and version in one XML.

- [x] Write failing package tests that decode/execute XML, launch the real helper,
  exercise native UI callbacks, save/reload, Start test/Stop/Release and Cleanup.
- [x] Implement paginated native pages, reliable requests/acks, learning/calibration,
  inline Release/Close confirmation and persistent show config/computer Python path.
- [x] Build personal and shareable packages; preserve settings hash; run all suites.
- [x] Request independent review; worker unavailable (usage limit). Complete local
  audit/fixes with regression coverage and document the review limitation.
- [x] Copy the verified personal XML into MA's import folder with filesystem approval.
