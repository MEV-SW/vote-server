<!-- AI 지시문: 기능요청서를 입력으로 엔드포인트·request·response를 도출하라. 기존 API와 이름 규칙을 맞추고, 오류 response를 반드시 포함하라.
     표기: 요청/응답이라 쓰지 말고 request/response로, body를 뜻하면 "request body"라고 명시. 산문은 한 줄에 한 문장. 참조는 전부 링크(DEV-PROCESS §8). -->
# API스펙_Keycloak앱접근

- 기능요청: [#3](https://github.com/MEV-SW/vote-server/issues/3)

회사 토큰은 앱 접근만 검사한다. 그 역할로 모든 투표를 관리하지 않는다. 소유권은 [#4](https://github.com/MEV-SW/vote-server/issues/4).

설정: `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN_ROLE`(비우면 유효한 회사 계정 전원), `AUTH_MODE`=`local`|`oidc`|`both`.

## 엔드포인트 목록
| Method | Path | 용도 | 인증 |
|---|---|---|---|
| GET | `/admin/auth/config` | 로그인 UI가 로컬/OIDC를 그릴지 | 없음 |
| POST | `/admin/login` | 로컬 아이디/비번 | 없음. `local_enabled`일 때만 |
| * | `/admin/*` (로그인·config 제외) | 관리 API | Bearer. 회사 JWT 또는 로컬 JWT |
| POST | `/polls/{poll_id}/verify-sso` | 제한 항목 자격 확인 | request body의 회사 `access_token` |

## 상세
### GET /admin/auth/config
- Request: 없음.
- Response 200:
```json
{
  "mode": "both",
  "local_enabled": true,
  "oidc_enabled": true,
  "issuer": "https://auth.example.com/realms/x",
  "client_id": "vote-web"
}
```
issuer/client_id는 OIDC가 꺼져 있으면 null.
- 오류: 없음.
- flag: 없음

### POST /admin/login
- Request: request body `{ "username", "password" }`.
- Response 200: `{ "access_token" }`.
- 오류: 400 로컬 로그인 비활성. 401 잘못된 계정.
- flag: 없음

### Bearer `/admin/*`
- Request: `Authorization: Bearer`. `oidc`/`both`이고 Keycloak이 켜져 있으면 회사 JWT를 먼저 검증한다. `KEYCLOAK_ADMIN_ROLE`이 있으면 그 역할이 있어야 한다.
- Response: 기존 관리 API와 동일. 회사 `sub`로 Admin 행을 만들거나 찾는다.
- 오류: 401 토큰 무효. 403 `이 앱에 접근 권한이 없습니다.` (역할 없음). 401이면 `both`에서만 로컬 JWT로 재시도.
- flag: 없음

### POST /polls/{poll_id}/verify-sso
- Request: request body `{ "access_token": "<회사 JWT>" }`.
- Response 200: 기존 `VerifyVoterResponse`. 기명이면 `voter_token`. 무기명이면 `ballot_token`([#2](https://github.com/MEV-SW/vote-server/issues/2)).
- 오류: 401 회사 토큰 무효. 403 진행 중 아님/대상 아님. 503 Keycloak 미설정. 404.
- flag: 없음
