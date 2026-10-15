# PSN Position Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional PSN (PosiStageNet) position output that moves the followspot MArker without replacing the operator's console selection, with a Release marker control and documentation.

**Architecture:** Pure PSN packet encoders and a `PsnStreamer` (one background thread, 30 Hz DATA and 1 Hz INFO, injectable socket and clock) live in `followspot_core.py`. `Controller` gets an optional `send_position` callback and uses it instead of the `ClearSelection; MArker ...` OSC commands when `position_output == 'psn'`. `App` owns the streamer: Stop holds it, Release marker closes it, and the lifecycle table in the spec decides every other event. Brightness, zoom/iris and button commands stay on OSC.

**Tech Stack:** Python 3.10+ standard library only (`socket`, `struct`, `threading`, `ipaddress`), Tkinter, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-14-psn-output-design.md` (read it first; background in `docs/PSN.md`).

## Global Constraints

- No third-party Python packages (`requirements.txt` stays comment-only).
- Python 3.10+; code style matches the surrounding files (single quotes, short functions, comments only where needed).
- `settings.example.json` must equal the `Settings` defaults. Old `settings.json` files without the new keys must load unchanged. Never edit or commit the operator's `settings.json`.
- PSN v2.03 packets: UDP, little-endian; chunk header is a uint32 `id | (data_length << 16) | (has_subchunks << 31)`; DATA packet `0x6755`, INFO packet `0x6756`; positions are float32 metres.
- Verified onPC transport: multicast `236.10.10.10`, port `56565`, `IP_MULTICAST_IF` set to the interface address, TTL 1; the default interface is `127.0.0.1`.
- Never replace `ClearSelection` with `ClearAll`; OSC mode behavior stays byte-for-byte unchanged.
- Local action name is `release_marker`; the Live button label is "Release marker".
- No AI attribution in commits. Conventional Commits, subject at most 72 characters.
- Run tests with `python3 -m unittest discover -s tests -v`. Tk tests skip when Tk or a window server is unavailable; report that separately from passing.
- Do not claim real onPC reception, joystick use or another-computer operation is verified: automated tests cannot establish them.

## Review Focus

Failure modes the spec implies that are most likely to bite an operator; each has a test in the owning task.

1. A tracker ID above 255 or a negative coordinate encodes wrongly, so the MArker lands in the wrong place or the packet is ignored (Task 2).
2. An old `settings.json` without the PSN keys fails to load or changes behavior (Task 1).
3. OSC mode accidentally creates a streamer, or PSN mode still sends `/cmd` marker commands that take the selection (Tasks 4 and 5).
4. A held stream goes unnoticed when it dies, because no joystick is open and nothing polls it (Task 5).
5. Closing the window or a cable pull drops the spot without the operator being told (Task 5).
6. Closing the streamer twice, or setting a position after close, raises inside the Tk poll (Task 3).

## File Structure

| File | Change |
| --- | --- |
| `followspot_core.py` | New settings and validation, `release_marker` action, PSN encoders, `PsnStreamer`, `Controller` PSN mode |
| `followspot.py` | Streamer lifecycle, `send_position`, `release_marker`, `check_streamer`, apply refusal, close confirmation, action priority |
| `followspot_ui.py` | Position output selector and PSN fields (OSC tab), Release marker button, held-position display, PSN summary |
| `settings.example.json` | New default keys |
| `tests/test_psn.py` (new) | Encoder and streamer tests |
| `tests/test_core.py` | Settings and controller tests |
| `tests/test_window.py` | Window lifecycle tests, helper changes |
| `tools/psn_test_sender.py`, `docs/PSN.md`, `README.md`, `AGENTS.md`, `docs/GRANDMA3_SETUP.md`, `docs/OPERATING.md` | Documentation |

---

### Task 1: Land the research docs and the test sender

These files already exist uncommitted from the investigation. Commit them first, separately, so the code commits stay clean.

**Files:**
- Already modified/created: `README.md`, `AGENTS.md`, `docs/GRANDMA3_SETUP.md`, `docs/OPERATING.md`, `docs/PSN.md`, `tools/psn_test_sender.py`

- [ ] **Step 1: Inspect and verify**

Run: `git status --short && git diff --check && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: only the six files above listed, no whitespace errors, tests `OK` (some skipped).

- [ ] **Step 2: Commit**

```bash
git add README.md AGENTS.md docs/GRANDMA3_SETUP.md docs/OPERATING.md docs/PSN.md tools/psn_test_sender.py
git commit -m "docs: record PSN findings and add the PSN test sender" -m "Verified in onPC 2.5.0.3: PSN moves a MArker without touching the
console selection or encoders. Documents the transport, onPC setup and
packet format, and keeps the stdlib test sender."
```

---

### Task 2: Settings, validation and the release_marker action

**Files:**
- Modify: `followspot_core.py` (imports, `BUTTON_ACTIONS`, `Settings`, `validate`)
- Modify: `settings.example.json`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces: `Settings.position_output: str`, `psn_tracker_id: int`, `psn_group: str`, `psn_port: int`, `psn_interface: str`; constant `PSN_FIELDS` (tuple of those five names); `BUTTON_ACTIONS['release_marker'] == 'Release PSN marker'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py` (before any `if __name__` block):

```python
class PsnSettingsTests(unittest.TestCase):
    def test_old_settings_default_to_osc_position_output(self):
        s = core.Settings.from_dict({'port': 8001})
        self.assertEqual((s.position_output, s.psn_tracker_id, s.psn_group, s.psn_port, s.psn_interface),
                         ('osc', 1, '236.10.10.10', 56565, '127.0.0.1'))

    def test_example_file_equals_defaults(self):
        example = core.Settings.load(Path(__file__).resolve().parent.parent / 'settings.example.json')
        self.assertEqual(example.to_dict(), core.Settings().to_dict())

    def test_invalid_psn_values_name_their_field(self):
        cases = (({'position_output': 'sacn'}, 'position_output'),
                 ({'psn_tracker_id': 0}, 'psn_tracker_id'),
                 ({'psn_tracker_id': 65536}, 'psn_tracker_id'),
                 ({'psn_port': 0}, 'psn_port'),
                 ({'psn_port': 70000}, 'psn_port'),
                 ({'psn_group': '10.0.0.5'}, 'psn_group'),
                 ({'psn_group': 'not-an-ip'}, 'psn_group'),
                 ({'psn_interface': 'localhost'}, 'psn_interface'),
                 ({'psn_interface': '::1'}, 'psn_interface'))
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(core.SettingsError) as caught:
                    core.Settings.from_dict(dict(core.Settings().to_dict(), **changes))
                self.assertIn(field, caught.exception.fields)

    def test_release_marker_is_a_local_action_without_ma_commands(self):
        s = core.Settings.from_dict(dict(core.Settings().to_dict(), buttons={'4': {'action': 'release_marker'}}))
        self.assertEqual(core.local_actions([4], s.buttons), ['release_marker'])
        with self.assertRaises(core.SettingsError):
            core.Settings.from_dict(dict(core.Settings().to_dict(),
                                         buttons={'4': {'action': 'release_marker', 'press': 'Go+'}}))
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_core.PsnSettingsTests -v`
Expected: FAIL (`position_output` unknown, `release_marker` invalid action).

