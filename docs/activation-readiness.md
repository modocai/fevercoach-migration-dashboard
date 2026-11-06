# Actions 검증과 자동 배포 활성화

이 문서는 준비 절차다. 코드 병합, Discord 전송, Pages 전환 또는 자동화 활성화가 완료됐다는 뜻이 아니다.

## 서로 다른 두 기능

| 기능 | 실행 경로 | 조건 |
| --- | --- | --- |
| PR #10 일일 알림 | `daily-notice.yml` → `daily_notice.py` | 전용 토큰으로 Issues·Project 조회, 기본 Actions 토큰으로 이전 전송 기록 조회 |
| PR #2 대시보드 배포 | `publish.yml` → `publish_dashboard.py` | Issues·Project·웹사이트 main의 Wix 집계, Pages Actions 배포, 활성화 변수 |

#10은 `DASHBOARD_AUTOUPDATE_ENABLED`를 사용하지 않는다. 병합되면 기존 예약 실행에서도 새 알림 코드가 동작한다. 기본 수동 실행은 dry-run이지만 예약 실행은 실제 전송이므로 병합 직후 검증할 시간을 확보한다. #2는 기본 비활성이다. #10 병합 자체가 #2의 필수 조건은 아니다.

## 2026-11-06 준비 시점에 확인한 상태

- dashboard main은 protected로 표시된다. 현재 계정에서는 세부 보호 규칙을 확인하지 못했으므로 관리자에게 필수 리뷰·CI 규칙을 확인한다.
- `dashboard-source` 환경은 main 브랜치만 허용하며 `DASHBOARD_SOURCE_TOKEN` 등록을 확인했다. secret 이름 조회는 실제 인증 성공을 증명하지 않는다.
- Pages는 main 루트의 기존 branch 배포이며 `DASHBOARD_AUTOUPDATE_ENABLED`는 미설정이다.
- 공개 Wix 파일은 website PR #35의 `docs/wix-export-dashboard-status.json`이다. main에는 아직 없다. #35의 Vercel 실패는 관리자가 main의 `web/` 부재로 설명했으며, #32의 정상 리뷰·통합 이후 #35를 최신 main 기준으로 재검증하는 순서가 필요하다. 검사를 우회하지 않는다.
- #10의 `d58d4319`에는 두 동료의 승인과 validate CI가 있다. #11은 별도 스냅샷 갱신이며 자동화 활성화와 관계없다.

시간이 지나면 위 상태는 다시 확인한다. 이 준비 PR은 화면·계산·알림·배포 동작 및 설정을 변경하지 않는다.

## 전용 인증과 실행 경계

전용 토큰은 `dashboard-source` **환경 secret**에만 둔다. 필요한 읽기 범위는 웹사이트 저장소의 Issues와 Contents, 조직 Project #11이다. 조직 승인·토큰 만료 및 실제 GraphQL 접근까지 확인한다. 개인 CLI 토큰을 복사하거나 secret 값을 로그·이슈·채팅에 쓰지 않는다.

사전 검사 workflow는 수동 main 실행만 허용한다. `contents: read`, `actions: read`만 사용하고, 체크아웃 자격 증명은 보존하지 않는다. webhook, Pages 쓰기 권한, artifact 업로드, 일정 실행이 없다. 소스 토큰은 소스 조회에만 사용하고 전송 기록 조회에는 기본 Actions 토큰을 사용한다. PR 브랜치의 코드를 환경 secret으로 실행하지 않는다.

## 1. 전송·배포 없는 Actions 검사

이 준비 PR을 검토 후 main에 병합해야 새 수동 workflow를 사용할 수 있다. 기존 `Collect dashboard snapshot`은 `dashboard-source` 환경을 지정하지 않으므로 이번 환경 secret 검증에 사용하지 않는다.

```sh
gh workflow run preflight.yml --repo modocai/fevercoach-migration-dashboard --ref main -f scope=publication
gh workflow run preflight.yml --repo modocai/fevercoach-migration-dashboard --ref main -f scope=notice
```

`scope=both`도 가능하다. 두 검사는 독립 실행되므로 Wix 실패가 알림 검사를 취소하지 않는다.

- **publication:** 공개 state·manifest 복원 또는 두 파일 모두 404인 최초 상태를 확인한다. Issues·Project·승인된 Wix main 파일을 조회하고 각 소스의 PASS/FAIL을 출력한다. 세 소스가 모두 성공해야 실제 배포와 같은 공개 필드·해시·용량·파일 목록 검증을 통과한 임시 사이트를 생성한다. 임시 사이트는 검사 후 삭제한다. 기존 데이터 보존으로 작동 가능한 상황이어도 활성화 검사에서는 소스 하나의 실패도 성공 처리하지 않는다.
- **notice:** #10 코드가 main에 있어야 한다. 실제 전송 기록 조회, Issues·Project 읽기와 메시지 구성을 확인한다. 둘 중 하나의 조회가 실패하면 알림 코드가 경고 메시지를 만들 수 있더라도 검사 자체는 실패한다. 메시지를 전송하거나 전송 기록을 저장하지 않는다. 기존 기록이 없다면 최초 실행 경로만 검증된 것이며 복원 성공으로 보고하지 않는다.
- 각 검사는 시작·종료 시 main SHA를 확인한다. 검사 중 main이 바뀌면 새 main에서 다시 실행한다.
- Wix main 파일이 없으면 publication 실패는 예상된 차단이다. Issues·Project PASS만으로 배포 준비 완료라고 하지 않는다.
- #10이 아직 없으면 notice는 해당 이유를 표시하고 실패한다. 미병합 코드 다운로드나 보호 우회는 하지 않는다.

