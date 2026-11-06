# Issue snapshot refresh — November 5, 2026 (Chicago)

The published dashboard was displaying nine completed issues from the October 31 snapshot. GitHub Issues now confirms eleven completed issues out of the same approved twenty-eight: **39%** when rounded for the display.

## Sources and scope

- Website issue states were read through the connected GitHub API on November 6 UTC. Only the existing public allowlist (number, state/reason, assignee login and update time) was retained.
- Project #11's twenty-eight rows and actual Status values were read through its authenticated browser UI at 2026-11-06 04:35:40 UTC. This is a manual observation; it does not verify an automation credential or change its scope.
- Completed: #1, #2, #3, #5, #6, #11, #12, #13, #15, #17, #18.
- Open: seventeen. The observed Project statuses are two In Progress (#16 and #19) and fifteen Todo. No statuses were inferred from issue text or edited to increase progress.
- Wix export measurements, their timestamps and source review state remain unchanged. The separate content comparison remains the November 1 CMS-connected Preview measurement (46.6%), not production cutover completion.

The generated HTML uses the existing calculation and template. This refresh does not activate the scheduled publisher or change the separate daily-notice PR #10. Automatic publishing is still waiting for the reviewed website-main summary and the activation/Actions checks being coordinated by the dashboard owner.

## Validation

- The data validator and `python scripts/build_dashboard.py --check` pass; both generated entrypoints match the source data.
- Local Windows execution ran 107 unit tests: 105 passed and two symbolic-link fixture setups require a Windows privilege unavailable on this machine. The unchanged Linux CI suite must pass before publication.
- Inspect the pull request Checks and the published page for the final CI and deployment result.
