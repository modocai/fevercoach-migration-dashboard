# Content comparison refresh — 2026-11-17 Chicago

The unchanged comparison algorithm measured **47.289821429670454%**, displayed
as **47.2%** under the existing floor-to-one-decimal rule. All **1,359 source
URLs** remain in the denominator, including **21 error rows scored zero**.
This is not a 50% content result or a production cutover claim.

The full scan finished at 2026-11-18 03:00:33 UTC against
https://fevercoach-website.vercel.app. Its before/after Wix root sitemap lists
were identical. The initial result was 47.25364051759195% with 22 errors.
Six newly public posts were imported during this scan. At 03:15:16 UTC, only
the two affected English URLs in this inventory were rechecked using the same
comparator. One cached 404 recovered; the other score did not change. The report
retains the full scan timestamp and records the later check separately.
This is a live sequential measurement, not a transactional snapshot or a second
complete scan. A stable URL list does not imply unchanged page bodies.

## Scope and reproducibility

- Source: https://www.fevercoach.us/sitemap.xml and all listed child sitemaps.
- Inventory: 1,330 English posts and 29 other URLs. Spanish/Korean alternates
  are not enumerated by this root inventory.
- Text normalization, image byte hashing, 50:50 weighting, error behavior and
  rounding are unchanged. Retired pages, profiles and failures were not removed.
- The request adapter percent-encodes request paths, allows up to three attempts
  for transient errors, and uses four workers with a 30-second timeout.
- [Evidence JSON](content-measurement-2026-11-17.json) records the run statistics,
  comparator hash and both affected rows' before/after values.
- The November 13 measurement and its evidence remain in repository history and
  the existing November 13 evidence documents.

The separate [public post URL acceptance audit](https://github.com/modocai/fevercoach-website/issues/19#issuecomment-6967953033)
passed 3,820/3,820 English/Spanish/Korean URLs after one cached-404 recheck.
That audit proves HTTP/canonical/sitemap behavior; it is not a 100% text/image
or layout score, and it does not replace this report's denominator.

## Why imported images can still score zero

The existing method compares image response bytes from server-rendered HTML.
Wix emits tiny blurred AVIF loading images while the new site serves larger
JPEG/PNG derivatives of the migrated assets. Different bytes score zero even
when the source asset is the same. Empty source image slots also remain unmatched.

[Dashboard issue #15](https://github.com/modocai/fevercoach-migration-dashboard/issues/15)
tracks this measurement limitation. Any future asset-preservation or rendered
image comparison needs a separately reviewed, versioned method and regression
tests. This refresh does not change the metric to cross a percentage threshold.
