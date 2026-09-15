import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import can_manage_poll, get_current_admin_from_token
from app.database import get_db
from app.models import Admin, Poll
from app.services.poll_events import subscribe_poll_events

router = APIRouter(tags=["events"])


def _poll_or_404(db: Session, poll_id: int) -> Poll:
    poll = db.query(Poll).filter(Poll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    return poll


async def _sse_stream(poll_id: int, request: Request):
    async def generate():
        yield ": connected\n\n"
        try:
            async for event in subscribe_poll_events(poll_id):
                if await request.is_disconnected():
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/polls/{poll_id}/events")
async def public_poll_events(poll_id: int, request: Request, db: Session = Depends(get_db)):
    _poll_or_404(db, poll_id)
    return await _sse_stream(poll_id, request)


@router.get("/admin/polls/{poll_id}/events")
async def admin_poll_events(
    poll_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin_from_token),
):
    poll = _poll_or_404(db, poll_id)
    if not can_manage_poll(_admin, poll):
        raise HTTPException(status_code=403, detail="이 투표의 관리자가 아닙니다.")
    return await _sse_stream(poll_id, request)
