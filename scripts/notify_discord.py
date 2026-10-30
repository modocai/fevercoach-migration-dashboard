#!/usr/bin/env python3
"""Send the dashboard's saved content completion percentage to Discord."""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from content_metric import validate_report
from dashboard_data import ROOT, read_json, task_states, validate_plan, validate_snapshot

DASHBOARD_URL = 'https://modocai.github.io/fevercoach-migration-dashboard/'
WEBHOOK = re.compile(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+\Z')


class NotificationError(Exception):
    """A safe error that never includes a webhook URL or response body."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_message(report, plan, snapshot):
    validate_report(report)
    validate_plan(plan)
    validate_snapshot(snapshot, plan, sources=('issues', 'project'))
    rows = task_states(plan, snapshot)
    done = sum(row['status'] == 'done' for row in rows)
    total = len(rows)
    percentage = done / total * 100 if total else 0
    issue_line = f'**이슈 완료율: {percentage:.0f}% ({done}/{total})**'
    source = snapshot['issues']
    if not source.get('last_success_at'):
        issue_line = '**이슈 완료율: 미확인**'
    elif source['status'] == 'error':
        issue_line += ' · 갱신 실패, 이전 기록 기준'
    if report['status'] == 'not_deployed':
        label, detail = '0', '새 사이트 배포 전'
    elif report['status'] == 'measured':
        # Match the dashboard: incomplete values must never round up to 100%.
        label = ('100.0' if all(row['score'] == 1 for row in report['results'])
                 else f'{math.floor(report["percentage"] * 10) / 10:.1f}')
        date = datetime.fromisoformat(report['generated_at'].replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('Measurement timestamp must include timezone')
        detail = f'저장된 측정 기준: {date.isoformat()}'
    else:
        raise ValueError('No completion measurement or explicit pre-deployment baseline')
    return f'**FeverCoach 이관 완성률: {label}%**\n{issue_line}\n{detail}\n{DASHBOARD_URL}'


def send_notice(webhook_url, message, opener=None, sleep=time.sleep):
    if not isinstance(webhook_url, str) or not WEBHOOK.fullmatch(webhook_url):
        raise NotificationError('A valid Discord engineering webhook is required')
    opener = opener or build_opener(NoRedirects()).open
    payload = json.dumps({'content': message, 'allowed_mentions': {'parse': []}}, ensure_ascii=False).encode('utf-8')
    request = Request(webhook_url + '?wait=true', data=payload, method='POST',
                      headers={'Content-Type': 'application/json', 'User-Agent': 'FeverCoach-Dashboard/1.0'})
    for attempt in range(3):
        try:
            with opener(request, timeout=20) as response:
                if response.status != 200:
                    raise NotificationError('Discord did not confirm the message')
                result = json.loads(response.read(65536))
                if not isinstance(result, dict) or not result.get('id'):
                    raise NotificationError('Discord did not return a message ID')
                return str(result['id'])
        except HTTPError as error:
            if error.code != 429 or attempt == 2:
                error.close()
                raise NotificationError(f'Discord request failed (HTTP {error.code})') from None
            try:
                data = json.loads(error.read(65536))
                delay = float(data.get('retry_after', error.headers.get('Retry-After')))
                if not math.isfinite(delay) or not 0 <= delay <= 60:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise NotificationError('Discord rate limit requires a later retry') from None
            finally:
                error.close()
            sleep(delay + .1)
        except NotificationError:
            raise
        except Exception:
            # Delivery may have succeeded before timeout; do not blindly retry.
            raise NotificationError('Discord delivery was not confirmed; not retried to avoid duplicates') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path(__file__).resolve().parents[1] / 'data/content-comparison.json')
    parser.add_argument('--plan', type=Path, default=ROOT / 'data/plan.json')
    parser.add_argument('--snapshot', type=Path, default=ROOT / 'data/snapshot.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding='utf-8'))
        message = make_message(report, read_json(args.plan), read_json(args.snapshot))
    except Exception:
        print('Invalid or unavailable completion report; no notification sent.', file=sys.stderr)
        return 1
    if args.dry_run:
        print(message)
        return 0
    try:
        message_id = send_notice(os.environ.get('DISCORD_ENGINEERING_WEBHOOK_URL'), message)
    except NotificationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f'Discord message confirmed: {message_id}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
