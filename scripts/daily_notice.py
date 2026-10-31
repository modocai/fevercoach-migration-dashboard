#!/usr/bin/env python3
"""Read current GitHub state before notifying; checkpoint only confirmed deliveries."""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from dashboard_data import ROOT, read_json, validate_plan, validate_snapshot, task_states
from content_metric import validate_report
from notify_discord import DASHBOARD_URL, send_notice
from sync_github import GitHub

RECEIPT = 'engineering-daily-notice-receipt'


def restore_receipt(repository):
    """Artifacts contain only public issue IDs, timestamps and delivery confirmation."""
    result = subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts?name={RECEIPT}&per_page=100'],
                            capture_output=True, check=True, timeout=60)
    artifacts = json.loads(result.stdout)['artifacts']
    if not artifacts:
        return None
    latest = max(artifacts, key=lambda a: a['id'])
    run_id = latest.get('workflow_run', {}).get('id')
    if not run_id:
        raise ValueError('Receipt workflow provenance missing')
    run = json.loads(subprocess.run(
        ['gh', 'api', f'repos/{repository}/actions/runs/{run_id}'],
        capture_output=True, check=True, timeout=60).stdout)
    if (run.get('path') != '.github/workflows/daily-notice.yml' or
            run.get('head_branch') != 'main' or
            run.get('event') not in ('schedule', 'workflow_dispatch') or
            run.get('head_repository', {}).get('full_name') != repository):
        raise ValueError('Untrusted receipt workflow')
    if latest['expired']:
        raise ValueError('Previous receipt expired; restore baseline before sending')
    archive = subprocess.run(['gh', 'api', f"repos/{repository}/actions/artifacts/{latest['id']}/zip"],
                             capture_output=True, check=True, timeout=60).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        info = z.getinfo('receipt.json')
        if info.file_size > 65536:
            raise ValueError('Receipt too large')
        receipt = json.loads(z.read(info))
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt):
    if not isinstance(receipt, dict) or receipt.get('schema_version') != 1:
        raise ValueError('Invalid receipt')
    if not isinstance(receipt.get('completed'), list) or any(type(n) is not int for n in receipt['completed']):
        raise ValueError('Invalid completed IDs')
    if not receipt.get('message_id') or not receipt.get('last_sent_at'):
        raise ValueError('Missing delivery confirmation')
    datetime.fromisoformat(receipt['last_sent_at'].replace('Z', '+00:00'))


def collect(plan, client, now):
    snapshot = {'schema_version': 1}
    for source in ('issues', 'project'):
        try:
            items = getattr(client, source)(plan)
            value = {'status': 'ok', 'attempted_at': now, 'last_success_at': now,
                     'error': None, 'items': items}
            validate_snapshot({'schema_version': 1, source: value}, plan, sources=(source,))
            snapshot[source] = value
        except Exception:
            # Never substitute old counts or include private API errors in Discord.
            snapshot[source] = {'status': 'error', 'attempted_at': now, 'last_success_at': None,
                                'error': 'github_request_failed', 'items': []}
    return snapshot


def content_line(report):
    try:
        validate_report(report)
        if report['status'] == 'measured':
            from math import floor
            value = 100 if all(r['score'] == 1 for r in report['results']) else floor(report['percentage'] * 10) / 10
            return f"콘텐츠 이관율: {value:g}% · 측정 시각 {report['generated_at']} (저장된 측정값)"
    except Exception:
        pass
    return '콘텐츠 이관율: 최신 측정 없음 (기존 배포 전 0% 기록을 현재 진척으로 사용하지 않음)'


