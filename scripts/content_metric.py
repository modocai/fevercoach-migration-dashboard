"""Validate and render the full-inventory content completion metric."""
import math
from html import escape


def validate_report(report):
    if report['status'] == 'unmeasured':
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
    score_sum = sum(row['score'] for row in rows)
    if not math.isclose(report['score_sum'], score_sum, abs_tol=0.00001):
        raise ValueError('Score sum mismatch')
    if not math.isclose(report['percentage'], score_sum / total * 100, abs_tol=0.00001):
        raise ValueError('Percentage mismatch')


def render_content(report):
    validate_report(report)
    intro = '<section class="panel" id="content-completion" aria-label="콘텐츠 이관 완성률"><h2>콘텐츠 이관 완성률</h2>'
    if report['status'] == 'unmeasured':
        return intro + '<div class="big content-score">미측정</div><p class="note">전체 기존 URL과 새 사이트의 텍스트·이미지 비교를 기다리고 있습니다.</p></section>'
    total = report['total_urls']
    pct = report['percentage']
    # Never round an incomplete migration up to 100%.
    label = '100.0' if all(row['score'] == 1 for row in report['results']) else f'{math.floor(pct * 10) / 10:.1f}'
    errors = sum(row['status'] == 'error' for row in report['results'])
    return (intro + f'<div class="big content-score">{label}<small>%</small></div>'
            f'<p class="progress-caption">{report["score_sum"]:,.2f} / {total:,}점 · 전체 {total:,}개 URL 기준</p>'
            f'<p class="note">텍스트·이미지 완전 일치 1점 · 일부 일치 부분 점수 · 오류 {errors:,}개는 0점</p>'
            f'<p class="note">측정: {escape(report["generated_at"])} · 대상: {escape(report["target_base_url"])}</p>'
            '<details><summary>계산 기준과 URL별 결과</summary><p class="note">페이지별 점수의 합 ÷ 전체 기존 URL 수 × 100. '
            '본문 텍스트와 이미지 파일 내용을 비교하며 화면 배치와 SEO는 별도 검증합니다. 어느 한쪽에 이미지가 있으면 텍스트·이미지 각 50%, 양쪽 모두 없으면 텍스트 100%입니다.</p>'
            '<a href="data/content-comparison.json">전체 URL별 점수 JSON 보기 ↗</a></details></section>')