- [ ] **Step 3: Implement**

In `followspot_core.py` add `import ipaddress` with the other imports (alphabetical, before `import json`). Replace the `BUTTON_ACTIONS` block with:

```python
BUTTON_ACTIONS = {'command': 'MA command', 'start': 'Start output',
                  'stop': 'Stop output', 'toggle': 'Toggle output',
                  'reset': 'Reset target', 'release_marker': 'Release PSN marker'}
PSN_FIELDS = ('position_output', 'psn_tracker_id', 'psn_group', 'psn_port', 'psn_interface')
```

In `Settings`, after `prefix: str = ''` and before `buttons`:

```python
    position_output: str = 'osc'
    psn_tracker_id: int = 1
    psn_group: str = '236.10.10.10'
    psn_port: int = 56565
    psn_interface: str = '127.0.0.1'
```

In `validate`, directly after the OSC `port` check (`if not 1 <= self.port <= 65535: ...`):

```python
        if self.position_output not in ('osc', 'psn'):
            raise SettingsError('Position output must be osc or psn.', 'position_output')
        if not 1 <= self.psn_tracker_id <= 65535:
            raise SettingsError('PSN tracker ID must be 1–65535.', 'psn_tracker_id')
        if not 1 <= self.psn_port <= 65535:
            raise SettingsError('PSN port must be 1–65535.', 'psn_port')
        try:
            group_is_multicast = ipaddress.IPv4Address(self.psn_group).is_multicast
        except ValueError:
            group_is_multicast = False
        if not group_is_multicast:
            raise SettingsError('PSN group must be an IPv4 multicast address such as 236.10.10.10.', 'psn_group')
        try:
            ipaddress.IPv4Address(self.psn_interface)
        except ValueError:
            raise SettingsError('PSN interface must be an IPv4 address of this computer, for example 127.0.0.1.', 'psn_interface') from None
```

Then update `settings.example.json`: add these keys with the default values, next to `prefix`, keeping the file's indentation:

```json
  "position_output": "osc",
  "psn_tracker_id": 1,
  "psn_group": "236.10.10.10",
  "psn_port": 56565,
  "psn_interface": "127.0.0.1",
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -4; python3 followspot.py --settings settings.example.json --check-settings`
Expected: `OK` and the settings check passes. If a window test fails because it lists button actions, fix the test's expectation only if it asserted the exact action list; otherwise investigate.

- [ ] **Step 5: Commit**

```bash
git add followspot_core.py settings.example.json tests/test_core.py
git commit -m "feat(settings): add PSN position output settings and release action"
```

---

### Task 3: PSN packet encoders

**Files:**
- Modify: `followspot_core.py` (add after `osc_packet`)
- Test: `tests/test_psn.py` (new)

**Interfaces:**
- Produces: `psn_chunk(chunk_id: int, payload: bytes, has_children: bool = False) -> bytes`; `psn_data_packet(tracker_id: int, xyz, timestamp_us: int, frame: int) -> bytes`; `psn_info_packet(system_name: str, tracker_id: int, tracker_name: str, timestamp_us: int, frame: int) -> bytes`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_psn.py`:

```python
"""PSN encoder and streamer tests; no network access is needed."""
import struct
import threading
import time
import unittest

import followspot_core as core

# Pinned from the encoder verified against the PSN-CPP reference decoder:
# tracker 300, position (1.0, -2.0, 3.5), timestamp 0x0102030405060708, frame 5.
DATA_BYTES = bytes.fromhex(
    '5567288000000c00080706050403020102000501010014802c01108000000c000000803f000000c000006040')
INFO_BYTES = bytes.fromhex(
    '5667348000000c0008070605040302010200050101000a00466f6c6c6f7773706f74020012802c010e8000000a00466f6c6c6f7773706f74')


def parse(data):
    """Independent chunk reader: list of (id, children-or-payload)."""
    chunks, offset = [], 0
    while offset < len(data):
        (header,) = struct.unpack_from('<I', data, offset)
        chunk_id, length, nested = header & 0xFFFF, (header >> 16) & 0x7FFF, bool(header >> 31)
        body = data[offset + 4:offset + 4 + length]
        assert len(body) == length, 'truncated chunk'
        chunks.append((chunk_id, parse(body) if nested else body))
        offset += 4 + length
    return chunks


class PsnEncoderTests(unittest.TestCase):
    def test_data_packet_bytes_are_pinned(self):
        self.assertEqual(core.psn_data_packet(300, (1.0, -2.0, 3.5), 0x0102030405060708, 5), DATA_BYTES)

    def test_info_packet_bytes_are_pinned(self):
        self.assertEqual(core.psn_info_packet('Followspot', 300, 'Followspot', 0x0102030405060708, 5), INFO_BYTES)

    def test_data_structure_carries_tracker_above_255_and_negative_coordinates(self):
        ((packet_id, children),) = parse(core.psn_data_packet(300, (1.0, -2.0, 3.5), 7, 5))
        self.assertEqual(packet_id, 0x6755)
        (header_id, header), (list_id, trackers) = children
        self.assertEqual((header_id, list_id), (0x0000, 0x0001))
        timestamp, high, low, frame, count = struct.unpack('<QBBBB', header)
        self.assertEqual((timestamp, high, low, frame, count), (7, 2, 0, 5, 1))
        ((tracker_id, ((pos_id, pos),)),) = trackers
        self.assertEqual((tracker_id, pos_id), (300, 0x0000))
        self.assertEqual(struct.unpack('<3f', pos), (1.0, -2.0, 3.5))

    def test_frame_number_wraps_to_one_byte(self):
        ((_, children),) = parse(core.psn_data_packet(1, (0, 0, 0), 0, 256 + 3))
        self.assertEqual(struct.unpack('<QBBBB', children[0][1])[3], 3)

    def test_info_names_the_system_and_the_tracker(self):
        ((packet_id, children),) = parse(core.psn_info_packet('Rig', 2, 'Spot', 0, 0))
        self.assertEqual(packet_id, 0x6756)
        self.assertEqual([c[0] for c in children], [0x0000, 0x0001, 0x0002])
        self.assertEqual(children[1][1], b'Rig')
        ((tracker_id, ((name_id, name),)),) = children[2][1]
        self.assertEqual((tracker_id, name_id, name), (2, 0x0000, b'Spot'))

    def test_oversized_chunk_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            core.psn_chunk(1, b'x' * 0x8000)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_psn -v`
Expected: FAIL with `AttributeError: module 'followspot_core' has no attribute 'psn_data_packet'`.

- [ ] **Step 3: Implement**

In `followspot_core.py` after `osc_packet`:

```python
PSN_DATA, PSN_INFO = 0x6755, 0x6756


