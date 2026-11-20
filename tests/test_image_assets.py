import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_image_assets import AssetAuditor, SafeFetcher, intersection_score, make_report, summarize_page_types, wix_original
from compare_content import Comparator
from content_metric import validate_report

SOURCE = 'https://old.example/post'
TARGET = 'https://new.example/post'
CMS = 'https://cms.example'
ORIGINAL = 'https://static.wixstatic.com/media/123_abc~mv2.png'
SMALL = ORIGINAL + '/v1/fill/w_49,h_33,blur_2/sample.avif'
LARGE = CMS + '/api/media/file/image-1200x800.jpg'
COPIED = CMS + '/api/media/file/image.png'


def html(images):
    return ('<body><main><p>Hello world</p>' + ''.join('<img src="' + s + '">' for s in images) + '</main></body>').encode()


class ImageAssetTests(unittest.TestCase):
    def test_source_page_groups_include_root_and_localized_failures(self):
        inputs = [('https://old.test', 1, 'ok'), ('https://old.test/ko/', 0, 'error'),
                  ('https://old.test/es/post/uno', 0.5, 'ok'), ('https://old.test/blog', 0, 'error'),
                  ('https://old.test/profile/a/profile', 0, 'error')]
        groups = summarize_page_types([{'source_url': url, 'status': status, 'diagnostic_text_asset_score': score}
                                      for url, score, status in inputs])
        self.assertEqual(groups, {'home': {'urls': 2, 'errors': 1, 'score_sum': 1},
                                  'articles': {'urls': 1, 'errors': 0, 'score_sum': 0.5},
                                  'other': {'urls': 2, 'errors': 2, 'score_sum': 0}})

    def fixture(self, source_images=None, target_images=None, original_bytes=b'original', copied_bytes=b'original',
                display_bytes=b'large-jpeg', docs=None):
        source_images = [SMALL] if source_images is None else source_images
        target_images = [LARGE] if target_images is None else target_images
        if docs is None:
            docs = [{'url': COPIED, 'legacy': {'wixUrl': ORIGINAL}, 'sizes': {'content': {'url': LARGE}}}]
        query = CMS + '/api/media?' + urlencode({'depth': '0', 'limit': '100', 'where[legacy.wixUrl][equals]': ORIGINAL})
        values = {
            SOURCE: (html(source_images), 'text/html', SOURCE),
            TARGET: (html(target_images), 'text/html', TARGET),
            SMALL: (b'small-avif', 'image/avif', SMALL),
            ORIGINAL: (original_bytes, 'image/png', ORIGINAL),
            COPIED: (copied_bytes, 'image/png', COPIED),
            LARGE: (display_bytes, 'image/jpeg', LARGE),
            query: (json.dumps({'docs': docs, 'hasNextPage': False}).encode(), 'application/json', query),
        }
        calls = []

        def fetch(url):
            calls.append(url)
            response = values[url]
            if isinstance(response, Exception):
                raise response
            return response

        return AssetAuditor(CMS, fetch), values, calls, fetch, query

    def test_resize_encoding_differences_require_equal_fetched_originals(self):
        auditor, _, calls, fetch, _ = self.fixture()
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['legacy_byte_image_score'], 0)
        self.assertEqual(result['verified_original_asset_score'], 1)
        self.assertEqual(result['diagnostic_text_asset_score'], 1)
        self.assertEqual(result['legacy_combined_score'], Comparator(fetch).compare(SOURCE, TARGET)['score'])
        self.assertIn(ORIGINAL, calls)
        self.assertIn(COPIED, calls)
        self.assertIn(LARGE, calls)

    def test_same_legacy_id_different_original_bytes_does_not_match(self):
        auditor, *_ = self.fixture(copied_bytes=b'WRONG IMAGE')
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['verified_original_asset_score'], 0)
        self.assertEqual(result['verified_original_pairs'], [])

    def test_broken_target_derivative_cannot_be_rescued_by_original(self):
        auditor, values, *_ = self.fixture()
        values[LARGE] = OSError('do-not-persist-this-private-error')
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['verified_original_asset_score'], 0)
        self.assertNotIn('private-error', json.dumps(result))

    def test_broken_source_placeholder_cannot_be_rescued_by_original(self):
        auditor, values, *_ = self.fixture()
        values[SMALL] = OSError('missing')
        self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 0)

    def test_empty_original_and_non_image_mime_fail(self):
        for body, mime in [(b'', 'image/png'), (b'<html>denied</html>', 'text/html')]:
            with self.subTest(mime=mime):
                auditor, values, *_ = self.fixture()
                values[COPIED] = (body, mime, COPIED)
                self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 0)

    def test_missing_placeholder_kept_in_denominator(self):
        auditor, *_ = self.fixture(source_images=[SMALL, ''])
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['source_image_slots'], 2)
        self.assertEqual(result['source_unresolved_slots'], 1)
        self.assertAlmostEqual(result['verified_original_asset_score'], 2/3)

    def test_duplicate_occurrences_are_not_deduplicated(self):
        auditor, *_ = self.fixture(target_images=[LARGE, LARGE])
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['target_image_slots'], 2)
        self.assertAlmostEqual(result['verified_original_asset_score'], 2/3)

    def test_unrelated_cms_record_does_not_match_by_filename(self):
        docs = [{'url': COPIED, 'legacy': {'wixUrl': ORIGINAL + 'other'}, 'sizes': {'content': {'url': LARGE}}}]
        auditor, *_ = self.fixture(docs=docs)
        self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 0)

    def test_cms_original_not_referenced_by_target_does_not_count(self):
        other = CMS + '/api/media/file/unrelated.jpg'
        auditor, values, *_ = self.fixture(target_images=[other])
        values[other] = (b'other', 'image/jpeg', other)
        self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 0)

    def test_metadata_failure_is_not_full_credit(self):
        auditor, values, _, _, query = self.fixture()
        values[query] = OSError('unavailable')
        result = auditor.audit(SOURCE, TARGET)
        self.assertEqual(result['verified_original_asset_score'], 0)
        self.assertIn('cms_lookup_failed', result['media_errors'])

    def test_metadata_pagination_fails_closed(self):
        auditor, values, _, _, query = self.fixture()
        values[query] = (b'{"docs":[],"hasNextPage":true}', 'application/json', query)
        self.assertIn('cms_lookup_failed', auditor.audit(SOURCE, TARGET)['media_errors'])

    def test_text_only_and_exact_bytes_keep_existing_behavior(self):
        auditor, *_ = self.fixture(source_images=[], target_images=[])
        self.assertEqual(auditor.audit(SOURCE, TARGET)['diagnostic_text_asset_score'], 1)
        old_image, new_image = 'https://old.example/a.png', 'https://new.example/a.png'
        auditor, values, *_ = self.fixture(source_images=[old_image], target_images=[new_image], docs=[])
        values[old_image] = (b'exact', 'image/png', old_image)
        values[new_image] = (b'exact', 'image/png', new_image)
        self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 1)

    def test_hotlinked_wix_image_is_not_a_migrated_asset(self):
        auditor, *_ = self.fixture(target_images=[SMALL])
        row = auditor.audit(SOURCE, TARGET)
        self.assertEqual(row['legacy_byte_image_score'], 1)
        self.assertEqual(row['verified_original_asset_score'], 0)

    def test_copied_loading_bytes_without_original_proof_is_not_full_credit(self):
        auditor, *_ = self.fixture(display_bytes=b'small-avif', docs=[])
        row = auditor.audit(SOURCE, TARGET)
        self.assertEqual(row['legacy_byte_image_score'], 1)
        self.assertEqual(row['verified_original_asset_score'], 0)

    def test_page_error_remains_zero_in_diagnostic_denominator(self):
        auditor, values, *_ = self.fixture()
        good = auditor.audit(SOURCE, TARGET)
        bad_source, bad_target = SOURCE + '-404', TARGET + '-404'
        values[bad_source] = values[SOURCE]
        values[bad_target] = OSError('secret details')
        bad = auditor.audit(bad_source, bad_target)
        report = make_report([good, bad])
        self.assertEqual(report['total_urls'], 2)
        self.assertEqual(report['diagnostic_text_asset_percentage'], 50)
        self.assertEqual(report['status'], 'diagnostic_only')
        self.assertFalse(report['accepted_dashboard_metric'])
        self.assertNotIn('secret details', json.dumps(report))
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_url_validation_blocks_host_spoofing_credentials_and_traversal(self):
        for url in ['https://static.wixstatic.com.evil/media/image.png',
                    'https://u:p@static.wixstatic.com/media/image.png',
                    'http://static.wixstatic.com/media/image.png',
                    'https://static.wixstatic.com/media/a%2fb.png',
                    'https://static.wixstatic.com/media/a.png/not-a-transform',
                    'https://static.wixstatic.com/media/..']:
            with self.subTest(url=url):
                self.assertIsNone(wix_original(url))
        self.assertEqual(wix_original(SMALL), ORIGINAL)

    def test_cms_file_must_stay_on_named_cms(self):
        auditor, *_ = self.fixture()
        self.assertEqual(auditor.cms_file('/api/media/file/a.png'), CMS + '/api/media/file/a.png')
        self.assertEqual(auditor.cms_file('/api/media/file/a.png?prefix=media'), CMS + '/api/media/file/a.png?prefix=media')
        for url in ['https://evil.example/api/media/file/a.png', '//evil.example/a',
                    '/api/users', '/api/media/file/a.png?token=private', '\\evil.example\\file',
                    '/api/media/file/a.png?prefix=private', '/api/media/file/a.png?prefix=media&token=x',
                    '/api/media/file/../../users', '/api/media/file/a%2fb.png']:
            self.assertIsNone(auditor.cms_file(url))

    def test_real_cms_prefix_query_retains_original_verification(self):
        copied, large = COPIED + '?prefix=media', LARGE + '?prefix=media'
        docs = [{'url': copied, 'legacy': {'wixUrl': ORIGINAL}, 'sizes': {'content': {'url': large}}}]
        auditor, values, *_ = self.fixture(target_images=[large], docs=docs)
        values[copied] = (b'original', 'image/png', copied)
        values[large] = (b'large-jpeg', 'image/jpeg', large)
        self.assertEqual(auditor.audit(SOURCE, TARGET)['verified_original_asset_score'], 1)

    def test_fetcher_and_redirect_handler_reject_outside_origins(self):
        fetch = SafeFetcher({CMS})
        for url in ['http://cms.example/file', 'https://cms.example.evil/file', 'https://user:pass@cms.example/file']:
            with self.assertRaises(ValueError):
                fetch.check(url)
        response = SimpleNamespace(returncode=0, stdout=b'HTTP/2 302\r\nLocation: https://evil.example/private\r\n\r\n', stderr=b'')
        with patch('audit_image_assets.subprocess.run', return_value=response) as run:
            with self.assertRaises(ValueError):
                fetch(CMS + '/file')
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('--location', run.call_args.args[0])

    def test_bounded_transport_accepts_image_and_rejects_error(self):
        fetch = SafeFetcher({CMS})
        response = SimpleNamespace(returncode=0, stdout=b'HTTP/2 200\r\nContent-Type: image/png\r\n\r\npixels', stderr=b'')
        with patch('audit_image_assets.subprocess.run', return_value=response) as run:
            self.assertEqual(fetch(COPIED), (b'pixels', 'image/png', COPIED))
            self.assertIn('--max-time', run.call_args.args[0])
            self.assertIn('--max-filesize', run.call_args.args[0])
            self.assertLessEqual(run.call_args.kwargs['timeout'], 32)
        response.returncode = 28
        with patch('audit_image_assets.subprocess.run', return_value=response):
            with self.assertRaises(ValueError):
                fetch(COPIED)

    def test_multiplicity_and_missing_values_cannot_score_one(self):
        self.assertAlmostEqual(intersection_score(['a', None], ['a']), 2/3)
        self.assertEqual(intersection_score([None], [None]), 0)
        self.assertEqual(intersection_score(['a'], ['b']), 0)

    def test_report_rejects_duplicate_or_empty_inventory(self):
        auditor, *_ = self.fixture()
        row = auditor.audit(SOURCE, TARGET)
        for rows in [[], [row, row]]:
            with self.assertRaises(ValueError):
                make_report(rows)


if __name__ == '__main__':
    unittest.main()
