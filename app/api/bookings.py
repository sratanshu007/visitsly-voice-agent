import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, mask_phone
from app.models.database import get_db
from app.models.entities import Booking, Call
from app.models.schemas import (
    BookingConfirmedRequest,
    BookingResponse,
    CallOutcome,
)
from app.services.consent import ConsentService, ConsentError
from app.services.optout import OptOutService
from app.services.call_scheduler import CallSchedulerService
from app.services.plivo_service import PlivoService
from app.services.webhook_sender import WebhookSenderService

logger = logging.getLogger("voice_agent.api.bookings")
router = APIRouter(prefix="/api/bookings", tags=["Bookings"])
settings = get_settings()


async def verify_api_key(
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
) -> None:
    expected = settings.API_KEY
    if not expected:
        return

    provided = x_api_key
    if not provided and authorization and authorization.startswith("Bearer "):
        provided = authorization[7:].strip()

    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key header",
        )


@router.post(
    "/confirmed",
    response_model=BookingResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
    summary="Accept confirmed booking from SaaS and queue outbound AI voice call",
)
async def booking_confirmed(
    req: BookingConfirmedRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by SaaS when a customer books a property site-visit.
    1. Validates booking idempotency.
    2. Validates and audits customer call consent.
    3. Checks opt-out registry.
    4. Evaluates calling window (09:00 - 21:00 IST).
    5. Dispatches call immediately or schedules for next window.
    """
    logger.info(
        f"Received booking confirmation: booking_id={req.booking_id}, "
        f"phone={mask_phone(req.phone)}, property={req.property_name}"
    )

    # 1. Idempotency Check
    stmt = select(Booking).where(Booking.booking_id == req.booking_id)
    res = await db.execute(stmt)
    existing_booking = res.scalar_one_or_none()
    if existing_booking:
        logger.info(f"Duplicate booking_id={req.booking_id}. Returning existing booking status.")
        call_stmt = select(Call).where(Call.booking_id == req.booking_id).order_by(Call.created_at.desc())
        call_res = await db.execute(call_stmt)
        last_call = call_res.scalar_one_or_none()
        return BookingResponse(
            status="EXISTS",
            message="Booking already received and processed.",
            booking_id=req.booking_id,
            call_id=last_call.id if last_call else None,
        )

    # 2. Consent Validation
    try:
        ConsentService.validate_request_consent(req.consent)
    except ConsentError as e:
        logger.warning(f"Consent rejected for booking {req.booking_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 3. Create Booking & Consent DB records
    booking = Booking(
        booking_id=req.booking_id,
        customer_name=req.customer_name,
        phone=req.phone,
        property_name=req.property_name,
        visit_datetime=req.visit_datetime,
        language=req.language or "hi",
        status="QUEUED",
    )
    db.add(booking)
    await db.flush()

    await ConsentService.record_consent(
        db=db,
        booking_id=req.booking_id,
        consent_schema=req.consent,
    )

    # 4. Check Opt-Out Status
    is_opted_out = await OptOutService.is_opted_out(db, req.phone)
    if is_opted_out:
        booking.status = "OPTED_OUT"
        call = Call(
            booking_id=req.booking_id,
            status="FAILED",
            outcome=CallOutcome.NOT_INTERESTED.value,
            transcript_summary="Customer phone is on opt-out registry. Call refused.",
        )
        db.add(call)
        await db.commit()

        # Notify SaaS via webhook
        await WebhookSenderService.send_call_result_webhook(
            db=db,
            booking_id=req.booking_id,
            outcome=CallOutcome.NOT_INTERESTED,
            attempts=1,
            duration=0,
            transcript_summary="Customer phone is on opt-out list.",
        )

        return BookingResponse(
            status="OPTED_OUT",
            message="Customer has opted out of voice calls. No call placed.",
            booking_id=req.booking_id,
            call_id=call.id,
        )

    # 5. Evaluate Calling Window (09:00 - 21:00 IST)
    within_window = CallSchedulerService.is_within_calling_window()
    call = Call(
        booking_id=req.booking_id,
        status="QUEUED",
        attempts=1,
    )
    db.add(call)
    await db.flush()

    if within_window:
        logger.info(f"Within calling window. Initiating outbound call for booking {req.booking_id}")
        try:
            plivo_resp = await PlivoService.place_outbound_call(
                to_phone=req.phone,
                call_id=call.id,
                booking_id=req.booking_id,
            )
            call.plivo_call_uuid = plivo_resp.get("request_uuid") or plivo_resp.get("call_uuid")
            call.status = "INITIATED"
            booking.status = "IN_PROGRESS"
            await db.commit()

            return BookingResponse(
                status="CALL_INITIATED",
                message="Call placed successfully via Plivo.",
                booking_id=req.booking_id,
                call_id=call.id,
            )
        except Exception as e:
            logger.error(f"Failed to place Plivo call: {e}")
            call.status = "FAILED"
            booking.status = "FAILED"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Plivo telephony call dispatch failed: {str(e)}",
            )
    else:
        # Schedule for next window start (09:00 IST)
        scheduled_for = CallSchedulerService.get_next_calling_window_start()
        call.status = "SCHEDULED"
        call.retry_at = scheduled_for
        booking.status = "SCHEDULED"
        await db.commit()

        logger.info(
            f"Outside calling window (09:00 - 21:00 IST). Call for {req.booking_id} "
            f"scheduled for {scheduled_for.isoformat()}."
        )

        return BookingResponse(
            status="CALL_SCHEDULED",
            message=f"Outside calling hours. Call scheduled for {scheduled_for.strftime('%Y-%m-%d %I:%M %p IST')}.",
            booking_id=req.booking_id,
            call_id=call.id,
            scheduled_for=scheduled_for,
        )

