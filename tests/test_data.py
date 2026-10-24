import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dashboard_data import (ROOT, gate_state, project_issues, project_items, project_wix,
                            read_json, safe_url, task_states, validate_baselines,
                            validate_plan, validate_snapshot)
from sync_github import FetchError, GitHub, refresh

NOW = "2026-10-23T16:00:00+00:00"
WIX = {"schema_version": 1, "scope": "public_sitemap_snapshot", "source": "https://www.fevercoach.us",
       "generated_at": NOW, "discovered_urls": 3589, "exported_urls": 3589,
       "unique_referenced_images": 6771, "downloaded_images": 1092, "images_not_downloaded_count": 5679,
       "failed_url_count": 0, "missing_url_count": 0, "media_error_count": 0,
       "all_discovered_urls_exported": True, "all_referenced_images_downloaded": False,
       "authoritative_wix_export_complete": False, "dns_zone_export_complete": False,
       "media_download_scope": "sample"}


def issue(number, state="open", reason=None):
    return {"number": number, "state": state, "state_reason": reason, "assignees": [],
            "updated_at": NOW, "html_url": f"https://github.com/modocai/fevercoach-website/issues/{number}",
            "body": "PRIVATE_BODY_MUST_NOT_APPEAR"}


def wix_result():
    return {"data": copy.deepcopy(WIX), "source_sha": "a" * 40, "review_state": "main",
            "source_url": "https://github.com/modocai/fevercoach-website/blob/" + "a" * 40 + "/docs/wix-export-status.json",
            "pr_url": None}


