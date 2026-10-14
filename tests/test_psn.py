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
