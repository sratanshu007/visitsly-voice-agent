import asyncio
import json
import logging
from typing import Callable, Optional
import websockets
from app.config import get_settings
from app.providers.base import STTProvider, STTResult

logger = logging.getLogger("voice_agent.stt.deepgram")


class DeepgramSTT(STTProvider):
    """Deepgram Streaming STT for 8kHz G.711 mu-law audio with Hindi/multi-language support."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.DEEPGRAM_API_KEY
        self.model = self.settings.DEEPGRAM_MODEL or "nova-2"
        self.language = self.settings.DEEPGRAM_LANGUAGE or "hi"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self.on_transcript_callback: Optional[Callable[[STTResult], None]] = None
        self.is_connected = False

    async def connect(self, on_transcript: Callable[[STTResult], None]) -> None:
        self.on_transcript_callback = on_transcript
        if not self.api_key:
            logger.warning("DEEPGRAM_API_KEY is not set. Deepgram STT will not connect.")
            return

        url = (
            f"wss://api.deepgram.com/v1/listen?"
            f"model={self.model}&language={self.language}&encoding=mulaw&sample_rate=8000&channels=1"
            f"&endpointing=300&interim_results=true&smart_format=true"
        )
        headers = {"Authorization": f"Token {self.api_key}"}

        try:
            self.ws = await websockets.connect(url, additional_headers=headers)
            self.is_connected = True
            self._receive_task = asyncio.create_task(self._listen_loop())
            logger.info("Connected to Deepgram streaming STT")
        except Exception as e:
            logger.error(f"Failed to connect to Deepgram STT: {e}")
            self.is_connected = False

    async def _listen_loop(self) -> None:
        try:
            while self.is_connected and self.ws:
                message = await self.ws.recv()
                data = json.loads(message)
                channel = data.get("channel", {})
                alternatives = channel.get("alternatives", [])
                if alternatives:
                    alt = alternatives[0]
                    transcript = alt.get("transcript", "").strip()
                    is_final = data.get("is_final", False)
                    confidence = alt.get("confidence", 1.0)
                    if transcript and self.on_transcript_callback:
                        result = STTResult(text=transcript, is_final=is_final, confidence=confidence)
                        if asyncio.iscoroutinefunction(self.on_transcript_callback):
                            await self.on_transcript_callback(result)
                        else:
                            self.on_transcript_callback(result)
        except websockets.ConnectionClosed:
            logger.info("Deepgram WebSocket closed.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Deepgram listen loop error: {e}")
        finally:
            self.is_connected = False

    async def send_audio(self, mulaw_chunk: bytes) -> None:
        if self.is_connected and self.ws:
            try:
                await self.ws.send(mulaw_chunk)
            except Exception as e:
                logger.error(f"Error sending audio chunk to Deepgram: {e}")

    async def disconnect(self) -> None:
        self.is_connected = False
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        logger.info("Deepgram STT disconnected cleanly")

