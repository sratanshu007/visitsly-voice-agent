import asyncio
import io
import logging
import re
from typing import AsyncGenerator
import edge_tts
import miniaudio
from app.config import get_settings
from app.providers.base import TTSProvider
from app.realtime.audio_utils import linear16_to_mulaw, split_into_chunks

logger = logging.getLogger("voice_agent.tts.edge")


def _humanize_speech_text(text: str) -> str:
    """Preprocesses text for natural, warm, humanized Hindi/Hinglish speech synthesis."""
    if not text:
        return ""
    t = text.strip()
    # Remove markdown formatting and raw brackets
    t = re.sub(r"[*#_\[\]`]", "", t)
    # Convert timestamps like '04:00 PM' -> 'shaam 4 baje', '11:00 AM' -> 'subah 11 baje'
    t = re.sub(r"(?:0?(\d+):00\s*(?:PM|pm))", r"shaam \1 baje", t)
    t = re.sub(r"(?:0?(\d+):00\s*(?:AM|am))", r"subah \1 baje", t)
    # Insert natural conversational micro-pause commas
    t = re.sub(r"\b(Namaste|Namaskar)\b(?!\s*,)", r"\1,", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(ji)\b(?!\s*,)", r"ji,", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class EdgeTTS(TTSProvider):
    """
    100% Free, zero-quota streaming TTS using Microsoft Edge Neural voices.
    Natural Indian Hindi female voice: 'hi-IN-SwaraNeural'.
    Decodes MP3 stream to 8000Hz mono PCM16 and converts to G.711 mu-law for Plivo.
    """

    def __init__(self):
        self.settings = get_settings()
        self.voice = self.settings.EDGE_TTS_VOICE or "hi-IN-SwaraNeural"

    async def stream_tts(self, text: str) -> AsyncGenerator[bytes, None]:
        clean_text = _humanize_speech_text(text)
        if not clean_text:
            return

        try:
            communicate = edge_tts.Communicate(
                text=clean_text,
                voice=self.voice,
                rate="+0%",
                volume="+0%",
                pitch="+0Hz",
            )

            # Collect stream chunks
            mp3_buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_buffer.extend(chunk["data"])

            if not mp3_buffer:
                return

            # Decode MP3 to 8000Hz 1-channel 16-bit signed PCM
            decoded = miniaudio.decode(
                bytes(mp3_buffer),
                nchannels=1,
                sample_rate=8000,
                output_format=miniaudio.SampleFormat.SIGNED16,
            )
            pcm_bytes = decoded.samples.tobytes()

            # Transcode linear PCM16 to 8-bit G.711 mu-law
            mulaw_bytes = linear16_to_mulaw(pcm_bytes)

            # Yield in 160-byte chunks (20ms frames) for smooth Plivo streaming
            for frame in split_into_chunks(mulaw_bytes, chunk_size=160):
                yield frame

        except Exception as e:
            logger.error(f"EdgeTTS synthesis error: {e}")

