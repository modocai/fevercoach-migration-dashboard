import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from daily_notice import collect, compose, content_line, deliver, main, restore_receipt, already_reported_today, ReceiptPersistenceError
from notify_discord import NotificationError
from dashboard_data import ROOT, read_json

NOW = '2026-10-31T15:00:00+00:00'

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.plan = read_json(ROOT / 'data/plan.json')
        self.snapshot = read_json(ROOT / 'data/snapshot.json')
        for i in self.snapshot['issues']['items']:
            i.update(state='open', state_reason=None)
        self.snapshot['issues']['items'][0].update(state='closed', state_reason='completed')
        self.previous = {'completed': [], 'last_successful_snapshot_at': '2026-10-30T00:00:00Z'}

    def compose(self, previous=None):
        return compose(self.plan, self.snapshot, {'status':'not_deployed'}, previous, NOW)

    @patch('daily_notice.subprocess.run')
    def test_receipt_only_from_trusted_runs(self, run):
        trusted = {'path': '.github/workflows/daily-notice.yml', 'head_branch': 'main',
                   'event': 'schedule', 'head_repository': {'full_name': 'org/repo'}}
        receipt = {'schema_version': 1, 'completed': [1], 'message_id': '9', 'last_sent_at': NOW}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('receipt.json', json.dumps(receipt))
        def artifact(id, run_id, **source):
            return {'id': id, 'expired': False, 'workflow_run': dict(
                {'id': run_id, 'head_branch': 'main', 'repository_id': 1, 'head_repository_id': 1}, **source)}
        run.side_effect = [
            Mock(stdout=json.dumps({'artifacts': [
                artifact(6, 2), artifact(9, 5, head_repository_id=99), artifact(8, 4, head_branch='x'),
                artifact(7, 3)]}).encode()),
            Mock(stdout=json.dumps(dict(trusted, event='pull_request')).encode()),
            Mock(stdout=json.dumps(dict(trusted, id=2)).encode()),
            Mock(stdout=archive.getvalue())]
        self.assertEqual(restore_receipt('org/repo'), receipt)
        urls = [c.args[0][2] for c in run.call_args_list]
        self.assertEqual(urls[1:], ['repos/org/repo/actions/runs/3',
                                    'repos/org/repo/actions/runs/2',
                                    'repos/org/repo/actions/artifacts/6/zip'])

    @patch('daily_notice.subprocess.run')
    def test_full_page_without_trusted_receipt_is_error(self, run):
        run.return_value.stdout = json.dumps({'artifacts': [
            {'id': i, 'expired': False, 'workflow_run': {'id': i, 'head_branch': 'x'}} for i in range(100)]}).encode()
        with self.assertRaises(ValueError):
            restore_receipt('org/repo')

    @patch('daily_notice.subprocess.run')
    def test_no_receipt_starts_baseline(self, run):
        run.return_value.stdout = b'{"artifacts": []}'
        self.assertIsNone(restore_receipt('org/repo'))

    def test_invalid_measurement_timestamp_is_not_displayed(self):
        report = {'status': 'measured', 'total_urls': 1, 'score_sum': 1, 'percentage': 100,
                  'results': [{'source_url': 'a', 'target_url': 'b', 'score': 1, 'status': 'ok'}]}
        self.assertIn('측정 시각', content_line(dict(report, generated_at='2026-10-24T01:00:00Z')))
        for value in ('not-a-timestamp', '2026-10-24T01:00:00'):
            self.assertIn('최신 측정 없음', content_line(dict(report, generated_at=value)))

    def test_preview_measurement_keeps_scope_in_final_notice(self):
        report = {'status': 'measured', 'total_urls': 1, 'score_sum': .466,
                  'percentage': 46.6, 'generated_at': NOW,
                  'target_base_url': 'https://fevercoach-website-git-wix-cms-integration-fevecoach-team.vercel.app',
                  'results': [{'source_url': 'a', 'target_url': 'b', 'score': .466, 'status': 'ok'}]}
        for item in self.snapshot['issues']['items']:
            item.update(state='closed', state_reason='completed')
        message, completed = compose(self.plan, self.snapshot, report, None, NOW)
        self.assertIn('콘텐츠 이관율: 46.6%', message)
        self.assertIn('CMS 연결 Preview 기준 · 운영 전환 완료율과 별도', message)
        self.assertIn(NOW, message)
        self.assertLessEqual(len(message), 1950)
        self.assertEqual(len(completed), 28)
        report['target_base_url'] = 'https://www.fevercoach.us'
        self.assertNotIn('Preview', content_line(report))

    @patch.dict('os.environ', {}, clear=True)
    @patch('daily_notice.collect')
    @patch('daily_notice.restore_receipt', return_value=None)
    @patch('daily_notice.send_notice', side_effect=NotificationError('Discord delivery was not confirmed; not retried to avoid duplicates'))
    def test_ambiguous_delivery_says_check_discord(self, send, restore, collect_):
        collect_.return_value = self.snapshot
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, patch('sys.argv', ['daily_notice', '--receipt', f'{d}/r.json']), \
                patch('sys.stderr', err):
            self.assertEqual(main(), 1)
            self.assertFalse(Path(d, 'r.json').exists())
        self.assertIn('not confirmed', err.getvalue())
        self.assertIn('Check Discord before rerunning', err.getvalue())

    def test_failed_query_notice_allows_same_day_recovery(self):
        previous = {'last_sent_at': NOW, 'last_successful_snapshot_at': '2026-10-30T00:00:00Z'}
        self.assertFalse(already_reported_today(previous, NOW))
        previous['last_successful_snapshot_at'] = NOW
        self.assertTrue(already_reported_today(previous, NOW))

    def test_confirmed_send_with_receipt_failure_is_distinct(self):
        sender = Mock(return_value='123')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'not-a-directory'
            p.write_text('block directory creation')
            with self.assertRaises(ReceiptPersistenceError):
                deliver('message', [1], None, self.snapshot, NOW, p / 'receipt.json', sender)
        sender.assert_called_once()

    def test_first_message_is_baseline_not_new_today(self):
        msg, completed = self.compose()
        self.assertIn('오늘 완료된 목록이 아님', msg)
        self.assertEqual(completed, [1])
        self.assertIn('최신 측정 없음', msg)
        self.assertNotIn('이관 완성률: 0%', msg)

    def test_only_new_completions_and_no_duplicates(self):
        msg, ids = self.compose(self.previous)
        self.assertIn('✅ [#1]', msg)
        self.previous['completed'] = ids
        msg, _ = self.compose(self.previous)
        self.assertNotIn('✅', msg)
        self.assertIn('없음', msg)

    def test_reopened_and_not_planned_not_counted(self):
        self.snapshot['issues']['items'][0].update(state='closed', state_reason='not_planned')
        self.previous['completed'] = [1]
        msg, ids = self.compose(self.previous)
        self.assertEqual(ids, [])
        self.assertIn('완료 0개', msg)
        self.assertIn('재열림 또는 종료 사유 변경', msg)

    def test_issue_failure_retains_checkpoint_without_old_counts(self):
        self.snapshot['issues'].update(status='error', items=[], last_success_at=None)
        self.previous['completed'] = [1,2]
        msg, ids = self.compose(self.previous)
        self.assertIn('Issues 조회 실패', msg)
        self.assertNotIn('전체 28개', msg)
        self.assertEqual(ids, [1,2])

    def test_project_failure_keeps_fresh_issue_count(self):
        self.snapshot['project'].update(status='error', items=[], last_success_at=None)
        msg, _ = self.compose(self.previous)
        self.assertIn('완료 1개', msg)
        self.assertIn('Project 조회 실패', msg)
        self.assertNotIn('할 일 27', msg)

    def test_incomplete_collection_rejected(self):
        client = Mock()
        client.issues.return_value = self.snapshot['issues']['items'][:-1]
        client.project.return_value = []
        result = collect(self.plan, client, NOW)
        self.assertEqual(result['issues']['status'], 'error')
        self.assertEqual(result['issues']['items'], [])

    def test_failure_does_not_advance_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'receipt.json'
            p.write_text('previous')
            with self.assertRaises(TimeoutError):
                deliver('message', [1], None, self.snapshot, NOW, p, Mock(side_effect=TimeoutError))
            self.assertEqual(p.read_text(), 'previous')

    def test_success_saves_confirmed_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'receipt.json'
            deliver('message', [1], None, self.snapshot, NOW, p, Mock(return_value='123'))
            r=json.loads(p.read_text())
            self.assertEqual(r['message_id'], '123')
            self.assertEqual(r['completed'], [1])
            self.assertEqual(r['last_successful_snapshot_at'], NOW)

    def test_all_completed_stays_under_discord_limit(self):
        for i in self.snapshot['issues']['items']:
            i.update(state='closed',state_reason='completed')
        msg, ids = self.compose()
        self.assertLessEqual(len(msg),1950)
        self.assertEqual(len(ids),28)
        self.assertIn('나머지 완료 목록',msg)

if __name__ == '__main__': unittest.main()
