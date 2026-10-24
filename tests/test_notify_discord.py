import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from notify_discord import NotificationError, make_message, send_notice

URL = 'https://discord.com/api/webhooks/123/fake_secret'


def response(body=None, status=200):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.status = status
    result.read.return_value = json.dumps(body if body is not None else {'id': '456'}).encode()
    return result


def report(score=.5):
    return dict(status='measured', generated_at='2026-10-24T01:00:00Z', total_urls=1,
                score_sum=score, percentage=score * 100,
                results=[dict(source_url='https://old/a', target_url='https://new/a', status='ok', score=score)])


class NoticeTests(unittest.TestCase):
    def test_predeployment_is_explicit_zero(self):
        message = make_message({'status': 'not_deployed'})
        self.assertIn('0%', message)
        self.assertIn('새 사이트 배포 전', message)
        self.assertEqual(message.count('%'), 1)

    def test_measured_snapshot_includes_date_and_matches_dashboard_rounding(self):
        message = make_message(report(.99999))
        self.assertIn('99.9%', message)
        self.assertIn('저장된 측정 기준: 2026-10-24T01:00:00+00:00', message)
        self.assertNotIn('100', message)
        self.assertIn('100.0%', make_message(report(1)))

    def test_no_invented_zero_for_unknown_or_invalid_report(self):
        for item in ({'status': 'unmeasured'}, {}, dict(report(), percentage=100)):
            with self.assertRaises((ValueError, KeyError)):
                make_message(item)

    def test_requires_timezone(self):
        with self.assertRaises(ValueError):
            make_message(dict(report(), generated_at='2026-10-24T01:00:00'))

    def test_posts_wait_true_and_no_mentions(self):
        opener = Mock(return_value=response())
        self.assertEqual(send_notice(URL, 'message', opener), '456')
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, URL + '?wait=true')
        self.assertEqual(json.loads(request.data), {'content': 'message', 'allowed_mentions': {'parse': []}})

    def test_rejects_webhook_substitution(self):
        for url in [None, 'http://discord.com/api/webhooks/123/token', URL + '?x=1',
                    URL.replace('discord.com', 'evil.test'), URL + '/extra',
                    'https://discord.com@evil.test/api/webhooks/123/token']:
            opener = Mock()
            with self.assertRaises(NotificationError):
                send_notice(url, 'x', opener)
            opener.assert_not_called()

    def test_rate_limit_obeys_delay(self):
        error = HTTPError(URL, 429, 'limited', {}, io.BytesIO(b'{"retry_after": 2.5}'))
        opener = Mock(side_effect=[error, response()])
        sleep = Mock()
        self.assertEqual(send_notice(URL, 'x', opener, sleep), '456')
        sleep.assert_called_once_with(2.6)
        self.assertEqual(opener.call_count, 2)

    def test_rate_limit_attempts_are_bounded(self):
        errors = [HTTPError(URL, 429, 'limited', {}, io.BytesIO(b'{"retry_after": 0}')) for _ in range(3)]
        opener = Mock(side_effect=errors)
        with self.assertRaises(NotificationError):
            send_notice(URL, 'x', opener, Mock())
        self.assertEqual(opener.call_count, 3)

    def test_unknown_delivery_not_retried_and_token_redacted(self):
        for error in [TimeoutError(URL), URLError(URL), HTTPError(URL, 403, URL, {}, io.BytesIO(b'error'))]:
            opener = Mock(side_effect=error)
            with self.assertRaises(NotificationError) as raised:
                send_notice(URL, 'x', opener)
            self.assertNotIn('fake_secret', str(raised.exception))
            self.assertEqual(opener.call_count, 1)

    def test_requires_saved_message_confirmation(self):
        for result in [response({}, 200), response({}, 204)]:
            with self.assertRaises(NotificationError):
                send_notice(URL, 'x', Mock(return_value=result))


if __name__ == '__main__':
    unittest.main()