def psn_chunk(chunk_id, payload, has_children=False):
    """One PSN chunk: header is id | length << 16 | has_children << 31, little-endian."""
    if len(payload) > 0x7FFF:
        raise ValueError('PSN chunk payload is too long.')
    return struct.pack('<I', chunk_id | len(payload) << 16 | int(has_children) << 31) + payload


def _psn_header(timestamp_us, frame):
    # Version 2.0, one packet per frame.
    return psn_chunk(0x0000, struct.pack('<QBBBB', timestamp_us, 2, 0, frame & 255, 1))


def psn_data_packet(tracker_id, xyz, timestamp_us, frame):
    position = psn_chunk(0x0000, struct.pack('<3f', *xyz))
    trackers = psn_chunk(0x0001, psn_chunk(tracker_id, position, True), True)
    return psn_chunk(PSN_DATA, _psn_header(timestamp_us, frame) + trackers, True)


def psn_info_packet(system_name, tracker_id, tracker_name, timestamp_us, frame):
    name = psn_chunk(0x0000, tracker_name.encode('utf-8'))
    trackers = psn_chunk(0x0002, psn_chunk(tracker_id, name, True), True)
    return psn_chunk(PSN_INFO, _psn_header(timestamp_us, frame)
                     + psn_chunk(0x0001, system_name.encode('utf-8')) + trackers, True)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_psn -v`
Expected: all encoder tests PASS (the unused `threading`/`time` imports are used by Task 4).

- [ ] **Step 5: Commit**

```bash
git add followspot_core.py tests/test_psn.py
git commit -m "feat(psn): add PSN v2 data and info packet encoders"
```

---

### Task 4: PsnStreamer

**Files:**
- Modify: `followspot_core.py` (imports `threading`, `time`; add class after the encoders)
- Test: `tests/test_psn.py`

**Interfaces:**
- Consumes: `psn_data_packet`, `psn_info_packet`, `Settings.psn_*`.
- Produces: `PsnStreamer(settings, xyz, sock=None, clock=time.monotonic, start=True)` with `.position` (tuple property), `.set_position(xyz)`, `.step()` (sends one frame, used by the thread and tests), `.poll_error() -> Exception | None` (returns and clears), `.close()` (idempotent, never raises into the caller). Constants `PSN_RATE = 30.0`, `PSN_SYSTEM_NAME = 'Followspot'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_psn.py`:

```python
class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.fail = None

    def sendto(self, data, destination):
        if self.fail:
            raise self.fail
        self.sent.append((data, destination))

    def close(self):
        self.closed = True


def streamer(clock, sock=None, start=False, **changes):
    settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn', **changes))
    sock = sock or FakeSocket()
    return core.PsnStreamer(settings, (1.0, 2.0, 1.5), sock=sock, clock=clock, start=start), sock


class PsnStreamerTests(unittest.TestCase):
    def test_first_step_sends_info_then_data_to_the_configured_group(self):
        now = [100.0]
        s, sock = streamer(lambda: now[0], psn_tracker_id=7, psn_group='239.1.2.3', psn_port=6000)
        s.step()
        self.assertEqual([d for _, d in sock.sent], [('239.1.2.3', 6000)] * 2)
        self.assertEqual(parse(sock.sent[0][0])[0][0], 0x6756)
        data = parse(sock.sent[1][0])
        self.assertEqual(data[0][0], 0x6755)
        self.assertEqual(data[0][1][1][1][0][0], 7)

    def test_info_repeats_about_once_a_second_and_data_every_step(self):
        now = [0.0]
        s, sock = streamer(lambda: now[0])
        kinds = []
        for _ in range(70):
            before = len(sock.sent)
            s.step()
            kinds.append([parse(p)[0][0] for p, _ in sock.sent[before:]])
            now[0] += 0.034
        info_steps = [i for i, k in enumerate(kinds) if 0x6756 in k]
        self.assertEqual(info_steps, [0, 30, 60])
        self.assertTrue(all(0x6755 in k for k in kinds))

    def test_set_position_changes_what_is_sent_and_frames_count_up(self):
        now = [0.0]
        s, sock = streamer(lambda: now[0])
        s.step()
        s.set_position((-3.0, 4.0, 2.0))
        now[0] += 0.033
        s.step()
        last = parse(sock.sent[-1][0])[0][1]
        self.assertEqual(struct.unpack('<3f', last[1][1][0][1][0][1]), (-3.0, 4.0, 2.0))
        self.assertEqual(struct.unpack('<QBBBB', last[0][1])[3], 1)
        self.assertEqual(s.position, (-3.0, 4.0, 2.0))

    def test_send_error_is_stored_not_raised_and_cleared_on_read(self):
        s, sock = streamer(time.monotonic, start=True)
        sock.fail = OSError('network down')
        deadline = time.monotonic() + 2
        error = None
        while error is None and time.monotonic() < deadline:
            error = s.poll_error()
            time.sleep(0.01)
        s.close()
        self.assertIsInstance(error, OSError)
        self.assertIsNone(s.poll_error())

    def test_thread_streams_until_closed_and_close_is_idempotent(self):
        s, sock = streamer(time.monotonic, start=True)
        deadline = time.monotonic() + 2
        while len(sock.sent) < 6 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(len(sock.sent), 6)
        s.close()
        s.close()
        count = len(sock.sent)
        time.sleep(0.1)
        self.assertEqual(len(sock.sent), count)
        self.assertTrue(sock.closed)
        s.set_position((0, 0, 0))
        self.assertFalse([t for t in threading.enumerate() if t.name == 'psn-stream'])

    def test_real_socket_opens_with_the_loopback_interface(self):
        settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn'))
        try:
            s = core.PsnStreamer(settings, (0, 0, 0), start=False)
        except PermissionError:
            self.skipTest('sandbox denies UDP sockets')
        s.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_psn.PsnStreamerTests -v`
Expected: FAIL (`PsnStreamer` missing).

- [ ] **Step 3: Implement**

In `followspot_core.py` add `import threading` and `import time` to the imports (alphabetical: `socket`, `struct`, `threading`, `time`, then `from typing ...`). After the PSN encoders:

```python
PSN_RATE = 30.0
PSN_SYSTEM_NAME = 'Followspot'


