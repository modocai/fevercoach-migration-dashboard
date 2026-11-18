# Root-sitemap original-image audit — 2026-11-17 Chicago

This is a read-only diagnostic for issue #15 and PR #16. It does not change
the accepted dashboard metric or establish a site completion/visual score.

## Fixed scope and observations

- All **1,359 root-sitemap URL pairs**: 1,330 English blog URLs
  and 29 other URLs. Spanish/Korean alternate inventories are not included.
  The source inventory was identical before and after the run, and matches
  every source URL in PR #14 at `0b30e8127addc2cb7c291485bb65b9c6e19724bc`.
- Started 2026-11-18T05:19:59.438517+00:00; finished 2026-11-18T05:58:11.044268+00:00.
- **1,335 successful page comparisons; 24 failures**, all retained with zero credit.
- **2,370 distinct original URLs** have fetched Wix/CMS bytes with equal SHA-256
  and a responding target image reference on 1,321 pages
  (1,321 blog pages). Repeated hashes per original URL are consistent.
- Missing CMS record lookups: 0. This covers records reached by this audit;
  it is not a claim that every image in every language or every optimizer URL was checked.
- Same run, same denominator: legacy text/displayed-byte image calculation
  **47.18850035%**; separate text/verified-original diagnostic
  **81.11430453%**. Both retain 50:50 text/image weights,
  blank candidates and duplicate slots. This is a method comparison, not a new official score.

The existing PR #14 accepted-method measurement is still **47.28982143%**.
The live dashboard currently holds its earlier 47.2% measurement. Neither
is overwritten by this report. Transport timing and this diagnostic's bounded
fetcher can also produce different failures; its legacy side is not a republished
`compare_content.py` report.

## Failures and follow-up

Initial media error counts: `{"cms_original_missing_or_hash_mismatch": 1, "source_original_unavailable": 6}`.
The summary lists error URLs/counts rather than silently dropping them.
Six early media-error pages were independently retried; all six then responded
with matching originals and no media errors. The failed preschool vision blog
page also passed a separate retry. Initial rows and both initial percentages
remain unchanged. These retries show the sampled failures are not proof of
persistently missing or different stored files; other initial failures retain
their unresolved status.

One later page still references `https://static.wixstatic.com/media/undefined`
in the Wix source. Its original request is unavailable (HEAD HTTP 403), and
a separate exact CMS lookup returns no record. This is an invalid source
candidate, not a verified missing migrated original. It remains without credit.
The zero missing-record count above applies only to lookups reached after a
successful original fetch; this later follow-up is reported separately.

Next.js image optimizer URLs are still not inferred back to CMS metadata.
Consequently, homepage/blog-index zero original matches do not establish missing
storage. File identity and live response checks do not verify derivative pixels,
crop, layout, headers/footers, or visual similarity. A full rendered comparison
and separate alternate-language coverage remain necessary.

## Evidence and reproduction

The adjacent JSON contains aggregates, error locations, run provenance, and
SHA-256 fingerprints. Full per-image observations and image bodies are not
uploaded in this follow-up; image bodies were only hashed in memory.

- Diagnostic method script SHA-256: `4d411588a0839b476726eca62bae9821cf0f082287977e33ba4667f9b3154155`.
- Full local report SHA-256: `3e7884b68ffec3698e24c495bde6dc49925f4e14ab6a38655e5be753ef5a9651`.
- Fixed sorted input JSON SHA-256: `c36c3bae1fff9913ca6abd640141650cd85ec3c87c3f38f2e8aa0593618c3fe0`.

To recreate the fixed input, use `results[].source_url` from
[PR #14's fixed comparison report](https://github.com/modocai/fevercoach-migration-dashboard/blob/0b30e8127addc2cb7c291485bb65b9c6e19724bc/data/content-comparison.json),
sort the URLs, and save `json.dumps(urls, indent=2)` as UTF-8 without a trailing
newline. Verify 1,359 unique entries and the input fingerprint above. Then run:

```sh
python3 scripts/audit_image_assets.py \
  --urls /tmp/root-inventory.json \
  --source-origin https://www.fevercoach.us \
  --target-origin https://fevercoach-website.vercel.app \
  --cms-origin https://fevercoach-cms-staging-891309230443.us-east1.run.app \
  --output /tmp/root-image-assets.json
```

The unchanged auditor was run with a local resumable wrapper: first four page
workers, then eight, retaining the first 368 completed rows. Each auditor image
pool uses at most six workers and each request has a 30-second total deadline
and 20 MiB response limit. First-stage counters are a lower bound, not an exact
whole-run network total; resumed-stage counters are recorded separately.
No authenticated API or remote write was used for this audit. Reruns can differ
if content or responses change; never overwrite this dated evidence silently.

Validation independently checked exact inventory coverage/uniqueness, finite
bounded scores, zero failed rows, recomputed means and original-hash consistency.
The status remains `diagnostic_only`, rejected by the dashboard publication
validator. Adopting a main metric still requires review. No formula, denominator,
generated HTML, workflow, production setting or live score is changed here.
