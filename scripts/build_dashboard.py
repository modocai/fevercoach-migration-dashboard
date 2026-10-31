#!/usr/bin/env python3
"""Build both standalone HTML entrypoints from validated, public snapshots."""
import argparse
from collections import Counter
from html import escape
from content_metric import render_content

from dashboard_data import (ROOT, gate_state, read_json, safe_url, task_states,
                            validate_baselines, validate_plan, validate_snapshot)

LABELS = {"todo": "할 일", "doing": "진행 중", "done": "완료", "blocked": "막힘",
          "unknown": "상태 미확인", "excluded": "미진행 종료"}


def e(value):
    return escape(str(value), quote=True)


def link(url, label, cls=""):
    if not safe_url(url):
        return e(label)
    return f'<a class="{e(cls)}" href="{e(url)}">{e(label)}</a>'


def date_label(value):
    return e(value.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC")) if value else "확인 기록 없음"


def source_notice(name, source):
    status = "수집 성공" if source["status"] == "ok" else "갱신 실패 · 이전 기록 유지" if source.get("last_success_at") else "조회 불가"
    reason = " · Project 읽기 권한 필요" if source.get("error") == "project_read_permission_required" else ""
    return (f'<div class="source-item"><strong>{e(name)}</strong><span>{status}{reason}</span>'
            f'<small>마지막 성공: {date_label(source.get("last_success_at"))}</small>'
            f'<small>최근 시도: {date_label(source.get("attempted_at"))}</small></div>')


def render_summary(plan, rows, snapshot):
    counts = Counter(row["status"] for row in rows)
    total, done = len(rows), counts["done"]
    pct = done / total * 100 if total else 0
    # Unknown Project state is visible rather than represented by a false zero.
    opened = sum(row["issue_state"] == "open" for row in rows)
    blocks = f'<span><b>{total}</b>전체 이슈</span><span><b>{done}</b>이슈 완료</span><span><b>{opened}</b>미완료 (Open)</span>'
    for status in ["doing", "todo", "blocked", "unknown", "excluded"]:
        if counts[status]:
            blocks += f'<span><b>{counts[status]}</b>{LABELS[status]}</span>'

    nav = []
    for phase in plan["phases"]:
        items = [r for r in rows if r["phase"] == phase["id"]]
        n = sum(r["status"] == "done" for r in items)
        percent = n / len(items) * 100 if items else 0
        nav.append(f'<a class="ph" href="#phase-{phase["id"]}"><span class="lbl"><span>{phase["id"]+1:02} · {e(phase["name"])}</span>'
                   f'<span>{percent:.0f}%</span></span><span class="bar"><i style="width:{percent:.4f}%"></i></span>'
                   f'<span class="meta">{n} / {len(items)} 이슈 완료</span></a>')
    return (f'<section class="summary" aria-label="전체 진행 현황"><div class="overall"><div><div class="eyebrow">ISSUE COMPLETION</div>'
            f'<div class="big">{pct:.0f}<small>%</small></div><div class="progress-caption">{done} / {total}개 이슈 완료 · 콘텐츠 이전율과 별도</div></div>'
            f'<div class="counts">{blocks}</div><div class="thermo" role="progressbar" aria-label="이슈 완료율" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct:.2f}"><i class="d" style="width:{pct:.4f}%"></i></div></div>'
            f'<nav class="phases" aria-label="단계별 바로가기">{"".join(nav)}</nav>'
            '<p class="note">진행 중·할 일·막힘은 Project에서 확인된 상태만 표시합니다. 이슈 종료와 보드 상태가 다르면 작업에 불일치를 표시합니다.</p>'
            '<div class="stack"><span>WEB · Next.js / Vercel</span><span>CMS · Payload / Cloud Run</span><span>DATA · PostgreSQL / GCS</span></div></section>'
            '<section class="source-grid" aria-label="데이터 갱신 상태">'
            + "".join(source_notice(name, snapshot[key]) for key, name in [("issues", "GitHub Issues"), ("project", "Project #11"), ("wix", "Wix 추출 자료")])
            + '</section>')


def render_wix(source):
    if not source.get("data"):
        return '<section class="panel" id="export"><h2>Wix 추출 현황</h2><p>자료 대기 · 수집 결과가 아직 없습니다.</p></section>'
    data = source["data"]
    review = 'PR #29 · 검토 중 · 미병합 자료' if source["review_state"] == "open_pr" else 'main에 반영된 자료'
    url_status = "발견한 공개 URL 수집 완료" if data["all_discovered_urls_exported"] else "공개 URL 수집 중"
    media_scope = "원본 샘플 확보" if data["media_download_scope"] == "sample" else "전체 원본 수집"
    dns = "백업 완료 보고" if data["dns_zone_export_complete"] else "미완료 · 관리자 패널 백업 필요"
    cms = "추출 완료 보고" if data["authoritative_wix_export_complete"] else "미완료 · 초안·예약 글·번역 연결 확인 필요"
    media_detail = (f' · 폰트 {data.get("downloaded_font_assets", 0):,}개 · 잘못된 참조 {data.get("invalid_reference_count", 0):,}개 별도'
                    if "legacy_reference_entries" in data else "")
    blog_detail = (f'인증 Blog 원본 확보: 게시 {data["authenticated_published_posts"]:,} · 미게시 초안 {data["authenticated_unpublished_drafts"]:,} · 예약 {data["authenticated_scheduled_posts"]:,}'
                   if data.get("authenticated_blog_export_complete") else cms)
    full_scope = "미사용 미디어·비공개 페이지 등 전체 Wix 자산 확인은 별도" if data.get("authenticated_blog_export_complete") else "CMS 이관·SEO 검증과 별도"
    return (f'<section class="panel" id="export"><div class="phase-head"><h2>Wix 추출 현황</h2><span class="pill">{review}</span></div>'
            f'<p class="note">수집 기준: {date_label(data["generated_at"])} · '
            f'{link(source["source_url"], "원본 상태 자료 ↗")} · 커밋 {e(source["source_sha"][:7])} · 상태 검증: {date_label(data.get("status_updated_at", data["generated_at"]))}</p>'
            '<div class="metric-grid">'
            f'<article class="metric"><h3>공개 URL</h3><strong class="num">{data["exported_urls"]:,} / {data["discovered_urls"]:,}</strong>'
            f'<p>{url_status}</p><small>공개 사이트맵에서 발견된 주소 기준</small></article>'
            f'<article class="metric"><h3>이미지 원본</h3><strong class="num">{data["downloaded_images"]:,} / {data["unique_referenced_images"]:,}</strong>'
            f'<p>{media_scope}</p><small>미수집 {data["images_not_downloaded_count"]:,}개 · 오류 {data["media_error_count"]:,}개{media_detail}</small></article>'
            f'<article class="metric"><h3>전체 DNS 백업</h3><p>{dns}</p><small>공개 DNS 조회 결과와 별도</small></article>'
            f'<article class="metric"><h3>인증 Blog / 전체 Wix 자산</h3><p>{blog_detail}</p><small>{full_scope}</small></article></div>'
            '<p class="notice">공개 페이지 수집 완료는 CMS 이관 완료를 뜻하지 않습니다. 이미지 원본 백업과 GCS 복사·사이트 표시 검증은 별도입니다.</p></section>')


def render_baselines(data):
    rows = []
    kinds = {"historical": "이전 참고 기록", "baseline": "이전 전 기준값", "staging": "새 사이트 측정"}
    for record in data["lighthouse"]:
        name = f'{kinds[record["kind"]]} · {"홈" if record["page"] == "home" else "대표 글"}'
        if record["status"] == "measured":
            score, lcp = str(record["performance"]), f'{record["lcp_seconds"]}초'
            evidence = (f'{e(record["measured_on"])} · {link(record["url"], "측정 URL")} · '
                        f'{link(record["evidence_url"], "측정 근거")}<br><small>{e(record["conditions"])}</small>')
        else:
            score, lcp, evidence = "미측정", "미측정", "측정 URL·일시·조건·리포트 필요"
        rows.append(f'<tr><th scope="row">{e(name)}</th><td>{score}</td><td>{lcp}</td><td>{evidence}</td></tr>')
    search = []
    for record in data["search_console"]:
        if record["status"] == "measured":
            search.append(f'<p>{e(record["period_start"])} ~ {e(record["period_end"])} · 클릭 {record["clicks"]:,} · '
                          f'노출 {record["impressions"]:,} · {link(record["evidence_url"], "근거 ↗")}</p>')
        else:
            search.append('<p>자료 대기 · 이전 전 28일의 클릭·노출과 기간을 기록해야 합니다.</p>')
    analytics = data["analytics"]
    return ('<section class="panel" id="baselines"><h2>기준값과 분석 준비</h2>'
            f'<p class="note">목표: 모바일 Lighthouse {data["targets"]["performance"]} 이상 · LCP {data["targets"]["lcp_seconds"]}초 이하. '
            '미측정 값은 0으로 계산하지 않습니다.</p>'
            '<div class="table-scroll" tabindex="0" role="region" aria-label="성능 기준값 표"><table><thead><tr><th scope="col">측정 구분</th>'
            '<th scope="col">성능 점수</th><th scope="col">LCP</th><th scope="col">일시·근거</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div><div class="baseline-notes"><div><h3>Search Console · 4주</h3>'
            + "".join(search) + '</div><div><h3>GA4 · 담당·검증 기준 협의 필요</h3>'
            f'<p>담당자: {e(analytics.get("owner") or "미확정")} · 제안 항목</p><ul>'
            + "".join(f'<li>{e(criterion)}</li>' for criterion in analytics["criteria"])
            + '</ul><p class="note">Search Console·Lighthouse 측정만으로 방문·이벤트 수집 검증이 완료되지는 않습니다.</p></div></div></section>')


def render_phases(plan, rows):
    sections = []
    for phase in plan["phases"]:
        items = [r for r in rows if r["phase"] == phase["id"]]
        count = sum(r["status"] == "done" for r in items)
        gates = [(gate, gate_state(gate, rows)) for gate in phase["gates"]]
        passed = sum(state[0] == "passed" for _, state in gates)
        details = []
        for gate, (status, label) in gates:
            proof = gate["verification"]
            evidence = (f' · {link(proof["url"], "검증 근거")} · {e(proof["reviewer"])} · {date_label(proof["checked_at"])}'
                        if proof["status"] == "passed" else "")
            refs = " ".join(link(f'https://github.com/{plan["repository"]}/issues/{n}', f'#{n}') for n in gate["issues"])
            details.append(f'<li><span>{e(gate["label"])} {refs}</span><small>{label}{evidence}</small></li>')
        articles = []
        for row in items:
            who = "담당 정보 미확인" if row["assignees"] is None else ", ".join(row["assignees"]) or "담당자 미배정"
            due = f' · 마감 {e(row["due_date"])}' if row["due_date"] else ""
            conflict = '<span class="conflict">이슈·보드 상태 불일치</span>' if row["conflict"] else ""
            state = row["status"]
            issue_link = link(f'https://github.com/{plan["repository"]}/issues/{row["number"]}', row["title"], "title")
            articles.append(f'<article class="row {"is-done" if state == "done" else ""}" data-status="{state}" data-issue-state="{row["issue_state"]}">'
                            f'<span class="check" aria-hidden="true">{"✓" if state == "done" else "○"}</span>'
                            f'{issue_link}'
                            f'<span class="status s-{state}">{LABELS[state]}</span>'
                            f'<span class="who">#{row["number"]:02} · {e(who)}{due} {conflict}</span></article>')
        sections.append(f'<section class="phase" id="phase-{phase["id"]}"><div class="phase-head"><div>'
                        f'<div class="eyebrow">PHASE {phase["id"]+1:02}</div><h2>{e(phase["name"])}</h2><p class="phase-note">{e(phase["note"])}</p></div>'
                        f'<span class="pct">{count} / {len(items)} 이슈 완료</span></div>'
                        f'<details class="gates"><summary>단계 검증 · {passed} / {len(gates)}개 근거 확인</summary><ul>{"".join(details)}</ul></details>'
                        f'<div class="rows">{"".join(articles)}</div></section>')
    return "\n".join(sections)


CSS = """
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:24px;display:grid;gap:16px;scroll-margin-top:16px}
.panel p,.summary p{margin:0}.panel h3{margin:0 0 8px;font-size:14px}.source-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.source-item{display:grid;gap:5px;border-left:3px solid var(--line);padding-left:12px;font-size:13px;overflow-wrap:anywhere}.source-item small{color:var(--muted);font-size:11px}
.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.metric{padding:16px;background:var(--bg);border-radius:8px;display:grid;gap:8px}.metric .num{font-size:26px}.metric small{color:var(--muted)}
.baseline-notes{display:grid;grid-template-columns:1fr 1fr;gap:20px;font-size:13px}.baseline-notes ul{padding-left:20px}.baseline-notes li{margin:5px 0}
.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}table{width:100%;min-width:640px;border-collapse:collapse;font-size:13px;text-align:left}th,td{padding:12px;vertical-align:top;border-bottom:1px solid var(--line)}thead{background:var(--bg)}th:first-child{min-width:120px}td small{color:var(--muted)}
.gates{background:var(--gate-soft);border-radius:8px;padding:0 14px;font-size:13px}.gates summary{cursor:pointer;min-height:44px;display:flex;align-items:center;gap:8px;color:var(--gate)}.gates summary::before{content:'＋'}.gates[open] summary::before{content:'−'}.gates ul{padding:0 0 12px;margin:0;list-style:none;display:grid;gap:12px}.gates li{display:grid;gap:3px}.gates small{color:var(--muted)}
.s-unknown,.s-excluded{background:var(--gate-soft);color:var(--gate)}.conflict{color:var(--bad);font-weight:600}.filters{flex-wrap:wrap}.counts{gap:12px 20px}.counts b{font-size:23px}.counts span{min-width:64px}.notice{overflow-wrap:anywhere}.empty-filter{padding:16px;color:var(--muted)}[hidden]{display:none!important}
summary:focus-visible,.table-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
@media(max-width:600px){.panel{padding:18px}.source-grid,.baseline-notes{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr}.filters{gap:6px}.filter{padding:8px 10px}.metric .num{font-size:24px}.counts{justify-content:flex-start}.table-scroll{max-width:100%}th,td{padding:10px}}
"""

SCRIPT = """
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  const filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
  document.querySelectorAll('.row').forEach(row => { row.hidden = filter === 'open' ? row.dataset.issueState !== 'open' : filter !== 'all' && row.dataset.status !== filter; });
  document.querySelectorAll('.phase').forEach(section => {
    section.hidden = ![...section.querySelectorAll('.row')].some(row => !row.hidden);
  });
  const count = [...document.querySelectorAll('.row')].filter(row => !row.hidden).length;
  document.querySelector('#filter-result').textContent = `${count}개 작업 표시`;
  document.querySelector('#empty-filter').hidden = count !== 0;
}));
document.querySelector('[data-filter="open"]').click();
// A phase link must still work after a filter has hidden that phase.
document.querySelectorAll('.phases a').forEach(anchor => anchor.addEventListener('click', () => {
  document.querySelector('[data-filter="all"]').click();
}));
"""


def render(plan, snapshot, baselines, content_report=None):
    validate_plan(plan)
    validate_snapshot(snapshot, plan)
    validate_baselines(baselines)
    rows = task_states(plan, snapshot)
    header = ('<header><div class="headerline"><div><div class="eyebrow">FEVERCOACH / WEBSITE MIGRATION</div>'
              '<h1>새로운 웹사이트로, 한 단계씩.</h1></div><span class="pill">출처와 근거로 확인하는 진행 현황</span></div>'
              '<div class="sub">Wix에서 Next.js + Payload로 이전하는 팀의 작업 공간</div><nav class="links" aria-label="프로젝트 링크">'
              + link('https://github.com/orgs/modocai/projects/11', '프로젝트 보드 ↗', 'btn primary')
              + link('https://github.com/modocai/fevercoach-website/issues?q=is%3Aissue+state%3Aopen', 'GitHub 미완료 이슈 ↗', 'btn')
              + link('https://github.com/modocai/fevercoach-website/blob/main/migration-brief.md', '이전 계획 ↗', 'btn')
              + '<a class="btn" href="#export">추출 현황</a><a class="btn" href="#baselines">기준값·분석</a></nav></header>')
    filters = ''.join(f'<button class="filter" data-filter="{state}" aria-pressed="{str(state == "open").lower()}">{label}</button>'
                      for state, label in [("open", "미완료"), ("all", "전체"), *LABELS.items()])
    content = (header + render_content(content_report or {"status": "unmeasured"}) + render_summary(plan, rows, snapshot) + render_wix(snapshot["wix"]) + render_baselines(baselines)
               + '<div class="toolbar"><div><h2>단계별 작업</h2><p class="note">콘텐츠·기능·분석의 이전 근거를 각 단계에서 확인합니다.</p></div>'
               f'<div class="filters" aria-label="작업 상태 필터">{filters}</div></div>'
               f'<p class="note">{e(plan["gate_policy"])}</p><p id="filter-result" class="note" role="status" aria-live="polite">{len(rows)}개 작업 표시</p>'
               '<p id="empty-filter" class="empty-filter" hidden>이 상태로 확인된 작업이 없습니다. 미확인 항목은 상태 미확인 필터에서 확인하세요.</p>'
               '<div id="sections">' + render_phases(plan, rows) + '</div>'
               '<footer><strong>저장된 데이터 기준 스냅샷</strong> · 브라우저에서 실시간 조회하지 않습니다. 갱신 후 배포된 시점의 기록입니다.<br>'
               '프로젝트와 웹사이트 이슈는 팀 접근 권한이 필요합니다. 운영 전환과 Wix 해지는 MC 승인 후 진행합니다.<br>'
               + link('https://github.com/modocai/fevercoach-migration-dashboard', '대시보드 리포 ↗') + '</footer>')
    template = (ROOT / "templates/dashboard.html").read_text(encoding="utf-8")
    # Replace each template token once, before inserting untrusted text into the body.
    return template.replace("@@EXTRA_CSS@@", CSS).replace("@@SCRIPT@@", SCRIPT).replace("@@CONTENT@@", content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if checked-in HTML differs from the data")
    args = parser.parse_args()
    output = render(read_json(ROOT / "data/plan.json"), read_json(ROOT / "data/snapshot.json"),
                    read_json(ROOT / "data/baselines.json"), read_json(ROOT / "data/content-comparison.json"))
    for name in ["index.html", "migration-dashboard.html"]:
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != output:
                raise SystemExit(f"Out of date: {name}. Run python3 scripts/build_dashboard.py")
        else:
            path.write_text(output, encoding="utf-8")
    print("Both HTML entrypoints match validated data." if args.check else "Generated both HTML entrypoints.")


if __name__ == "__main__":
    main()


