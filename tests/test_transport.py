"""Receive real UDP packets on loopback; never contact onPC or multicast."""
import contextlib
import io
import socket
import struct
import unittest

import followspot_core as core
from tools import psn_test_sender as diagnostic


class LoopbackTransportTests(unittest.TestCase):
    def setUp(self):
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addCleanup(self.listener.close)
            self.listener.bind(('127.0.0.1', 0))
            self.listener.settimeout(1)
        except PermissionError:
            self.skipTest('environment denies loopback UDP sockets')
        self.host, self.port = self.listener.getsockname()

    def receive(self):
        return self.listener.recvfrom(65535)[0]

    def test_osc_string_and_float_packets_arrive_with_prefix(self):
        sender = core.OscSender(self.host, self.port, prefix='show')
        self.addCleanup(sender.close)
        sender.send('/cmd', 'Go')
        sender.send('/x', 50.0)
        self.assertEqual(self.receive(), b'/show/cmd\0\0\0,s\0\0Go\0\0')
        self.assertEqual(self.receive(), b'/show/x\0,f\0\0BH\0\0')

    def test_streamer_info_and_data_reach_a_local_receiver(self):
        settings = core.Settings(position_output='psn', psn_tracker_id=300)
        stream = core.PsnStreamer(settings, (1.0, -2.0, 3.5), clock=lambda: 0, start=False)
        self.addCleanup(stream.close)
        # Substitute only the multicast destination; use the real configured socket.
        stream.destination = (self.host, self.port)
        stream.step()
        info, data = self.receive(), self.receive()
        self.assertEqual(info[:4], bytes.fromhex('56673480'))
        self.assertEqual(info[-10:], b'Followspot')
        self.assertEqual(data, bytes.fromhex(
            '5567288000000c00000000000000000002000001010014802c01108000000c000000803f000000c000006040'))

    def test_diagnostic_sender_emits_tracker_and_home_to_loopback(self):
        with contextlib.redirect_stdout(io.StringIO()):
            diagnostic.main(['--dest', self.host, '--port', str(self.port), '--seconds', '0.1', '--rate', '10',
                             '--pattern', 'static', '--home', '1', '-2', '3.5', '--tracker', '300'])
        info, data = self.receive(), self.receive()
        self.assertEqual(struct.unpack_from('<H', info)[0], 0x6756)
        self.assertEqual(struct.unpack_from('<H', data)[0], 0x6755)
        self.assertEqual(struct.unpack_from('<H', data, 24)[0], 300)
        self.assertEqual(struct.unpack_from('<3f', data, 32), (1.0, -2.0, 3.5))
