import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
from dateutil import parser as dt_parser


WEEKDAYS = {
    "monday": 0, "somvar": 0, "somvaar": 0,
    "tuesday": 1, "mangal": 1, "mangalvar": 1, "mangalvaar": 1,
    "wednesday": 2, "budh": 2, "budhvar": 2, "budhvaar": 2,
    "thursday": 3, "guru": 3, "guruvar": 3, "veervar": 3, "brihaspativar": 3,
    "friday": 4, "shukra": 4, "shukravar": 4, "jumma": 4,
    "saturday": 5, "shani": 5, "shanivar": 5, "shanivaar": 5,
    "sunday": 6, "itvar": 6, "itvaar": 6, "ravivar": 6, "ravivaar": 6,
}


def parse_hindi_relative_datetime(
    text: str,
    base_datetime: Optional[datetime] = None,
    tz_name: str = "Asia/Kolkata",
) -> Optional[Tuple[datetime, str]]:
    """
    Parses Hindi/Hinglish and English relative date/time expressions into an
    Asia/Kolkata aware datetime and a friendly confirmation string.

    Examples:
    - 'kal shaam 5 baje' -> Tomorrow at 17:00
    - 'parso subah 11 baje' -> Day after tomorrow at 11:00
    - 'sunday ko 4 pm' -> Next Sunday at 16:00
    - 'aaj dopahar 2:30 baje' -> Today at 14:30
    """
    if not text:
        return None

    tz = ZoneInfo(tz_name)
    now = base_datetime or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    lower = text.lower()
    target_date = now.date()
    date_matched = False

    # 1. Check relative day words
    if "parso" in lower or "day after tomorrow" in lower:
        target_date = now.date() + timedelta(days=2)
        date_matched = True
    elif "tarso" in lower:
        target_date = now.date() + timedelta(days=3)
        date_matched = True
    elif "kal" in lower or "tomorrow" in lower:
        target_date = now.date() + timedelta(days=1)
        date_matched = True
    elif "aaj" in lower or "today" in lower:
        target_date = now.date()
        date_matched = True
    else:
        # Check weekdays
        for w_name, w_idx in WEEKDAYS.items():
            if re.search(r"\b" + re.escape(w_name) + r"\b", lower):
                days_ahead = (w_idx - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Next week's weekday if mentioned
                target_date = now.date() + timedelta(days=days_ahead)
                date_matched = True
                break

    # 2. Check time of day modifier
    is_pm = False
    is_am = False
    if "shaam" in lower or "evening" in lower or "dopahar" in lower or "afternoon" in lower or "raat" in lower or "pm" in lower:
        is_pm = True
    elif "subah" in lower or "morning" in lower or "am" in lower:
        is_am = True

    # 3. Check special Hindi time words: dedh (1:30), dhai (2:30), sadhe
    target_hour = 11  # default morning visit
    target_minute = 0
    time_matched = False

    if "dedh" in lower:
        target_hour = 1 if is_am else 13
        target_minute = 30
        time_matched = True
    elif "dhai" in lower:
        target_hour = 2 if is_am else 14
        target_minute = 30
        time_matched = True
    else:
        # Regex for hour e.g. "5 baje", "5:30 baje", "11:00 am", "4 pm"
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(?:baje|am|pm|o'?clock)?", lower)
        if match:
            h = int(match.group(1))
            m = int(match.group(2)) if match.group(2) else 0

            # Only consider valid hours
            if 1 <= h <= 24:
                # If "sadhe" preceded it e.g. "sadhe teen"
                if "sadhe" in lower and m == 0:
                    m = 30

                if is_pm and h < 12:
                    h += 12
                elif is_am and h == 12:
                    h = 0
                elif not is_pm and not is_am and h < 8:
                    # e.g., "5 baje" without am/pm for a site visit usually means 5:00 PM (17:00)
                    h += 12

                target_hour = h
                target_minute = m
                time_matched = True

    # Fallback: standard dateutil parse if neither matched
    if not date_matched and not time_matched:
        try:
            dt = dt_parser.parse(text, fuzzy=True, default=now)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            human_text = dt.strftime("%d %B %Y ko %I:%M %p")
            return dt, human_text
        except Exception:
            return None

    parsed_dt = datetime(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=target_hour,
        minute=target_minute,
        tzinfo=tz,
    )

    day_label = (
        "Kal" if target_date == now.date() + timedelta(days=1)
        else "Parso" if target_date == now.date() + timedelta(days=2)
        else "Aaj" if target_date == now.date()
        else parsed_dt.strftime("%A")
    )
    time_label = parsed_dt.strftime("%I:%M %p")
    date_str = parsed_dt.strftime("%d %B %Y")
    friendly_str = f"{day_label} {time_label} ({date_str})"

    return parsed_dt, friendly_str
