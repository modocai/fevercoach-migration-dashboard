# 자동 갱신 도입안과 운영 절차

## 이번 변경의 범위

기존 6단계·28개 작업, 디자인과 문구는 유지한다. 저장소 루트의 두 HTML과 템플릿은 이번 변경에서 수정하지 않는다. 별도 작업 브랜치의 PR로 검토하며, 병합·운영 활성화는 저장소 관리자가 결정한다. 강제 푸시나 자동 커밋은 사용하지 않는다.

자동 갱신도 정적 사이트로 배포한다. 서버나 클라이언트용 인증 토큰을 추가하는 대신 Actions가 원본을 읽고 HTML을 다시 만든다. 브라우저는 같은 사이트의 공개 `manifest.json`만 확인한다.

```
승인된 웹사이트 main + Project #11
              ↓ 읽기 전용 / 별도 인증 환경
     검증 → 공개 필드 선별 → HTML 생성
              ↓ 전용 Pages artifact
         GitHub Pages 배포
              ↓ 공개 manifest 확인
       열려 있는 화면의 버전 갱신
```

## 동작과 실패 처리

- 활성화 후 main 푸시, 수동 실행, 매시 7·22·37·52분에 수집한다. 일정은 UTC 기준이며 Actions 사정에 따라 늦거나 누락될 수 있다. 즉시 반영이나 15분 이내 반영을 보장하지 않는다.
- 기존 이슈 번호만 조회한다. 완료율은 기존의 `closed + completed` 기준, 진행 상태는 Project의 승인된 매핑을 사용한다. 새 이슈를 자동으로 범위에 넣거나 단계·운영 전환을 승인하지 않는다.
- Wix 집계는 웹사이트 **main**의 `docs/wix-export-status.json`만 사용한다. 미병합 PR #29를 사용하는 기존 수동 수집 경로와 다르다. 해당 파일이 승인·병합되기 전에는 최초 자동 배포를 완료할 수 없다.
- 최초 실행에서는 세 원본을 모두 정상 수집해야 한다. 이후에는 마지막으로 공개 배포한 `state.json`과 일치하는 `manifest.json`을 복원한다. 저장소에 남은 오래된 스냅샷을 복구 자료로 사용하지 않는다.
- 복원 자료의 형식·범위·해시가 맞지 않거나 공개 파일이 서로 다르면 배포를 중단한다. 파일이 둘 다 404인 경우에만 최초 도입으로 처리한다. 일시적 네트워크 장애를 빈 초기 상태로 취급하지 않는다.
- 일부 또는 전체 원본 조회가 실패하면 해당 원본의 마지막 정상 데이터와 성공 시각을 보존하고 실패를 표시한다. 이 공개 파일을 배포한 뒤 별도 report 작업을 실패 처리한다. 빌드를 먼저 실패시켜 경고 배포까지 막지 않는다.
- 배포 전체를 `pages` 동시 실행 그룹으로 직렬화하고, 수집 전과 배포 직전에 main SHA와 실행 순서를 확인한다. main이 바뀌었거나 동일·상위 세대가 배포되어 있으면 중단한다. 워크플로 파일을 삭제·재생성해 실행 번호를 초기화하지 않는다.
- 브라우저는 활성 탭에서 60초 간격과 포커스 복귀 시 공개 manifest를 확인한다. 버전이 바뀌면 `?v=<해시>`로 이동하고 필터·열어 둔 검증 항목·스크롤을 복원한다. 세션 저장소가 차단되어도 URL로 같은 버전의 반복 이동을 막는다. CDN이 이전 HTML을 계속 주면 안내를 표시한다.
- 조회 실패 시 현재 화면을 유지한다. 원본 최종 성공 시각이 45분 이상 오래되면 안내한다. JavaScript를 끄거나 로컬 파일로 열어도 HTML을 읽을 수 있다.

## 최신 main의 콘텐츠 지표·일일 알림 연결

