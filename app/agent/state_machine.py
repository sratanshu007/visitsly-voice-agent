import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from app.config import get_settings
from app.models.schemas import CallOutcome
from app.agent.prompts import (
    get_system_prompt,
    get_opening_line,
    SILENCE_REPROMPT_MESSAGE,
    SILENCE_HANGUP_MESSAGE,
    MAX_DURATION_HANGUP_MESSAGE,
)
from app.agent.date_parser import parse_hindi_relative_datetime

logger = logging.getLogger("voice_agent.state_machine")

OPT_OUT_PATTERNS = [
    r"call\s*mat\s*karo",
    r"phone\s*mat\s*karo",
    r"dobara\s*call\s*mat",
    r"don'?t\s*call",
    r"stop\s*calling",
    r"remove\s*(my\s*)?number",
    r"unsubscribe",
    r"opt\s*out",
    r"number\s*hatao",
    r"block\s*karo",
]


class CallStateMachine:
    """Manages the conversational turn lifecycle, silence detection, and outcome state."""

    def __init__(
        self,
        call_id: str,
        booking_id: str,
        customer_name: str,
        phone: str,
        property_name: str,
        visit_datetime: str,
    ):
        self.settings = get_settings()
        self.call_id = call_id
        self.booking_id = booking_id
        self.customer_name = customer_name
        self.phone = phone
        self.property_name = property_name
        self.visit_datetime = visit_datetime

        self.messages: List[Dict[str, str]] = []
        self.turn_count = 0
        self.outcome: Optional[CallOutcome] = None
        self.new_datetime: Optional[str] = None
        self.notes: Optional[str] = None

        self.silence_count = 0
        self.max_silence_prompts = self.settings.MAX_SILENCE_PROMPTS
        self.silence_timeout = self.settings.SILENCE_TIMEOUT_SECONDS
        self.max_duration = self.settings.MAX_CALL_DURATION_SECONDS

        self.start_time = time.perf_counter()
        self.is_finalized = False
        self.is_terminated = False
        self.opt_out_detected = False

    def build_system_prompt(self) -> str:
        now_ist = datetime.now(self.settings.tz).strftime("%Y-%m-%d %I:%M %p IST")
        return get_system_prompt(
            company_name=self.settings.COMPANY_NAME,
            customer_name=self.customer_name,
            property_name=self.property_name,
            visit_datetime=self.visit_datetime,
            current_datetime_ist=now_ist,
        )

    def get_initial_greeting(self) -> str:
        greeting = get_opening_line(
            company_name=self.settings.COMPANY_NAME,
            customer_name=self.customer_name,
            property_name=self.property_name,
            visit_datetime=self.visit_datetime,
        )
        self.messages.append({"role": "assistant", "content": greeting})
        self.turn_count += 1
        return greeting

    def check_opt_out(self, text: str) -> bool:
        lower = text.lower()
        for pat in OPT_OUT_PATTERNS:
            if re.search(pat, lower):
                self.opt_out_detected = True
                self.outcome = CallOutcome.NOT_INTERESTED
                self.notes = "Customer requested opt-out / DND"
                self.is_finalized = True
                return True
        return False

    def handle_silence_prompt(self) -> Tuple[bool, str]:
        """
        Returns (should_hangup, speech_text).
        If user was silent 6s -> reprompt. After 2 reprompts -> hangup.
        """
        self.silence_count += 1
        if self.silence_count > self.max_silence_prompts:
            self.is_terminated = True
            if not self.outcome:
                self.outcome = CallOutcome.NO_ANSWER
            return True, SILENCE_HANGUP_MESSAGE
        return False, SILENCE_REPROMPT_MESSAGE

    def reset_silence(self) -> None:
        self.silence_count = 0

    def check_duration_exceeded(self) -> Tuple[bool, str]:
        elapsed = time.perf_counter() - self.start_time
        if elapsed >= self.max_duration:
            self.is_terminated = True
            if not self.outcome:
                self.outcome = CallOutcome.CALLBACK_REQUESTED
            return True, MAX_DURATION_HANGUP_MESSAGE
        return False, ""

    def finalize_call(
        self,
        outcome: CallOutcome,
        new_datetime: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        self.outcome = outcome
        self.new_datetime = new_datetime
        self.notes = notes
        self.is_finalized = True
        logger.info(
            f"[Call {self.call_id}] Finalized outcome={outcome.value}, "
            f"new_datetime={new_datetime}, notes={notes}"
        )

    def get_call_duration_seconds(self) -> int:
        return int(time.perf_counter() - self.start_time)

