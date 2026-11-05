import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class CallOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    WRONG_PERSON = "WRONG_PERSON"
    FAILED = "FAILED"
    BUSY = "BUSY"
    NO_ANSWER = "NO_ANSWER"
    VOICEMAIL = "VOICEMAIL"


class ConsentSchema(BaseModel):
    given: bool = Field(..., description="Whether customer gave explicit calling consent")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Consent timestamp")
    ip: str = Field(default="127.0.0.1", description="IP address where consent was granted")
    text: str = Field(..., min_length=5, description="Exact consent disclosure copy")


class BookingConfirmedRequest(BaseModel):
    booking_id: str = Field(..., min_length=1, max_length=120, description="Unique booking ID from SaaS")
    customer_name: str = Field(..., min_length=1, max_length=120, description="Customer name")
    phone: str = Field(..., description="Customer phone in E.164 format")
    property_name: str = Field(..., min_length=1, max_length=200, description="Property/Project name")
    visit_datetime: str = Field(..., description="Scheduled visit date and time (ISO or formatted)")
    language: str = Field(default="hi", description="Conversation language (hi, en, hinglish)")
    consent: ConsentSchema

    @field_validator("phone")
    @classmethod
    def validate_e164(cls, v: str) -> str:
        clean = re.sub(r"[\s\-\(\)]", "", v)
        if not clean.startswith("+"):
            # If 10 digits provided for India, normalize to +91
            if len(clean) == 10 and clean.isdigit():
                clean = f"+91{clean}"
            else:
                clean = f"+{clean}"
        if not re.match(r"^\+[1-9]\d{6,14}$", clean):
            raise ValueError(f"Invalid E.164 phone number: {v}")
        return clean


class BookingResponse(BaseModel):
    status: str
    message: str
    booking_id: str
    call_id: Optional[str] = None
    scheduled_for: Optional[datetime] = None


class FinalizeCallArgs(BaseModel):
    outcome: CallOutcome
    new_datetime: Optional[str] = Field(None, description="ISO format or formatted string if rescheduled")
    notes: Optional[str] = Field(None, description="Summary notes or questions requested")


class OutboundWebhookPayload(BaseModel):
    booking_id: str
    outcome: CallOutcome
    new_datetime: Optional[str] = None
    attempts: int
    duration: int
    transcript_summary: str
    recording_url: Optional[str] = None
    # Compatibility fields for Visitsly-Backend
    execution_id: Optional[str] = None
    status: str
    summary: str
    transcript: Optional[str] = None
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    user_data: Dict[str, Any] = Field(default_factory=dict)


class OptOutRequest(BaseModel):
    phone: str
    reason: Optional[str] = "Customer requested opt-out"


class OptOutResponse(BaseModel):
    phone_hash: str
    status: str
    created_at: datetime

