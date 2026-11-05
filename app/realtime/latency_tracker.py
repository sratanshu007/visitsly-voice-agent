import logging
import time
from typing import Optional

logger = logging.getLogger("voice_agent.latency")


class TurnLatencyTracker:
    """Tracks and logs per-turn latencies for Voice AI pipeline tuning."""

    def __init__(self, turn_index: int = 1):
        self.turn_index = turn_index
        self.user_speech_end_time: Optional[float] = None
        self.stt_received_time: Optional[float] = None
        self.llm_start_time: Optional[float] = None
        self.llm_first_token_time: Optional[float] = None
        self.tts_start_time: Optional[float] = None
        self.tts_first_byte_time: Optional[float] = None
        self.first_audio_dispatched_time: Optional[float] = None

    def mark_user_speech_end(self) -> None:
        self.user_speech_end_time = time.perf_counter()

    def mark_stt_received(self) -> None:
        self.stt_received_time = time.perf_counter()

    def mark_llm_start(self) -> None:
        self.llm_start_time = time.perf_counter()

    def mark_llm_first_token(self) -> None:
        if self.llm_first_token_time is None:
            self.llm_first_token_time = time.perf_counter()

    def mark_tts_start(self) -> None:
        if self.tts_start_time is None:
            self.tts_start_time = time.perf_counter()

    def mark_tts_first_byte(self) -> None:
        if self.tts_first_byte_time is None:
            self.tts_first_byte_time = time.perf_counter()

    def mark_first_audio_dispatched(self) -> None:
        if self.first_audio_dispatched_time is None:
            self.first_audio_dispatched_time = time.perf_counter()

    @property
    def stt_latency_ms(self) -> Optional[float]:
        if self.user_speech_end_time and self.stt_received_time:
            return round((self.stt_received_time - self.user_speech_end_time) * 1000, 1)
        return None

    @property
    def llm_ttft_ms(self) -> Optional[float]:
        if self.llm_start_time and self.llm_first_token_time:
            return round((self.llm_first_token_time - self.llm_start_time) * 1000, 1)
        return None

    @property
    def tts_ttfb_ms(self) -> Optional[float]:
        if self.tts_start_time and self.tts_first_byte_time:
            return round((self.tts_first_byte_time - self.tts_start_time) * 1000, 1)
        return None

    @property
    def total_turnaround_ms(self) -> Optional[float]:
        start = self.user_speech_end_time or self.stt_received_time
        if start and self.first_audio_dispatched_time:
            return round((self.first_audio_dispatched_time - start) * 1000, 1)
        return None

    def log_turn_summary(self) -> None:
        total = self.total_turnaround_ms
        stt = self.stt_latency_ms or 0.0
        ttft = self.llm_ttft_ms or 0.0
        ttfb = self.tts_ttfb_ms or 0.0

        logger.info(
            f"[Turn {self.turn_index} Latency] Total: {total}ms | "
            f"STT: {stt}ms | LLM TTFT: {ttft}ms | TTS TTFB: {ttfb}ms"
        )

