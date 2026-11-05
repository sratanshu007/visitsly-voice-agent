import logging
import uuid
from typing import Dict, Optional, Any
import httpx
from app.config import get_settings, mask_phone
from app.services.rate_limiter import AsyncTokenBucketRateLimiter

logger = logging.getLogger("voice_agent.services.plivo")

settings = get_settings()
plivo_rate_limiter = AsyncTokenBucketRateLimiter(calls_per_second=settings.PLIVO_CPS)


class PlivoService:
    @staticmethod
    async def place_outbound_call(
        to_phone: str,
        call_id: str,
        booking_id: str,
    ) -> Dict[str, Any]:
        """Places an outbound call using Plivo REST API under configured CPS rate limits."""
        curr_settings = get_settings()
        await plivo_rate_limiter.acquire()

        auth_id = curr_settings.PLIVO_AUTH_ID.strip().strip('"').strip("'")
        auth_token = curr_settings.PLIVO_AUTH_TOKEN.strip().strip('"').strip("'")
        caller_id = curr_settings.PLIVO_CALLER_ID.strip().strip('"').strip("'")
        base_url = curr_settings.webhook_base_url

        answer_url = f"{base_url}/plivo/answer?call_id={call_id}&booking_id={booking_id}"
        hangup_url = f"{base_url}/plivo/hangup?call_id={call_id}&booking_id={booking_id}"
        machine_url = f"{base_url}/plivo/machine?call_id={call_id}"

        # If Plivo credentials are mock, test, or missing, simulate outbound call ID
        if (
            not auth_id
            or not auth_token
            or auth_id.startswith("your_")
            or auth_id.startswith("test_")
            or curr_settings.ENVIRONMENT == "testing"
        ):
            logger.info(
                f"[Plivo Mock] Simulating outbound call to {mask_phone(to_phone)} "
                f"(call_id={call_id}, booking_id={booking_id})"
            )
            return {
                "message": "call fired (mock)",
                "request_uuid": str(uuid.uuid4()),
                "api_id": str(uuid.uuid4()),
                "mock": True,
            }

        endpoint = f"https://api.plivo.com/v1/Account/{auth_id}/Call/"
        payload = {
            "from": caller_id,
            "to": to_phone,
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": hangup_url,
            "hangup_method": "POST",
        }

        # Only enable AMD if configured (avoid aggressive false-positive hangup on real mobile phones)
        amd_mode = getattr(curr_settings, "PLIVO_MACHINE_DETECTION", "none").lower()
        if amd_mode in ("true", "hangup"):
            payload["machine_detection"] = amd_mode
            payload["machine_detection_url"] = machine_url
            payload["machine_detection_method"] = "POST"

        logger.info(
            f"Plivo dialing {mask_phone(to_phone)} using Auth ID {auth_id[:8]}... | "
            f"Answer URL: {answer_url}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    endpoint,
                    json=payload,
                    auth=(auth_id, auth_token),
                )
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    logger.info(
                        f"Plivo outbound call initiated: request_uuid={data.get('request_uuid')} "
                        f"to {mask_phone(to_phone)}"
                    )
                    return data
                else:
                    logger.error(
                        f"Plivo API returned {resp.status_code}: {resp.text} "
                        f"for destination {mask_phone(to_phone)} with Auth ID {auth_id[:8]}..."
                    )
                    raise RuntimeError(f"Plivo call failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Error placing Plivo call: {e}")
            raise

    @staticmethod
    async def hangup_call(call_uuid: str) -> bool:
        """Terminates an active Plivo call via REST API."""
        curr_settings = get_settings()
        auth_id = curr_settings.PLIVO_AUTH_ID.strip().strip('"').strip("'")
        auth_token = curr_settings.PLIVO_AUTH_TOKEN.strip().strip('"').strip("'")
        if not auth_id or not auth_token or auth_id.startswith("your_"):
            logger.info(f"[Plivo Mock] Hangup call_uuid={call_uuid}")
            return True

        endpoint = f"https://api.plivo.com/v1/Account/{auth_id}/Call/{call_uuid}/"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.delete(endpoint, auth=(auth_id, auth_token))
                return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Failed to hangup Plivo call {call_uuid}: {e}")
            return False
