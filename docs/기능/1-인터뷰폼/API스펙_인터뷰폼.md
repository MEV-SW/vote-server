<!-- AI 지시문: 기능요청서를 입력으로 엔드포인트·request·response를 도출하라. 기존 API와 이름 규칙을 맞추고, 오류 response를 반드시 포함하라.
     표기: 요청/응답이라 쓰지 말고 request/response로, body를 뜻하면 "request body"라고 명시. 산문은 한 줄에 한 문장. 참조는 전부 링크(DEV-PROCESS §8). -->
# API스펙_인터뷰폼

- 기능요청: [#1](https://github.com/MEV-SW/vote-server/issues/1)

프론트 프록시는 `/api` 접두를 떼고 아래 Path로 보낸다.

문항 `type`: `short_text` | `long_text` | `single_choice` | `multi_choice` | `scale`.

## 엔드포인트 목록
| Method | Path | 용도 | 인증 |
|---|---|---|---|
| POST | `/admin/polls` | 폼 생성 (`kind=form`) | Bearer (앱 접근) |
| GET | `/admin/polls/{poll_id}` | 폼 상세(문항 포함) | Bearer |
| PATCH | `/admin/polls/{poll_id}` | 제목·상태 등 | Bearer · 소유자 |
| POST | `/admin/polls/{poll_id}/questions` | 문항 추가 | Bearer · 소유자 |
| PATCH | `/admin/polls/{poll_id}/questions/{question_id}` | 문항 수정 | Bearer · 소유자 |
| DELETE | `/admin/polls/{poll_id}/questions/{question_id}` | 문항 삭제 | Bearer · 소유자 |
| POST | `/admin/polls/{poll_id}/questions/{question_id}/options` | 보기 추가 | Bearer · 소유자 |
| PATCH | `/admin/polls/{poll_id}/questions/{question_id}/options/{option_id}` | 보기 수정 | Bearer · 소유자 |
| DELETE | `/admin/polls/{poll_id}/questions/{question_id}/options/{option_id}` | 보기 삭제 | Bearer · 소유자 |
| GET | `/admin/polls/{poll_id}/form-results` | 집계+개별 응답 | Bearer · 소유자 |
| GET | `/admin/polls/{poll_id}/form-results/csv` | CSV | Bearer · 소유자 |
| GET | `/polls/{poll_id}` | 참여용 폼(문항) | 없음 (active/closed만) |
| POST | `/polls/{poll_id}/responses` | 응답 제출 | fingerprint. 제한이면 voter_token |
| GET | `/polls/{poll_id}/form-results` | 공개 집계 (주관식 원문 없음) | 없음 (closed만) |
| GET | `/polls/{poll_id}/check` | 이미 제출했는지 | fingerprint · voter_token |

## 상세
### POST /admin/polls
- Request: request body. `title` 필수. `kind`=`form`. `candidates`는 빈 배열. `identity_mode`는 서버가 `identified`로 고정.
- Response 201: `PollOut` (`id`, `kind`, `questions`, `status`=`draft` 등).
- 오류: 401 미인증. 422 검증 실패.
- flag: 없음

### GET /admin/polls/{poll_id}
- Request: path `poll_id`.
- Response 200: `PollOut` (문항·보기 포함).
- 오류: 401. 403 소유자 아님 (`이 투표의 관리자가 아닙니다.`). 404.
- flag: 없음

### PATCH /admin/polls/{poll_id}
- Request: request body 부분 갱신. `status`를 `active`로 올리려면 문항 1개 이상.
- Response 200: `PollOut`.
- 오류: 400 문항 없음 / 폼에 `identity_mode=secret`. 401. 403. 404.
- flag: 없음

### POST /admin/polls/{poll_id}/questions
- Request: request body. `title`, `type` 필수. `required` 기본 true. `single_choice`/`multi_choice`는 `options` 2개 이상. `scale`은 `scale_min` < `scale_max`.
- Response 201: `QuestionOut`.
- 오류: 400 폼이 아님. 401. 403. 404. 422.
- flag: 없음

### PATCH /admin/polls/{poll_id}/questions/{question_id}
- Request: request body. `title`/`help_text`/`required`/`order_num`/`scale_min`/`scale_max`.
- Response 200: `QuestionOut`.
- 오류: 400 폼이 아님. 401. 403. 404.
- flag: 없음

### DELETE /admin/polls/{poll_id}/questions/{question_id}
- Request: path만.
- Response 204.
- 오류: 400 폼이 아님. 401. 403. 404.
- flag: 없음

### POST /admin/polls/{poll_id}/questions/{question_id}/options
- Request: request body `{ "label": "보기" }`.
- Response 201: `QuestionOptionOut`.
- 오류: 400. 401. 403. 404.
- flag: 없음

### PATCH /admin/polls/{poll_id}/questions/{question_id}/options/{option_id}
- Request: request body `{ "label"?, "order_num"? }`.
- Response 200: `QuestionOptionOut`.
- 오류: 400. 401. 403. 404.
- flag: 없음

### DELETE /admin/polls/{poll_id}/questions/{question_id}/options/{option_id}
- Request: path만.
- Response 204.
- 오류: 400. 401. 403. 404.
- flag: 없음

### GET /admin/polls/{poll_id}/form-results
- Request: path `poll_id`.
- Response 200:
```json
{
  "total_responses": 1,
  "eligible_count": 0,
  "participation_rate": 0,
  "questions": [{"question_id": 1, "title": "...", "type": "single_choice", "required": true, "response_count": 1, "option_counts": [{"option_id": 1, "label": "A", "count": 1}], "scale_avg": null, "scale_counts": {}, "texts": []}],
  "responses": [{"ballot_id": 1, "submitted_at": "2026-09-14T00:00:00Z", "voter_name": "홍길동", "voter_email": null, "answers": []}]
}
```
- 오류: 400 폼이 아님. 401. 403. 404.
- flag: 없음

### GET /admin/polls/{poll_id}/form-results/csv
- Request: path `poll_id`.
- Response 200: `text/csv`.
- 오류: 400. 401. 403. 404.
- flag: 없음

### GET /polls/{poll_id}
- Request: path `poll_id`.
- Response 200: `PollOut` (문항 포함).
- 오류: 403 `Poll is not available` (draft). 404.
- flag: 없음

### POST /polls/{poll_id}/responses
- Request: request body.
```json
{
  "fingerprint": "abcdefgh",
  "voter_token": null,
  "answers": [{"question_id": 1, "text_value": "답", "scale_value": null, "option_ids": []}]
}
```
제한 폼은 `voter_token` 필요.
- Response 201: `{ "ok": true }`.
- 오류: 400 폼이 아님/필수 미응답. 403 진행 중이 아님. 409 이미 제출. 404.
- flag: 없음

### GET /polls/{poll_id}/form-results
- Request: path `poll_id`.
- Response 200: `FormResultsOut`에서 `responses`는 비우고, 주관식 `texts`는 비운다. 객관식·척도 집계만.
- 오류: 400 폼이 아님. 403 종료 전. 404.
- flag: 없음

### GET /polls/{poll_id}/check
- Request: query `fingerprint` 필수. `voter_token` 선택.
- Response 200: `{ "voted": true, "answers": null }`.
- 오류: 404.
- flag: 없음
