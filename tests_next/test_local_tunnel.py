import http.server
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from extensions.models.settings import example, save, validate
from ui.local_tunnel import LocalTunnel, TunnelError, tunnel_config


class TunnelSettingsTests(unittest.TestCase):
    def settings(self):
        return validate(example('role', 'db'))

    def test_tunnel_is_opt_in_and_requires_loopback_endpoint(self):
        settings = self.settings()
        self.assertFalse(settings['auxiliary']['tunnel']['enabled'])
        settings['auxiliary'].update(enabled=True, provider='ollama',
                                     endpoint='http://127.0.0.1:18114')
        settings['auxiliary']['tunnel'].update(enabled=True, host='192.168.31.227',
                                               user='lostrain')
        validate(settings)
        settings['auxiliary']['endpoint'] = 'http://192.168.31.227:11434'
        with self.assertRaisesRegex(ValueError, 'loopback'):
            validate(settings)

    def test_tunnel_rejects_command_like_host_and_cloud_provider(self):
        settings = self.settings()
        settings['auxiliary'].update(enabled=True, provider='ollama',
                                     endpoint='http://127.0.0.1:18114')
        settings['auxiliary']['tunnel'].update(enabled=True, host='-oProxyCommand=x',
                                               user='lostrain')
        with self.assertRaises(ValueError):
            validate(settings)
        settings['auxiliary']['tunnel']['host'] = '192.168.31.227'
        settings['auxiliary']['provider'] = 'openai-compatible'
        settings['auxiliary']['endpoint'] = 'https://api.example.com'
        with self.assertRaisesRegex(ValueError, 'loopback auxiliary provider'):
            validate(settings)


class LocalTunnelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'settings.json'
        settings = validate(example('role', 'db'))
        self.settings = settings

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_tunnel_does_not_spawn_or_report_running(self):
        save(self.settings, self.path)
        tunnel = LocalTunnel(self.path, ssh_executable=sys.executable)
        status = tunnel.autostart()
        self.assertFalse(status['enabled'])
        self.assertFalse(status['running'])
        self.assertFalse(status['healthy'])
        tunnel.close()

    def test_start_requires_enabled_and_available_ssh(self):
        self.settings['auxiliary'].update(enabled=True, provider='ollama',
                                          endpoint='http://127.0.0.1:18114')
        self.settings['auxiliary']['tunnel'].update(
            enabled=True, host='192.168.31.227', user='lostrain')
        save(self.settings, self.path)
        tunnel = LocalTunnel(self.path, ssh_executable='')
        try:
            with self.assertRaisesRegex(TunnelError, 'OpenSSH'):
                tunnel.start()
        finally:
            tunnel.close()

    def test_local_port_conflict_is_reported_without_killing_owner(self):
        with socket.socket() as owner:
            owner.bind(('127.0.0.1', 0))
            owner.listen()
            port = owner.getsockname()[1]
            self.settings['auxiliary'].update(
                enabled=True, provider='ollama',
                endpoint=f'http://127.0.0.1:{port}')
            self.settings['auxiliary']['tunnel'].update(
                enabled=True, host='192.168.31.227', user='lostrain')
            save(self.settings, self.path)
            tunnel = LocalTunnel(self.path, ssh_executable=sys.executable)
            with self.assertRaisesRegex(TunnelError, 'already in use'):
                tunnel.start()
            self.assertFalse(tunnel.status()['running'])
        tunnel.close()

    def test_optional_preload_posts_keep_alive_and_reports_ready(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                seen.append((self.path, json.loads(self.rfile.read(length))))
                body = b'{}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.settings['auxiliary'].update(
                enabled=True, provider='ollama',
                endpoint=f'http://127.0.0.1:{server.server_port}',
                model='qwen2.5:7b-instruct-q4_K_M')
            self.settings['auxiliary']['tunnel'].update(enabled=True, preload=True)
            tunnel = LocalTunnel(self.path, ssh_executable='')
            tunnel._config = tunnel_config(self.settings)
            tunnel._maybe_preload()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and tunnel.status()['preload'] != 'ready':
                time.sleep(.02)
            self.assertEqual(tunnel.status()['preload'], 'ready')
            self.assertEqual(seen[0][0], '/api/generate')
            self.assertEqual(seen[0][1]['model'], 'qwen2.5:7b-instruct-q4_K_M')
            self.assertEqual(seen[0][1]['keep_alive'], '30m')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_config_derives_health_path_and_local_port_from_endpoint(self):
        self.settings['auxiliary'].update(provider='ollama',
                                          endpoint='http://127.0.0.1:18114')
        config = tunnel_config(self.settings)
        self.assertEqual(config['local_port'], 18114)
        self.assertEqual(config['health_url'], 'http://127.0.0.1:18114/api/tags')
        self.settings['auxiliary'].update(provider='openai-compatible-local',
                                          endpoint='http://127.0.0.1:18084')
        config = tunnel_config(self.settings)
        self.assertEqual(config['health_url'], 'http://127.0.0.1:18084/v1/models')


if __name__ == '__main__':
    unittest.main()
