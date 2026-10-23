# FeverCoach migration dashboard

Wix → Next.js(Vercel) + Payload(GCP) 이전의 작업 상태, 추출 범위, 기준값과 단계별 검증 근거를 확인합니다.

- [대시보드](https://modocai.github.io/fevercoach-migration-dashboard/)
- [Project #11](https://github.com/orgs/modocai/projects/11)
- [웹사이트 계획·Issues](https://github.com/modocai/fevercoach-website)

## 구성

사이트는 서버나 패키지 없이 동작하는 정적 HTML/CSS/JavaScript입니다. Python 3.9 이상 표준 라이브러리로 데이터를 검증하고 두 HTML을 생성합니다. 브라우저는 GitHub API를 호출하지 않습니다.

| 경로 | 역할 |
| --- | --- |
| `data/plan.json` | 기존 28개 작업·6단계, Project 필드 매핑, 제안된 단계 검증 조건과 근거 |
| `data/snapshot.json` | 공개용 GitHub·Wix 집계, 성공/시도 시각, 실패 상태 |
| `data/baselines.json` | 이전 참고 기록, 이전 전·스테이징 성능, Search Console, GA4 준비 |
| `templates/dashboard.html` | 기존 디자인을 유지한 HTML 템플릿 |
| `scripts/sync_github.py` | 인증된 GitHub CLI로 원본을 읽고 공개 허용 필드만 저장 |
| `scripts/build_dashboard.py` | 검증 후 동일한 `index.html`, `migration-dashboard.html` 생성 |
| `migration-dashboard-original.html` | 과거 원본 보관본. 현재 데이터·구현의 기준이 아님 |

## 로컬 갱신

기존 GitHub 로그인 계정으로 실행합니다. 수집은 읽기 전용이며 이슈·Project를 변경하지 않습니다.

```sh
python3 scripts/sync_github.py
python3 scripts/build_dashboard.py
python3 -m unittest discover -s tests -v
python3 scripts/build_dashboard.py --check
git diff --check
```

수집 명령은 일부 조회 실패 시 종료 코드 1을 반환합니다. 원본을 독립 처리하므로 성공한 자료는 갱신하고 실패한 자료는 마지막 정상 기록을 유지합니다. 실패 원인을 검토한 뒤 HTML을 생성할 수 있지만 전체 연동 성공으로 보고하지 않습니다. 처음부터 확보하지 못한 값은 미확인으로 남습니다.

공개 페이지에는 저장된 스냅샷이 표시됩니다. 수집만으로 배포 화면이 바뀌지는 않습니다. 변경을 검토해 본인 계정으로 커밋하고 `dashboard → main` PR을 병합하면 기존 GitHub Pages 배포가 갱신됩니다. 자동 커밋이나 봇 작성자 커밋은 만들지 않습니다.

## 인증과 Project 매핑

비공개 웹사이트 저장소와 Project #11 읽기 권한이 모두 필요합니다. 현재 인증에 Project 읽기 scope가 부족하면 계정 소유자가 다음 명령으로 갱신할 수 있습니다.

```sh
gh auth refresh -s read:project
gh project view 11 --owner modocai --format json
```

실제 `Status` 선택지에 맞게 `data/plan.json`의 `project.status_map`을 조정합니다. 알 수 없는 값은 미확인으로 유지합니다. 마감일은 실제 날짜 필드를 확인해 `due_date_field`에 설정한 경우만 사용합니다. 보드 필드를 임의로 만들거나 변경하지 않습니다.

첫 실제 조회에서는 Issues·Wix 수집이 성공하고 Project는 `read:project` 권한 부족으로 실패했습니다. 실제 보드 변경 반영 검증은 권한 확보 후 진행해야 하며 페이지에 이 한계가 표시됩니다.

`Collect dashboard snapshot` 워크플로는 `main`에서 수동 실행합니다. `DASHBOARD_SOURCE_TOKEN` secret에 비공개 원본 저장소와 Project를 읽을 수 있는 토큰이 필요합니다. 검증한 JSON·HTML을 다운로드 가능한 artifact로 제공하며 커밋·PR·배포는 생성하지 않습니다. 일부 수집 실패는 artifact와 별개로 실행 실패로 보고합니다. 토큰을 코드·HTML·JSON에 넣지 않습니다.

## 상태의 의미

- **이슈 완료율:** 계획에 명시된 이슈 중 `closed` + `completed` 개수. PR·다른 저장소·새 범위 밖 항목은 제외합니다. `not_planned` 종료는 완료가 아니며 범위에서 빼려면 계획을 별도 검토해야 합니다.
- **진행 중·할 일·막힘:** Project에서 읽고 매핑한 상태. 열린 이슈만 보고 추측하지 않습니다. 이슈와 보드가 다르면 불일치를 표시합니다.
- **공개 URL 수집:** 공개 사이트맵의 URL 수집 결과. 초안·예약 글·전체 이미지·CMS 이관·검색 검증을 대신하지 않습니다.
- **이미지 샘플:** 전체 목록과 원본 샘플 수집을 구분합니다. 샘플 범위 밖 이미지는 다운로드 오류가 아닙니다.
- **DNS / 관리자 콘텐츠 추출:** 공개 수집과 별도 지표입니다. 플래그만으로 이슈나 단계가 자동 완료되지 않습니다.
- **갱신 실패:** 마지막 성공 시각과 이전 데이터를 유지하며 최근 실패도 표시합니다.

Wix 자료는 웹사이트 `main`의 `docs/wix-export-status.json`을 우선 읽습니다. 파일이 없을 때만 같은 저장소의 열린 PR #29를 확인하고 정확한 head SHA를 기록합니다. 닫힌 미병합 PR은 새 자료로 사용하지 않습니다. 원본의 로컬 경로·DNS 상세·본문·인벤토리는 공개 데이터로 복사하지 않습니다.

## 기준값과 단계 검증

Lighthouse에는 URL·날짜·조건·점수·LCP·근거를 기록합니다. 기존 2026-10-14 홈 기록은 참고값으로 보존합니다. 이전 전 기준값과 새 사이트 측정을 구분하고 미측정 값은 `null`로 둡니다.

Search Console 기준값은 시작일·종료일 포함 정확히 28일의 클릭·노출입니다. GA4 속성·주요 이벤트 수집은 별도 담당과 검증이 필요합니다. 현재 제안 항목은 합의된 완료 기준이나 구현 완료를 의미하지 않습니다.

단계 기준은 기존 계획을 상세화한 **팀 검토용 제안**입니다. 이슈 완료와 별도 증빙을 함께 요구합니다. `verification.status`를 `passed`로 변경하려면 HTTPS 근거 URL, 시간대 포함 `checked_at`, 검토자 `reviewer`를 기록합니다. MC 승인 항목은 승인 근거와 `reviewer: "MC"`가 필요합니다. 화면은 운영 전환·Wix 해지를 자동 승인하거나 실행하지 않습니다.

## 검증

PR 검사는 데이터·상태 해석·실패 시 보존·출력 이스케이프와 두 HTML의 재현성을 확인합니다. Playwright가 있는 검증 환경에서는 다음을 실행할 수 있습니다. 사이트 실행에는 Playwright가 필요하지 않습니다.

```sh
node tests/browser.cjs
```

별도 설치 경로는 `PLAYWRIGHT_MODULE`, 브라우저 실행 경로는 `BROWSER_PATH`로 지정합니다. 1440px 데스크톱·1280px 노트북, 키보드 필터, 빈 결과, 단계 바로가기, JavaScript 비활성, 외부 요청·런타임 오류를 확인합니다. 보고서·스크린샷은 커밋하지 않는 `artifacts/`에 저장합니다.

## Lighthouse 재측정

Lighthouse 12.6.1의 기본 모바일 simulated throttling 조건으로 홈·대표 글을 순차 측정합니다. 두 실행은 경고가 없고 최상위 문서가 HTTP 200이어야 합니다. 원본 보고서는 로컬 artifacts에 보관하고, 공개 증빙에는 지표·조건·원본 SHA-256만 저장합니다.

```sh
mkdir -p artifacts
npx --yes lighthouse@12.6.1 https://www.fevercoach.us/ --quiet --chrome-flags='--headless' --only-categories=performance --output=json --output-path=artifacts/lighthouse-home.json
npx --yes lighthouse@12.6.1 https://www.fevercoach.us/post/oral-antibiotics-after-iv-drip --quiet --chrome-flags='--headless' --only-categories=performance --output=json --output-path=artifacts/lighthouse-post.json
python3 scripts/import_lighthouse.py --home artifacts/lighthouse-home.json --post artifacts/lighthouse-post.json --evidence-ref dashboard
python3 scripts/build_dashboard.py
```

새 기록을 main에 직접 반영할 때는 `--evidence-ref main`을 사용합니다. 페이지별 1회 실험실 측정이므로 사용자 실측 데이터나 이전 효과의 증명으로 해석하지 않습니다.

[구현 및 검증 기록](docs/validation.md)