대표님이 추가한 `compare_content.py`, `content_metric.py`, `notify_discord.py`와 화면 생성기·템플릿·루트 HTML은 수정하지 않는다. 점수 계산, 배포 전 0%, 오류 URL의 분모 포함, 100% 반올림 방지와 기존 화면을 유지한다.

자동 빌드는 현재 main에 검토·저장된 `data/content-comparison.json`을 읽는다. `public_content.py`가 기존 점수 검증기를 재사용하고 URL·시각·숫자를 확인한 뒤 정해진 보고서 필드만 남긴다. 임의 추가 필드와 원문 오류는 공개하지 않는다. 정상 보고서를 화면 생성기의 네 번째 인자로 전달하고 링크 대상 JSON도 artifact에 포함한다. 기존에 보고서를 전달하지 않아 자동 배포에서 ‘미측정’으로 바뀌던 문제를 방지한다.

공개 `state.json`은 콘텐츠 보고서가 포함된 **schema version 2**다. 전체 내용의 build ID를 검증하므로 보고서만 바뀌어도 화면 갱신 대상이 된다. manifest는 기존 version 1을 유지한다. state는 512 KiB, 전체 artifact는 2 MiB 제한을 유지하며 초과하면 배포를 중단한다. 대규모 보고서가 이 제한에 걸리면 압축·분리 설계를 검토해야 하며 제한을 임의로 해제하지 않는다. PR #2의 이전 version 1 state는 운영 배포된 적이 없으며, 발견할 경우 자동 변환하거나 초기화하지 않고 실패 처리한다.

`Daily engineering completion notice`의 예약 시간·권한·웹훅은 유지한다. 변경은 `DASHBOARD_AUTOUPDATE_ENABLED` 변수 전달과 `notify_published.py` 실행 연결 두 곳이다.

- 비활성: 기존 `notify_discord.py`의 저장 자료 기반 실행에 그대로 위임한다.
- 활성: 같은 공개 사이트의 state·manifest를 인증 헤더 없이 읽는다. 일치하는 build ID, 데이터 형식과 작업 범위를 검증하고 기존 `make_message`와 `send_notice`를 사용한다. 저장된 리포 스냅샷은 읽지 않는다.
- 공개 배포와 원본별 확인 시각을 표시한다. 45분 이상 지난 자료나 원본 실패가 있으면 마지막 확인값이라는 경고를 덧붙인다. 유효한 이전 배포가 있으면 그 사실을 명시해 보고한다.
- 파일 없음·불일치·손상·작업 범위 변경·네트워크 장애는 전송 실패다. 활성화 후 첫 배포가 끝나기 전에 알림이 실행돼도 이전 리포 수치로 대체하지 않는다.
- 알림이 데이터를 새로 수집하거나 콘텐츠를 재비교하지 않는다. 수집·배포와 알림 사이에 새 배포가 진행되어 두 파일의 버전이 달라지면 혼합된 수치를 보내지 않고 실패한다.

오전 9시 KST는 GitHub 예약 시각이다. 실행 지연·누락은 이 연결 수정으로 해결되지 않으며, 정확한 시각이 필수라면 운영자가 별도 스케줄러 도입을 결정해야 한다. 승인된 대상 사이트의 전체 콘텐츠 비교는 기존 절차대로 수행하고 결과를 PR로 검토한다. 자동화는 그 결과를 보존·배포하며 새 점수를 임의로 생성하지 않는다.

## 공개 데이터와 인증 경계

공개 artifact에는 `index.html`, `migration-dashboard.html`, `state.json`, `manifest.json`, `assets/auto-refresh.js`, `.nojekyll`, `data/content-comparison.json`만 넣는다. 디렉터리는 `assets/`와 `data/`만 허용한다. 링크·추가 파일·추가 디렉터리와 과도한 용량을 거부한다. 저장소 전체, API 원문, Actions 캐시를 업로드하지 않는다.

