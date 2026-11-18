# Public original-image sample — 2026-11-17 Chicago

This is a diagnostic sample for issue #15, not a replacement for the dashboard
metric and not evidence that the whole website has reached 50%.

The explicit 16-URL input was fixed before measurement. It includes home,
download, privacy, blog index, two known failed routes, all six latest imported
en/es/ko posts, one prior post per language selected by the lowest SHA-256 of
its public path, and the original issue reproduction post.

## Observed results

- Finished: 2026-11-18 03:52:41 UTC (11/17 Chicago).
- 16 URL pairs: 14 successful comparisons and 2 failed page comparisons.
  The retired `/product-page/inp` and missing `/profile/admin/profile` remain
  in the denominator with zero credit.
- The same sample's legacy text/byte-image calculation: **42.58589179%**.
- Separate text/verified-original diagnostic: **59.17680088%**.
- Ten blog pages reference 16 distinct originals whose actual Wix and CMS
  bytes match by SHA-256. The displayed CMS derivatives also respond with
  nonempty image bodies. Public URLs and hashes are in the JSON report.
- Six new posts each retain three blank source-image candidates. Each has
  one verified image pair out of five combined candidate slots, so the
  original-asset component is 40%, not 100%.
- Four older blog posts each retain three blank candidates. Four verified
  pairs across eleven combined slots give 72.72727273%, not 100%.
- Home/download and the blog index receive no original-asset match through
  Next.js optimizer URL inference, which this version does not implement.
  Their candidates remain in the denominator. This is not a claim that
  their images are missing from storage.
- 780 public requests, 224,578,304 received bytes, 30-second total deadline
  per request, at most six concurrent image requests. No authenticated API,
  private content, writes, or stored image bodies were used.

## Interpretation and limitations

The 42.59% and 59.18% values compare methods on these same 16 URLs only.
Neither is the site's 1,359-URL score. The current unchanged-formula full
inventory result remains **47.28982143%**, documented separately in PR #14.
Do not replace that report with this sample or extrapolate from it.

The original-file check proves preservation and a live derivative reference;
it does not prove that derivative pixels, cropping, layout or header/footer
match the old website. The report deliberately has `status=diagnostic_only`
and is rejected by the existing dashboard publication validator.

Some optimizer candidates timed out during public HTTP reads. In a follow-up
browser check, the tested team-profile image's selected 828px candidate
loaded successfully (natural width 820). A separate 750px HTTP read timed
out after receiving only part of a 200 response. This is not sufficient to
declare a general rendering defect; no website code was changed on that basis.

## Reproduction and validation

Use the invocation in `image-asset-diagnostic.md` with the committed URLs.
The exact script used for this run has SHA-256:
`4d411588a0839b476726eca62bae9821cf0f082287977e33ba4667f9b3154155`.

The new module has 22 regression tests covering original-byte mismatches,
broken images, missing slots, duplicate occurrences, CMS metadata and URL
validation, hotlinks, copied placeholders, error denominators, and refusal
to publish a diagnostic report as an accepted dashboard metric. The final
PR's Linux CI must run the complete repository suite before merge.

Acceptance of a new main metric needs review, full-inventory coverage and a
separate rendered comparison. No weights, denominator, live dashboard data,
workflow or production settings are changed by this proposal.
