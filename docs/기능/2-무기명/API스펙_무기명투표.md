<!-- AI 지시문: 기능요청서를 입력으로 엔드포인트·request·response를 도출하라. 기존 API와 이름 규칙을 맞추고, 오류 response를 반드시 포함하라.
     표기: 요청/응답이라 쓰지 말고 request/response로, body를 뜻하면 "request body"라고 명시. 산문은 한 줄에 한 문장. 참조는 전부 링크(DEV-PROCESS §8). -->
# API스펙_무기명투표

- 기능요청: [#2](https://github.com/MEV-SW/vote-server/issues/2)

프론트 프록시는 `/api` 접두를 떼고 아래 Path로 보낸다.

폼(`kind=form`)은 기명만 허용한다. 이 카드는 `kind=vote` + `identity_mode=secret`이다.

## 엔드포인트 목록
| Method | Path | 용도 | 인증 |
|---|---|---|---|
| POST | `/admin/polls` | 제한 투표를 `identity_mode=secret`로 생성 | Bearer |
| POST | `/polls/{poll_id}/verify` | PIN 자격 증명. 무기명이면 `ballot_token` 발급 | 없음 |
| GET | `/polls/{poll_id}/check` | 이미 투표했는지 | `ballot_token` (무기명) |
| POST | `/polls/{poll_id}/vote` | 순위 제출 | request body의 `ballot_token` |
| GET | `/admin/polls/{poll_id}/results` | 집계만. 개인 명단 없음 | Bearer |
| DELETE | `/admin/polls/{poll_id}/voters/{voter_id}/vote` | 개인 표 취소 | Bearer. 무기명이면 400 |

## 상세
### POST /admin/polls
- Request: request body. 제한 투표는 `identity_mode`=`secret` 또는 `identified`. 불특정은 서버가 `secret`으로 둔다.
- Response 201: `PollOut`에 `identity_mode`.
- 오류: 401. 422. 폼에 `secret`이면 이후 PATCH에서 400.
- flag: 없음

### POST /polls/{poll_id}/verify
- Request: request body. 기존 PIN 필드. 무기명이면 자격만 확인하고 선택지와 조인하지 않는다.
- Response 200:
```json
{
  "verified": true,
  "voter_token": null,
  "ballot_token": "<jwt typ=ballot>",
  "voter_name": "투표자",
  "already_voted": false,
  "pin_required": false,
  "pin_setup": false,
  "identity_mode": "secret"
}
```
이미 참여했으면 `ballot_token`은 null, `already_voted`는 true.
- 오류: 403 대상자 아님/PIN 불일치. 404.
- flag: 없음

### GET /polls/{poll_id}/check
- Request: query `fingerprint` 필수. 무기명 제한 투표는 query `ballot_token` 필수.
- Response 200: `{ "voted": true, "votes": [...] }`.
- 오류: 401 토큰 없음/불일치. 404.
- flag: 없음

### POST /polls/{poll_id}/vote
- Request: request body. 무기명 제한은 `ballot_token` 필수. `eligible_voter_id`를 ballot에 넣지 않는다. `ballot_token_hash`만 저장한다.
- Response 201: `{ "ok": true }`.
- 오류: 401 토큰. 409 이미 투표. 403 진행 중 아님.
- flag: 없음

### GET /admin/polls/{poll_id}/results
- Request: path `poll_id`.
- Response 200: 기존 집계 `ResultsOut`. 대상자별 투표 여부 조인은 제공하지 않는다.
- 오류: 401. 404.
- flag: 없음

### DELETE /admin/polls/{poll_id}/voters/{voter_id}/vote
- Request: path만.
- Response 200: 기명 제한 투표만.
- 오류: 400 무기명(`개인별 투표 취소를 지원하지 않습니다`). 401. 404.
- flag: 없음
