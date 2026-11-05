import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, Query, Request, Response, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db, AsyncSessionLocal
from app.models.entities import Call, Booking
from app.models.schemas import CallOutcome
from app.realtime.stream_handler import PlivoStreamHandler
from app.services.call_scheduler import CallSchedulerService
from app.services.webhook_sender import WebhookSenderService

logger = logging.getLogger("voice_agent.api.plivo")
router = APIRouter(prefix="/plivo", tags=["Plivo Telephony"])
settings = get_settings()


@router.post("/answer", summary="Plivo Answer URL callback")
async def plivo_answer(
    request: Request,
    call_id: Optional[str] = Query(None),
    booking_id: Optional[str] = Query(None),
):
    """
    Called by Plivo media server when customer answers the outbound call.
    Returns Plivo XML response with bidirectional <Stream>.
    """
    # Plivo may also pass parameters in form body
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass

    resolved_call_id = call_id or form_data.get("call_id") or ""
    resolved_booking_id = booking_id or form_data.get("booking_id") or ""

    # In XML, query parameters must be escaped as &amp;
    stream_url = f"{settings.stream_ws_url}?call_id={resolved_call_id}"
    if resolved_booking_id:
        stream_url += f"&amp;booking_id={resolved_booking_id}"

    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Response>\n'
        f'    <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">{stream_url}</Stream>\n'
        '</Response>'
    )

    logger.info(
        f"Plivo call answered: call_id={resolved_call_id}, booking_id={resolved_booking_id}. "
        f"Streaming to {stream_url}"
    )
    return Response(content=xml_content, media_type="application/xml")


@router.websocket("/stream")
async def plivo_stream_ws(
    websocket: WebSocket,
    call_id: Optional[str] = Query(None),
    booking_id: Optional[str] = Query(None),
):
    """WebSocket endpoint handling real-time bi-directional audio streaming with Plivo."""
    resolved_call_id = call_id or websocket.query_params.get("call_id") or ""
    resolved_booking_id = (
        booking_id
        or websocket.query_params.get("booking_id")
        or websocket.query_params.get("amp;booking_id")
        or ""
    )

    handler = PlivoStreamHandler(
        websocket=websocket,
        call_id=resolved_call_id,
        booking_id=resolved_booking_id,
    )
    await handler.run()


@router.post("/hangup", summary="Plivo Call Status / Hangup Callback")
async def plivo_hangup(
    request: Request,
    call_id: Optional[str] = Query(None),
    booking_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Called by Plivo when call ends or fails (completed, busy, no-answer, failed).
    Handles retry policies if busy/no-answer.
    """
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass

    call_uuid = form_data.get("CallUUID", "")
    call_status = str(form_data.get("CallStatus", "")).lower()
    hangup_cause = form_data.get("HangupCause", "")
    duration_str = form_data.get("Duration") or form_data.get("BillDuration") or "0"

    try:
        duration = int(duration_str)
    except ValueError:
        duration = 0

    resolved_call_id = call_id or form_data.get("call_id")
    resolved_booking_id = booking_id or form_data.get("booking_id")

    logger.info(
        f"Plivo hangup: call_uuid={call_uuid}, status={call_status}, "
        f"cause={hangup_cause}, duration={duration}s"
    )

    # Find call record
    stmt = select(Call)
    if resolved_call_id:
        stmt = stmt.where(Call.id == resolved_call_id)
    elif call_uuid:
        stmt = stmt.where(Call.plivo_call_uuid == call_uuid)

    res = await db.execute(stmt)
    call_rec = res.scalar_one_or_none()
    if not call_rec:
        logger.warning(f"Hangup callback received for unknown call: uuid={call_uuid}")
        return {"status": "ok"}

    call_rec.ended_at = datetime.utcnow()
    call_rec.duration = duration
    attempts = call_rec.attempts or 1

    # Check if call was busy or unanswered
    if call_status in ("busy", "no-answer", "timeout", "rejected"):
        next_retry = CallSchedulerService.calculate_next_retry(current_attempt=attempts)
        if next_retry:
            call_rec.status = "RETRY_SCHEDULED"
            call_rec.retry_at = next_retry
            call_rec.outcome = CallOutcome.BUSY.value if call_status == "busy" else CallOutcome.NO_ANSWER.value
            await db.commit()
            logger.info(
                f"[Call {call_rec.id}] Marked for retry attempt #{attempts + 1} at {next_retry.isoformat()}"
            )
        else:
            # Retries exhausted -> mark FAILED and trigger fallback webhook
            call_rec.status = "FAILED"
            call_rec.outcome = CallOutcome.FAILED.value
            call_rec.transcript_summary = (
                f"Customer unreachable after {attempts} attempts ({call_status}). "
                f"Triggering WhatsApp/SMS fallback."
            )
            await db.commit()

            logger.warning(
                f"[Call {call_rec.id}] Max retries exhausted. Sending fallback webhook to SaaS."
            )
            await WebhookSenderService.send_call_result_webhook(
                db=db,
                booking_id=call_rec.booking_id,
                outcome=CallOutcome.FAILED,
                attempts=attempts,
                duration=duration,
                transcript_summary=call_rec.transcript_summary,
            )
    else:
        # Normal completion or handled by websocket
        if call_rec.status != "COMPLETED":
            call_rec.status = "COMPLETED"
            await db.commit()

    return {"status": "processed"}


@router.post("/machine", summary="Plivo Answering Machine Detection Callback")
async def plivo_machine_detection(
    request: Request,
    call_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Plivo Answering Machine Detection (AMD) callback.
    If voicemail/machine detected, hangup immediately and schedule retry.
    """
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass

    call_uuid = form_data.get("CallUUID", "")
    machine = str(form_data.get("Machine", "")).lower()

    logger.info(f"Plivo AMD callback: call_uuid={call_uuid}, machine={machine}")

    if machine in ("true", "hangup", "machine"):
        # Voicemail detected
        resolved_call_id = call_id or form_data.get("call_id")
        stmt = select(Call)
        if resolved_call_id:
            stmt = stmt.where(Call.id == resolved_call_id)
        else:
            stmt = stmt.where(Call.plivo_call_uuid == call_uuid)

        res = await db.execute(stmt)
        call_rec = res.scalar_one_or_none()
        if call_rec:
            call_rec.status = "VOICEMAIL"
            call_rec.outcome = CallOutcome.VOICEMAIL.value
            attempts = call_rec.attempts or 1
            next_retry = CallSchedulerService.calculate_next_retry(current_attempt=attempts)
            if next_retry:
                call_rec.retry_at = next_retry
            await db.commit()

    return {"status": "machine_processed"}

