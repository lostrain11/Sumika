import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

from extensions.desktop.reference_analysis import ConfiguredReferenceAnalyzer
from extensions.models.settings import example, save


class ReferenceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.settings=self.root/'settings.json'
        self.config=example(self.root/'role',self.root/'usage.sqlite3')
        self.config['auxiliary']['enabled']=True
        save(self.config,self.settings)

    def tearDown(self):
        self.directory.cleanup()

    def test_configured_analysis_records_reported_usage(self):
        report={'classification':'needs-validation','summary':'需要核对语音源码','modules':['voice']}
        with patch('extensions.desktop.reference_analysis.analyze_reference',return_value={
                'status':'reported','text':json.dumps(report),'usage':{'prompt_tokens':10,'completion_tokens':3}}) as generate:
            self.assertEqual(ConfiguredReferenceAnalyzer(self.settings)({'id':'demo'}),report)
        self.assertEqual(generate.call_args.args[0]['auxiliary']['model'],self.config['auxiliary']['model'])
        with closing(sqlite3.connect(self.root/'usage.sqlite3')) as db:
            row=db.execute('SELECT session,status,total_tokens FROM usage').fetchone()
        self.assertEqual(row,('reference-research','reported',13))

    def test_disabled_provider_and_revocation_do_not_call(self):
        analyzer=ConfiguredReferenceAnalyzer(self.settings)
        self.config['auxiliary']['enabled']=False
        save(self.config,self.settings)
        with patch('extensions.desktop.reference_analysis.analyze_reference') as generate:
            with self.assertRaises(ValueError): analyzer({'id':'demo'})
            with self.assertRaises(ValueError): ConfiguredReferenceAnalyzer(self.settings)
        generate.assert_not_called()

    def test_unknown_usage_stays_null_and_truncated_answer_rejected(self):
        with patch('extensions.desktop.reference_analysis.analyze_reference',return_value={
                'status':'reported','text':'{}','finish_reason':'length','usage':{}}):
            with self.assertRaises(ValueError): ConfiguredReferenceAnalyzer(self.settings)({'id':'demo'})
        with closing(sqlite3.connect(self.root/'usage.sqlite3')) as db:
            row=db.execute('SELECT status,prompt_tokens,total_tokens FROM usage').fetchone()
        self.assertEqual(row,('unknown',None,None))
