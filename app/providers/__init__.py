from app.config import get_settings
from app.providers.base import STTProvider, LLMProvider, TTSProvider, STTResult, LLMToken
from app.providers.stt_deepgram import DeepgramSTT
from app.providers.stt_groq import GroqWhisperSTT
from app.providers.stt_sarvam import SarvamSTT
from app.providers.llm_claude import ClaudeLLM
from app.providers.llm_groq import GroqLLM
from app.providers.llm_gemini import GeminiLLM
from app.providers.tts_edge import EdgeTTS
from app.providers.tts_sarvam import SarvamTTS
from app.providers.tts_elevenlabs import ElevenLabsTTS


def get_stt_provider(name: str = None) -> STTProvider:
    settings = get_settings()
    provider = (name or settings.STT_PROVIDER).lower()
    if provider == "deepgram" and settings.DEEPGRAM_API_KEY:
        return DeepgramSTT()
    elif provider == "sarvam" and settings.SARVAM_API_KEY:
        return SarvamSTT()
    return GroqWhisperSTT()


def get_llm_provider(name: str = None) -> LLMProvider:
    settings = get_settings()
    provider = (name or settings.LLM_PROVIDER).lower()
    if provider == "claude" and settings.ANTHROPIC_API_KEY:
        return ClaudeLLM()
    elif provider == "gemini" and settings.GEMINI_API_KEY:
        return GeminiLLM()
    elif provider == "groq" and settings.GROQ_API_KEY:
        return GroqLLM()
    # Default priority
    if settings.GROQ_API_KEY:
        return GroqLLM()
    if settings.GEMINI_API_KEY:
        return GeminiLLM()
    if settings.ANTHROPIC_API_KEY:
        return ClaudeLLM()
    return GroqLLM()


def get_tts_provider(name: str = None) -> TTSProvider:
    settings = get_settings()
    provider = (name or settings.TTS_PROVIDER).lower()
    if provider == "elevenlabs" and settings.ELEVENLABS_API_KEY:
        return ElevenLabsTTS()
    elif provider == "sarvam" and settings.SARVAM_API_KEY:
        return SarvamTTS()
    # EdgeTTS is 100% free, natural Indian Hindi voice, and zero quota limit
    return EdgeTTS()


__all__ = [
    "STTProvider",
    "LLMProvider",
    "TTSProvider",
    "STTResult",
    "LLMToken",
    "DeepgramSTT",
    "GroqWhisperSTT",
    "SarvamSTT",
    "ClaudeLLM",
    "GroqLLM",
    "GeminiLLM",
    "EdgeTTS",
    "SarvamTTS",
    "ElevenLabsTTS",
    "get_stt_provider",
    "get_llm_provider",
    "get_tts_provider",
]
