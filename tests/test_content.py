import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compare_content import Comparator, compare_inventory, main, parse_page, preflight_target, sitemap_urls, target_url, write_report


OLD = 'https://old.example'
NEW = 'https://new.vercel.app'


def page(text, image=''):
    return f'<html><body><header>Ignore this chrome</header><main>{text}{image}</main></body></html>'.encode()


class FixtureFetcher:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return value
        return value, 'text/html', url


class ContentTests(unittest.TestCase):
    def compare(self, old, new, extra=None):
        fetch = FixtureFetcher({OLD + '/post': old, NEW + '/post': new, **(extra or {})})
        return Comparator(fetch).compare(OLD + '/post', NEW + '/post')

    def test_exact_text_and_different_image_urls_with_same_bytes(self):
        result = self.compare(page('Hello world', '<img src="/old.jpg">'),
                              page('Hello world', '<img src="/new.jpg">'),
                              {OLD + '/old.jpg': (b'image-bytes', 'image/jpeg', OLD + '/old.jpg'),
                               NEW + '/new.jpg': (b'image-bytes', 'image/jpeg', NEW + '/new.jpg')})
        self.assertEqual(result['score'], 1)
        self.assertEqual(result['status'], 'ok')

    def test_partial_text_and_reordered_text_are_below_one(self):
        for text in ['Hello changed world', 'world Hello']:
            result = self.compare(page('Hello world'), page(text))
            self.assertGreater(result['score'], 0)
            self.assertLess(result['score'], 1)

    def test_missing_and_broken_images_penalize_even_equal_urls(self):
        image = '<img src="https://cdn.example/image.png">'
        broken = {'https://cdn.example/image.png': OSError('unavailable')}
        result = self.compare(page('Hello', image), page('Hello', image), broken)
        self.assertEqual(result['score'], 0.5)
        self.assertEqual(result['image_score'], 0)
        result = self.compare(page('Hello', image), page('Hello'), broken)
        self.assertEqual(result['score'], 0.5)

    def test_extra_image_and_duplicate_image_count_are_penalized(self):
        values = {OLD + '/img': (b'a', 'image/png', OLD + '/img'),
                  NEW + '/img': (b'a', 'image/png', NEW + '/img')}
        result = self.compare(page('Hello', '<img src="/img">'),
                              page('Hello', '<img src="/img"><img src="/img">'), values)
        self.assertAlmostEqual(result['image_score'], 2 / 3)
        self.assertLess(result['score'], 1)

    def test_404_scores_zero_without_requesting_source(self):
        error = HTTPError(NEW + '/post', 404, 'missing', {}, None)
        self.addCleanup(error.close)
        fetch = FixtureFetcher({NEW + '/post': error})
        result = Comparator(fetch).compare(OLD + '/post', NEW + '/post')
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(fetch.calls, [NEW + '/post'])

    def test_source_failure_and_empty_or_soft404_targets_score_zero(self):
        self.assertEqual(self.compare(OSError('source missing'), page('hello'))['score'], 0)
        self.assertEqual(self.compare(page('hello'), page(''))['score'], 0)
        self.assertEqual(self.compare(page('hello'), b'<title>404: Not found</title>' + page('Not found'))['score'], 0)

    def test_target_redirect_back_to_original_is_not_full_credit(self):
        result = self.compare(page('Hello'), (page('Hello'), 'text/html', OLD + '/post'))
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['error'], 'target_redirect_outside_deployment')

    def test_excludes_chrome_scripts_and_hidden_text_and_normalizes_spaces(self):
        html = b'<body>outside<main>Hello <script>bad</script><nav>menu</nav><span hidden>hidden</span><span aria-hidden="true">hidden</span> world</main><footer>footer</footer></body>'
        text, images = parse_page(html, OLD)
        self.assertEqual(text, 'Hello world')
        self.assertEqual(images, [])

    def test_article_wins_over_main_and_body(self):
        text, _ = parse_page(b'<body>Body<main>Main<article>Article text</article></main></body>', OLD)
        self.assertEqual(text, 'Article text')

    def test_full_denominator_includes_errors_and_mapping_keeps_encoding(self):
        urls = [OLD + '/a', OLD + '/b', OLD + '/%ED%95%9C?q=1']
        values = {OLD + '/a': page('Hello'), NEW + '/a': page('Hello'),
                  NEW + '/b': OSError('missing'), NEW + '/%ED%95%9C?q=1': OSError('missing')}
        report = compare_inventory(urls, NEW, OLD + '/sitemap.xml', FixtureFetcher(values), workers=2)
        self.assertEqual(report['total_urls'], 3)
        self.assertEqual(len(report['results']), 3)
        self.assertEqual(report['score_sum'], 1)
        self.assertAlmostEqual(report['percentage'], 100 / 3)
        self.assertEqual(report['results'][2]['target_url'], NEW + '/%ED%95%9C?q=1')

    def test_duplicate_source_or_target_mapping_rejected(self):
        for urls in [[OLD + '/a', OLD + '/a'], [OLD + '/a', 'https://other.example/a']]:
            with self.assertRaises(ValueError):
                compare_inventory(urls, NEW, OLD + '/sitemap.xml')
        with self.assertRaises(ValueError):
            target_url(OLD + '/a', NEW + '/prefix')

    def test_same_origin_cannot_compare_against_itself(self):
        for target in [OLD, OLD + ':443']:
            with self.assertRaisesRegex(ValueError, 'different_origins'):
                target_url(OLD + '/a', target)
        with self.assertRaisesRegex(ValueError, 'different_origins'):
            compare_inventory([OLD + '/a'], OLD, OLD + '/sitemap.xml')

    def test_preflight_accepts_content_and_rejects_invalid_deployment(self):
        preflight_target(NEW, FixtureFetcher({NEW + '/': page('Home')}))
        for response in [(b'DEPLOYMENT_NOT_FOUND', 'text/plain', NEW + '/'),
                         page('DEPLOYMENT_NOT_FOUND'), page(''),
                         (page('Sign in'), 'text/html', 'https://vercel.com/login')]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                preflight_target(NEW, FixtureFetcher({NEW + '/': response}))

    def test_preflight_protection_failure_keeps_prior_report_and_skips_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            write_report(path, {'percentage': 50})
            error = HTTPError(NEW + '/', 401, 'protected', {}, None)
            self.addCleanup(error.close)
            with patch('sys.argv', ['compare_content.py', '--source-sitemap', OLD + '/sitemap.xml',
                                    '--target-base-url', NEW, '--output', str(path)]), \
                    patch('compare_content.fetch', side_effect=error), \
                    patch('compare_content.sitemap_urls') as inventory:
                with self.assertRaises(HTTPError):
                    main()
                inventory.assert_not_called()
            self.assertEqual(json.loads(path.read_text()), {'percentage': 50})

    def test_recursive_sitemaps_and_deduplication(self):
        fetch = FixtureFetcher({OLD + '/sitemap.xml': b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://old.example/posts.xml</loc></sitemap></sitemapindex>',
                                OLD + '/posts.xml': b'<urlset><url><loc>https://old.example/a</loc></url><url><loc>https://old.example/a</loc></url></urlset>'})
        self.assertEqual(sitemap_urls(OLD + '/sitemap.xml', fetch), [OLD + '/a'])

    def test_incomplete_inventory_fails_instead_of_shrinking_denominator(self):
        fetch = FixtureFetcher({OLD + '/sitemap.xml': b'<sitemapindex><sitemap><loc>https://old.example/missing.xml</loc></sitemap></sitemapindex>',
                                OLD + '/missing.xml': OSError('missing')})
        with self.assertRaises(OSError):
            sitemap_urls(OLD + '/sitemap.xml', fetch)

    def test_image_sitemap_metadata_does_not_become_a_page(self):
        fetch = FixtureFetcher({OLD + '/sitemap.xml': b'<urlset xmlns:image="https://example.org"><url><loc>https://old.example/a</loc><image:image><image:loc>https://cdn.example/image</image:loc></image:image></url></urlset>'})
        self.assertEqual(sitemap_urls(OLD + '/sitemap.xml', fetch), [OLD + '/a'])

    def test_report_atomic_write_and_invalid_json_preserves_old_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            write_report(path, {'percentage': 50})
            with self.assertRaises(ValueError):
                write_report(path, {'percentage': float('nan')})
            self.assertEqual(json.loads(path.read_text()), {'percentage': 50})
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