동적 공개 값은 승인된 이슈 번호·상태, Project 상태 enum, 수집 시각, Wix의 허용된 개수·완료 플래그·출처 SHA로 제한한다. 담당자 계정·개인 프로필·새 이슈 제목·본문·댓글·날짜 필드·원본 인벤토리·로컬 경로·DNS 상세는 제외한다. Wix 출처 링크는 고정된 저장소와 검증한 SHA로 다시 만든다. 알 수 없는 오류는 고정 코드로 치환한다. 저장소의 템플릿·계획·기준값은 이미 공개된 검토 대상 소스다. 이후 수정 시에도 공개 가능 여부를 확인해야 한다.

원본 API 응답은 수집 프로세스 메모리에서만 처리한다. 예외 본문과 GitHub CLI stdout/stderr를 공개 로그에 출력하지 않는다. 테스트는 합성 자료를 사용한다. 공개 artifact와 Actions 로그는 누구나 읽을 수 있다는 전제로 운영한다.

원본 인증은 `dashboard-source` **환경 secret**의 `DASHBOARD_SOURCE_TOKEN`으로만 전달한다. 저장소 공용 secret이나 개인 `gh` OAuth 토큰을 복사하지 않는다. 수집 step만 이 값을 받고 배포 job은 받지 않는다. checkout 자격 증명은 저장하지 않으며, 사용 action은 전체 SHA로 고정한다. 코드 변경 권한자가 악의적으로 워크플로를 수정하면 secret을 읽을 수 있으므로, 토큰 마스킹만으로 보호된다고 가정하지 않는다.

장기 운영은 설치 범위·권한을 제한한 GitHub App이 권장된다. 현재 워크플로는 환경 secret 토큰을 받으므로 App을 쓴다면 만료 전 갱신 경로를 추가해야 한다. 초기 대안은 사용자 소유의 만료일 있는 fine-grained PAT다. 조직을 resource owner로 선택하고 웹사이트 저장소 Contents/Issues 읽기 및 조직 Projects 읽기를 부여한다. 실제 조직 정책과 GraphQL 호출 가능 여부를 확인한다. 불필요한 쓰기 권한, 전체 저장소 접근, 영구 토큰을 부여하지 않는다. 토큰 값은 채팅·PR·로그에 적지 않는다.

## 활성화 전 관리자가 할 일

이 PR은 자동 갱신을 **기본 비활성** 상태로 추가한다. 이 문서는 설정 변경이나 운영 배포를 완료했다는 보고가 아니다.

1. 대표님의 화면·내용 변경을 먼저 반영하고 이 PR을 검토한다. 디자인은 `templates/dashboard.html`, 생성 로직·문구는 `scripts/build_dashboard.py`, 계획은 `data/plan.json`에서 수정한다. 루트 HTML만 고치면 이후 재생성 시 사라지므로 생성 결과도 함께 검증한다.
2. main에 직접 쓰기를 제한하고 PR 검토 및 필수 CI를 요구하는 보호 규칙을 설정한다. 특히 `.github/workflows/**`와 수집·출력 코드는 신뢰할 수 있는 검토자 승인을 거치게 한다. 환경·보호 설정은 관리자 권한이 필요하다. 현재 main이 보호되지 않은 상태에서는 원본 secret을 등록하거나 활성화하지 않는다.
3. `dashboard-source` 환경을 만들고 배포 가능 브랜치를 main으로만 제한한다. 매 수집마다 승인을 요구하면 무인 실행이 되지 않으므로, 검토된 main 코드만 접근하는 보호 경계를 먼저 만든다. 이 환경에만 최소 권한·만료일이 있는 원본 토큰을 등록한다. `github-pages` 환경도 main만 허용한다.
4. 웹사이트 main에 Wix 공개 집계 파일이 존재하고 스키마가 유효한지 확인한다. 비공개 Project 접근과 실제 상태 매핑도 점검한다. 로컬 `gh`의 `read:project` 갱신은 Actions 인증을 대신하지 않는다.
5. 새 PR을 정상 병합하고 CI를 확인한다. Pages 소스는 이 시점까지 기존 branch 배포를 유지한다. 이 PR은 루트 HTML을 바꾸지 않으므로 기존 화면을 보존한다.
6. Pages의 Build and deployment Source를 **GitHub Actions**로 전환하고 저장소 variable `DASHBOARD_AUTOUPDATE_ENABLED=true`를 설정한다. 전환 중에는 이전 화면이 잠시 유지되거나 갱신이 멈출 수 있으므로 관리자가 실행 결과를 확인한다. 다른 Pages 배포 워크플로가 있다면 중복을 해소한다.
7. main의 `Publish current migration progress`를 수동 실행한다. 공개 페이지, manifest, state의 build ID 일치, 비밀값이 없는 artifact, 실제 Project 상태와 완료율, Wix 출처 main SHA, Pages 배포 성공을 확인한다. 이 확인을 위해 운영 이슈를 임의 변경하지 않는다. 합의된 실제 업무 변경이나 별도 시험 자료로 다음 갱신을 확인한다.
8. 승인된 일일 알림 실행에서 공개 화면과 콘텐츠·이슈 완료율, 원본 확인 시각이 같은지 확인한다. 이어지는 예약 실행과 열린 브라우저 갱신을 확인한 뒤 자동 운영 완료로 판단한다. 원본 토큰 만료·정기 실행 상태를 확인할 담당자를 정한다. 공개 저장소는 활동이 60일 없으면 예약 실행이 비활성화될 수 있다.

