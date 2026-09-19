import copy
import json
import unittest

from tools.verify_self_development_live import verified_test_result


class DevelopmentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.command = 'python -B -m unittest test_paths'
        self.call = {'turn': 2, 'step': 1, 'callId': 'one', 'name': 'pwsh',
                     'arguments': json.dumps({'command': self.command})}
        self.block = {'type': 'tool-result', 'toolCallId': 'one', 'isError': False,
                      'content': [{'type': 'text', 'text':
                                   '[stderr]\n....\r\nRan 4 tests in 0.578s\r\n\r\nOK\r\n'}]}
        self.result = {'turn': 2, 'step': 1, 'message': {
            'source': {'kind': 'tool', 'callId': 'one'}, 'content': [self.block]}}
        self.events = [{'event': {'type': 'tool/call', 'data': self.call}},
                       {'event': {'type': 'tool/result', 'data': self.result}}]

    def check(self):
        return verified_test_result(self.events, self.command, 4)

    def test_native_success(self):
        self.assertTrue(self.check())

    def test_wrong_call_or_execution(self):
        for key in ('turn', 'step'):
            with self.subTest(key=key):
                old = self.result[key]
                self.result[key] = 999
                self.assertFalse(self.check())
                self.result[key] = old
        self.block['toolCallId'] = 'other'
        self.assertFalse(self.check())
        self.block['toolCallId'] = 'one'
        self.result['message']['source']['callId'] = 'other'
        self.assertFalse(self.check())

    def test_error_and_truncation(self):
        self.block['isError'] = True
        self.assertFalse(self.check())
        self.block['isError'] = False
        self.result['meta'] = {'truncated': True}
        self.assertFalse(self.check())

    def test_duplicates_and_missing_results(self):
        self.events.append(copy.deepcopy(self.events[-1]))
        self.assertFalse(self.check())
        self.events = self.events[:1]
        self.assertFalse(self.check())

    def test_wrong_or_ambiguous_output(self):
        for output in ('Ran 14 tests in 0.1s\n\nOK\n',
                       'example Ran 4 tests\nOK\n',
                       'Ran 4 tests in 0.1s\nFAILED (errors=1)\nOK\n',
                       'Ran 4 tests in 0.1s\nOK\n[exit code: 1]',
                       'Ran 4 tests in 0.1s\nOK\nRan 4 tests in 0.1s\nOK\n'):
            with self.subTest(output=output):
                self.block['content'][0]['text'] = output
                self.assertFalse(self.check())

    def test_wrong_command_and_malformed_arguments(self):
        for arguments in ('bad json', 'null', '{}', json.dumps({'command': 'different'})):
            self.call['arguments'] = arguments
            self.assertFalse(self.check())


if __name__ == '__main__':
    unittest.main()