class PsnStreamer:
    """Streams one tracker's latest position as PSN at about 30 Hz.

    A stopped stream makes onPC reset the MArker to 0, 0, 0, so the thread
    keeps sending even while the joystick is idle. Errors are stored for
    the window's poll; nothing is raised into the Tk callback.
    """
    def __init__(self, settings, xyz, sock=None, clock=time.monotonic, start=True):
        self.destination = (settings.psn_group, settings.psn_port)
        self.tracker_id = settings.psn_tracker_id
        self.clock = clock
        self.began = clock()
        self.lock = threading.Lock()
        self._xyz = tuple(xyz)
        self._error = None
        self.frame = 0
        self.last_info = None
        self.stopping = threading.Event()
        self.thread = None
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(settings.psn_interface))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            except OSError:
                sock.close()
                raise
        self.socket = sock
        if start:
            self.thread = threading.Thread(target=self._run, name='psn-stream', daemon=True)
            self.thread.start()

    @property
    def position(self):
        with self.lock:
            return self._xyz

    def set_position(self, xyz):
        with self.lock:
            self._xyz = tuple(xyz)

    def poll_error(self):
        with self.lock:
            error, self._error = self._error, None
        return error

    def step(self):
        now = self.clock()
        timestamp = int((now - self.began) * 1_000_000)
        if self.last_info is None or now - self.last_info >= 1.0:
            self.socket.sendto(psn_info_packet(PSN_SYSTEM_NAME, self.tracker_id, PSN_SYSTEM_NAME,
                                               timestamp, self.frame), self.destination)
            self.last_info = now
        self.socket.sendto(psn_data_packet(self.tracker_id, self.position, timestamp, self.frame), self.destination)
        self.frame += 1

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.step()
            except Exception as exc:
                with self.lock:
                    self._error = exc
                return
            self.stopping.wait(1 / PSN_RATE)

    def close(self):
        self.stopping.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)
        self.socket.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_psn -v`
Expected: PASS. The INFO test steps the clock by 0.034 s (not exactly 1/30) so float accumulation cannot move the 1-second INFO boundary; with that step INFO is sent at steps 0, 30 and 60.

- [ ] **Step 5: Commit**

```bash
git add followspot_core.py tests/test_psn.py
git commit -m "feat(psn): add the background PSN streamer"
```

---

### Task 5: Controller PSN mode

**Files:**
- Modify: `followspot_core.py` (`Controller.__init__`, `_output_position`)
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `Settings.position_output`.
- Produces: `Controller(settings, send, send_position=None)`; in PSN mode every output calls `send_position(tuple_xyz)`; OSC mode unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_core.py`:

```python
class PsnControllerTests(unittest.TestCase):
    def psn(self, **changes):
        settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn', **changes))
        sent, positions = [], []
        controller = core.Controller(settings, lambda a, v: sent.append((a, v)), positions.append)
        return controller, sent, positions

    def test_psn_mode_requires_a_position_callback(self):
        settings = core.Settings.from_dict(dict(core.Settings().to_dict(), position_output='psn'))
        with self.assertRaises(ValueError):
            core.Controller(settings, lambda a, v: None)

    def test_psn_mode_sends_positions_not_marker_commands(self):
        controller, sent, positions = self.psn()
        controller.start([0, 0, -1])
        controller.tick([1, 0, -1], 0.1)
        self.assertEqual(positions[0], (0.0, 0.0, 1.5))
        self.assertGreater(positions[-1][0], 0.0)
        self.assertFalse([a for a, _ in sent if a == '/cmd'])

    def test_psn_mode_keeps_brightness_zoom_and_button_commands_on_osc(self):
        controller, sent, _ = self.psn(zoom_enabled=True, buttons={'0': {'press': 'Go+ Sequence 10', 'release': 'Off'}})
        edges = core.ButtonEdges()
        edges.seed([False])
        controller.start([0, 0, -1, 0])
        presses, releases = edges.sample([True])
        controller.tick([0, 0, -1, 0], 0.03, presses, releases)
        self.assertIn(('/Page1/Fader201', 0.0), sent)
        self.assertIn(('/Page1/Fader202', 50.0), sent)
        self.assertIn(('/cmd', 'Go+ Sequence 10'), sent)

    def test_psn_mode_resends_position_every_tick_even_when_idle(self):
        controller, _, positions = self.psn()
        controller.start([0, 0, -1])
        controller.tick([0, 0, -1], 0.03)
        controller.tick([0, 0, -1], 0.03)
        self.assertEqual(len(positions), 3)

    def test_live_reset_in_psn_mode_sends_the_initial_position(self):
        controller, _, positions = self.psn(reset_locked=False, initial_x=1.0)
        controller.start([0, 0, -1])
        controller.motion.xyz = [5.0, 5.0, 1.5]
        controller.reset_target()
        self.assertEqual(positions[-1], (1.0, 0.0, 1.5))

    def test_osc_mode_is_unchanged(self):
        sent = []
        controller = core.Controller(core.Settings(), lambda a, v: sent.append((a, v)))
        controller.start([0, 0, -1])
        self.assertTrue(sent[0][1].startswith('ClearSelection; MArker 1;'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_core.PsnControllerTests -v`
Expected: FAIL (`Controller` takes 2 positional arguments). The expected values were checked against the current OSC path: slider -1 sends brightness 0 and an enabled zoom starts at 50.0.

- [ ] **Step 3: Implement**

In `Controller.__init__` replace the signature and first lines:

```python
    def __init__(self, settings, send, send_position=None):
        settings.validate()
        if settings.position_output == 'psn' and send_position is None:
            raise ValueError('PSN position output needs a position callback.')
        self.settings = settings
        self.send_position = send_position
```

(keep the remaining attribute lines as they are). Replace `_output_position`:

```python
    def _output_position(self):
        if self.settings.position_output == 'psn':
            # The streamer keeps sending; the selection is never touched.
            self.send_position(tuple(self.motion.xyz))
            return
        commands = marker_commands(self.settings, self.motion.xyz)
        if commands != self.last_commands:
            # Keep selection and XYZ assignments in one OSC command string.
            # MA does not accept OSC bundles.
            self.send('/cmd', '; '.join(commands))
            self.last_commands = commands
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add followspot_core.py tests/test_core.py
git commit -m "feat(controller): send position through PSN when selected"
```

