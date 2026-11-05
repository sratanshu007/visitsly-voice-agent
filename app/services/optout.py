import hashlib
import logging
import re
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import OptOut
from app.config import mask_phone

logger = logging.getLogger("voice_agent.services.optout")


def hash_phone(phone: str) -> str:
    """Normalizes phone number and returns SHA-256 hash."""
    clean = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not clean.startswith("+"):
        if len(clean) == 10 and clean.isdigit():
            clean = f"+91{clean}"
        else:
            clean = f"+{clean}"
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


class OptOutService:
    @staticmethod
    async def is_opted_out(db: AsyncSession, phone: str) -> bool:
        """Checks if normalized phone hash exists in opt_outs table."""
        p_hash = hash_phone(phone)
        stmt = select(OptOut).where(OptOut.phone_hash == p_hash)
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            logger.info(f"Phone {mask_phone(phone)} is opted out (hash={p_hash[:10]}...)")
            return True
        return False

    @staticmethod
    async def add_opt_out(db: AsyncSession, phone: str, reason: str = "Customer request") -> OptOut:
        """Adds a phone number hash to opt-out registry."""
        p_hash = hash_phone(phone)
        stmt = select(OptOut).where(OptOut.phone_hash == p_hash)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        opt_out = OptOut(phone_hash=p_hash, reason=reason)
        db.add(opt_out)
        await db.commit()
        logger.info(f"Added opt-out for {mask_phone(phone)} (hash={p_hash[:10]}...)")
        return opt_out

    @staticmethod
    async def remove_opt_out(db: AsyncSession, phone: str) -> bool:
        """Removes a phone number hash from opt-out registry."""
        p_hash = hash_phone(phone)
        stmt = delete(OptOut).where(OptOut.phone_hash == p_hash)
        res = await db.execute(stmt)
        await db.commit()
        return res.rowcount > 0

    @staticmethod
    async def list_opt_outs(db: AsyncSession, limit: int = 100) -> list[OptOut]:
        stmt = select(OptOut).order_by(OptOut.created_at.desc()).limit(limit)
        res = await db.execute(stmt)
        return list(res.scalars().all())

