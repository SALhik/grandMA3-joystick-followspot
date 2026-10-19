"""Diagnostic sender validates before any transport side effects."""
import contextlib
import io
import socket
import unittest
from unittest.mock import patch

from tools import psn_test_sender as sender


class DiagnosticSocket:
    def __init__(self, send_error=None, setup_error=None):
        self.sent = []
        self.options = []
        self.closed = False
        self.send_error = send_error
        self.setup_error = setup_error

    def settimeout(self, timeout):
        self.timeout = timeout

    def setsockopt(self, *option):
        if self.setup_error:
            raise self.setup_error
        self.options.append(option)

    def sendto(self, packet, destination):
        if self.send_error:
            raise self.send_error
        self.sent.append((packet, destination))

    def close(self):
        self.closed = True


class DiagnosticTests(unittest.TestCase):
    def run_sender(self, args, sock):
        with patch('sys.argv', ['psn_test_sender', '--seconds', '0.05', *args]), \
                patch.object(sender.socket, 'socket', return_value=sock), \
                patch.object(sender.time, 'monotonic', side_effect=[100.0, 100.0, 100.01, 100.1]), \
                patch.object(sender.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            sender.main()

    def test_invalid_arguments_are_rejected_before_socket_creation(self):
        cases = [('--rate', '0'), ('--rate', '-1'), ('--rate', 'nan'), ('--rate', 'inf'),
                 ('--rate', '1e-320'), ('--seconds', '0'), ('--seconds', '-1'),
                 ('--seconds', 'nan'), ('--seconds', 'inf'), ('--seconds', '1e20'),
                 ('--tracker', '0'), ('--tracker', '65536'), ('--port', '0'), ('--port', '65536'),
                 ('--home', 'nan', '0', '0'), ('--home', '0', 'inf', '0'),
                 ('--home', '0', '0', '1e40'), ('--radius', '-1'), ('--radius', 'nan'),
                 ('--radius', 'inf'), ('--radius', '1e40'),
                 ('--home', '3e38', '0', '0', '--radius', '1e38'),
                 ('--dest', 'bad-address'), ('--iface', 'bad-address')]
        for args in cases:
            with self.subTest(args=args), patch('sys.argv', ['psn_test_sender', *args]), \
                    patch.object(sender.socket, 'socket', side_effect=AssertionError('socket created')) as create, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    sender.main()
                self.assertEqual(caught.exception.code, 2)
                create.assert_not_called()

    def test_successful_send_closes_socket_and_handles_all_multicast_ranges(self):
        sock = DiagnosticSocket()
        self.run_sender(['--dest', '224.1.2.3', '--tracker', '300', '--pattern', 'static'], sock)
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.sent), 2)
        self.assertEqual([destination for _, destination in sock.sent], [('224.1.2.3', 56565)] * 2)
        self.assertIn((socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('127.0.0.1')), sock.options)

    def test_socket_is_closed_on_send_failure_or_interrupt(self):
        for error in (OSError('send failed'), KeyboardInterrupt()):
            sock = DiagnosticSocket(send_error=error)
            with self.subTest(error=error), self.assertRaises(type(error)):
                self.run_sender([], sock)
            self.assertTrue(sock.closed)

    def test_socket_is_closed_on_setup_failure(self):
        sock = DiagnosticSocket(setup_error=OSError('setup failed'))
        with self.assertRaisesRegex(OSError, 'setup failed'):
            self.run_sender([], sock)
        self.assertTrue(sock.closed)