---

### Task 6: App lifecycle wiring

**Files:**
- Modify: `followspot.py` (import line, `App.__init__`, `input_lost`, `apply_settings`, `start_output`, `stop_output`, `poll`, `process_input`, `close`; new methods)
- Modify: `tests/test_window.py` (helper and new tests)

**Interfaces:**
- Consumes: `PsnStreamer`, `PSN_FIELDS`, `Controller(settings, send, send_position)`.
- Produces on `App`: `streamer` (None or `PsnStreamer`), `send_position(xyz)`, `open_streamer() -> bool` (True if it created one), `close_streamer()`, `release_marker() -> bool`, `check_streamer()`; fault kind `'psn'`.

- [ ] **Step 1: Update the test helper and add failing tests**

In `tests/test_window.py`, add a `FakeStreamer` class after `Sender`:

```python
class FakeStreamer:
    def __init__(self, settings, xyz):
        self.positions = [tuple(xyz)]
        self.closed = False
        self.error = None

    @property
    def position(self):
        return self.positions[-1]

    def set_position(self, xyz):
        self.positions.append(tuple(xyz))

    def poll_error(self):
        error, self.error = self.error, None
        return error

    def close(self):
        self.closed = True
```

In `WindowTests.app`: after `app.sender = None` add `app.streamer = None`; change `app.controller = Controller(app.settings, app.send)` to `app.controller = Controller(app.settings, app.send, app.send_position)`; replace `app.messagebox = SimpleNamespace(showerror=lambda *args: app.errors.append(args))` with:

```python
        app.confirm = True
        app.messagebox = SimpleNamespace(showerror=lambda *args: app.errors.append(args),
                                         askokcancel=lambda *args: app.confirm)
```

and just before `return app, messages` add:

```python
        self.streamers = []
        def new_streamer(settings, xyz):
            streamer = FakeStreamer(settings, xyz)
            self.streamers.append(streamer)
            return streamer
        streamer_patch = patch.object(followspot, 'PsnStreamer', side_effect=new_streamer)
        streamer_patch.start()
        self.addCleanup(streamer_patch.stop)
```

Add `from unittest.mock import patch` is already imported. Append the new test class after `WindowTests` (the `app = WindowTests.app` line reuses the helper without re-running its tests):

```python
class PsnWindowTests(unittest.TestCase):
    app = WindowTests.app

    def test_psn_mode_sends_no_marker_commands_stop_holds_release_closes(self):
        app, messages = self.app(position_output='psn')
        app.start_output()
        self.assertTrue(app.controller.active)
        self.assertEqual(len(self.streamers), 1)
        self.assertFalse([m for m in messages if m[0] == '/cmd'])
        self.assertTrue([m for m in messages if m[0].startswith('/Page1/Fader')])
        app.controller.tick([1.0, 0, 0], 0.1)
        self.assertGreater(self.streamers[0].position[0], 0)
        app.stop_output()
        self.assertFalse(app.controller.active)
        self.assertIs(app.streamer, self.streamers[0])
        self.assertFalse(self.streamers[0].closed)
        self.assertIn('Release marker', app.status.get())
        self.assertTrue(app.release_marker())
        self.assertTrue(self.streamers[0].closed)
        self.assertIsNone(app.streamer)
        self.assertIn('0, 0, 0', app.status.get())

    def test_osc_mode_never_creates_a_streamer(self):
        app, messages = self.app()
        app.start_output()
        self.assertEqual(self.streamers, [])
        self.assertTrue([m for m in messages if m[0] == '/cmd'])
        self.assertFalse(app.release_marker())
        self.assertIn('No PSN stream', app.status.get())

    def test_restart_reuses_the_held_stream(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.start_output()
        self.assertEqual(len(self.streamers), 1)

    def test_streamer_error_with_no_joystick_stops_output_and_records_a_fault(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.joystick = None
        self.streamers[0].error = OSError('network down')
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)
        self.assertTrue(self.streamers[0].closed)
        self.assertIn('network down', app.faults['psn'])

    def test_held_stream_error_while_stopped_is_reported(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.joystick = None
        self.streamers[0].error = OSError('network down')
        app.poll()
        self.assertIsNone(app.streamer)
        self.assertIn('psn', app.faults)

    def test_failed_start_closes_only_a_stream_it_created(self):
        app, messages = self.app(position_output='psn')
        failing = Sender(messages)
        failing.fail = True
        with patch.object(followspot, 'OscSender', return_value=failing):
            app.start_output()
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)
        self.assertTrue(self.streamers[0].closed)
        app.start_output()
        app.stop_output()
        with patch.object(followspot, 'OscSender', return_value=failing):
            app.start_output()
        self.assertIsNotNone(app.streamer)
        self.assertFalse(self.streamers[1].closed)

    def test_psn_settings_cannot_change_while_a_stream_is_open(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.stop_output()
        app.values['psn_port'].set('56570')
        self.assertFalse(app.apply_settings())
        self.assertEqual(app.settings.psn_port, 56565)
        app.release_marker()
        self.assertTrue(app.apply_settings())
        self.assertEqual(app.settings.psn_port, 56570)

    def test_joystick_loss_holds_the_stream_and_says_so(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        def unplugged():
            raise OSError('unplugged')
        app.joystick.read = unplugged
        app.poll()
        self.assertFalse(app.controller.active)
        self.assertIsNotNone(app.streamer)
        self.assertFalse(self.streamers[0].closed)
        self.assertIn('Release marker', app.faults['input'])

    def test_release_marker_button_ranks_after_stop_and_before_start(self):
        app, _ = self.app(position_output='psn',
                          buttons={'0': {'action': 'release_marker'}, '1': {'action': 'start'}, '2': {'action': 'stop'}})
        app.start_output()
        app.stop_output()
        app.buttons = [True, True, False]
        app.process_input(0.033)
        self.assertIsNone(app.streamer)
        self.assertFalse(app.controller.active)
        app.start_output()
        app.buttons = [False, False, False]
        app.button_edges.seed(app.buttons)
        app.buttons = [True, False, True]
        app.process_input(0.033)
        self.assertFalse(app.controller.active)
        self.assertIsNone(app.streamer)

    def test_close_asks_before_dropping_a_held_stream(self):
        app, _ = self.app(position_output='psn')
        destroyed = []
        app.root.destroy = lambda: destroyed.append(True)
        app.joystick.shutdown = lambda: None
        app.start_output()
        app.confirm = False
        app.close()
        self.assertEqual(destroyed, [])
        self.assertTrue(app.controller.active)
        app.confirm = True
        app.close()
        self.assertEqual(destroyed, [True])
        self.assertTrue(self.streamers[0].closed)
```

