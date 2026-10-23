import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_lighthouse import summarize


class LighthouseTests(unittest.TestCase):
    def setUp(self):
        self.report = {"runtimeError": None, "runWarnings": [], "finalDisplayedUrl": "https://www.fevercoach.us/",
                       "fetchTime": "2026-10-23T06:22:59Z", "lighthouseVersion": "12.6.1",
                       "configSettings": {"formFactor": "mobile", "throttlingMethod": "simulate", "throttling": {}},
                       "categories": {"performance": {"score": .72}},
                       "audits": {"largest-contentful-paint": {"numericValue": 5092.4865},
                                  "network-requests": {"details": {"items": [{"resourceType": "Document",
                                      "url": "https://www.fevercoach.us/", "statusCode": 200}]}}}}

    def test_valid_report_keeps_units_and_provenance(self):
        result = summarize(self.report, "home", "hash")
        self.assertEqual(result["performance"], 72)
        self.assertEqual(result["lcp_seconds"], 5.092)
        self.assertEqual(result["raw_report_sha256"], "hash")

    def test_failed_or_warning_run_cannot_be_imported(self):
        for field, value in [("runtimeError", {"code": "NO_FCP"}), ("runWarnings", ["warning"])]:
            report = copy.deepcopy(self.report)
            report[field] = value
            with self.assertRaises(ValueError): summarize(report, "home", "hash")

    def test_error_page_and_wrong_device_cannot_be_baselines(self):
        self.report["audits"]["network-requests"]["details"]["items"][0]["statusCode"] = 404
        with self.assertRaises(ValueError): summarize(self.report, "home", "hash")
        self.report["configSettings"]["formFactor"] = "desktop"
        with self.assertRaises(ValueError): summarize(self.report, "home", "hash")


if __name__ == "__main__":
    unittest.main()
