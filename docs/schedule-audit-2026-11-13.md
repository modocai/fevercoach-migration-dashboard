# Scheduled publication audit — 2026-11-13

The publisher works when invoked, but its configured 15-minute schedule is not
being observed in the available GitHub run history. Keep the current cron;
changing the minute expression is not an evidenced fix for this finding.

## Evidence

The [machine-readable audit](schedule-audit-2026-11-13.json) contains every
scheduled run returned since activation, with public run IDs and timestamps.
The request returned all 69 publisher runs, matching the API total count.

- All 27 scheduled runs after activation succeeded.
- Intervals between their creation timestamps range from 3.29 to 10.52 hours.
- `run_started_at` equals `created_at` for these runs. The multi-hour gaps are
  before recorded run creation, not multi-hour runner waits in these records.
- Latest sampled run: [43523189798](https://github.com/modocai/fevercoach-migration-dashboard/actions/runs/43523189798).
  Build ran 22:55:42–22:55:56 UTC; deployment ran 22:56:02–22:56:23 UTC.
- Default branch is `main`, workflow is active, the activation variable is
  `true`, and the main workflow contains `7,22,37,52 * * * *`.
- The recorded schedule actor still resolves to an existing GitHub account.
- Both publication environments allow only `main`; current published sources
  are healthy, and state/manifest/HTML agree.

The public dashboard revision remains `d40964e56cf17d6a91961e45177d9e44c4725016`.
Fresh publications without new dashboard commits confirm that collection and
deployment do not depend on a manual snapshot PR.

## Conclusion and limits

The evidence locates the gap before recorded scheduled-run creation. It does
not establish GitHub's internal cause or prove that every nominal trigger was
queued and dropped. Reading repository Actions policy settings returned HTTP
403, so administrator-only policy inspection remains unavailable here.

[GitHub's troubleshooting documentation](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
states that scheduled events can be delayed or dropped under load.
[GitHub's incident history](https://www.githubstatus.com/history) reports Actions
and webhook incidents overlapping part of the period. Those reports are
context, not proof that they explain all gaps in this repository.

Do not describe this as a guaranteed 15-minute refresh. Report the configured
interval together with the last successful collection time. The existing
browser notice warns when successful-source timestamps exceed 45 minutes.

## Decision

Keep the 15-minute cron and existing publication/security settings. No new
scheduler, credential, notification workflow, or speculative cron change is
included. The user chose analysis and measurement first on November 13.

If shorter dependable trigger intervals become required, an administrator can
take the run IDs and timestamps to GitHub Support. A separate proposal can
evaluate an external scheduler with dedicated least-privilege workflow-dispatch
authentication. A second GitHub cron job would share the same trigger dependency.

## Reproduce

```sh
gh api 'repos/modocai/fevercoach-migration-dashboard/actions/workflows/publish.yml/runs?per_page=100'
gh api repos/modocai/fevercoach-migration-dashboard/actions/runs/43523189798/jobs
```

If the API total exceeds the returned page size, paginate before drawing a new
conclusion. Compare scheduled events separately from manual and push events.
