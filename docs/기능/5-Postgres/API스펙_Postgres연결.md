<!-- AI 지시문: 기능요청서를 입력으로 엔드포인트·request·response를 도출하라. 기존 API와 이름 규칙을 맞추고, 오류 response를 반드시 포함하라.
     표기: 요청/응답이라 쓰지 말고 request/response로, body를 뜻하면 "request body"라고 명시. 산문은 한 줄에 한 문장. 참조는 전부 링크(DEV-PROCESS §8). -->
# API스펙_Postgres연결

- 기능요청: [#5](https://github.com/MEV-SW/vote-server/issues/5)

HTTP Path는 바꾸지 않는다. 클라이언트가 보는 request/response는 기존과 같다.

연결 계약: `DATABASE_URL`이 `postgresql+psycopg://` 동기 URL이다. `postgresql+asyncpg`는 쓰지 않는다. 기동 시 `create_all` + `ensure_schema`. `public` 스키마 CREATE 권한은 앱이 부여하지 않는다.

## 엔드포인트 목록
| Method | Path | 용도 | 인증 |
|---|---|---|---|
| — | (변경 없음) | 기존 투표/폼/관리 API 그대로 | 기존과 동일 |

## 상세
### 기존 API
- Request: 변경 없음.
- Response 200: 변경 없음. SQLite와 Postgres에서 같은 JSON 필드.
- 오류: DB 연결 실패는 기동 실패. 엔드포인트 4xx 계약은 바꾸지 않는다.
- flag: 없음