Note: `Sender`'s `fail` flag makes `send` raise `OSError('send failed')`; the failed Start therefore ends in the existing error path.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_window.PsnWindowTests -v`
Expected: FAIL (`App` has no `send_position`, `PsnStreamer` not in `followspot`). Also run the existing suite: `python3 -m unittest tests.test_window -v` should still pass apart from the new class.

- [ ] **Step 3: Implement in `followspot.py`**

Change the core import to include the new names:

```python
from followspot_core import (BUTTON_ACTIONS, PSN_FIELDS, ButtonEdges, Controller, OscSender, PsnStreamer, Settings,
                              SettingsError, clamp, learn_axis, local_actions, setting_types)
```

In `App.__init__`: after `self.sender = None` add `self.streamer = None`; change the controller line to `self.controller = Controller(self.settings, self.send, self.send_position)`.

In `apply_settings`, replace `self.controller = Controller(settings, self.send)` with `self.controller = Controller(settings, self.send, self.send_position)` and, inside the `try` right after `settings = settings_from_values(self.values, self.draft_buttons)` and before `settings.save(...)`, add:

```python
            if self.streamer is not None and any(getattr(settings, key) != getattr(self.settings, key) for key in PSN_FIELDS):
                raise SettingsError('Release the PSN marker before changing position output or PSN settings.', *PSN_FIELDS)
```

In `start_output`: define `created_stream = False` immediately before the `try:`; after `self.sender = OscSender(s.host, s.port, s.prefix)` add:

```python
            if s.position_output == 'psn':
                created_stream = self.open_streamer()
```

after `self.clear_fault('output')` add `self.clear_fault('psn')`; and in `except (OSError, RuntimeError, ValueError) as exc:` insert as its first line `if created_stream: self.close_streamer()`.

Add these methods next to `send` / `stop_output`:

```python
    def send_position(self, xyz):
        if self.streamer is None:
            raise OSError('PSN stream is not open.')
        self.streamer.set_position(xyz)

    def open_streamer(self):
        """Open the PSN stream unless one is already held; True when this call created it."""
        if self.streamer is not None:
            return False
        self.streamer = PsnStreamer(self.settings, self.controller.motion.xyz)
        return True

    def close_streamer(self):
        if self.streamer is not None:
            self.streamer.close()
            self.streamer = None

    def release_marker(self):
        if self.streamer is None:
            self.status.set('No PSN stream is open.')
            return False
        if self.controller.active:
            self.stop_output()
        self.close_streamer()
        self.clear_fault('psn')
        self.update_position()
        self.status.set('PSN marker released. onPC resets the MArker to 0, 0, 0.')
        return True

    def check_streamer(self):
        """A held stream may outlive output and the joystick; surface its failure from every poll."""
        if self.streamer is None:
            return
        error = self.streamer.poll_error()
        if error is None:
            return
        reason = f'PSN stream failed: {error}. The marker returns to 0, 0, 0 in onPC.'
        self.close_streamer()
        if self.controller.active:
            self.stop_output(reason, fault_kind='psn')
        else:
            self.record_fault('psn', reason)
            self.status.set(reason)
        self.update_position()
```

In `stop_output`, after the `message = ...` line add:

```python
        if self.streamer is not None:
            message += ' PSN is still holding the marker; use Release marker to let it reset.'
```

and as the last statement of `stop_output` add `if self.streamer is not None: self.update_position()`.

In `input_lost`, extend the fault text:

```python
        hold = ' The PSN stream is still holding the marker; use Release marker to let it reset.' if self.streamer is not None else ''
        self.record_fault('input', f'Joystick unavailable — output stopped. {reason}\nReconnect it, then Refresh in Setup → Joystick.{hold}')
```

At the top of `poll`'s `try:` block add `self.check_streamer()` as the first statement.

Replace the start of `process_input`'s priority logic (from `# Stop wins;` through the `start_output` branch) with:

```python
        # Stop and Release marker both act; Start and Reset are then ignored this sample.
        # Otherwise Start wins over Reset when stopped and is ignored when active.
        stopping = 'stop' in actions or ('toggle' in actions and self.controller.active)
        releasing = 'release_marker' in actions
        if stopping:
            self.stop_output()
        if releasing:
            self.release_marker()
        if stopping or releasing:
            return
        if not self.controller.active and ('start' in actions or 'toggle' in actions):
            self.start_output()
            return
```

(the following `if 'reset' in actions and ...` block stays unchanged).

Replace `close`:

```python
    def close(self):
        if self.streamer is not None and not self.messagebox.askokcancel(
                'Close and reset the marker?',
                'The PSN stream is open. Closing stops it, and onPC resets the MArker to 0, 0, 0.'):
            return
        if self.controller:
            self.stop_output()
        self.close_streamer()
        if self.joystick:
            self.joystick.shutdown()
        self.root.destroy()
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -5`
Expected: `OK` (Tk tests may skip). Existing tests that built `Controller(app.settings, app.send)` elsewhere must still pass because OSC mode needs no callback. Fix any test that fails because `streamer` is missing on a hand-built `App`, by setting `app.streamer = None` in that helper, not by guarding the app code.

- [ ] **Step 5: Commit**

```bash
git add followspot.py tests/test_window.py
git commit -m "feat(window): stream PSN position, hold on Stop, add Release marker"
```

---

### Task 7: Window controls

**Files:**
- Modify: `followspot_ui.py` (`build_live`, `build_network`, `refresh`, `draw_stage`)
- Modify: `followspot.py` (`update_position` held text)
- Test: `tests/test_window.py` (`RealWindowTests`, `PsnWindowTests`)

**Interfaces:**
- Consumes: `App.streamer`, `App.release_marker`, `app.values['position_output']` and the four `psn_*` values.
- Produces: `app.release_button` (Tk button, packed only when PSN is selected or a stream is open), canvas item tagged `held`.

- [ ] **Step 1: Write the failing tests**

Add to `PsnWindowTests`:

```python
    def test_position_label_shows_the_held_position_while_stopped(self):
        app, _ = self.app(position_output='psn')
        app.start_output()
        app.controller.tick([1.0, 0, 0], 0.1)
        app.stop_output()
        self.assertIn('Held at', app.position_label.get())
        app.release_marker()
        self.assertNotIn('Held at', app.position_label.get())
```

