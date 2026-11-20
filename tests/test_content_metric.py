import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from content_metric import render_asset_diagnostic, render_content, validate_report
from dashboard_data import ROOT, read_json


class MetricTests(unittest.TestCase):
    def test_diagnostic_displays_reviewed_groups_and_keeps_errors_in_denominator(self):
        summary = read_json(ROOT / 'docs/image-assets-root-inventory-2026-11-17.summary.json')
        html = render_asset_diagnostic(summary)
        for label in ('81.11%', '홈 · 44.01%', '블로그 글 · 82.67%', '기타 페이지·프로필 · 8.41%',
                      'URL 28개 · 오류 23개', '다른 언어의 대체 URL', '화면 유사도'):
            self.assertIn(label, html)
        self.assertNotIn('class="big content-score"', html)
        with self.assertRaises(ValueError):
            validate_report(summary)
        group = summary['by_page_type']['other']
        group['urls'] -= group['errors']
        group['errors'] = 0
        with self.assertRaises(ValueError):
            render_asset_diagnostic(summary)

    def setUp(self):
        self.report = dict(status='measured', generated_at='2026-10-24T00:00:00Z',
                           target_base_url='https://example.vercel.app', total_urls=3,
                           score_sum=1.5, percentage=50.0,
                           results=[dict(source_url=f'https://old.test/{i}', target_url=f'https://new.test/{i}',
                                         status='error' if i == 2 else 'ok', score=score)
                                    for i, score in enumerate([1, .5, 0])])

    def test_full_denominator_and_single_percentage(self):
        html = render_content(self.report)
        self.assertIn('50.0<small>%', html)
        self.assertIn('1.50 / 3점', html)
        self.assertIn('오류 1개는 0점', html)

    def test_unmeasured_is_not_zero(self):
        html = render_content({'status': 'unmeasured'})
        self.assertIn('미측정', html)
        self.assertNotIn('0<small>%', html)

    def test_not_deployed_is_zero_with_explanation(self):
        html = render_content({'status': 'not_deployed'})
        self.assertIn('0<small>%', html)
        self.assertIn('새 사이트 배포 전', html)
        self.assertNotIn('미측정', html)

    def test_invalid_reports_rejected(self):
        for mutate in [lambda r: r.update(total_urls=2),
                       lambda r: r.update(percentage=100),
                       lambda r: r['results'][2].update(score=.5),
                       lambda r: r['results'][1].update(target_url=r['results'][0]['target_url']),
                       lambda r: r['results'][0].update(score=float('nan'))]:
            report = copy.deepcopy(self.report)
            mutate(report)
            with self.assertRaises(ValueError):
                validate_report(report)

    def test_incomplete_never_rounds_up_to_100(self):
        self.report.update(total_urls=1, results=self.report['results'][:1], score_sum=.99999, percentage=99.999)
        self.report['results'][0]['score'] = .99999
        self.assertIn('99.9<small>%', render_content(self.report))

    def test_escape_report_metadata(self):
        self.report['target_base_url'] = '<script>alert(1)</script>'
        self.assertNotIn('<script>', render_content(self.report))

    def test_breakdown_retains_failed_urls_in_average_and_original_score(self):
        for row, text, image in zip(self.report['results'], [1, .8, 0], [1, .2, 0]):
            row.update(text_score=text, image_score=image)
        self.report['results'][0]['source_url'] = 'https://old.test/es/post/title'
        before = copy.deepcopy(self.report)
        html = render_content(self.report)
        self.assertEqual(before, self.report)
        self.assertIn('50.0<small>%', html)
        self.assertIn('60.0%', html)
        self.assertIn('40.0%', html)
        self.assertIn('블로그 1개', html)
        self.assertIn('기타 페이지·프로필 2개', html)
        self.assertIn('자동 갱신과 콘텐츠 재측정은 별도', html)

    def test_missing_components_are_not_reported_as_zero(self):
        html = render_content(self.report)
        self.assertNotIn('본문 텍스트 일치</h3>', html)
        self.assertNotIn('이미지 파일 일치</h3>', html)

    def test_failure_links_escape_text_and_reject_unsafe_schemes(self):
        self.report['results'][2].update(source_url='https://old.test/<script>',
                                        target_url='javascript:alert(1)', error='<img src=x>')
        html = render_content(self.report)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img src=x&gt;', html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn('<img src=x>', html)

    def test_invalid_components_cannot_be_presented_as_progress(self):
        for value in [float('nan'), 2, -1, True]:
            report = copy.deepcopy(self.report)
            report['results'][0]['text_score'] = value
            with self.assertRaises(ValueError):
                render_content(report)
        self.report['results'][2]['image_score'] = 1
        with self.assertRaises(ValueError):
            render_content(self.report)
