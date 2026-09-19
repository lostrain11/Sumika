import hashlib
import json
from pathlib import Path
import shutil
from contextlib import contextmanager
import uuid
import unittest
from unittest.mock import patch

from tools.audit_package_licenses import audit, finding_total, match_supplemental_notices, sharp_component_coverage


@contextmanager
def retained_fixture():
    """Owned unique workspace fixture; preserve evidence, never remove paths."""
    root = Path(__file__).resolve().parents[1]/'.sumika-next'/'notice-tests'/uuid.uuid4().hex
    root.mkdir(parents=True)
    yield root


class EmbeddedNoticeReviewTests(unittest.TestCase):
    """Retain unique workspace fixtures; no private temp ACL or cleanup commands."""

    def fixture(self):
        import uuid
        from tools.audit_package_licenses import MIT_TERMS, EMBEDDED_REVIEW_KIND
        root = Path(__file__).resolve().parents[1]/'.sumika-next'/'notice-tests'/uuid.uuid4().hex
        package = root/'runtime/dsh/node_modules/example'
        package.mkdir(parents=True)
        (package/'package.json').write_text(json.dumps(dict(name='example', version='1', license='MIT')), encoding='utf8')
        excerpt = 'Copyright (c) 2026 Example Author\n\n' + MIT_TERMS + '\n'
        (package/'README.md').write_text('# Package\n\n' + excerpt, encoding='utf8')
        notices = root/'licenses'; notices.mkdir()
        (notices/'excerpt.txt').write_text(excerpt, encoding='utf8')
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        source = dict(file='excerpt.txt', sha256=digest(notices/'excerpt.txt'),
                      review_kind=EMBEDDED_REVIEW_KIND,
                      dependency=dict(ecosystem='npm', name='example', version='1',
                                      manifest_sha256=digest(package/'package.json')),
                      source_artifact=(package/'README.md').relative_to(root).as_posix(),
                      source_sha256=digest(package/'README.md'))
        return root, package, source

    def run_fixture(self, root, source):
        (root/'licenses/sources.json').write_text(json.dumps({'sources': [source]}), encoding='utf8')
        with patch('tools.audit_package_licenses.verify', return_value={'status': 'fixture'}):
            return audit(root)['dependencies'][0]

    def test_complete_exact_review(self):
        root, package, source = self.fixture()
        row = self.run_fixture(root, source)
        self.assertEqual(row['findings'], [])
        self.assertEqual(row['embedded_notice_candidates'][0]['status'], 'verified_reviewed_excerpt')

    def test_identity_mismatch_stays_flagged(self):
        for key in ('ecosystem', 'name', 'version', 'manifest_sha256'):
            with self.subTest(key=key):
                root, package, source = self.fixture()
                source['dependency'][key] = 'changed'
                self.assertIn('embedded_license_text_requires_review', self.run_fixture(root, source)['findings'])

    def test_missing_or_mismatched_review_stays_flagged(self):
        for key, value in [('review_kind', None), ('review_kind', 'unknown'),
                           ('source_artifact', 'runtime/dsh/node_modules/other/README.md'),
                           ('source_sha256', 'changed'), ('unresolved', ['pending'])]:
            with self.subTest(key=key, value=value):
                root, package, source = self.fixture(); source[key] = value
                self.assertIn('embedded_license_text_requires_review', self.run_fixture(root, source)['findings'])

    def test_changed_readme_stays_flagged(self):
        root, package, source = self.fixture()
        with (package/'README.md').open('a', encoding='utf8') as out: out.write('\nchanged')
        self.assertIn('embedded_license_text_requires_review', self.run_fixture(root, source)['findings'])

    def test_incomplete_or_reworded_excerpt_stays_flagged(self):
        for change in ('empty', 'partial', 'modified', 'invalid_utf8', 'unrelated'):
            with self.subTest(change=change):
                root, package, source = self.fixture(); p=root/'licenses/excerpt.txt'; raw=p.read_bytes()
                raw = {'empty': b'', 'partial': raw[:600],
                       'modified': raw.replace(b'free of charge', b'for a fee'),
                       'invalid_utf8': raw+b'\xff', 'unrelated': b'Generic license text'}[change]
                p.write_bytes(raw); source['sha256']=hashlib.sha256(raw).hexdigest()
                self.assertIn('embedded_license_text_requires_review', self.run_fixture(root, source)['findings'])

    def test_tampered_supplement_fails_closed(self):
        root, package, source = self.fixture()
        (root/'licenses/excerpt.txt').write_bytes(b'tampered')
        with self.assertRaises(ValueError): self.run_fixture(root, source)

    def test_review_does_not_clear_other_findings(self):
        root, package, source = self.fixture()
        manifest=package/'package.json'
        manifest.write_text(json.dumps(dict(name='example', version='1', license='MPL-2.0')), encoding='utf8')
        source['dependency']['manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        (package/'versions.json').write_text('{"native":"1"}', encoding='utf8')
        row=self.run_fixture(root, source)
        self.assertNotIn('embedded_license_text_requires_review', row['findings'])
        self.assertIn('native_component_licenses_require_review', row['findings'])
        self.assertIn('terms_require_specific_review', row['findings'])

    def test_five_existing_reviewed_notices_are_complete(self):
        from tools.audit_package_licenses import complete_mit_excerpt, EMBEDDED_REVIEW_KIND
        folder=Path(__file__).resolve().parents[1]/'packaging/notices'
        entries=json.loads((folder/'sources.json').read_text(encoding='utf8'))['sources']
        reviews=[e for e in entries if e.get('review_kind')==EMBEDDED_REVIEW_KIND]
        self.assertEqual(len(reviews), 5)
        for entry in reviews:
            self.assertTrue(complete_mit_excerpt((folder/entry['file']).read_text(encoding='utf8')))


class SupplementalNoticesTests(unittest.TestCase):
    def test_native_components_checked_in_both_directions(self):
        text='| Library | Used under the terms of |\n|---|---|\n|libvips|LGPLv3|\n|libnsgif|MIT|\n'
        result=sharp_component_coverage(text,{'vips':'8','new-library':'1'})
        self.assertEqual(result['declared_without_version'],['libnsgif'])
        self.assertEqual(result['version_without_declaration'],['new-library'])
        self.assertEqual(result['components'][0]['version'],'8')
        self.assertIsNone(result['components'][1]['version'])

    def test_missing_native_table_never_means_complete(self):
        result=sharp_component_coverage('No table',{'vips':'8'})
        self.assertFalse(result['table_found'])
        self.assertEqual(result['version_without_declaration'],['vips'])

    def test_duplicate_native_alias_refused(self):
        with self.assertRaises(ValueError):
            sharp_component_coverage('| Library | Terms |\n|libvips|MIT|\n|vips|LGPLv3|',{'vips':'8'})

    def test_declared_terms_do_not_clear_pending_notice_obligations(self):
        with retained_fixture() as temp:
            root=Path(temp)
            package=root/'runtime/dsh/node_modules/example'
            package.mkdir(parents=True)
            manifest=package/'package.json'
            manifest.write_text(json.dumps(dict(name='example',version='1',license='Apache-2.0')),encoding='utf8')
            notices=root/'licenses';notices.mkdir()
            notice=notices/'LICENSE';notice.write_bytes(b'fixture terms')
            source=dict(file='LICENSE',sha256=hashlib.sha256(notice.read_bytes()).hexdigest(),
                        dependency=dict(ecosystem='npm',name='example',version='1',
                                        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()),
                        license_scope='declared_license_text_only',
                        unresolved=['version_specific_copyright_and_notice_not_verified'])
            (notices/'sources.json').write_text(json.dumps({'sources':[source]}),encoding='utf8')
            with patch('tools.audit_package_licenses.verify',return_value={'status':'fixture'}):
                report=audit(root)
            self.assertEqual(finding_total(report),1)
            row=report['dependencies'][0]
            self.assertNotIn('no_package_license_file_found',row['findings'])
            self.assertIn('supplemental_notice_obligations_unresolved',row['findings'])
            self.assertEqual(row['supplemental_notices'][0]['unresolved'],source['unresolved'])

    def test_reviewed_assets_match_exact_manifest_only(self):
        sources=Path(__file__).resolve().parents[1]/'packaging/notices'
        entries=json.loads((sources/'sources.json').read_text(encoding='utf8'))['sources']
        bound=[item for item in entries if item.get('dependency')]
        self.assertEqual({entry['dependency']['name'] for entry in bound}, {
            '@earendil-works/pi-ai', '@earendil-works/pi-telemetry', '@xterm/headless',
            'standardwebhooks', '@koromix/koffi-win32-x64',
            'data-uri-to-buffer', 'debug', 'jwa', 'jws',
            '@aws-sdk/credential-provider-http', '@aws-sdk/credential-provider-login', '@aws-sdk/nested-clients'})
        with retained_fixture() as temp:
            root=Path(temp)
            shutil.copytree(sources,root/'licenses')
            for entry in bound:
                row=dict(entry['dependency'])
                matches=match_supplemental_notices(root,row,entries)
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]['unresolved'],entry.get('unresolved',[]))
                for field in ('version','manifest_sha256','name'):
                    self.assertEqual(match_supplemental_notices(root,{**row,field:'changed'},entries),[])

    def test_tampered_notice_or_escape_rejected(self):
        with retained_fixture() as temp:
            root=Path(temp);(root/'licenses').mkdir()
            (root/'licenses/LICENSE').write_bytes(b'changed')
            row=dict(ecosystem='npm',name='example',version='1',manifest_sha256='hash')
            entry=dict(dependency=row,file='LICENSE',sha256=hashlib.sha256(b'original').hexdigest())
            with self.assertRaises(ValueError):match_supplemental_notices(root,row,[entry])
            entry['file']='../LICENSE'
            with self.assertRaises(ValueError):match_supplemental_notices(root,row,[entry])