class DataTests(unittest.TestCase):
    def setUp(self):
        self.plan = read_json(ROOT / "data/plan.json")
        self.raw = [issue(n, "closed" if n == 5 else "open", "completed" if n == 5 else None)
                    for n in range(1, 29)]
        self.snapshot = {"schema_version": 1, "issues": {"items": project_issues(self.raw, self.plan)},
                         "project": {"items": []}}

    def test_catalog_preserves_original_scope(self):
        validate_plan(self.plan)
        self.assertEqual([t["number"] for t in self.plan["tasks"]], list(range(1, 29)))
        self.assertEqual([sum(t["phase"] == p for t in self.plan["tasks"]) for p in range(6)], [4, 7, 8, 3, 4, 2])

    def test_pr_is_not_a_29th_task_and_private_body_is_removed(self):
        self.raw.append({**issue(29), "pull_request": {"url": "private"}})
        rows = project_issues(self.raw, self.plan)
        self.assertEqual(len(rows), 28)
        self.assertNotIn("PRIVATE_BODY", str(rows))

    def test_partial_and_duplicate_issue_responses_are_rejected(self):
        for raw in [self.raw[:-1], self.raw + [self.raw[0]]]:
            with self.assertRaises(ValueError):
                project_issues(raw, self.plan)

    def test_open_issues_do_not_imply_todo_or_zero_in_progress(self):
        rows = task_states(self.plan, self.snapshot)
        self.assertEqual(sum(r["status"] == "done" for r in rows), 1)
        self.assertEqual(sum(r["status"] == "unknown" for r in rows), 27)

    def test_cancellation_and_closed_without_reason_are_not_completion(self):
        self.snapshot["issues"]["items"][4]["state_reason"] = "not_planned"
        self.assertEqual(task_states(self.plan, self.snapshot)[4]["status"], "excluded")
        self.snapshot["issues"]["items"][4]["state_reason"] = None
        self.assertEqual(task_states(self.plan, self.snapshot)[4]["status"], "unknown")

    def test_project_issue_conflicts_are_visible(self):
        self.snapshot["project"]["items"] = [{"number": 1, "status": "done"}, {"number": 5, "status": "todo"}]
        rows = task_states(self.plan, self.snapshot)
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertTrue(rows[0]["conflict"])
        self.assertTrue(rows[4]["conflict"])

    def test_foreign_repository_pr_and_unknown_status_do_not_create_tasks(self):
        def item(kind, repo, number, status):
            return {"content": {"__typename": kind, "number": number, "repository": {"nameWithOwner": repo}},
                    "fieldValues": {"nodes": [{"name": status, "field": {"name": "Status"}}]}}
        raw = [item("Issue", self.plan["repository"], 1, "In Progress"),
               item("Issue", self.plan["repository"], 2, "Custom unknown value"),
               item("Issue", "elsewhere/repo", 3, "Done"),
               item("PullRequest", self.plan["repository"], 29, "Done")]
        rows = project_items(raw, self.plan)
        self.assertEqual([r["number"] for r in rows], [1, 2])
        self.assertEqual([r["status"] for r in rows], ["doing", "unknown"])

    def test_graphql_paginates_items(self):
        class Client(GitHub):
            calls = 0
            def api(self, endpoint, *args):
                self.calls += 1
                if self.calls == 2:
                    assert "cursor=next" in args
                return {"data": {"organization": {"projectV2": {"items": {
                    "nodes": [], "pageInfo": {"hasNextPage": self.calls == 1, "endCursor": "next"}}}}}}
        client = Client()
        self.assertEqual(client.project(self.plan), [])
        self.assertEqual(client.calls, 2)

    def test_graphql_truncated_fields_fail_instead_of_fabricating_status(self):
        class Client(GitHub):
            def api(self, *args):
                return {"data": {"organization": {"projectV2": {"items": {
                    "nodes": [{"fieldValues": {"pageInfo": {"hasNextPage": True}}}],
                    "pageInfo": {"hasNextPage": False}}}}}}
        with self.assertRaises(ValueError):
            Client().project(self.plan)

    def test_failure_keeps_last_success_and_other_sources_refresh(self):
        previous = {"project": {"status": "ok", "last_success_at": NOW,
                                "items": [{"number": 1, "status": "doing", "due_date": None}]}}
        raw = self.raw
        class Client:
            def issues(self, plan): return project_issues(raw, plan)
            def project(self, plan): raise FetchError("project_read_permission_required")
            def wix(self, plan): return wix_result()
        result, failures = refresh(self.plan, previous, Client(), "2026-10-24T16:00:00+00:00")
        self.assertEqual(failures, ["project"])
        self.assertEqual(result["project"]["items"], previous["project"]["items"])
        self.assertEqual(result["project"]["last_success_at"], NOW)
        self.assertEqual(result["issues"]["status"], "ok")
        self.assertEqual(previous["project"]["status"], "ok")

    def test_successful_source_requires_payload(self):
        snapshot = read_json(ROOT / "data/snapshot.json")
        snapshot["wix"] = {k: v for k, v in snapshot["wix"].items()
                           if k in {"status", "attempted_at", "last_success_at", "error"}}
        with self.assertRaises(ValueError):
            validate_snapshot(snapshot, self.plan)

    def test_invalid_refresh_retains_valid_wix_cache(self):
        previous = {"wix": {"status": "ok", "attempted_at": NOW,
                            "last_success_at": NOW, "error": None, **wix_result()}}
        raw = self.raw
        class Client:
            def issues(self, plan): return project_issues(raw, plan)
            def project(self, plan): return []
            def wix(self, plan): return {"data": {}}
        result, failures = refresh(self.plan, previous, Client(), "2026-10-24T16:00:00+00:00")
        self.assertEqual(failures, ["wix"])
        self.assertEqual(result["wix"]["data"], previous["wix"]["data"])
        self.assertEqual(result["wix"]["last_success_at"], NOW)
        self.assertEqual(result["issues"]["status"], "ok")
        self.assertEqual(result["project"]["status"], "ok")

    def test_success_cannot_retain_error_message(self):
        snapshot = read_json(ROOT / "data/snapshot.json")
        snapshot["issues"]["error"] = "github_request_failed"
        with self.assertRaises(ValueError):
            validate_snapshot(snapshot, self.plan)

    def test_public_export_is_not_dns_or_authenticated_export_completion(self):
        raw = copy.deepcopy(WIX)
        raw["snapshot_folder"] = "PRIVATE_PATH"
        raw["dns_records"] = "PRIVATE_DNS"
        projected = project_wix(raw)
        self.assertTrue(projected["all_discovered_urls_exported"])
        self.assertFalse(projected["authoritative_wix_export_complete"])
        self.assertFalse(projected["dns_zone_export_complete"])
        self.assertEqual(projected["media_download_scope"], "sample")
        self.assertNotIn("PRIVATE", str(projected))

    def test_inconsistent_export_data_rejected(self):
        raw = copy.deepcopy(WIX)
        raw["downloaded_images"] += 1
        with self.assertRaises(ValueError): project_wix(raw)

    def test_done_tickets_alone_do_not_pass_a_gate(self):
        rows = [{"number": 5, "status": "done", "conflict": False}]
        gate = {"issues": [5], "verification": {"status": "pending"}}
        self.assertEqual(gate_state(gate, rows)[0], "pending")

    def test_passed_gate_requires_reviewed_evidence_and_approval(self):
        gate = self.plan["phases"][4]["gates"][1]
        gate["verification"] = {"status": "passed", "url": "https://github.com/modocai/fevercoach-website/issues/24",
                                "checked_at": NOW, "reviewer": "someone"}
        with self.assertRaises(ValueError): validate_plan(self.plan)
        gate["verification"]["reviewer"] = "MC"
        validate_plan(self.plan)

    def test_missing_measurements_are_not_zero(self):
        baseline = read_json(ROOT / "data/baselines.json")
        validate_baselines(baseline)
        next(r for r in baseline["lighthouse"] if r["status"] == "pending")["performance"] = 0
        with self.assertRaises(ValueError): validate_baselines(baseline)

    def test_checked_in_data_and_public_urls(self):
        validate_snapshot(read_json(ROOT / "data/snapshot.json"), self.plan)
        self.assertFalse(safe_url("javascript:alert(1)"))
        self.assertFalse(safe_url("https://token:secret@example.com"))

    def test_baseline_targets_must_be_numeric(self):
        baseline = read_json(ROOT / "data/baselines.json")
        baseline["targets"]["performance"] = '<script>alert(1)</script>'
        with self.assertRaises(ValueError): validate_baselines(baseline)


if __name__ == "__main__":
    unittest.main()
