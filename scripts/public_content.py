"""Project the reviewed content report without exporting arbitrary extra fields."""
import math
from urllib.parse import urlsplit

from content_metric import validate_report
from dashboard_data import require, timestamp

ERROR_CODES = {
    'HTTPError', 'URLError', 'TimeoutError', 'OSError', 'ConnectionError',
    'UnicodeError', 'ValueError', 'response_too_large', 'soft_404', 'empty_content',
    'target_not_html', 'source_not_html', 'target_redirect_outside_deployment',
    'source_redirect_outside_site', 'comparison_failed',
}


def public_url(value):
    require(isinstance(value, str) and len(value) <= 4096, 'invalid report URL')
    parts = urlsplit(value)
    require(parts.scheme in {'http', 'https'} and parts.hostname and not parts.username
            and not parts.password and not parts.fragment
            and not any(ord(char) < 33 for char in value), 'invalid report URL')
    return value


def public_content(report):
    # Keep the CEO's score validation and scoring semantics unchanged.
    validate_report(report)
    result = {'status': report['status']}
    if report['status'] != 'measured':
        return result
    timestamp(report['generated_at'])
    result.update(generated_at=report['generated_at'],
                  source_sitemap=public_url(report['source_sitemap']),
                  target_base_url=public_url(report['target_base_url']),
                  total_urls=report['total_urls'], score_sum=report['score_sum'],
                  percentage=report['percentage'], results=[])
    for row in report['results']:
        item = {key: row[key] for key in ('status', 'score', 'text_score', 'image_score')}
        for key in ('text_score', 'image_score'):
            require(type(item[key]) in (int, float) and math.isfinite(item[key])
                    and 0 <= item[key] <= 1, 'invalid component score')
        item.update(source_url=public_url(row['source_url']), target_url=public_url(row['target_url']))
        if row['status'] == 'error':
            code = row.get('error')
            item['error'] = code if isinstance(code, str) and code in ERROR_CODES else 'comparison_failed'
        result['results'].append(item)
    validate_report(result)
    return result
