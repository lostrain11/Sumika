import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from extensions.models.cancellation import CancellationToken, RequestCancelled, model_response


class ModelCancellationTests(unittest.TestCase):
    def test_cancel_active_request_before_provider_responds(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                entered.set()
                release.wait(5)
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', '2')
                    self.end_headers()
                    self.wfile.write(b'{}')
                except OSError:
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        token = CancellationToken()
        def request():
            try:
                with token.activate():
                    req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/')
                    with model_response(req, timeout=5) as response:
                        response.read()
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=request)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            token.cancel()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(release.is_set())
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], RequestCancelled)
            self.assertEqual(len(token._callbacks), 0)
        finally:
            release.set()
            worker.join(5)
            server.shutdown(); server.server_close(); serving.join(2)

    def test_cancel_before_admission_and_idempotent_callback(self):
        token = CancellationToken()
        calls = []
        token.register(lambda: calls.append('stop'))
        token.cancel(); token.cancel()
        self.assertEqual(calls, ['stop'])
        with self.assertRaises(RequestCancelled):
            with token.activate():
                self.fail('cancelled request was admitted')
