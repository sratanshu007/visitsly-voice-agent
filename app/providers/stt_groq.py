import asyncio
import io
import logging
from typing import Callable, Optional
from groq import AsyncGroq
from app.config import get_settings
from app.providers.base import STTProvider, STTResult
from app.realtime.audio_utils import mulaw_to_wav, compute_audio_energy

logger = logging.getLogger("voice_agent.stt.groq")

# Energy threshold for detecting speech (RMS) - calibrated to reject line noise (~20) and accept voice (>150)
SPEECH_ENERGY_THRESHOLD = 150.0
# Number of consecutive silence frames (20ms each) to trigger endpoint (~320ms)
SILENCE_FRAMES_ENDPOINT = 16
# Minimum speech frames required to consider it real speech (~80ms)
MIN_SPEECH_FRAMES = 4

WHISPER_PROMPT = "हाँ, कर दीजिए। नहीं, टाइम चेंज कर दो। कल या परसों चार बजे।"


class GroqWhisperSTT(STTProvider):
    """Fast speech transcription using Groq's Whisper API with Voice Activity Detection (VAD)."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.GROQ_API_KEY
        self.client: Optional[AsyncGroq] = None
        if self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)
        self.on_transcript_callback: Optional[Callable[[STTResult], None]] = None
        self.buffer = bytearray()
        self.pre_buffer = bytearray()
        self.is_connected = False
        self.has_active_speech = False
        self.speech_frames = 0
        self.silence_frames = 0

    async def connect(self, on_transcript: Callable[[STTResult], None]) -> None:
        self.on_transcript_callback = on_transcript
        self.is_connected = True
        self.buffer.clear()
        self.pre_buffer.clear()
        self.has_active_speech = False
        self.speech_frames = 0
        self.silence_frames = 0
        logger.info("Groq Whisper STT ready with real-time VAD endpointing")

    async def send_audio(self, mulaw_chunk: bytes) -> None:
        if not self.is_connected or not mulaw_chunk:
            return

        energy = compute_audio_energy(mulaw_chunk)

        if energy >= SPEECH_ENERGY_THRESHOLD:
            # Active speech detected
            if not self.has_active_speech and self.pre_buffer:
                # Prepend the pre-speech buffer (retains word onsets)
                self.buffer.extend(self.pre_buffer)
                self.pre_buffer.clear()

            self.has_active_speech = True
            self.speech_frames += 1
            self.silence_frames = 0
            self.buffer.extend(mulaw_chunk)

            # Cap maximum speech buffer to 3.5 seconds to avoid overruns
            if len(self.buffer) >= 28000:
                await self.flush()
        else:
            # Silence or background noise
            if self.has_active_speech:
                self.silence_frames += 1
                self.buffer.extend(mulaw_chunk)

                if self.silence_frames >= SILENCE_FRAMES_ENDPOINT:
                    # User finished speaking!
                    if self.speech_frames >= MIN_SPEECH_FRAMES:
                        await self.flush()
                    else:
                        self.buffer.clear()
                    self.has_active_speech = False
                    self.speech_frames = 0
                    self.silence_frames = 0
            else:
                # Keep small circular rolling pre-buffer (~120ms = 960 bytes)
                self.pre_buffer.extend(mulaw_chunk)
                if len(self.pre_buffer) > 960:
                    self.pre_buffer = self.pre_buffer[-960:]

    async def flush(self) -> None:
        if len(self.buffer) < 1200 or not self.client:  # Less than 0.15s audio
            self.buffer.clear()
            return

        audio_data = bytes(self.buffer)
        self.buffer.clear()

        try:
            # Resample to 16kHz WAV for high-fidelity Whisper recognition
            wav_bytes = mulaw_to_wav(audio_data, sample_rate=16000)
            file_obj = ("speech.wav", io.BytesIO(wav_bytes), "audio/wav")

            transcription = await self.client.audio.transcriptions.create(
                file=file_obj,
                model="whisper-large-v3-turbo",
                language="hi",
                prompt=WHISPER_PROMPT,
                response_format="text",
                temperature=0.0,
            )
            text = str(transcription).strip()

            # Filter repetitive Whisper silence hallucinations
            if not text or len(text) < 2:
                return
            if any(h in text.lower() for h in ("vocabulary", "site visit book ki hai", "aapne property")):
                return
            words = text.split()
            if len(words) >= 3 and len(set(words)) == 1:
                return  # E.g. "झाल झाल झाल"
            if text in ("झाल", "झाल झाल", "झालाल", "अबड़ बड़ाओ", "आओट", "कर दो अब दो और दो दो"):
                return

            if text and self.on_transcript_callback:
                res = STTResult(text=text, is_final=True, confidence=0.95)
                if asyncio.iscoroutinefunction(self.on_transcript_callback):
                    await self.on_transcript_callback(res)
                else:
                    self.on_transcript_callback(res)
        except Exception as e:
            logger.error(f"Groq Whisper transcription error: {e}", exc_info=True)

    async def transcribe_complete(self, mulaw_audio: bytes) -> str:
        if not self.client or len(mulaw_audio) < 1600:
            return ""
        try:
            wav_bytes = mulaw_to_wav(mulaw_audio, sample_rate=8000)
            file_obj = ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")
            transcription = await self.client.audio.transcriptions.create(
                file=file_obj,
                model="whisper-large-v3-turbo",
                language="hi",
                response_format="text",
            )
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Groq transcribe_complete error: {e}")
            return ""

    async def disconnect(self) -> None:
        self.is_connected = False
        self.buffer.clear()

