# Content comparison refresh — 2026-11-13

The saved November 1 comparison was refreshed against the current main website
on its temporary Vercel domain. The result is **47.2% displayed**
(`47.25107514407258` before flooring), with all **1,357 URLs** retained.
This is a text/image comparison result, not production cutover completion.

## Target and scope

- Source: <https://www.fevercoach.us/sitemap.xml> and its child `<loc>` entries.
- Target: <https://fevercoach-website.vercel.app>, connected to the existing
  staging CMS. No operating-domain or Wix shutdown change is included.
- Website main revision: `b853ef132923ea9ad021a64e83ff8ffccc2313f0`.
- Vercel deployment: `dpl_V8dNfPJoKBKapNk3Sr5FjYf8Ea55`, READY; the alias still
  resolved to this deployment after the measurement.
- Measurement window: November 13, 23:12:35–23:40:02 UTC.
- The sitemap inventory was identical before and after measurement: 1,357 URLs.
  Compared with the prior report, 36 URLs were added and none removed.
- This inventory contains 1,328 English `/post/` URLs and 29 other URLs. It
  does not enumerate the Korean/Spanish alternate-language URLs. It must not
  be described as a comparison of all 3,814 multilingual CMS posts.

The prior report displayed 46.6% over 1,321 URLs against an older Preview alias.
Both the inventory and target changed, so the difference is not a controlled
same-page, same-target measure of implementation progress.

## Errors and method

Every row was validated and every error row was requested again:

| Rechecked result | URLs |
| --- | ---: |
| Target HTTP 404 | 20 |
| Target HTTP 410 (`/product-page/inp`) | 1 |
| Source body not extractable; target HTTP 200 | 1 |
| Total zero-score error rows | 22 |

The unextractable source is `/post/child-low-grade-fever-flu-test`. Its HTML
returns 200, but the existing parser reports `empty_content`; that does not
prove the rendered page is blank. All 22 sources returned HTTP 200 on recheck.
No error row recovered to a parseable source and destination pair.

The 410 remains in the denominator under the existing rules. Approved retired
pages and other exclusions need a separately reviewed scope change; they were
not silently removed to improve this result.

The existing `scripts/compare_content.py` and scoring remain unchanged:
normalized body/article text comparison and image-byte hashes; text/image
50:50 when either page has images, otherwise text 100%; failed rows score zero.
Requests used four workers, a 30-second timeout, and percent-encoded non-ASCII
request paths while preserving report URLs. The request adapter allowed up to
three attempts for transient 429/5xx/transport failures; **zero retries were
needed**. One image request returned 403 and remained unmatched under the
existing image-error behavior. No credential or protection bypass was used.

[Machine-readable evidence](content-measurement-2026-11-13.json) includes the
inventory delta, run statistics, comparison-script hash and every error recheck.
The report is a sequential live measurement, not a transactional CMS snapshot.
Stable URL inventory does not guarantee that every page body stayed unchanged.
Layout, navigation, SEO, scheduling/publishing functionality and multilingual
coverage still require their own verification.

## Integration and validation

The refreshed report and both generated HTML entrypoints are included. A
minimal notification change retains the existing Preview-specific explanation
and adds a general cutover disclaimer for measurements against other targets.
It does not send a Discord message or change delivery behavior. Open PR #10
must preserve this disclaimer when it is integrated.

A local publication build fetched approved main Issues, Project and Wix data
successfully, using the same publication boundary as the scheduled publisher:
`state.json` was 445,506 bytes (limit 524,288); the complete artifact was
977,319 bytes (limit 2,097,152). The actual candidate rendered 47.2% and 12/28
completed issues (43%) without overflow or browser errors at 1440px and 1280px.
The separate synthetic auto-refresh suite passed 30 browser assertions.

All 122 unit tests passed under Python 3.12.14, and generated HTML consistency
and whitespace checks passed. An initial run with macOS/Xcode Python 3.9 hit
two existing HTTPError fixture failures in `tempfile`; the same two failures
were reproduced from unchanged main. No application code was changed to work
around that runtime. PR CI uses Python 3.11 and must pass before
merge.

The Blog summary is a separate upstream change in
[website PR #38](https://github.com/modocai/fevercoach-website/pull/38). Its
published/draft/scheduled counts are verified backup counts, not this report's
comparison denominator. Once that PR is merged, the next successful publisher
run reads it without a dashboard snapshot commit. This report itself becomes
public only after the dashboard PR is reviewed, merged and published.

The 15-minute cron, activation settings, scoring weights, issue catalog,
layout, stored issue snapshot and failure-retention mechanics are unchanged.
Scheduled publication refreshes source status; it does not rerun the full
text/image comparison. See the [schedule audit](schedule-audit-2026-11-13.md)
for the observed trigger gaps and their remaining uncertainty.
