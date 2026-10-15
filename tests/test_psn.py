"""PSN encoder and streamer tests; no network access is needed."""
import socket
import struct
import threading
import time
import unittest

import followspot_core as core

# Pinned bytes; tools/psn_test_sender.py (verified in onPC) produces identical bytes for these inputs:
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
        try:
            self.assertEqual(s.socket.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, 4), socket.inet_aton('127.0.0.1'))
            self.assertEqual(s.socket.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL), 1)
        finally:
            s.close()