기록할 근거: 실행 URL, 검사한 main SHA, 모드, 소스별 결과, 콘텐츠 측정 시각, 남은 차단 조건. 로컬 `gh`를 사용한 dry-run은 Actions 전용 인증 검증과 별도다.

## 2. #10 실제 실행 검증

1. 최신 수정본 리뷰와 전용 인증 준비를 확인하고 병합 시점을 조율한다. 토큰은 등록돼 있어도 만료·조직 승인·권한이 틀릴 수 있다.
2. main에서 위 notice 사전 검사와 기존 `daily-notice.yml` 수동 `dry_run=true`를 실행한다. 최신 완료 목록, 최초 실행 기준 표시, 저장된 콘텐츠 측정 시각과 Preview 설명을 확인한다.
3. 담당자가 승인한 실제 전송 1회에서 Discord 메시지 확인과 `engineering-daily-notice-receipt` artifact 저장을 확인한다. 이 문서와 사전 검사 실행은 실제 전송 승인이 아니다.
4. 후속 dry-run에서 실제 저장된 기록 복원을 확인하고, 같은 UTC 날짜의 정상 조회·전송 후 재실행이 중복을 보내지 않는지 승인된 검증으로 확인한다. API 성공·전송 성공·artifact 저장 성공을 각각 기록한다.
5. 전송 응답 유실 또는 artifact 업로드 실패는 무작정 재실행하지 않는다. 기존 메시지 확인과 전송 기록 복구가 먼저다.

## 3. #2 Pages 활성화

1. website #32·#35 검토와 통합 후 **main**의 Wix 파일 스키마·출처·시각을 확인한다. 파일을 main에 복사하는 것은 새 Wix 추출을 수행하는 일이 아니다.
2. publication 사전 검사를 통과시킨다. 첫 공개 배포 전에 인증·사이트 생성·공개 파일 검증을 완료한다.
3. 관리자가 main/워크플로 보호와 `github-pages`의 main 배포 제한을 확인한다. 준비 시점에는 `gh-pages`도 허용돼 있으므로 필요 여부를 검토한다.
4. 관리자가 Pages Source를 GitHub Actions로 전환하고 `DASHBOARD_AUTOUPDATE_ENABLED=true`를 설정한다. 기존 branch 배포와 겹치지 않게 한다.
5. `Publish current migration progress`를 main에서 실행한다. 성공한 배포의 HTML·state·manifest build ID, 최신 Issues·Project 집계, Wix main 출처를 확인한다. 콘텐츠 점수·측정 시각은 저장된 보고서와 같아야 한다.
6. 다음 예약 실행과 열린 브라우저 갱신을 확인한다. 실제 업무 변경으로 검증하며 완료율을 시험하려고 운영 이슈를 임의로 닫지 않는다. 실패 시 이전 배포 보존과 경고 표시도 확인한다.

이 과정을 통과하면 기존 범위의 작업 현황을 반영하기 위해 대시보드 main에 매번 커밋할 필요가 없다. 새 이슈 범위·화면·기준값 변경은 여전히 PR 대상이다. Wix 추출, 콘텐츠 비교 재실행, GA4/Search Console 수집은 이 검사나 자동 배포가 수행하지 않는다.

## 중단

대시보드는 활성화 변수를 false로 바꾸고 진행 중 배포도 확인한다. 이는 #10 알림을 중단하지 않는다. 알림 중단이 필요하면 별도로 daily-notice workflow를 비활성화하고 진행 중 실행·이미 전송된 메시지를 확인한다. 장애 시 검증된 이전 배포로 복구하며 강제 푸시·히스토리 재작성은 하지 않는다.

## 준비 코드 검증 기록

- 기존 main 기반 테스트 121개(기존 107 + 사전 검사 14), HTML 재현 검사 및 workflow actionlint 통과.
- #10 `d58d4319` 코드와 #11 `1c8dedc` 데이터·HTML을 임시 디렉터리에서 조합한 테스트 138개 및 HTML 재현 검사 통과. 실제 브랜치 병합이나 운영 배포는 아니다.
- 로컬 GitHub 로그인으로 실행한 읽기 전용 검사: 알림용 Issues·Project·메시지 구성 성공, 이전 전송 기록은 없어 최초 경로만 확인. publication의 Issues·Project는 성공했으나 승인된 Wix main 파일이 없어 실패했다.
- 위 로컬 실행은 전용 Actions secret의 검증이 아니다. 실제 Discord 전송, receipt 저장·복원, Pages 배포는 수행하지 않았다.