def compose(plan, snapshot, report, previous, now):
    rows = task_states(plan, snapshot)
    lines = ['**FeverCoach 엔지니어링 일일 업데이트**', f'GitHub 조회 시각: {now}']
    old = set(previous['completed']) if previous else set()
    current = {r['number'] for r in rows if r['status'] == 'done'}
    if snapshot['issues']['status'] != 'ok':
        lines.append('⚠️ GitHub Issues 조회 실패. 완료율·새 완료 목록은 미확인입니다. 다음 알림에서 다시 확인합니다.')
        current = old
    else:
        opened = sum(r['issue_state'] == 'open' for r in rows)
        excluded = sum(r['status'] == 'excluded' for r in rows)
        lines.append(f'전체 {len(rows)}개 · 완료 {len(current)}개 ({len(current)/len(rows)*100:.0f}%) · 미완료 {opened}개')
        if excluded:
            lines.append(f'미진행 종료 {excluded}개 (완료에 포함하지 않음)')
        if snapshot['project']['status'] == 'ok':
            counts = {k: sum(r['status'] == k for r in rows) for k in ('doing', 'todo', 'blocked', 'unknown')}
            lines.append(f"진행 중 {counts['doing']} · 할 일 {counts['todo']} · 막힘 {counts['blocked']} · 상태 미확인 {counts['unknown']}")
        else:
            lines.append('⚠️ Project 조회 실패. 진행 중·할 일 구분은 미확인입니다.')
        baseline = previous is None or previous.get('last_successful_snapshot_at') is None
        added = current if baseline else current - old
        lines.append('**첫 조회 기준 완료 목록 (오늘 완료된 목록이 아님)**' if baseline else '**지난 정상 알림 이후 새로 완료된 이슈**')
        if not added:
            lines.append('없음')
        for row in rows:
            if row['number'] in added:
                # Fixed public catalog; no private issue bodies, comments or new titles.
                title = row['title'].replace('\n', ' ')[:90]
                url = f"https://github.com/{plan['repository']}/issues/{row['number']}"
                lines.append(f"✅ [#{row['number']}]({url}) {title}")
        reopened = old - current if not baseline else set()
        if reopened:
            lines.append('완료 목록에서 제외됨 (재열림 또는 종료 사유 변경): ' + ', '.join(f'#{n}' for n in sorted(reopened)))
    lines += [content_line(report), '대시보드와 동일한 이슈 범위·집계 기준입니다. 화면은 마지막 배포 시점에 따라 지연될 수 있습니다.', DASHBOARD_URL]
    # Discord content limit. Full issue IDs still remain in the receipt.
    while len('\n'.join(lines)) > 1950:
        candidates = [i for i, line in enumerate(lines) if line.startswith('✅ ')]
        if not candidates:
            raise ValueError('Message exceeds Discord limit')
        i = candidates[-1]
        lines.pop(i)
        if '나머지 완료 목록은 GitHub Issues에서 확인해 주세요.' not in lines:
            lines.insert(i, '나머지 완료 목록은 GitHub Issues에서 확인해 주세요.')
    return '\n'.join(lines), sorted(current)


def deliver(message, completed, previous, snapshot, now, receipt_path, sender):
    message_id = sender(message)
    receipt = {'schema_version': 1, 'message_id': message_id, 'last_sent_at': now,
               'completed': completed,
               'last_successful_snapshot_at': now if snapshot['issues']['status'] == 'ok' else
                    (previous or {}).get('last_successful_snapshot_at')}
    validate_receipt(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(receipt_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--receipt', type=Path, default=ROOT / '_notice/receipt.json')
    args = parser.parse_args()
    try:
        plan = read_json(ROOT / 'data/plan.json')
        validate_plan(plan)
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        previous = restore_receipt(os.environ.get('GITHUB_REPOSITORY', 'modocai/fevercoach-migration-dashboard'))
        if previous and previous['last_sent_at'][:10] == now[:10] and not args.dry_run:
            print('Already confirmed a notice today; skipped.')
            return 0
        workflow_token = os.environ.get('GH_TOKEN')
        source_token = os.environ.get('DASHBOARD_SOURCE_TOKEN')
        try:
            if os.environ.get('GITHUB_ACTIONS') and not source_token:
                raise ValueError('Source-read token is required in Actions')
            if source_token:
                os.environ['GH_TOKEN'] = source_token
            snapshot = collect(plan, GitHub(), now)
        finally:
            if workflow_token is None:
                os.environ.pop('GH_TOKEN', None)
            else:
                os.environ['GH_TOKEN'] = workflow_token
        message, completed = compose(plan, snapshot, read_json(ROOT / 'data/content-comparison.json'), previous, now)
        if args.dry_run:
            print(message)
            return 0
        deliver(message, completed, previous, snapshot, now, args.receipt,
                lambda msg: send_notice(os.environ.get('DISCORD_ENGINEERING_WEBHOOK_URL'), msg))
        print('Discord delivery confirmed; receipt ready for persistent artifact upload.')
        return 0
    except Exception:
        print('Daily notice failed; no success checkpoint advanced. Check source access and receipt storage.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