이슈·Project·승인된 Wix 집계가 바뀔 때마다 대시보드에 커밋할 필요는 없다. Wix 추출 실행 자체, Lighthouse 재측정, Search Console·GA4 자료 수집, 새 작업 범위 추가와 검증 승인까지 자동화하는 변경은 아니다. 정적 계획·기준값·디자인을 바꿀 때는 계속 PR이 필요하다.

## 중단과 복구

`DASHBOARD_AUTOUPDATE_ENABLED`를 false로 바꾸고 실행 중인 발행 워크플로도 중단한다. variable만 바꾸면 이미 시작한 job이 즉시 멈추지는 않는다. 필요하면 검증된 이전 공개 artifact를 재배포하거나 Pages 소스를 기존 main 루트 branch 방식으로 되돌린다. 후자는 저장소에 저장된 시점의 화면으로 돌아간다. 강제 푸시·히스토리 재작성·자동 롤백 커밋은 사용하지 않는다. 복구 배포의 완료도 확인한다. 자격 증명 유출이 의심되면 해당 토큰을 폐기·교체하고 공개 로그·artifact를 점검한다.

## 검증 방법과 남은 확인

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_dashboard.py --check
node tests/autoupdate-browser.cjs
git diff --check
```

추가 통합 테스트는 보고서 → HTML·결과 JSON → 일일 알림의 수치 일치, 보고서 변경 시 버전 변경, 기존 비활성 알림 유지, 손상·오래된 배포 처리를 검증한다. 브라우저에서도 0%에서 50%로 갱신되는 화면과 결과 JSON 링크를 확인한다.

Python 테스트는 공개 필드 선별, 미승인 원본 거부, 복원·보존, 부분 응답, 최초 실패, 해시·세대 검증과 출력 파일 경계를 확인한다. Chromium 테스트는 합성 서버에서 자동 이동·상태 복원, 오래된 CDN 응답·무한 이동 방지, 오프라인·손상·과대 응답, 세션 저장소 차단, JavaScript 비활성·로컬 파일과 데스크톱/노트북 화면을 확인한다. 토큰을 요구하는 CI 테스트는 없다.

실제 환경 secret 제한, Pages 전환, 원본 인증, 운영 CDN과 예약 실행은 관리자 설정·승인 후 별도로 확인해야 한다. 로컬 테스트 통과를 운영 연동 완료로 보고하지 않는다.

공식 근거: [Pages 사용자 지정 워크플로](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [예약 실행 제한](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [Actions 보안](https://docs.github.com/en/actions/reference/security/secure-use), [PAT 관리](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
