"""Committed management operations are never retried on response disconnect."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ui.server import _handler


class ResponseDisconnectTests(unittest.TestCase):
    def make_handler(self):
        management = Mock()
        management.dispatch.return_value = {'status': 'complete'}
        handler_type = _handler(SimpleNamespace(management=management))
        handler = handler_type.__new__(handler_type)
        handler.path = '/api/manage/fixture'
        handler.headers = {}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        handler.close_connection = False
        handler._body = Mock(return_value={'action': 'save'})
        return handler, management

    def test_disconnected_response_does_not_redispatch_or_send_error(self):
        for exception in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            for stage in ('headers', 'body'):
                with self.subTest(exception=exception, stage=stage):
                    handler, management = self.make_handler()
                    if stage == 'headers':
                        handler.end_headers.side_effect = exception()
                    else:
                        handler.wfile = Mock()
                        handler.wfile.write.side_effect = exception()
                    handler._manage('POST')
                    management.dispatch.assert_called_once_with(
                        'POST', handler.path, {'action': 'save'})
                    handler.send_response.assert_called_once_with(200)
                    self.assertTrue(handler.close_connection)

    def test_normal_response_keeps_content_and_headers(self):
        handler, _ = self.make_handler()
        handler._json(200, {'text': '中文'})
        self.assertEqual(handler.wfile.getvalue(), '{"text": "中文"}'.encode('utf8'))
        self.assertFalse(handler.close_connection)
        handler.send_header.assert_any_call('Content-Length', '18')

    def test_other_transport_errors_are_not_silenced(self):
        handler, _ = self.make_handler()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = OSError('unexpected transport failure')
        with self.assertRaisesRegex(OSError, 'unexpected transport failure'):
            handler._json(200, {})


if __name__ == '__main__':
    unittest.main()
