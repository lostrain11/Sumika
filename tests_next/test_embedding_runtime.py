import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from extensions.memory.embedding_runtime import embed_batch


class EmbeddingRuntimeTests(unittest.TestCase):
    @patch('extensions.memory.embedding_runtime.subprocess.run')
    def test_offline_batch_has_no_shell_or_model_fallback(self, run):
        run.return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'vectors':[[1,0]],'query':[0,1]}))
        self.assertEqual(embed_batch('python','cache',['事实'],'查询'),([[1,0]],[0,1]))
        args=run.call_args.kwargs
        self.assertEqual(args['env']['HF_HUB_OFFLINE'],'1')
        self.assertFalse(args.get('shell',False))
        self.assertEqual(json.loads(args['input'])['texts'],['事实'])

    @patch('extensions.memory.embedding_runtime.subprocess.run')
    def test_invalid_output_and_timeout_do_not_retry(self, run):
        for value in ({'vectors':[],'query':[1]}, {'vectors':[[1,2]],'query':[1]},
                      {'vectors':[[0]],'query':[1]}, {'vectors':[[float('nan')]],'query':[1]}):
            run.return_value=SimpleNamespace(returncode=0,stdout=json.dumps(value))
            with self.assertRaises(RuntimeError):embed_batch('python','cache',['fact'],'query')
        run.reset_mock();run.side_effect=subprocess.TimeoutExpired('fixture',60)
        with self.assertRaises(RuntimeError):embed_batch('python','cache',[],'query')
        self.assertEqual(run.call_count,1)
