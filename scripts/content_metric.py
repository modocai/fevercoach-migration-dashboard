"""Validate and render the full-inventory content completion metric."""
import math
from html import escape
from urllib.parse import urlsplit
from dashboard_data import safe_url


def validate_report(report):
    if report['status'] in ('unmeasured', 'not_deployed'):
        return
    if report['status'] != 'measured':
        raise ValueError('Invalid content report status')
    rows = report['results']
    total = report['total_urls']
    if type(total) is not int or total <= 0 or len(rows) != total:
        raise ValueError('Every source URL must be included in the denominator')
    for key in ('source_url', 'target_url'):
        if len({row[key] for row in rows}) != total:
            raise ValueError('URL mapping must be one to one')
    for row in rows:
        score = row['score']
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid page score')
        if row['status'] not in ('ok', 'error') or (row['status'] == 'error' and score != 0):
            raise ValueError('Errors must score zero')
        for key in ('text_score', 'image_score'):
            if key in row:
                value = row[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Invalid component score')
                if row['status'] == 'error' and value != 0:
                    raise ValueError('Error component scores must be zero')
    score_sum = sum(row['score'] for row in rows)
    if not math.isclose(report['score_sum'], score_sum, abs_tol=0.00001):
        raise ValueError('Score sum mismatch')
    if not math.isclose(report['percentage'], score_sum / total * 100, abs_tol=0.00001):
        raise ValueError('Percentage mismatch')


def render_breakdown(report):
    """Explain a saved measurement without changing its scores or inventory."""
    rows, total = report['results'], report['total_urls']
    posts = sum('/post/' in urlsplit(row['source_url']).path for row in rows)
    failures = [row for row in rows if row['status'] == 'error']
    cards = []
    for key, title in [('text_score', '본문 텍스트 일치'), ('image_score', '이미지 파일 일치')]:
        if all(key in row for row in rows):
            value = 100 * sum(row[key] for row in rows) / total
            label = '100.0' if all(row[key] == 1 for row in rows) else f'{math.floor(value * 10) / 10:.1f}'
            cards.append(f'<article class="metric"><h3>{title}</h3><strong class="num">{label}%</strong>'
                         f'<small>오류를 0점으로 포함한 {total:,}개 URL 평균</small></article>')
    cards.append(f'<article class="metric"><h3>비교 결과</h3><strong class="num">{total - len(failures):,} / {total:,}</strong>'
                 f'<small>비교 응답 정상 · 오류 {len(failures):,}개 별도 확인 필요. 정상 응답은 콘텐츠 완전 일치와 다릅니다.</small></article>')
    cards.append(f'<article class="metric"><h3>이번 측정 범위</h3><strong class="num">블로그 {posts:,}개</strong>'
                 f'<small>기타 페이지·프로필 {total - posts:,}개. 원본 사이트맵에 나온 URL 기준이며 CMS 전체 글 수와 다를 수 있습니다.</small></article>')
    result = '<div class="metric-grid" aria-label="콘텐츠 비교 세부 결과">' + ''.join(cards) + '</div>'
    if failures:
        links = []
        for row in failures[:20]:
            def item_link(key, label):
                url = row[key]
                return (f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'
                        if safe_url(url) else label)
            path = escape(urlsplit(row['source_url']).path or '/')
            links.append(f'<li style="overflow-wrap:anywhere">{path} · {item_link("source_url", "기존 페이지")} · '
                         f'{item_link("target_url", "새 페이지")} · {escape(row.get("error", "comparison_failed"))}</li>')
        result += (f'<details><summary>비교 오류 {len(failures):,}개 확인</summary>'
                   '<p class="note">아래는 기존 측정 당시의 오류입니다. 삭제 승인 여부·접속 상태·본문 추출 결과를 확인하세요. '
                   '최대 20개를 표시하며 전체 목록은 아래 JSON에서 확인할 수 있습니다.</p><ul>' + ''.join(links) + '</ul></details>')
    return result


def render_content(report):
    validate_report(report)
    intro = '<section class="panel" id="content-completion" aria-label="콘텐츠 이관 완성률"><h2>콘텐츠 이관 완성률</h2>'
    if report['status'] == 'not_deployed':
        return intro + '<div class="big content-score">0<small>%</small></div><p class="note">새 사이트 배포 전 · 배포 후 전체 URL의 텍스트·이미지를 비교합니다.</p></section>'
    if report['status'] == 'unmeasured':
        return intro + '<div class="big content-score">미측정</div><p class="note">전체 기존 URL과 새 사이트의 텍스트·이미지 비교를 기다리고 있습니다.</p></section>'
    total = report['total_urls']
    pct = report['percentage']
    # Never round an incomplete migration up to 100%.
    label = '100.0' if all(row['score'] == 1 for row in report['results']) else f'{math.floor(pct * 10) / 10:.1f}'
    errors = sum(row['status'] == 'error' for row in report['results'])
    target = escape(report['target_base_url'], quote=True)
    if safe_url(report['target_base_url']):
        target = f'<a href="{target}" target="_blank" rel="noopener noreferrer" style="overflow-wrap:anywhere">{target}</a>'
    return (intro + f'<div class="big content-score">{label}<small>%</small></div>'
            f'<p class="progress-caption">{report["score_sum"]:,.2f} / {total:,}점 · 측정한 원본 사이트맵 {total:,}개 URL 기준</p>'
            f'<p class="note">텍스트·이미지 완전 일치 1점 · 일부 일치 부분 점수 · 오류 {errors:,}개는 0점</p>'
            f'<p class="note">측정: {escape(report["generated_at"])} · 대상: {target}</p>'
            '<p class="notice">이슈·추출 정보 자동 갱신과 콘텐츠 재측정은 별도입니다. 새 배포나 이슈 완료만으로 이 점수가 바뀌지는 않으며, 전체 URL 비교를 다시 실행해 반영해야 합니다.</p>'
            + render_breakdown(report) +
            '<p class="note">이미지 크기·인코딩이 달라지면 표시되어도 파일 일치 점수가 낮아질 수 있습니다. 이 점수는 이관된 페이지 개수 비율이나 운영 전환 완료율이 아닙니다.</p>'
            '<details><summary>계산 기준과 URL별 결과</summary><p class="note">페이지별 점수의 합 ÷ 전체 기존 URL 수 × 100. '
            '본문 텍스트와 이미지 파일 내용을 비교하며 화면 배치와 SEO는 별도 검증합니다. 어느 한쪽에 이미지가 있으면 텍스트·이미지 각 50%, 양쪽 모두 없으면 텍스트 100%입니다.</p>'
            '<a href="data/content-comparison.json">전체 URL별 점수 JSON 보기 ↗</a></details></section>')
