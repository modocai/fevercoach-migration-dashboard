#!/usr/bin/env python3
"""Read-only Actions preflight: no Discord delivery or Pages publication."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

from dashboard_data import ROOT, read_json, require, validate_plan
from public_content import public_content
from public_dashboard import PublicGitHub, make_state, write_site
from publish_dashboard import REPOSITORY, previous_state
from sync_github import refresh


@contextmanager
def source_credentials():
    """Keep the workflow token for receipt metadata; scope source access narrowly."""
    token = os.environ.get('DASHBOARD_SOURCE_TOKEN')
    require(bool(token), 'Dedicated source credential required')
    previous = os.environ.get('GH_TOKEN')
    os.environ['GH_TOKEN'] = token
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('GH_TOKEN', None)
        else:
            os.environ['GH_TOKEN'] = previous


def check_revision(revision):
    result = subprocess.run(
        ['gh', 'api', f'repos/{REPOSITORY}/commits/main', '--jq', '.sha'],
        capture_output=True, text=True, timeout=30)
    require(result.returncode == 0 and result.stdout.strip() == revision,
            'Default branch changed or could not be verified')


def check_notice(plan, report, now):
    # Import only reviewed main code after PR #10 is merged; never fetch PR code.
    try:
        notice = importlib.import_module('daily_notice')
    except ModuleNotFoundError as error:
        if error.name != 'daily_notice':
            raise
        print('FAIL: daily_notice.py is not available on this revision; merge reviewed PR #10 first.')
        return False
    previous = notice.restore_receipt(REPOSITORY)
    print('receipt: ' + ('existing record validated' if previous else 'none; initial-run path only'))
    with source_credentials():
        snapshot = notice.collect(plan, PublicGitHub(), now)
    healthy = True
    for name in ('issues', 'project'):
        ok = snapshot[name]['status'] == 'ok'
        print(f'{name}: ' + ('PASS' if ok else 'FAIL'))
        healthy = healthy and ok
    if not healthy:
        return False
    message, _ = notice.compose(plan, snapshot, public_content(report), previous, now)
    require(0 < len(message) <= 1950, 'Invalid notice size')
    print('PASS: live sources, notice composition and receipt lookup.')
    print('Discord delivery and receipt persistence were NOT exercised.')
    return True


def check_publication(plan, report, baselines, revision, nonce, now):
    previous = previous_state(plan, nonce)
    # Only a disposable build. This number never enters the publisher's sequence.
    generation = previous['generation'] + 1 if previous else 1
    with source_credentials():
        snapshot, failures = refresh(plan, previous['snapshot'] if previous else {},
                                     PublicGitHub(), now)
    for name in ('issues', 'project', 'wix'):
        print(f'{name}: ' + ('FAIL' if name in failures else 'PASS'))
    # Retained data is appropriate for an operating site, not an activation pass.
    if failures:
        print('FAIL: publication requires fresh successful reads of all three sources.')
        return False
    state = make_state(snapshot, plan, revision, generation, now, report)
    with tempfile.TemporaryDirectory(prefix='dashboard-preflight-') as directory:
        write_site(Path(directory) / 'site', state, plan, baselines)
    print('PASS: approved sources, public state and disposable site artifact validation.')
    print('No artifact was uploaded and no Pages deployment was performed.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=('notice', 'publication'))
    args = parser.parse_args()
    try:
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Unexpected repository')
        require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'Main required')
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'Manual run required')
        require(bool(os.environ.get('GH_TOKEN')), 'Workflow credential required')
        require(bool(os.environ.get('DASHBOARD_SOURCE_TOKEN')), 'Source credential required')
        revision = os.environ.get('GITHUB_SHA', '')
        require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'Invalid revision')
        check_revision(revision)
        plan = read_json(ROOT / 'data/plan.json')
        validate_plan(plan)
        report = read_json(ROOT / 'data/content-comparison.json')
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if args.mode == 'notice':
            passed = check_notice(plan, report, now)
        else:
            nonce = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
            passed = check_publication(plan, report, read_json(ROOT / 'data/baselines.json'),
                                       revision, nonce, now)
        check_revision(revision)
        return 0 if passed else 1
    except Exception:
        # API responses, exception bodies, credentials and receipt IDs stay out of logs.
        print('FAIL: preflight stopped. Check source permissions, approved main inputs, '
              'public state and the current main revision. No delivery or deployment attempted.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
