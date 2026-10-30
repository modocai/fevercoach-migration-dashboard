"""Synthetic inputs only; never call private APIs in tests or browser checks."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dashboard_data import ROOT, read_json
from public_dashboard import make_state, write_site
from sync_github import refresh

NOW = "2026-10-23T16:00:00+00:00"
REVISION = "a" * 40
PLAN = read_json(ROOT / "data/plan.json")


class SyntheticGitHub:
    def issues(self, plan):
        return [{"number": t["number"], "state": "open", "state_reason": None} for t in plan["tasks"]]

    def project(self, plan):
        return [{"number": t["number"], "status": "doing" if t["number"] == 1 else "todo", "due_date": None}
                for t in plan["tasks"]]

    def wix(self, plan):
        return {"data": {"schema_version": 1, "scope": "public_sitemap_snapshot",
                         "source": "https://www.fevercoach.us", "generated_at": NOW,
                         "discovered_urls": 3, "exported_urls": 2, "unique_referenced_images": 4,
                         "downloaded_images": 1, "images_not_downloaded_count": 3, "failed_url_count": 1,
                         "missing_url_count": 1, "media_error_count": 0, "all_discovered_urls_exported": False,
                         "all_referenced_images_downloaded": False, "authoritative_wix_export_complete": False,
                         "dns_zone_export_complete": False, "media_download_scope": "sample"},
                "source_sha": REVISION, "source_url": "https://github.com/example/example",
                "review_state": "main", "pr_url": None}


def fixture(now=NOW, generation=1, content_report=None):
    snapshot, failures = refresh(PLAN, {}, SyntheticGitHub(), now)
    assert not failures
    return make_state(snapshot, PLAN, REVISION, generation, now,
                      content_report if content_report is not None else {"status": "not_deployed"})


if __name__ == "__main__":
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    generation = int(sys.argv[2])
    report = {"status": "not_deployed"}
    if generation == 2:
        report = {"status": "measured", "generated_at": now,
                  "source_sitemap": "https://www.fevercoach.us/sitemap.xml",
                  "target_base_url": "https://example.invalid", "total_urls": 1,
                  "score_sum": 0.5, "percentage": 50.0,
                  "results": [{"source_url": "https://www.fevercoach.us/one",
                               "target_url": "https://example.invalid/one", "status": "ok",
                               "score": 0.5, "text_score": 0.5, "image_score": 0.5}]}
    write_site(Path(sys.argv[1]), fixture(now, generation, report), PLAN, read_json(ROOT / "data/baselines.json"))
