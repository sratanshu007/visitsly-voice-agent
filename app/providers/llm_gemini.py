import json
import logging
import warnings
from typing import AsyncGenerator, Dict, List, Optional, Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=FutureWarning)
    import google.generativeai as genai

from app.config import get_settings
from app.providers.base import LLMProvider, LLMToken

logger = logging.getLogger("voice_agent.llm.gemini")


class GeminiLLM(LLMProvider):
    """Google Gemini streaming LLM provider."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model_name = self.settings.GEMINI_MODEL or "gemini-1.5-flash"
        if self.api_key:
            genai.configure(api_key=self.api_key)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[LLMToken, None]:
        if not self.api_key:
            logger.error("Gemini API key is not configured.")
            yield LLMToken(text="Theek hai ji.", is_final=True)
            return

        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
            )

            # Convert message history to Gemini contents format
            history = []
            last_user_message = ""
            for m in messages:
                role = "user" if m["role"] == "user" else "model"
                if m == messages[-1] and m["role"] == "user":
                    last_user_message = m["content"]
                else:
                    history.append({"role": role, "parts": [m["content"]]})

            chat = model.start_chat(history=history)
            response = await chat.send_message_async(
                last_user_message or "Hello",
                stream=True,
            )

            first_token = True
            async for chunk in response:
                if chunk.text:
                    yield LLMToken(text=chunk.text, is_first=first_token, is_final=False)
                    first_token = False

            yield LLMToken(text="", is_final=True)
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            yield LLMToken(text="Ji bilkul.", is_final=True)

