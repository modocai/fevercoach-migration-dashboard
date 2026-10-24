import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from content_metric import render_content, validate_report


class MetricTests(unittest.TestCase):
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
