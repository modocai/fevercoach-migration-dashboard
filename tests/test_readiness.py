import copy
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from publication_fixture import NOW, PLAN, REVISION, SyntheticGitHub, fixture
from dashboard_data import ROOT, read_json
import check_readiness as check
from sync_github import FetchError


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'GH_TOKEN': 'WORKFLOW_CANARY', 'DASHBOARD_SOURCE_TOKEN': 'SOURCE_CANARY',
            'GITHUB_REPOSITORY': check.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': REVISION,
            'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        self.capture = redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def notice_module(self, failed=None):
        snapshot = copy.deepcopy(fixture()['snapshot'])
        if failed:
            snapshot[failed]['status'] = 'error'
        def restore(repo):
            self.assertEqual(os.environ['GH_TOKEN'], 'WORKFLOW_CANARY')
            return None
        def collect(*args):
            self.assertEqual(os.environ['GH_TOKEN'], 'SOURCE_CANARY')
            return snapshot
        return SimpleNamespace(restore_receipt=Mock(side_effect=restore),
                               collect=Mock(side_effect=collect),
                               compose=Mock(return_value=('safe notice', [])),
                               send_notice=Mock(), deliver=Mock())

    def test_notice_composes_without_delivering_and_restores_workflow_token(self):
        module = self.notice_module()
        with patch.object(check.importlib, 'import_module', return_value=module):
            self.assertTrue(check.check_notice(PLAN, {'status': 'not_deployed'}, NOW))
        module.send_notice.assert_not_called()
        module.deliver.assert_not_called()
        module.compose.assert_called_once()
        self.assertEqual(os.environ['GH_TOKEN'], 'WORKFLOW_CANARY')

    def test_notice_source_failures_cannot_pass_as_warning_only_messages(self):
        for source in ('issues', 'project'):
            module = self.notice_module(source)
            with patch.object(check.importlib, 'import_module', return_value=module):
                self.assertFalse(check.check_notice(PLAN, {'status': 'not_deployed'}, NOW))
            module.compose.assert_not_called()
            module.deliver.assert_not_called()

    def test_notice_not_merged_is_explicit_and_does_not_run_pr_code(self):
        with patch.object(check.importlib, 'import_module',
                          side_effect=ModuleNotFoundError(name='daily_notice')):
            self.assertFalse(check.check_notice(PLAN, {'status': 'not_deployed'}, NOW))
        self.assertIn('merge reviewed PR #10 first', self.output.getvalue())

    def test_token_is_restored_when_collection_raises(self):
        with self.assertRaises(RuntimeError):
            with check.source_credentials():
                raise RuntimeError('PRIVATE_CANARY')
        self.assertEqual(os.environ['GH_TOKEN'], 'WORKFLOW_CANARY')
        del os.environ['GH_TOKEN']
        with check.source_credentials():
            self.assertEqual(os.environ['GH_TOKEN'], 'SOURCE_CANARY')
        self.assertNotIn('GH_TOKEN', os.environ)

    def test_missing_source_token_never_falls_back_to_cli_login(self):
        del os.environ['DASHBOARD_SOURCE_TOKEN']
        with self.assertRaises(ValueError):
            with check.source_credentials():
                self.fail('Must not use personal authentication')

    def publication(self):
        return check.check_publication(PLAN, {'status': 'not_deployed'},
                                       read_json(ROOT / 'data/baselines.json'), REVISION, '1', NOW)

    def test_publication_creates_valid_disposable_site_and_removes_it(self):
        original = check.write_site
        sites = []
        def inspect(path, *args):
            original(path, *args)
            self.assertTrue((path / 'manifest.json').is_file())
            sites.append(path)
        with patch.object(check, 'previous_state', return_value=None), \
             patch.object(check, 'PublicGitHub', return_value=SyntheticGitHub()), \
             patch.object(check, 'write_site', side_effect=inspect):
            self.assertTrue(self.publication())
        self.assertEqual(len(sites), 1)
        self.assertFalse(sites[0].exists())
        self.assertEqual(os.environ['GH_TOKEN'], 'WORKFLOW_CANARY')

    def test_unavailable_wix_blocks_bootstrap_and_cached_activation(self):
        class Failed(SyntheticGitHub):
            def wix(self, plan):
                raise FetchError('approved_wix_source_unavailable')
        for previous in (None, fixture()):
            with patch.object(check, 'previous_state', return_value=previous), \
                 patch.object(check, 'PublicGitHub', return_value=Failed()), \
                 patch.object(check, 'write_site') as writer:
                self.assertFalse(self.publication())
                writer.assert_not_called()
        self.assertIn('wix: FAIL', self.output.getvalue())

    def test_disposable_generation_follows_live_state_not_preflight_run_number(self):
        previous = fixture()
        with patch.object(check, 'previous_state', return_value=previous), \
             patch.object(check, 'PublicGitHub', return_value=SyntheticGitHub()), \
             patch.object(check, 'write_site') as writer:
            self.assertTrue(self.publication())
        self.assertEqual(writer.call_args.args[1]['generation'], previous['generation'] + 1)

    def test_invalid_public_cache_stops_before_source_access(self):
        with patch.object(check, 'previous_state', side_effect=ValueError('PRIVATE_CANARY')), \
             patch.object(check, 'PublicGitHub') as client:
            with self.assertRaises(ValueError):
                self.publication()
            client.assert_not_called()

    def run_main(self, mode='notice'):
        with patch('sys.argv', ['check_readiness.py', '--mode', mode]):
            return check.main()

    def test_main_rejects_wrong_repository_ref_event_and_missing_credentials(self):
        for key, value in [('GITHUB_REPOSITORY', 'other/repo'),
                           ('GITHUB_REF', 'refs/pull/1/merge'),
                           ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_SHA', 'bad'), ('GH_TOKEN', ''),
                           ('DASHBOARD_SOURCE_TOKEN', '')]:
            with patch.dict(os.environ, {key: value}), patch.object(check, 'check_notice') as probe:
                self.assertEqual(self.run_main(), 1)
                probe.assert_not_called()

    def test_main_masks_failure_details(self):
        with patch.object(check, 'check_revision'), \
             patch.object(check, 'check_notice', side_effect=RuntimeError('SOURCE_CANARY PRIVATE_CANARY')):
            self.assertEqual(self.run_main(), 1)
        self.assertNotIn('CANARY', self.output.getvalue())

    def test_main_rechecks_revision_after_probe(self):
        with patch.object(check, 'check_revision', side_effect=[None, ValueError('changed')]) as guard, \
             patch.object(check, 'check_notice', return_value=True):
            self.assertEqual(self.run_main(), 1)
            self.assertEqual(guard.call_count, 2)

    def test_main_returns_failure_for_unsuccessful_notice(self):
        with patch.object(check, 'check_revision'), patch.object(check, 'check_notice', return_value=False):
            self.assertEqual(self.run_main(), 1)

    def test_revision_check_does_not_accept_stale_or_failed_lookup(self):
        for result in (SimpleNamespace(returncode=1, stdout=REVISION),
                       SimpleNamespace(returncode=0, stdout='b' * 40)):
            with patch.object(check.subprocess, 'run', return_value=result):
                with self.assertRaises(ValueError):
                    check.check_revision(REVISION)
