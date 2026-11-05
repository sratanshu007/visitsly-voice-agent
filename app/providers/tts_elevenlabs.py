import asyncio
import logging
from typing import AsyncGenerator
import httpx
from app.config import get_settings
from app.providers.base import TTSProvider
from app.realtime.audio_utils import split_into_chunks

logger = logging.getLogger("voice_agent.tts.elevenlabs")


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs streaming TTS with native ulaw_8000 output."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.ELEVENLABS_API_KEY
        self.voice_id = self.settings.ELEVENLABS_VOICE_ID or "cgSgspJ2msm6clMCkdW9"
        self.model_id = self.settings.ELEVENLABS_MODEL or "eleven_flash_v2_5"

    async def stream_tts(self, text: str) -> AsyncGenerator[bytes, None]:
        clean_text = text.strip()
        if not clean_text or not self.api_key:
            return

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream?output_format=ulaw_8000"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": clean_text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code == 200:
                        async for chunk in resp.aiter_bytes():
                            for frame in split_into_chunks(chunk, chunk_size=160):
                                yield frame
                                await asyncio.sleep(0.005)
                    else:
                        error_body = await resp.aread()
                        logger.error(f"ElevenLabs TTS failed: {resp.status_code} - {error_body.decode(errors='ignore')}")
        except Exception as e:
            logger.error(f"ElevenLabs TTS synthesis error: {e}")

