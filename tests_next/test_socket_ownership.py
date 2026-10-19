import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sumika_next.dsh import Dsh, DshError
from sumika_next.socket_ownership import listener_pids


class SocketOwnershipTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows native TCP tables')
    def test_live_ipv4_listener_and_closed_port(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0));server.listen()
            port=server.getsockname()[1]
            self.assertEqual(listener_pids(port), {os.getpid()})
        self.assertEqual(listener_pids(port), set())

    @unittest.skipUnless(os.name == 'nt' and socket.has_ipv6, 'Windows IPv6')
    def test_live_ipv6_listener(self):
        with socket.socket(socket.AF_INET6) as server:
            try:server.bind(('::1', 0))
            except OSError as error:self.skipTest(str(error))
            server.listen()
            self.assertEqual(listener_pids(server.getsockname()[1]), {os.getpid()})

    def test_managed_check_rejects_foreign_ambiguous_missing_and_query_failure(self):
        with tempfile.TemporaryDirectory() as d:
            adapter=Dsh(Path(d),Path(d)/'home')
            adapter.process=MagicMock(pid=123)
            adapter.process.poll.return_value=None
            with patch('sumika_next.dsh.listener_pids',return_value={123}) as query:
                adapter._check_owner(12345);query.assert_called_once_with(12345)
            for owners in ({999},{123,999},set()):
                with patch('sumika_next.dsh.listener_pids',return_value=owners):
                    with self.assertRaises(DshError):adapter._check_owner(12345)
            with patch('sumika_next.dsh.listener_pids',side_effect=OSError('unavailable')):
                with self.assertRaises(DshError):adapter._check_owner(12345)
