import base64
import copy
import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError

from publication_fixture import NOW, PLAN, REVISION, SyntheticGitHub, fixture
from dashboard_data import ROOT, read_json, task_states
from public_dashboard import (FILES, MAX_STATE_BYTES, PublicGitHub, NoRedirect, audit_tree, canonical, catalog_id, fetch_public, manifest,
                              public_snapshot, validate_manifest, validate_state, write_site)
from publish_dashboard import guard, main, prepare, previous_state
from sync_github import FetchError


def missing(*args):
    raise HTTPError("https://example.invalid", 404, "missing", {}, None)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.state = fixture()

    def test_public_projection_drops_private_fields_and_reconstructs_source_url(self):
        raw = copy.deepcopy(self.state["snapshot"])
        raw["issues"]["items"][0].update(assignees=["PRIVATE_CANARY"], body="PRIVATE_CANARY", updated_at=NOW)
        raw["wix"]["source_url"] = "https://example.invalid/PRIVATE_CANARY"
        raw["wix"]["data"]["raw_inventory"] = "PRIVATE_CANARY"
        raw["project"]["items"][0]["due_date"] = "2026-12-01"
        result = public_snapshot(raw, PLAN)
        self.assertNotIn("PRIVATE_CANARY", canonical(result).decode())
        self.assertNotIn("assignees", canonical(result).decode())
        self.assertIsNone(result["project"]["items"][0]["due_date"])
        self.assertEqual(task_states(PLAN, result)[0]["status"], "doing")

    def test_unmerged_wix_data_is_rejected(self):
        self.state["snapshot"]["wix"].update(review_state="open_pr", pr_url="https://github.com/modocai/fevercoach-website/pull/29")
        with self.assertRaises(ValueError):
            public_snapshot(self.state["snapshot"], PLAN)

    def test_cached_state_rejects_extra_fields_and_hash_tampering(self):
        for mutate in [lambda s: s.update(private="CANARY"),
                       lambda s: s["snapshot"]["issues"]["items"][0].update(assignees=["CANARY"]),
                       lambda s: s.update(build_id="b" * 64),
                       lambda s: s.update(generation=True)]:
            state = copy.deepcopy(self.state)
            mutate(state)
            with self.assertRaises((ValueError, TypeError)):
                validate_state(state, PLAN)

    def test_cache_compatibility_tracks_ids_not_editorial_titles(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["title"] = "Editorial revision"
        self.assertEqual(catalog_id(plan), catalog_id(PLAN))
        validate_state(self.state, plan)
        plan["tasks"].pop()
        with self.assertRaises(ValueError):
            validate_state(self.state, plan)

    def test_restore_requires_valid_matching_manifest(self):
        responses = {"state.json": self.state, "manifest.json": manifest(self.state)}
        self.assertEqual(previous_state(PLAN, "1", lambda name, _: responses[name]), self.state)
        responses["manifest.json"]["build_id"] = "b" * 64
        with self.assertRaises(ValueError):
            previous_state(PLAN, "1", lambda name, _: responses[name])

    def test_bootstrap_requires_both_endpoints_404(self):
        self.assertIsNone(previous_state(PLAN, "1", missing))
        def partial(name, nonce):
            return missing() if name == "state.json" else manifest(self.state)
        with self.assertRaises(ValueError):
            previous_state(PLAN, "1", partial)
        def unavailable(*args):
            raise HTTPError("https://example.invalid", 503, "unavailable", {}, None)
        with self.assertRaises(HTTPError):
            previous_state(PLAN, "1", unavailable)

    def test_failed_initial_collection_does_not_build_a_site(self):
        class Failed(SyntheticGitHub):
            def project(self, plan): raise FetchError("project_read_permission_required")
        with self.assertRaises(ValueError):
            prepare(PLAN, None, Failed(), REVISION, 1, NOW)

    def test_failed_refresh_preserves_published_cache_not_repository_seed(self):
        class Failed(SyntheticGitHub):
            def issues(self, plan): raise FetchError("PRIVATE_CANARY")
            def project(self, plan): return [{"number": 1, "status": "blocked", "due_date": None}]
        later = "2026-10-23T17:00:00+00:00"
        state, failures = prepare(PLAN, self.state, Failed(), REVISION, 2, later)
        self.assertEqual(failures, ["issues"])
        self.assertEqual(state["snapshot"]["issues"]["last_success_at"], NOW)
        self.assertEqual(state["snapshot"]["issues"]["items"], self.state["snapshot"]["issues"]["items"])
        self.assertEqual(state["snapshot"]["project"]["items"][0]["status"], "blocked")
        self.assertNotIn("PRIVATE_CANARY", canonical(state).decode())
        self.assertTrue(manifest(state)["degraded"])
        self.assertEqual(manifest(state)["last_success_at"], NOW)

    def test_all_sources_failed_keeps_last_good_records(self):
        class Failed:
            def __getattr__(self, name):
                def fail(plan): raise FetchError("github_request_failed")
                return fail
        state, failures = prepare(PLAN, self.state, Failed(), REVISION, 2, NOW)
        self.assertEqual(len(failures), 3)
        validate_state(state, PLAN)
        self.assertEqual(state["snapshot"]["wix"]["data"], self.state["snapshot"]["wix"]["data"])

    def test_incomplete_issue_response_does_not_replace_cache(self):
        class Partial(SyntheticGitHub):
            def issues(self, plan): return super().issues(plan)[:-1]
        state, failures = prepare(PLAN, self.state, Partial(), REVISION, 2, NOW)
        self.assertEqual(failures, ["issues"])
        self.assertEqual(len(state["snapshot"]["issues"]["items"]), 28)

    def test_guard_rejects_old_main_and_duplicate_generation(self):
        fetch = lambda *args: manifest(self.state)
        guard(REVISION, 2, "1", fetch=fetch, api=lambda: REVISION)
        for revision, generation in [("b" * 40, 2), (REVISION, 1), (REVISION, 0)]:
            with self.assertRaises(ValueError):
                guard(revision, generation, "1", fetch=fetch, api=lambda: REVISION)
        guard(REVISION, 1, "1", fetch=missing, api=lambda: REVISION)
        with self.assertRaises(ValueError):
            prepare(PLAN, self.state, SyntheticGitHub(), REVISION, 1, NOW)

    def test_issue_query_requests_only_approved_ids_and_minimal_fields(self):
        class Client(PublicGitHub):
            def api(self, endpoint, *args):
                query = " ".join(args)
                for forbidden in ["body", "assignees", "updatedAt", "title", "comments", "issue(number:29)"]:
                    assert forbidden not in query
                return {"data": {"repository": {f'i{t["number"]}': {"number": t["number"], "state": "OPEN", "stateReason": None}
                                                  for t in PLAN["tasks"]}}}
        self.assertEqual(len(Client().issues(PLAN)), 28)

    def test_autonomous_wix_never_falls_back_to_unmerged_pr(self):
        class Client(PublicGitHub):
            calls = []
            def api(self, endpoint, *args):
                self.calls.append(endpoint)
                if "/commits/main" in endpoint: return {"sha": REVISION}
                raise FetchError("not_found")
        client = Client()
        with self.assertRaisesRegex(FetchError, "approved_wix_source_unavailable"):
            client.wix(PLAN)
        self.assertEqual(len(client.calls), 2)
        self.assertFalse(any("pulls" in call for call in client.calls))

    def test_main_wix_is_projected_before_return(self):
        raw = SyntheticGitHub().wix(PLAN)["data"]
        raw["private"] = "PRIVATE_CANARY"
        class Client(PublicGitHub):
            def api(self, endpoint, *args):
                if "/commits/main" in endpoint: return {"sha": REVISION}
                return {"encoding": "base64", "content": base64.b64encode(json.dumps(raw).encode()).decode()}
        self.assertNotIn("PRIVATE_CANARY", str(Client().wix(PLAN)))

    def test_artifact_is_exact_public_allowlist_and_entrypoints_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            write_site(output, self.state, PLAN, read_json(ROOT / "data/baselines.json"))
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}, FILES)
            html = (output / "index.html").read_text()
            self.assertEqual(html, (output / "migration-dashboard.html").read_text())
            self.assertIn(self.state["build_id"], html)
            self.assertIn('assets/auto-refresh.js?v=', html)
            validate_state(read_json(output / "state.json"), PLAN)
            validate_manifest(read_json(output / "manifest.json"))
            (output / "secret.txt").write_text("CANARY")
            with self.assertRaises(ValueError): audit_tree(output)

    def test_artifact_rejects_links_and_unknown_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            write_site(output, self.state, PLAN, read_json(ROOT / "data/baselines.json"))
            (output / "extra").mkdir()
            with self.assertRaises(ValueError): audit_tree(output)
            (output / "extra").rmdir()
            (output / "link").symlink_to(output / "state.json")
            with self.assertRaises(ValueError): audit_tree(output)

    def test_artifact_root_cannot_be_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            link = Path(temporary) / "site"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                write_site(link, self.state, PLAN, read_json(ROOT / "data/baselines.json"))
            self.assertEqual(list(target.iterdir()), [])

    def test_public_cache_request_has_no_credentials_and_bounds_body(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                self.size = size
                return canonical(manifest(fixture()))
        response = Response()
        class Opener:
            def open(self, request, timeout):
                self.request = request
                assert request.full_url.startswith('https://modocai.github.io/fevercoach-migration-dashboard/manifest.json?')
                assert 'Authorization' not in request.headers and 'Cookie' not in request.headers
                assert timeout == 15
                return response
        opener = Opener()
        with patch('public_dashboard.build_opener', return_value=opener), patch.dict(os.environ, {'GH_TOKEN': 'SECRET_CANARY'}):
            validate_manifest(fetch_public('manifest.json', '1-1'))
        self.assertEqual(response.size, MAX_STATE_BYTES + 1)
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_public_cache_rejects_unknown_endpoint_and_oversize(self):
        with self.assertRaises(ValueError): fetch_public('../private.json', '1')
        with self.assertRaises(ValueError): fetch_public('state.json', 'bad/query')
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'x' * size
        with patch('public_dashboard.build_opener') as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaises(ValueError): fetch_public('state.json', '1')

    def test_cli_never_logs_raw_exception_or_credential(self):
        environment = {'GITHUB_REPOSITORY': 'modocai/fevercoach-migration-dashboard', 'GITHUB_REF': 'refs/heads/main',
                       'GITHUB_SHA': REVISION, 'GITHUB_RUN_NUMBER': '2', 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
                       'GH_TOKEN': 'SECRET_CANARY'}
        output = io.StringIO()
        with patch.dict(os.environ, environment), patch('sys.argv', ['publish_dashboard.py']), \
             patch('publish_dashboard.previous_state', side_effect=RuntimeError('PRIVATE_CANARY')), \
             patch('publish_dashboard.write_site') as writer, redirect_stdout(output):
            self.assertEqual(main(), 1)
            writer.assert_not_called()
        self.assertNotIn('CANARY', output.getvalue())

    def test_cli_builds_only_public_site_and_fixed_job_output(self):
        for degraded in [False, True]:
            with self.subTest(degraded=degraded), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'data').mkdir()
                (root / 'data/plan.json').write_text(json.dumps(PLAN))
                (root / 'data/baselines.json').write_text((ROOT / 'data/baselines.json').read_text())
                output = root / 'job-output'
                environment = {'GITHUB_REPOSITORY': 'modocai/fevercoach-migration-dashboard', 'GITHUB_REF': 'refs/heads/main',
                               'GITHUB_SHA': REVISION, 'GITHUB_RUN_NUMBER': '2', 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
                               'GH_TOKEN': 'SECRET_CANARY', 'GITHUB_OUTPUT': str(output)}
                class Failed(SyntheticGitHub):
                    def project(self, plan): raise FetchError('PRIVATE_CANARY')
                client = Failed() if degraded else SyntheticGitHub()
                with patch.dict(os.environ, environment), patch('sys.argv', ['publish_dashboard.py']), \
                     patch('publish_dashboard.ROOT', root), patch('publish_dashboard.previous_state', return_value=self.state if degraded else None), \
                     patch('publish_dashboard.PublicGitHub', return_value=client), redirect_stdout(io.StringIO()) as logs:
                    self.assertEqual(main(), 0)
                self.assertEqual(output.read_text(), 'degraded=' + str(degraded).lower() + '\n')
                state = read_json(root / '_site/state.json')
                validate_state(state, PLAN)
                self.assertEqual(manifest(state)['degraded'], degraded)
                self.assertNotIn('CANARY', logs.getvalue())
                for path in (root / '_site').rglob('*'):
                    if path.is_file(): self.assertNotIn('CANARY', path.read_text())


if __name__ == "__main__":
    unittest.main()