Add to `RealWindowTests` (the real window must never reach the blocking confirmation dialog, so the test releases before the cleanup `app.close`):

```python
    def test_real_window_psn_controls_and_held_marker(self):
        streamers = []
        def new_streamer(settings, xyz):
            streamers.append(FakeStreamer(settings, xyz))
            return streamers[-1]
        with patch.object(followspot, 'PsnStreamer', side_effect=new_streamer):
            app = self.open_app(position_output='psn')
            self.assertIn('position_output', app.view.fields)
            app.view.refresh()
            self.assertEqual(str(app.release_button.cget('state')), 'disabled')
            app.start_output()
            app.view.refresh()
            self.assertEqual(str(app.release_button.cget('state')), 'normal')
            app.stop_output()
            app.root.update_idletasks()
            app.view.draw_stage()
            self.assertTrue(app.view.stage.find_withtag('held'))
            app.release_button.invoke()
            self.assertIsNone(app.streamer)
            app.view.draw_stage()
            self.assertFalse(app.view.stage.find_withtag('held'))
            self.assertIn('PSN', app.view.summary.get())
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_window.PsnWindowTests tests.test_window.RealWindowTests -v`
Expected: the first fails on the missing "Held at" text; the real-window test fails on `release_button` (or skips if Tk cannot open a window; report a skip honestly).

- [ ] **Step 3: Implement**

`followspot.py`, replace `update_position`:

```python
    def update_position(self):
        x, y, z = self.controller.motion.xyz
        text = f'X {x:+.3f} m   Y {y:+.3f} m   Z {z:.3f} m'
        if self.streamer is not None and not self.controller.active:
            hx, hy, hz = self.streamer.position
            text += f'\nHeld at  X {hx:+.3f} m   Y {hy:+.3f} m   Z {hz:.3f} m'
        self.position_label.set(text)
        self.zoom_label.set(f'Zoom / iris  {self.controller.motion.zoom_level:.1f}%' if self.settings.zoom_enabled else
                            'Zoom / iris  disabled')
        self.view.refresh()
```

`followspot_ui.py`:

1. In `build_live`, after the `ttk.Checkbutton(...)` line in the reset row add:

```python
        app.release_button = ttk.Button(reset, text='Release marker', command=app.release_marker)
```

(do not pack it here; `refresh` packs it).

2. In `build_network`, after the existing instruction label add rows 7–12 (the existing label sits at row 6):

```python
        caption = ttk.Label(parent, text='Position output')
        caption.grid(row=7, column=0, sticky='w', padx=(0, 16), pady=(16, 5))
        self.field_captions['position_output'] = caption
        box = self.edit(ttk.Combobox(parent, textvariable=self.app.values['position_output'], values=['osc', 'psn'],
                                     state='readonly', width=8), 'readonly')
        box.grid(row=7, column=1, sticky='w', pady=(16, 5))
        self.fields['position_output'] = box
        self.field_labels['position_output'] = 'Position output'
        self.field_pages['position_output'] = self.current_page
        for row, (key, label) in enumerate([('psn_tracker_id', 'PSN tracker ID'), ('psn_group', 'PSN multicast group'),
                                            ('psn_port', 'PSN port'), ('psn_interface', 'PSN interface (this computer)')], 8):
            self.entry(parent, row, label, key, width=26)
        self.label(parent, text='osc moves the MArker with commands and takes the console selection. psn streams the position without touching the selection; brightness, zoom / iris and buttons still use OSC. In onPC set the PSN row Interface to this computer, add a tracker whose Tracker ID and MArker ID match, and see docs/PSN.md. Stop holds the position; Release marker lets the MArker reset to 0, 0, 0.').grid(row=12, column=0, columnspan=3, sticky='w', pady=12)
```

3. In `refresh`, after `app.reset_button.configure(...)` add:

```python
        show_release = s.position_output == 'psn' or app.streamer is not None
        if show_release:
            app.release_button.pack(side='left', padx=(16, 0))
        else:
            app.release_button.pack_forget()
        app.release_button.configure(state='normal' if app.streamer is not None else 'disabled')
```

and extend the summary:

```python
        self.summary.set(f'{s.device_name or "No saved joystick"}  ·  MArker {s.marker_id}  ·  OSC {s.host}:{s.port}' +
                         (f' /{s.prefix}' if s.prefix else '') +
                         (f'  ·  PSN tracker {s.psn_tracker_id} → {s.psn_group}:{s.psn_port} via {s.psn_interface}'
                          if s.position_output == 'psn' else ''))
```

4. In `draw_stage`, after the `canvas.create_oval(... tags='target')` line add:

```python
        if self.app.streamer is not None and not self.app.controller.active:
            hx, hy, _ = self.app.streamer.position
            hpx = left + (clamp(hx, s.x_min, s.x_max) - s.x_min) * scale
            hpy = bottom - (clamp(hy, s.y_min, s.y_max) - s.y_min) * scale
            canvas.create_oval(hpx-8, hpy-8, hpx+8, hpy+8, outline=color, dash=(3, 2), tags='held')
```

Because `refresh` is called by the hand-built test `App` with a `SimpleNamespace` view, the `WindowTests` helper is unaffected.

- [ ] **Step 4: Run all tests and look at the window**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -5; git diff --check`
Expected: `OK`. Then, if a display is available, launch `python3 followspot.py`, open Setup → OSC and confirm the Position output selector and PSN fields appear and the Live view shows Release marker only after choosing psn and saving. If no display is available, say so in the report; do not call the UI verified.

- [ ] **Step 5: Commit**

```bash
git add followspot.py followspot_ui.py tests/test_window.py
git commit -m "feat(ui): add PSN selector, Release marker and held-position display"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/PSN.md`, `docs/GRANDMA3_SETUP.md`, `docs/OPERATING.md`, `README.md`, `AGENTS.md`, `docs/superpowers/specs/2026-10-14-psn-output-design.md`

Keep each fact in one place and link rather than duplicate.

- [ ] **Step 1: Turn `docs/PSN.md` into the PSN guide**

Replace its status line with "Status: available as an optional output in the app (Setup → OSC → Position output). Verified in onPC 2.5.0.3 with the test sender; not yet checked with the real joystick or a real show." Add after "Configure onPC" a section "Configure the app":

```markdown
## Configure the app

1. Stop output and open **Setup → OSC**.
2. Set **Position output** to `psn`. Leave the tracker ID, group, port and interface at their defaults when onPC runs on this Mac (tracker 1, `236.10.10.10`, `56565`, interface `127.0.0.1`), and match the tracker ID to the PSN row in onPC.
3. **Save settings**, then Start. The Live view gets a **Release marker** button.

