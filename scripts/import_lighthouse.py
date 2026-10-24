#!/usr/bin/env python3
"""Import two successful mobile Lighthouse reports as dated, auditable baseline summaries."""
import argparse
import hashlib
from pathlib import Path
from urllib.parse import quote, urlsplit

from dashboard_data import ROOT, read_json, require, timestamp, validate_baselines, write_json


def summarize(report, page, raw_hash):
    require(not report.get("runtimeError") and not report.get("runWarnings"), "Lighthouse run needs review")
    settings = report["configSettings"]
    require(settings["formFactor"] == "mobile" and settings["throttlingMethod"] == "simulate",
            "baseline requires mobile simulated throttling")
    url = report["finalDisplayedUrl"]
    parsed = urlsplit(url)
    require(parsed.scheme == "https" and parsed.netloc == "www.fevercoach.us" and not parsed.query,
            "unexpected baseline URL")
    require(parsed.path in {"", "/"} if page == "home" else parsed.path.startswith("/post/"),
            "wrong baseline page type")
    documents = report["audits"]["network-requests"]["details"]["items"]
    require(any(i.get("resourceType") == "Document" and i.get("url") == url and i.get("statusCode") == 200
                for i in documents), "main document must return HTTP 200")
    timestamp(report["fetchTime"])
    score = report["categories"]["performance"]["score"]
    lcp = report["audits"]["largest-contentful-paint"]["numericValue"]
    require(type(score) in {int, float} and 0 <= score <= 1, "invalid performance score")
    require(type(lcp) in {int, float} and 0 <= lcp < float("inf"), "invalid LCP")
    return {"page": page, "url": url, "measured_at": report["fetchTime"],
            "lighthouse_version": report["lighthouseVersion"], "performance": round(score * 100),
            "lcp_seconds": round(lcp / 1000, 3), "form_factor": settings["formFactor"],
            "throttling_method": settings["throttlingMethod"], "throttling": settings["throttling"],
            "runs": 1, "http_status": 200, "warnings": [], "raw_report_sha256": raw_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--post", type=Path, required=True)
    parser.add_argument("--evidence-ref", default="main", help="GitHub ref containing the evidence file")
    args = parser.parse_args()
    reports = [summarize(read_json(path), page, hashlib.sha256(path.read_bytes()).hexdigest())
               for page, path in [("home", args.home), ("post", args.post)]]
    require(len({r["lighthouse_version"] for r in reports}) == 1, "use the same Lighthouse version")
    dates = {r["measured_at"][:10] for r in reports}
    require(len(dates) == 1, "baseline runs must share the same UTC date")
    date = next(iter(dates))
    filename = f"docs/lighthouse-{date}.json"
    evidence_url = ("https://github.com/modocai/fevercoach-migration-dashboard/blob/"
                    + quote(args.evidence_ref, safe="") + "/" + filename)
    data = read_json(ROOT / "data/baselines.json")
    for summary in reports:
        record = next(r for r in data["lighthouse"] if r["kind"] == "baseline" and r["page"] == summary["page"])
        record.update({"status": "measured", "url": summary["url"], "measured_on": date,
                       "performance": summary["performance"], "lcp_seconds": summary["lcp_seconds"],
                       "conditions": f'Lighthouse {summary["lighthouse_version"]} · 모바일 · simulated throttling · 페이지별 1회 · 실험실 측정',
                       "evidence_url": evidence_url})
    validate_baselines(data)
    write_json(ROOT / filename, {"schema_version": 1,
                                "note": "Each page was measured once, sequentially. Lab measurements are not field data or proof of migration impact.",
                                "reports": reports})
    write_json(ROOT / "data/baselines.json", data)
    print(f"Recorded two mobile baseline reports in {filename}")


if __name__ == "__main__":
    main()
