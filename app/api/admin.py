from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.database import get_db
from app.models.schemas import OptOutRequest, OptOutResponse
from app.services.optout import OptOutService

router = APIRouter(prefix="/api/admin", tags=["Admin & Compliance"])
settings = get_settings()


async def verify_admin_key(
    x_admin_key: str = Header(None, alias="X-Admin-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
) -> None:
    expected = settings.ADMIN_API_KEY
    if not expected:
        return

    provided = x_admin_key
    if not provided and authorization and authorization.startswith("Bearer "):
        provided = authorization[7:].strip()

    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Admin API Key",
        )


@router.post(
    "/opt-out",
    response_model=OptOutResponse,
    dependencies=[Depends(verify_admin_key)],
    summary="Add a phone number to opt-out / DND registry",
)
async def add_opt_out(
    req: OptOutRequest,
    db: AsyncSession = Depends(get_db),
):
    record = await OptOutService.add_opt_out(db, req.phone, req.reason or "Admin opt-out")
    return OptOutResponse(
        phone_hash=record.phone_hash,
        status="OPTED_OUT",
        created_at=record.created_at,
    )


@router.delete(
    "/opt-out/{phone}",
    dependencies=[Depends(verify_admin_key)],
    summary="Remove a phone number from opt-out registry",
)
async def remove_opt_out(
    phone: str,
    db: AsyncSession = Depends(get_db),
):
    removed = await OptOutService.remove_opt_out(db, phone)
    if not removed:
        raise HTTPException(status_code=404, detail="Phone number hash not found in opt-out registry")
    return {"status": "REMOVED", "phone": phone}


@router.get(
    "/opt-out",
    dependencies=[Depends(verify_admin_key)],
    summary="List recent opted-out phone hashes",
)
async def list_opt_outs(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    items = await OptOutService.list_opt_outs(db, limit=limit)
    return [
        {"phone_hash": it.phone_hash, "reason": it.reason, "created_at": it.created_at}
        for it in items
    ]

