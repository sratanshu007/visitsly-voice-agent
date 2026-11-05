from datetime import datetime, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from app.config import get_settings

settings = get_settings()


class CallSchedulerService:
    @staticmethod
    def get_current_ist_time() -> datetime:
        return datetime.now(settings.tz)

    @classmethod
    def is_within_calling_window(cls, dt: Optional[datetime] = None) -> bool:
        """Checks if datetime falls within allowed 09:00 - 21:00 IST window."""
        target_dt = dt or cls.get_current_ist_time()
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=settings.tz)
        else:
            target_dt = target_dt.astimezone(settings.tz)

        hour = target_dt.hour
        start = settings.CALLING_WINDOW_START_HOUR
        end = settings.CALLING_WINDOW_END_HOUR
        return start <= hour < end

    @classmethod
    def get_next_calling_window_start(cls, dt: Optional[datetime] = None) -> datetime:
        """Returns the start of the next 09:00 IST calling window."""
        target_dt = dt or cls.get_current_ist_time()
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=settings.tz)
        else:
            target_dt = target_dt.astimezone(settings.tz)

        start_hour = settings.CALLING_WINDOW_START_HOUR
        end_hour = settings.CALLING_WINDOW_END_HOUR

        if target_dt.hour < start_hour:
            # Earlier today: schedule for today 09:00 IST
            next_start = target_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        else:
            # At or after 21:00 IST (or during day if requested): tomorrow 09:00 IST
            tomorrow = target_dt.date() + timedelta(days=1)
            next_start = datetime(
                year=tomorrow.year,
                month=tomorrow.month,
                day=tomorrow.day,
                hour=start_hour,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=settings.tz,
            )
        return next_start

    @classmethod
    def calculate_next_retry(
        cls,
        current_attempt: int,
        base_time: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """
        Calculates retry time for no-answer/busy.
        - Retry up to MAX_RETRY_ATTEMPTS times (total attempts = 1 initial + max retries).
        - At least 2 hours apart.
        - Strictly within 09:00 - 21:00 IST.
        """
        if current_attempt > settings.MAX_RETRY_ATTEMPTS:
            return None

        now = base_time or cls.get_current_ist_time()
        if now.tzinfo is None:
            now = now.replace(tzinfo=settings.tz)
        else:
            now = now.astimezone(settings.tz)

        target = now + timedelta(hours=settings.RETRY_MIN_INTERVAL_HOURS)

        if cls.is_within_calling_window(target):
            return target
        else:
            return cls.get_next_calling_window_start(target)

