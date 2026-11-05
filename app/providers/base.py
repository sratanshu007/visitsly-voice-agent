from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Callable, Dict, List, Optional, Any


@dataclass
class STTResult:
    text: str
    is_final: bool
    confidence: float = 1.0


@dataclass
class LLMToken:
    text: str = ""
    is_first: bool = False
    is_final: bool = False
    tool_call: Optional[Dict[str, Any]] = None


class STTProvider(ABC):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    async def connect(self, on_transcript: Callable[[STTResult], Any]) -> None:
        """Initializes connection to streaming STT."""
        pass

    @abstractmethod
    async def send_audio(self, mulaw_chunk: bytes) -> None:
        """Pushes an incoming 8kHz mu-law audio chunk."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Closes connection cleanly."""
        pass

    async def transcribe_complete(self, mulaw_audio: bytes) -> str:
        """Fallback non-streaming transcription of an audio buffer."""
        return ""


class LLMProvider(ABC):
    """Abstract interface for streaming LLM providers."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[LLMToken, None]:
        """Streams response tokens and tool calls."""
        yield LLMToken()


class TTSProvider(ABC):
    """Abstract interface for Text-to-Speech providers."""

    @abstractmethod
    async def stream_tts(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Synthesizes text into 8000Hz 8-bit G.711 mu-law audio chunks
        ready for direct transmission to Plivo WebSocket.
        """
        yield b""

