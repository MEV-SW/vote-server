<!-- AI 지시문: 기능요청서를 입력으로 엔드포인트·request·response를 도출하라. 기존 API와 이름 규칙을 맞추고, 오류 response를 반드시 포함하라.
     표기: 요청/응답이라 쓰지 말고 request/response로, body를 뜻하면 "request body"라고 명시. 산문은 한 줄에 한 문장. 참조는 전부 링크(DEV-PROCESS §8). -->
# API스펙_생성자소유권

- 기능요청: [#4](https://github.com/MEV-SW/vote-server/issues/4)

Blocked by [#3](https://github.com/MEV-SW/vote-server/issues/3). 회사 토큰의 `sub` 또는 `local:{username}`이 `owner_id`가 된다.

전역 슈퍼관리자는 없다. `owner_id`가 없는 구 행은 로컬 로그인만 관리한다.

## 엔드포인트 목록
| Method | Path | 용도 | 인증 |
|---|---|---|---|
| POST | `/admin/polls` | 생성 시 `owner_id`/`owner_name` 기록 | Bearer |
| GET | `/admin/polls` | 내가 만든 항목만 | Bearer |
| GET/PATCH/DELETE | `/admin/polls/{poll_id}` 및 하위 | 소유자만 | Bearer · 소유자 |

## 상세
### POST /admin/polls
- Request: request body. 기존 생성 필드. 클라이언트가 `owner_id`를 넣어도 서버가 무시하고 현재 사용자로 넣는다.
- Response 201: `PollOut`.
- 오류: 401.
- flag: 없음

### GET /admin/polls
- Request: 없음.
- Response 200: `owner_id`가 현재 사용자인 목록. 로컬 계정은 `owner_id`가 null인 구 행도 포함한다. 회사 계정은 구 행을 보지 않는다.
- 오류: 401.
- flag: 없음

### GET/PATCH/DELETE `/admin/polls/{poll_id}` 및 문항·후보·대상자·결과·리셋
- Request: 기존과 동일.
- Response: 소유자면 기존과 동일.
- 오류: 403 `이 투표의 관리자가 아닙니다.` 소유자가 아니거나, 구 행을 회사 계정이 만질 때. 401. 404.
- flag: 없음
