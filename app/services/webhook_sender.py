import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.entities import WebhookEvent
from app.models.schemas import OutboundWebhookPayload, CallOutcome

logger = logging.getLogger("voice_agent.services.webhook")
settings = get_settings()


def compute_hmac_signature(secret: str, payload_bytes: bytes) -> str:
    """Computes SHA-256 HMAC signature for webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


class WebhookSenderService:
    @staticmethod
    async def send_call_result_webhook(
        db: AsyncSession,
        booking_id: str,
        outcome: CallOutcome,
        attempts: int,
        duration: int,
        transcript_summary: str,
        new_datetime: Optional[str] = None,
        recording_url: Optional[str] = None,
        transcript_full: Optional[str] = None,
        target_url: Optional[str] = None,
    ) -> bool:
        """
        Dispatches outbound call result to SaaS with HMAC signature and exponential backoff retry.
        Compatible with both standard SaaS webhooks and Visitsly-Backend format.
        """
        url = target_url or settings.SAAS_WEBHOOK_URL
        secret = settings.SAAS_WEBHOOK_SECRET

        # Parse extracted date and time for Visitsly-Backend compatibility
        visit_date = None
        visit_time = None
        if new_datetime:
            parts = new_datetime.split(" ")
            if len(parts) >= 1:
                visit_date = parts[0]
            if len(parts) >= 2:
                visit_time = parts[1]

        interested = outcome in (CallOutcome.CONFIRMED, CallOutcome.RESCHEDULED)

        payload = OutboundWebhookPayload(
            booking_id=booking_id,
            outcome=outcome,
            new_datetime=new_datetime,
            attempts=attempts,
            duration=duration,
            transcript_summary=transcript_summary,
            recording_url=recording_url,
            # Visitsly-Backend compatible attributes:
            execution_id=str(uuid.uuid4()),
            status="completed" if outcome in (CallOutcome.CONFIRMED, CallOutcome.RESCHEDULED, CallOutcome.CANCELLED) else outcome.value.lower(),
            summary=transcript_summary,
            transcript=transcript_full or transcript_summary,
            extracted_data={
                "interested": interested,
                "visit_date": visit_date,
                "visit_time": visit_time,
                "outcome": outcome.value,
            },
            user_data={
                "propai_call_id": booking_id,
                "booking_id": booking_id,
            },
        )

        payload_dict = payload.model_dump()
        payload_bytes = json.dumps(payload_dict, default=str).encode("utf-8")
        signature = compute_hmac_signature(secret, payload_bytes)

        event_id = str(uuid.uuid4())
        webhook_event = WebhookEvent(
            event_id=event_id,
            event_type="call.outcome",
            payload=payload_dict,
            status="PENDING",
            attempts=0,
        )
        db.add(webhook_event)
        await db.commit()

        # Fire async retry worker
        asyncio.create_task(
            WebhookSenderService._dispatch_with_retry(
                event_id=event_id,
                url=url,
                payload_bytes=payload_bytes,
                signature=signature,
            )
        )
        return True

    @staticmethod
    async def _dispatch_with_retry(
        event_id: str,
        url: str,
        payload_bytes: bytes,
        signature: str,
        max_retries: int = 4,
    ) -> None:
        headers = {
            "Content-Type": "application/json",
            "X-Signature-SHA256": signature,
            "X-Hub-Signature-256": f"sha256={signature}",
            "User-Agent": "Visitsly-Voice-Agent/1.0",
        }

        delay = 1.0
        from app.models.database import AsyncSessionLocal
        from sqlalchemy import select

        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, content=payload_bytes, headers=headers)
                    if resp.status_code in (200, 201, 202, 204):
                        logger.info(f"[Webhook {event_id}] Delivered to {url} on attempt {attempt}")
                        async with AsyncSessionLocal() as session:
                            stmt = select(WebhookEvent).where(WebhookEvent.event_id == event_id)
                            res = await session.execute(stmt)
                            event = res.scalar_one_or_none()
                            if event:
                                event.status = "DELIVERED"
                                event.attempts = attempt
                                event.last_attempt_at = datetime.utcnow()
                                await session.commit()
                        return
                    else:
                        logger.warning(
                            f"[Webhook {event_id}] HTTP {resp.status_code} from {url} on attempt {attempt}"
                        )
            except Exception as e:
                logger.warning(f"[Webhook {event_id}] Failed on attempt {attempt}: {e}")

            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2.0

        # Mark as FAILED if all retries exhausted
        async with AsyncSessionLocal() as session:
            stmt = select(WebhookEvent).where(WebhookEvent.event_id == event_id)
            res = await session.execute(stmt)
            event = res.scalar_one_or_none()
            if event:
                event.status = "FAILED"
                event.attempts = max_retries
                event.last_attempt_at = datetime.utcnow()
                event.error = f"Max retries exhausted to {url}"
                await session.commit()

