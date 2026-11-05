# Preview content comparison, 2026-11-01

MC requested measuring the running CMS-connected Preview rather than retaining the pre-deployment baseline.

- Target: https://fevercoach-website-git-wix-cms-integration-fevecoach-team.vercel.app
- Deployment: `dpl_3uvQwyZTzfPtpZFGPxEgGUxV1Ws3` (Preview, not production)
- Source: https://www.fevercoach.us/sitemap.xml, including every child sitemap.
- Access: authenticated Vercel automation access. Deployment protection remains enabled. No credential is included in the report.
- Method: existing `compare_content.py` scoring, with an authenticated fetch adapter for the target host only. Full URL inventory, normalized server-rendered text, image byte hashes, and error pages retained in the denominator.
- Interpretation: content similarity on the Preview, not production cutover completion or a count of fully verified pages. Reencoded images can reduce scores despite appearing similar. Layout, SEO, and functional acceptance remain separate checks.

The saved report feeds both the dashboard and the currently scheduled Discord notice. Updating this measurement does not activate continuous crawling or merge the separate daily-notice PR #10.

## Result

- 1,321 URLs checked; 1,286 comparable pages; 35 target HTTP 404s confirmed on retry.
- Score: 46.69031299663424%, displayed as 46.6% using the existing floor-to-one-decimal rule.
- One non-ASCII path was percent-encoded before retry; it is included successfully.
- Image scores are near zero. A sampled article serves small Wix image variants on the source and larger CMS image files on the target; both fetched successfully but hashes differ. This score must not be interpreted as 53.4% of pages missing or as proof that images are absent.
- The current sitemap includes member profiles, store and older landing-page paths. These remain in the denominator rather than silently changing the project scope.
