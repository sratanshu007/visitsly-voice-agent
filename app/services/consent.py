import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import Consent, Booking
from app.models.schemas import ConsentSchema

logger = logging.getLogger("voice_agent.services.consent")


class ConsentError(ValueError):
    """Raised when call consent validation fails."""
    pass


class ConsentService:
    @staticmethod
    def validate_request_consent(consent: ConsentSchema) -> None:
        """Enforces that consent was explicitly granted."""
        if not consent.given:
            raise ConsentError("Call consent was not granted by the customer.")
        if not consent.text or len(consent.text.strip()) < 5:
            raise ConsentError("Consent disclosure text must be provided and valid.")

    @staticmethod
    async def record_consent(
        db: AsyncSession,
        booking_id: str,
        consent_schema: ConsentSchema,
    ) -> Consent:
        """Stores consent audit trail in the database."""
        consent_rec = Consent(
            booking_id=booking_id,
            given=consent_schema.given,
            timestamp=consent_schema.timestamp,
            ip=consent_schema.ip,
            text=consent_schema.text,
        )
        db.add(consent_rec)
        await db.flush()
        return consent_rec

    @staticmethod
    async def has_valid_consent(db: AsyncSession, booking_id: str) -> bool:
        """Checks if a valid consent record exists in the DB for this booking."""
        stmt = select(Consent).where(
            Consent.booking_id == booking_id,
            Consent.given == True,
        )
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()
        return record is not None

