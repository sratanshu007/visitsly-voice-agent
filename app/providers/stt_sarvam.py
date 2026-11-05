import asyncio
import io
import logging
from typing import Callable, Optional
import httpx
from app.config import get_settings
from app.providers.base import STTProvider, STTResult
from app.realtime.audio_utils import mulaw_to_wav

logger = logging.getLogger("voice_agent.stt.sarvam")


class SarvamSTT(STTProvider):
    """Sarvam Saaras STT API integration for Indian languages (Hindi / Hinglish)."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.SARVAM_API_KEY
        self.on_transcript_callback: Optional[Callable[[STTResult], None]] = None
        self.buffer = bytearray()
        self.is_connected = False

    async def connect(self, on_transcript: Callable[[STTResult], None]) -> None:
        self.on_transcript_callback = on_transcript
        self.is_connected = True
        self.buffer.clear()
        logger.info("Sarvam STT initialized")

    async def send_audio(self, mulaw_chunk: bytes) -> None:
        if not self.is_connected or not mulaw_chunk:
            return
        self.buffer.extend(mulaw_chunk)
        if len(self.buffer) >= 24000:
            await self.flush()

    async def flush(self) -> None:
        if len(self.buffer) < 3200 or not self.api_key:
            self.buffer.clear()
            return

        audio_data = bytes(self.buffer)
        self.buffer.clear()
        wav_bytes = mulaw_to_wav(audio_data, sample_rate=8000)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                files = {"file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")}
                data = {"model": "saaras:v1", "language_code": "hi-IN"}
                headers = {"api-subscription-key": self.api_key}

                resp = await client.post("https://api.sarvam.ai/speech-to-text", files=files, data=data, headers=headers)
                if resp.status_code == 200:
                    result_json = resp.json()
                    transcript = result_json.get("transcript", "").strip()
                    if transcript and self.on_transcript_callback:
                        res = STTResult(text=transcript, is_final=True, confidence=0.9)
                        if asyncio.iscoroutinefunction(self.on_transcript_callback):
                            await self.on_transcript_callback(res)
                        else:
                            self.on_transcript_callback(res)
        except Exception as e:
            logger.error(f"Sarvam STT error: {e}")

    async def disconnect(self) -> None:
        self.is_connected = False
        self.buffer.clear()

