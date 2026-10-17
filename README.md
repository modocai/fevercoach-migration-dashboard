# FeverCoach migration dashboard

Wix → Next.js(Vercel) + Payload(GCP) 이전 진행 기록입니다.

- `migration-dashboard.html`: 최신 계획의 28개 작업, 완료 1개. 정적 HTML이며 브라우저에서 열 수 있습니다.
- `migration-dashboard-original.html`: 이전 Claude 원본 보관본. Claude 런타임 의존성이 있으며 현재 계획이 아닙니다.

상태 변경은 HTML과 웹사이트 리포의 계획 체크리스트를 함께 수정하고 커밋합니다. 공유 상태 저장 UI나 실시간 동기화는 아직 없습니다.

계획: https://github.com/modocai/fevercoach-website

## 티켓 관리

[GitHub Project](https://github.com/orgs/modocai/projects/11)에서 작업 상태를 관리합니다. 연결된 GitHub Issues가 진행 상태의 정본이며 HTML 대시보드는 정적 스냅샷입니다. 담당자와 일정은 아직 배정하지 않았습니다.

## HTML 공유 주소

https://modocai.github.io/fevercoach-migration-pages/

공개 배포 리포는 `modocai/fevercoach-migration-pages`이며 HTML만 게시합니다. 기존 두 작업 리포는 비공개로 유지합니다. 현재 수동 배포 스냅샷이며 GitHub Project와 자동 동기화되지 않습니다. 업데이트 시 `migration-dashboard.html`과 `index.html`, 공개 리포의 `index.html`을 함께 갱신합니다.
