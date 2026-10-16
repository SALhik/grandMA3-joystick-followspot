# Comprehensive review fixes implementation plan

> **For agentic workers:** Use test-first fixes and parallel agents for the disjoint ownership below. Review the integrated changes before completion.

**Goal:** Address the defects and improvements approved in the comprehensive project review on 2026-10-16.

**Architecture:** Keep the existing App, view, core and joystick boundaries. Share settings preflight between readiness and application, explicitly preview pending transmission, and harden existing device and transport lifecycles without adding runtime dependencies.

**Tech stack:** Python 3.10+, stdlib, Tk/ttk, optional SDL2 and native macOS HID.

**Spec:** The comprehensive review and the user's instruction to fix all identified issues in this conversation; no separate architectural redesign is intended.

## Global constraints

- Preserve AGENTS.md integration contracts except the explicitly approved UI improvements.
- Never overwrite or commit operator-owned settings.json; tests use temporary settings and fake output.
- Keep runtime free of third-party Python packages and preserve existing defaults.
- Do not change MA command syntax or claim unperformed physical/onPC/Windows checks passed.
- Window Release marker requires deliberate confirmation; mapped release_marker remains immediate.
- Ordinary Stop continues to hold a PSN marker and never blacks out lights.

## Review focus

- Pending inversion, axis, mode, Z and bounds changes must not hide what Start will transmit.
- A held PSN stream must block changed PSN fields consistently in both readiness and apply.
- A removed SDL instance must not be substituted by the controller now occupying its index.
- First PSN test DATA must contain the initial test target, even when the thread runs immediately.
- Transport failure and shutdown must retain the established button-release/fault lifecycle.

## Task 1: Preflight, startup and operator interface

**Files:** followspot.py, followspot_ui.py, tests/test_window.py and new focused UI tests as needed.

- [x] Add failing regressions for draft transmission preview, held-stream readiness, joystick-free test explanation and first PSN test DATA.
- [x] Share preflight settings-change validation between apply and readiness; retain field-specific errors.
- [x] Add explicit pending Start target/brightness/zoom preview while keeping Live on applied settings.
- [x] Seed a new test stream with figure_eight(settings, 0) before its thread starts.
- [x] Show OUTPUT STOPPED · PSN HOLDING and confirm window Release clicks, preserving mapped-action priority.
- [x] Give button command-entry states one owner; guard delayed reveal callbacks after destruction.
- [x] Cache unchanged stage rendering and provide vertical mapping-table scrolling without page interception.
- [x] Verify focused tests and self-review; report edits and evidence without committing.

## Task 2: Device identity, backends and launchers

**Files:** joystick.py, both launchers, tests/test_joystick.py and focused launcher tests if meaningful.

- [x] Reproduce cached SDL selection after hotplug and implement instance-ID verification/resolution at open.
- [x] Disable unused SDL joystick events while preserving state polling and disconnect discovery.
- [x] Add native HID denied-open, invalid/no-axis, read failure and cleanup failure coverage using doubles.
- [x] Require Python >=3.10 and Tk in both launcher probes.
- [x] Verify focused tests and self-review; report edits and evidence without committing.

## Task 3: Transport and diagnostic robustness

**Files:** followspot_core.py, tools/psn_test_sender.py, tests/test_core.py, tests/test_psn.py and new diagnostic tests.

- [x] Reproduce finite coordinates that exceed float32 or overflow a movement-space span; reject them on the active path with field errors.
- [x] Bound real PSN socket sends and test shutdown/error observability with a stalled sender.
- [x] Validate diagnostic CLI arguments before creating/sending with a socket; close sockets reliably.
- [x] Add meaningful loopback transport coverage if practical, with no onPC dependency.
- [x] Verify focused tests and self-review; report edits and evidence without committing.

## Task 4: Automation, docs and acceptance evidence

**Files:** .github/workflows/tests.yml, README.md, AGENTS.md, operator docs and a single acceptance record/checklist.

- [x] Add Python 3.10/latest headless Linux/Windows CI plus explicit macOS Tk/native checks; expose skips.
- [x] Correct stale PSN test/default/tab claims, scoped-validation wording and transport guidance.
- [x] Document preflight preview, held state, confirmation, trusted-control-network assumption and startup behavior.
- [x] Consolidate onPC, physical input, long-run/background PSN, snap-back, Windows and visual/keyboard checks with clear pending evidence.
- [x] Run the integrated suite, settings check, launcher syntax and git diff --check.
- [x] Obtain independent final review; address substantive findings and report remaining external validation honestly.

## Verification result

On 2026-10-16 the integrated macOS/Python 3.12.10 suite ran 229 tests: 228 passed and the Windows-only actual batch launcher test was explicitly skipped. Real Tk, visible startup/geometry, focus-reveal and local UDP receiver checks ran. Settings validation, launcher syntax, whitespace and workflow YAML parsing passed. Independent whole-diff review found no remaining actionable issue after the Release-priority and minimum-size layout fixes.

Remote CI and Windows hardware remain unverified. Console checks were left pending at the operator's request. Desktop capture stalled after exposing footer clipping; the correction is covered by visible geometry tests, while the complete manual visual/dark/keyboard pass remains partial. See docs/ACCEPTANCE.md. Changes are local and uncommitted on fix/comprehensive-review.
