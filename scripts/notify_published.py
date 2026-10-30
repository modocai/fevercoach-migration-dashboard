#!/usr/bin/env python3
"""Use the published dashboard for notices once automatic publishing is enabled."""
import argparse
from datetime import datetime, timezone
import os
import sys
import uuid

import notify_discord
from dashboard_data import ROOT, read_json, require, timestamp
from public_dashboard import fetch_public, manifest
from publish_dashboard import previous_state


def published_message(plan, nonce, now, fetch=fetch_public):
    state = previous_state(plan, nonce, fetch=fetch)
    require(state is not None, 'no automatic publication')
    age = (now - timestamp(state['generated_at'])).total_seconds()
    require(age >= -300, 'publication is in the future')
    message = notify_discord.make_message(state['content_report'], plan, state['snapshot'])
    message += '\n대시보드 갱신: ' + state['generated_at']
    sources = state['snapshot']
    message += '\n원본 확인: ' + ' · '.join(
        label + ' ' + (sources[key].get('last_success_at') or '미확인')
        for key, label in [('issues', 'Issues'), ('project', 'Project'), ('wix', 'Wix')])
    info = manifest(state)
    last_success = info['last_success_at']
    if age > 45 * 60 or not last_success or (now - timestamp(last_success)).total_seconds() > 45 * 60:
        message += '\n주의: 45분 이내 갱신을 확인하지 못했습니다. 마지막 확인값입니다.'
    if info['degraded']:
        message += '\n주의: 일부 원본 조회에 실패하여 이전 기록을 포함합니다.'
    return message


def main():
    # Preserve the existing saved-report behavior, including its CLI and sender.
    if os.environ.get('DASHBOARD_AUTOUPDATE_ENABLED') != 'true':
        return notify_discord.main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        message = published_message(read_json(ROOT / 'data/plan.json'), uuid.uuid4().hex,
                                    datetime.now(timezone.utc))
    except Exception:
        print('Published dashboard unavailable or inconsistent; no notification sent.', file=sys.stderr)
        return 1
    if args.dry_run:
        print(message)
        return 0
    try:
        message_id = notify_discord.send_notice(os.environ.get('DISCORD_ENGINEERING_WEBHOOK_URL'), message)
    except notify_discord.NotificationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f'Discord message confirmed: {message_id}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
