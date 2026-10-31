import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from daily_notice import collect, compose, deliver, restore_receipt
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
    def test_receipt_from_other_workflow_is_rejected(self, run):
        run.side_effect = [
            Mock(stdout=json.dumps({'artifacts': [{'id': 1, 'expired': False,
                'workflow_run': {'id': 2}}]}).encode()),
            Mock(stdout=json.dumps({'path': '.github/workflows/other.yml',
                'head_branch': 'main', 'event': 'workflow_dispatch',
                'head_repository': {'full_name': 'org/repo'}}).encode())]
        with self.assertRaises(ValueError):
            restore_receipt('org/repo')
        self.assertEqual(run.call_count, 2)

    @patch('daily_notice.subprocess.run')
    def test_no_receipt_starts_baseline(self, run):
        run.return_value.stdout = b'{"artifacts": []}'
        self.assertIsNone(restore_receipt('org/repo'))

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
