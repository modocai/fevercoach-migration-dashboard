import copy
import io
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from publication_fixture import NOW, PLAN, fixture
from dashboard_data import ROOT, read_json
from public_content import public_content
from public_dashboard import canonical, manifest, validate_state, write_site
from notify_discord import make_message
from notify_published import main, published_message


def measured(score=0.5):
    return dict(status='measured', generated_at=NOW,
                source_sitemap='https://www.fevercoach.us/sitemap.xml',
                target_base_url='https://example.invalid', total_urls=1,
                score_sum=score, percentage=score * 100,
                results=[dict(source_url='https://www.fevercoach.us/post/one',
                              target_url='https://example.invalid/post/one', status='ok',
                              score=score, text_score=score, image_score=score)])


def responses(state):
    values = {'state.json': state, 'manifest.json': manifest(state)}
    return lambda filename, nonce: values[filename]


class PublicationIntegrationTests(unittest.TestCase):
    def test_report_survives_html_json_and_published_notification(self):
        for report, label in [({'status': 'not_deployed'}, '0'), (measured(), '50.0'),
                              (measured(1), '100.0')]:
            with self.subTest(status=report['status'], label=label), tempfile.TemporaryDirectory() as directory:
                state = fixture(content_report=report)
                output = Path(directory) / 'site'
                write_site(output, state, PLAN, read_json(ROOT / 'data/baselines.json'))
                html = (output / 'index.html').read_text()
                self.assertIn('content-score">' + label + '<small>%', html)
                self.assertNotIn('content-score">미측정', html)
                self.assertEqual(read_json(output / 'data/content-comparison.json'), report)
                published = read_json(output / 'state.json')
                message = published_message(PLAN, '1', datetime.fromisoformat(NOW), responses(published))
                self.assertIn(make_message(report, PLAN, published['snapshot']), message)
                self.assertNotIn('주의:', message)
                if report['status'] == 'measured':
                    self.assertIn('href="data/content-comparison.json"', html)

    def test_incomplete_percentage_is_never_rounded_to_complete(self):
        report = measured(0.99999)
        state = fixture(content_report=report)
        message = published_message(PLAN, '1', datetime.fromisoformat(NOW), responses(state))
        self.assertIn('99.9%', message)
        self.assertNotIn('100.0%', message)

    def test_report_change_updates_build_identity_even_when_source_statuses_do_not_change(self):
        a = fixture(content_report=measured(0.5))
        b = fixture(content_report=measured(0.8))
        self.assertNotEqual(a['build_id'], b['build_id'])
        b['content_report']['percentage'] = 1
        with self.assertRaises(ValueError): validate_state(b, PLAN)

    def test_public_report_excludes_extra_fields_and_raw_error_text(self):
        report = measured(0)
        report['private'] = 'SECRET_CANARY'
        report['results'][0].update(status='error', error='SECRET_CANARY', html='SECRET_CANARY')
        public = public_content(report)
        self.assertNotIn('CANARY', canonical(public).decode())
        self.assertEqual(public['results'][0]['error'], 'comparison_failed')
        self.assertEqual(public_content({'status': 'not_deployed', 'private': 'CANARY'}), {'status': 'not_deployed'})

    def test_invalid_report_and_credential_urls_cannot_publish(self):
        for mutate in [lambda r: r.update(percentage=99),
                       lambda r: r.update(generated_at='2026-10-23'),
                       lambda r: r.update(target_base_url='https://user:password@example.invalid'),
                       lambda r: r['results'][0].update(text_score=float('nan')),
                       lambda r: r['results'][0].update(source_url='file:///private')]:
            report = measured()
            mutate(report)
            with self.assertRaises((ValueError, TypeError)):
                fixture(content_report=report)

    def test_notice_uses_published_issue_status_not_repository_snapshot(self):
        state = fixture()
        # Simulate a repository seed that differs from the published snapshot.
        seed = copy.deepcopy(state['snapshot'])
        seed['issues']['items'][0].update(state='closed', state_reason='completed')
        self.assertIn('(1/28)', make_message({'status': 'not_deployed'}, PLAN, seed))
        message = published_message(PLAN, '1', datetime.fromisoformat(NOW), responses(state))
        self.assertIn('(0/28)', message)
        self.assertNotIn('(1/28)', message)

    def test_notice_exposes_stale_and_failed_collection_without_inventing_fresh_data(self):
        state = fixture()
        message = published_message(PLAN, '1', datetime(2026, 10, 24, tzinfo=timezone.utc), responses(state))
        self.assertIn('45분', message)
        self.assertIn(NOW, message)
        from public_dashboard import make_state
        raw = copy.deepcopy(state['snapshot'])
        raw['project'].update(status='error', error='github_request_failed')
        failed = make_state(raw, PLAN, state['revision'], 2, NOW, state['content_report'])
        self.assertIn('일부 원본 조회에 실패', published_message(PLAN, '1', datetime.fromisoformat(NOW), responses(failed)))

    def test_missing_inconsistent_or_incompatible_publication_does_not_fall_back(self):
        from urllib.error import HTTPError
        def missing(*args): raise HTTPError('https://example.invalid', 404, 'missing', {}, None)
        with self.assertRaises(ValueError): published_message(PLAN, '1', datetime.fromisoformat(NOW), missing)
        state = fixture()
        values = {'state.json': state, 'manifest.json': {**manifest(state), 'build_id': 'b' * 64}}
        with self.assertRaises(ValueError):
            published_message(PLAN, '1', datetime.fromisoformat(NOW), lambda name, _: values[name])
        changed = copy.deepcopy(PLAN)
        changed['tasks'].pop()
        with self.assertRaises(ValueError): published_message(changed, '1', datetime.fromisoformat(NOW), responses(state))

    def test_disabled_mode_delegates_to_existing_sender_unchanged(self):
        with patch.dict(os.environ, {'DASHBOARD_AUTOUPDATE_ENABLED': 'false'}), \
             patch('notify_published.notify_discord.main', return_value=0) as legacy, \
             patch('notify_published.published_message') as published:
            self.assertEqual(main(), 0)
            legacy.assert_called_once_with()
            published.assert_not_called()

    def test_enabled_failure_is_redacted_and_never_sends(self):
        with patch.dict(os.environ, {'DASHBOARD_AUTOUPDATE_ENABLED': 'true'}), \
             patch('sys.argv', ['notify_published.py']), \
             patch('notify_published.published_message', side_effect=ValueError('SECRET_CANARY')), \
             patch('notify_published.notify_discord.send_notice') as sender, redirect_stderr(io.StringIO()) as log:
            self.assertEqual(main(), 1)
            sender.assert_not_called()
            self.assertNotIn('CANARY', log.getvalue())

    def test_enabled_dry_run_and_send_share_message_and_existing_delivery_checks(self):
        for dry_run in [False, True]:
            with self.subTest(dry_run=dry_run), \
                 patch.dict(os.environ, {'DASHBOARD_AUTOUPDATE_ENABLED': 'true', 'DISCORD_ENGINEERING_WEBHOOK_URL': 'SECRET_CANARY'}), \
                 patch('sys.argv', ['notify_published.py'] + (['--dry-run'] if dry_run else [])), \
                 patch('notify_published.published_message', return_value='published report') as message, \
                 patch('notify_published.notify_discord.send_notice', return_value='123') as sender, \
                 redirect_stdout(io.StringIO()) as log:
                self.assertEqual(main(), 0)
                message.assert_called_once()
                if dry_run: sender.assert_not_called()
                else: sender.assert_called_once_with('SECRET_CANARY', 'published report')
                self.assertNotIn('CANARY', log.getvalue())
