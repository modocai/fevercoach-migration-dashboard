import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_dashboard import render
from dashboard_data import ROOT, read_json


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.plan = read_json(ROOT / "data/plan.json")
        self.snapshot = read_json(ROOT / "data/snapshot.json")
        self.baselines = read_json(ROOT / "data/baselines.json")

    def render(self):
        return render(self.plan, self.snapshot, self.baselines)

    def test_all_tasks_and_links_exist_without_javascript(self):
        doc = Document(self.render())
        rows = [attrs for tag, attrs in doc.tags if tag == "article" and "row" in attrs.get("class", "").split()]
        self.assertEqual(len(rows), len(self.plan["tasks"]))
        self.assertFalse(any("hidden" in attrs for attrs in rows))
        titles = [attrs for tag, attrs in doc.tags if tag == "a" and attrs.get("class") == "title"]
        self.assertEqual({attrs["href"] for attrs in titles},
                         {f'https://github.com/{self.plan["repository"]}/issues/{t["number"]}' for t in self.plan["tasks"]})

    def test_output_deterministic_and_both_entrypoints_identical(self):
        self.assertEqual(self.render(), self.render())
        self.assertEqual((ROOT / "index.html").read_bytes(), (ROOT / "migration-dashboard.html").read_bytes())

    def test_external_text_is_not_interpreted_as_markup_or_script(self):
        self.plan["tasks"][0]["title"] = '<script>alert("x")</script>'
        self.snapshot["issues"]["items"][0]["assignees"] = ['<img src=x onerror=alert(1)>']
        output = self.render()
        self.assertNotIn('<script>alert', output)
        self.assertNotIn('<img src=x', output)
        self.assertIn('&lt;script&gt;', output)

    def test_failed_sources_without_data_render_unknown(self):
        for name in ["issues", "project", "wix"]:
            self.snapshot[name] = {"status": "error", "attempted_at": "2026-10-23T16:00:00Z",
                                   "last_success_at": None, "error": "github_request_failed"}
        output = self.render()
        self.assertEqual(output.count('data-status="unknown"'), 28)
        self.assertIn('자료 대기 · 수집 결과', output)
        self.assertNotIn('data-status="todo"', output)

    def test_stale_snapshot_and_conflict_are_disclosed(self):
        self.snapshot["issues"]["status"] = "error"
        self.snapshot["issues"]["error"] = "github_request_failed"
        self.snapshot["issues"]["items"][0]["state"] = "open"
        self.snapshot["project"]["items"] = [{"number": 1, "status": "done", "due_date": None}]
        output = self.render()
        self.assertIn('갱신 실패 · 이전 기록 유지', output)
        self.assertIn('class="conflict"', output)

    def test_no_external_runtime_requests_or_credentials(self):
        doc = Document(self.render())
        self.assertFalse(any(tag == "script" and attrs.get("src") for tag, attrs in doc.tags))
        for forbidden in ['fetch(', 'localStorage', 'GH_TOKEN', 'GITHUB_TOKEN', 'snapshot_folder']:
            self.assertNotIn(forbidden, self.render())


if __name__ == "__main__":
    unittest.main()
