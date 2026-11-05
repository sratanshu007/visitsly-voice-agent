import asyncio
import base64
import logging
from typing import AsyncGenerator
import httpx
import miniaudio
from app.config import get_settings
from app.providers.base import TTSProvider
from app.realtime.audio_utils import linear16_to_mulaw, split_into_chunks

logger = logging.getLogger("voice_agent.tts.sarvam")


class SarvamTTS(TTSProvider):
    """Sarvam Bulbul TTS for Indian Hindi/Hinglish speech synthesis."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.SARVAM_API_KEY
        self.voice = self.settings.SARVAM_TTS_VOICE or "meera"

    async def stream_tts(self, text: str) -> AsyncGenerator[bytes, None]:
        clean_text = text.strip()
        if not clean_text or not self.api_key:
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {
                    "api-subscription-key": self.api_key,
                    "Content-Type": "application/json",
                }
                payload = {
                    "inputs": [clean_text],
                    "target_language_code": "hi-IN",
                    "speaker": self.voice,
                    "model": "bulbul:v1",
                }
                resp = await client.post("https://api.sarvam.ai/text-to-speech", json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    audios = data.get("audios", [])
                    if audios:
                        audio_b64 = audios[0]
                        raw_bytes = base64.b64decode(audio_b64)
                        decoded = miniaudio.decode(
                            raw_bytes,
                            nchannels=1,
                            sample_rate=8000,
                            output_format=miniaudio.SampleFormat.SIGNED16,
                        )
                        mulaw_bytes = linear16_to_mulaw(decoded.samples.tobytes())
                        for frame in split_into_chunks(mulaw_bytes, chunk_size=160):
                            yield frame
                            await asyncio.sleep(0.005)
                else:
                    logger.error(f"Sarvam TTS failed: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Sarvam TTS synthesis error: {e}")

