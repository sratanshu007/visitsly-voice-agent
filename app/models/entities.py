import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(120), unique=True, nullable=False, index=True)
    customer_name = Column(String(120), nullable=False)
    phone = Column(String(32), nullable=False, index=True)
    property_name = Column(String(200), nullable=False)
    visit_datetime = Column(String(100), nullable=False)
    language = Column(String(20), default="hi")
    status = Column(String(40), default="QUEUED", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consent = relationship("Consent", back_populates="booking", uselist=False, cascade="all, delete-orphan")
    calls = relationship("Call", back_populates="booking", cascade="all, delete-orphan")


class Consent(Base):
    __tablename__ = "consents"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(120), ForeignKey("bookings.booking_id", ondelete="CASCADE"), nullable=False, index=True)
    given = Column(Boolean, nullable=False, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    ip = Column(String(45), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    booking = relationship("Booking", back_populates="consent")


class Call(Base):
    __tablename__ = "calls"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(120), ForeignKey("bookings.booking_id", ondelete="CASCADE"), nullable=False, index=True)
    plivo_call_uuid = Column(String(64), nullable=True, index=True)
    status = Column(String(40), default="QUEUED", index=True)  # QUEUED, IN_PROGRESS, COMPLETED, BUSY, NO_ANSWER, FAILED
    attempts = Column(Integer, default=1)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Integer, default=0)  # seconds
    outcome = Column(String(50), nullable=True, index=True)  # CONFIRMED, RESCHEDULED, CANCELLED, etc.
    new_datetime = Column(String(100), nullable=True)
    recording_url = Column(String(500), nullable=True)
    transcript_summary = Column(Text, nullable=True)
    retry_at = Column(DateTime, nullable=True, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking = relationship("Booking", back_populates="calls")
    transcripts = relationship("Transcript", back_populates="call", cascade="all, delete-orphan")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    call_id = Column(String(36), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    text = Column(Text, nullable=False)
    latency_ms = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    call = relationship("Call", back_populates="transcripts")


class OptOut(Base):
    __tablename__ = "opt_outs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    phone_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256 hash of normalized E.164 phone
    reason = Column(String(255), default="Customer request")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    event_id = Column(String(100), unique=True, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(30), default="PENDING", index=True)  # PENDING, DELIVERED, FAILED
    attempts = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

