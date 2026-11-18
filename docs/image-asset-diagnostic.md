# Original image diagnostic (proposal, not a dashboard score)

Issue #15 found that the current server-HTML comparator gives zero image credit
when Wix's blurred loading AVIF and Payload's large JPEG represent the same
original asset. This tool makes the reason reviewable without replacing the
accepted comparison metric, altering the website to resemble a loading image,
or dropping failed URLs.

## What is verified

1. Parse the same article/main/body text and image candidates as the existing
   comparator. Preserve empty slots, responsive candidates, and duplicate
   occurrences. Fetch the displayed source and target image responses.
2. For a Wix media URL, fetch its untransformed original. Query the public CMS
   media API by that exact legacy source URL; only CMS file URLs are accepted.
3. Fetch the CMS original and require an exact SHA-256 match with the Wix
   original. A legacy ID, filename, source URL, or database claim alone earns
   no credit. The target HTML must reference that record's original or an
   explicitly recorded derivative, and that displayed file must also respond
   successfully with a nonempty image response.
4. Match verified original hashes as multisets, preserving all candidate slots.
   Missing images, mismatched originals, unavailable metadata, ambiguous records,
   and unsuccessful page requests cannot earn a match. Failed pages remain zero.

Non-Wix images may match by exact displayed bytes when hosted on the named
target/CMS origin. Wix images require the original/CMS proof above. A hotlinked
Wix image or a copy of only its loading-thumbnail bytes does not earn asset
preservation credit, even if the legacy byte comparator calls it a full match.
The CMS storage query `prefix=media` is accepted; other query parameters are
rejected. This version does not unwrap Next.js `/_next/image` URLs into CMS
metadata matches. Those candidates are still fetched and retained in the
denominator, but earn no original-asset credit through URL inference.

The report retains the legacy byte-based score next to the original-asset
diagnostic. Both combine text/images with the existing 50:50 weight only for
side-by-side analysis. `status=diagnostic_only` is deliberately rejected by
the dashboard's `validate_report`. This report cannot silently become the live
completion score.

## What this does not verify

This verifies original file preservation and live image references. It does not
compare derivative pixels, cropping, resolution quality, positions, responsive
layout, headers/footers, accessibility, SEO, or overall visual similarity. A
wrong derivative stored under a valid CMS record still requires a rendered
image/pixel audit. The asset diagnostic must not be labeled a visual score.

The input is an explicit list of URLs. A sample's score is not a full-site
percentage. Before accepting a replacement metric, MC/reviewers must decide
how asset preservation and rendered similarity are displayed separately, and
how language/home/general-page coverage is reported. Keep the old score and
method version visible during any change. Do not infer a 50% site milestone
from a diagnostic sample.

## Read-only invocation

```sh
python3 scripts/audit_image_assets.py \
  --urls docs/image-asset-sample-2026-11-17.urls.json \
  --source-origin https://www.fevercoach.us \
  --target-origin https://fevercoach-website.vercel.app \
  --cms-origin https://fevercoach-cms-staging-891309230443.us-east1.run.app \
  --output /tmp/image-asset-report.json
python3 -m unittest discover -s tests -p test_image_assets.py
```

No key is required. Python 3.9+ and the official curl command are required.
Each request and redirect is limited to the explicitly named HTTPS sites and
`static.wixstatic.com`, with a response-size limit and a total request deadline.
Redirects are validated before fetching, and curl never auto-follows them.
Image bodies are hashed in memory, not written into the repository. Reports
contain public URLs, hashes, counts, and classified errors, never response
bodies or raw network exception text.
Up to six image requests run concurrently. Identical URLs are fetched once
per cache entry; their repeated occurrences still count separately in scoring.

The committed sample is selected before measurement: home, download, privacy,
blog index, an approved retired product and a still-missing profile route; all
six latest imported language posts; one prior post per language chosen by the
lowest SHA-256 of its public path; and the original #15 reproduction page.
It is a regression sample, not a random population estimate. Failures remain
in the sample denominator.

## Review and rollout

The existing `compare_content.py`, dashboard data, generated HTML, workflow,
publication rules, and production configuration are unchanged by this proposal.
Review the regression tests and live sample first. A follow-up full inventory
audit and a rendered comparison are needed before adopting any new main metric.