What changes in PSN mode: the app no longer sends `ClearSelection; MArker ...`, so your selection and encoders stay free. Brightness, zoom / iris and buttons still go over OSC, so the OSC setup in [GRANDMA3_SETUP.md](GRANDMA3_SETUP.md) is still needed.

**Stop and Release marker.** PSN has no hold: if packets stop, onPC resets the MArker to 0, 0, 0. So **Stop keeps sending the last position** and the lights stay put; **Release marker** (Live button, or a button mapped to "Release PSN marker") ends the stream, and the MArker then resets to 0, 0, 0. Closing the window asks before it does this. If the app crashes or the computer sleeps, the stream stops and the MArker resets. A joystick disconnect or an OSC failure stops output but keeps the stream holding.

Settings in the PSN group cannot be changed while a stream is open; Release marker first. The Fixture Sheet and the MArker encoders do not show the PSN position (they read 0, 0, 0); use the 3D view or the PSN row.
```

Add a section "Running the script on a different computer (unverified)":

```markdown
## Script on a different computer (unverified)

Not tested. The same-Mac setup above is the only verified one. In principle:

1. Put both computers on the same network segment. PSN is multicast UDP, so the switch or Wi-Fi must pass multicast (IGMP snooping misconfigured, or Wi-Fi multicast filtering, are common causes of silence).
2. In onPC, set the PSN **Interface** to onPC's network interface instead of `lo0`, and keep the multicast group and port.
3. In the app, set **PSN interface** to this computer's IPv4 address on that same network (not `127.0.0.1`).
4. OSC still needs its own setup: set **onPC host / IP** and the OSC Interface as in GRANDMA3_SETUP.md Step 8.
5. A VPN can take the default multicast route. On the test Mac, sending multicast through the LAN interface failed with "No route to host" because the default multicast route went through the VPN tunnel; disconnect the VPN or add a multicast route for the interface.

Check with `lsof -nP -iUDP:56565` on the onPC computer and watch the tracker in the PSN menu.
```

Add a "Troubleshooting" list: tracker stays red (interface, tracker/MArker IDs, Enable Input); marker moves then jumps to 0, 0, 0 (stream stopped or Released); nothing moves (merge mode Prio, requested). Update the "Open decisions" section: remove the items now decided and keep the unmeasured snap-back timeout and App Nap notes.

- [ ] **Step 2: Update the other docs**

- `docs/GRANDMA3_SETUP.md`: replace the line I added under References with a pointer in Step 8 ("To keep the console selection free, use PSN position output: see [PSN.md](PSN.md)").
- `docs/OPERATING.md`: in Stop and restart add one paragraph (PSN Stop holds, Release marker, closing asks); in the button-priority list add "Release marker acts with Stop and beats Start and Reset (both ignored in that sample)"; update the limitation about the selection to say PSN mode avoids it and OSC idle-resend rule is per mode; note `release_marker` in the valid actions sentence of "Settings file", and document the five new settings.
- `README.md`: adjust the PSN row in the documentation table to say it is available.
- `AGENTS.md`: code map rows for `PsnStreamer`/`tools/psn_test_sender.py`; integration contracts: add a PSN paragraph (position output setting, streamer thread, Stop holds, Release marker, lifecycle events, idle streaming exception to "no idle resend", fault kind `psn`); update the handoff note: "implemented 2026-10-14; automated tests only; not verified with the real joystick or a real show".

- [ ] **Step 3: Align the spec with what was built**

In `docs/superpowers/specs/2026-10-14-psn-output-design.md` make three small edits: (a) the UI section says PSN fields are "editable only while stopped and not holding" - change to "editable while stopped; applying a change is refused while a stream is open"; (b) the priority sentence - "Stop and Release marker both act; Start and Reset are then ignored for that sample"; (c) the streamer test line - drop the "One real loopback UDP test" clause, replacing it with "One test opens a real socket on the loopback interface and skips when the sandbox denies it; multicast reception is checked manually with `tools/psn_test_sender.py`".

- [ ] **Step 4: Verify and commit**

Run: `git diff --check && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: no whitespace errors, tests `OK`.

```bash
git add docs README.md AGENTS.md
git commit -m "docs: document PSN position output and Release marker"
```

---

### Task 9: Final verification and operator checklist

**Files:** none changed unless a check fails.

- [ ] **Step 1: Full automated run**

Run: `python3 -m unittest discover -s tests -v 2>&1 | tail -15; python3 followspot.py --settings settings.example.json --check-settings; git diff --check; git status --short`
Expected: tests `OK` (report the skip count and why), settings check passes, no stray files. Confirm `settings.json` is not in the diff.

- [ ] **Step 2: Manual checks for the operator (cannot be automated; report as not yet done until the operator confirms)**

1. onPC set up per `docs/PSN.md`; app set to `psn`; Start the figure-8 test. Expect: the MArker traces a figure 8 in the 3D view, and the selection and encoders stay untouched.
2. Press Stop. Expect: the MArker stays; press Release marker, and it drops to 0, 0, 0.
3. Start with the joystick; move the stick; confirm brightness and (if enabled) zoom / iris still work over OSC.
4. Pull the joystick cable mid-output. Expect: output stops, the MArker stays, the fault mentions Release marker.
5. Close the window while holding. Expect: a confirmation dialog.

- [ ] **Step 3: Report**

Summarize what was verified (tests, which skipped) separately from what needs the operator (steps above), and the branch state (`feat/psn-output`, local commits, nothing pushed).

---

## Self-Review

- **Spec coverage:** settings (Task 2), encoder (3), streamer incl. injectable socket/clock and join timeout (4), controller (5), lifecycle table events: Stop holds, Release closes, window close, `input_lost` holds, OSC failure holds (no code change; covered by `stop_output` holding), Start failure, streamer error (6); first-packet position, two Controller construction sites, `release_marker` naming and priority, Release button keyed to stream, held display, close confirmation, settings refusal (6, 7); validation unchanged (2); tests incl. new example-equality test (2); docs incl. another-computer section (8).
- **Placeholder scan:** none found. Two numeric assumptions in the tests (INFO timing, controller values) were checked by running the current code.
- **Type consistency:** `PsnStreamer(settings, xyz, sock=None, clock=..., start=True)`, `FakeStreamer(settings, xyz)` and `followspot.PsnStreamer(self.settings, self.controller.motion.xyz)` agree; `release_marker`, `open_streamer`, `close_streamer`, `check_streamer`, `send_position` are used consistently; fault kind `'psn'`.
