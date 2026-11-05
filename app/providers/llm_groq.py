import json
import logging
from typing import AsyncGenerator, Dict, List, Optional, Any
from groq import AsyncGroq
from app.config import get_settings
from app.providers.base import LLMProvider, LLMToken

logger = logging.getLogger("voice_agent.llm.groq")


class GroqLLM(LLMProvider):
    """Groq streaming LLM (Llama 3.3 70B / Qwen) for ultra-low latency voice responses."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.GROQ_API_KEY
        self.model = self.settings.GROQ_MODEL or "qwen/qwen3.8-27b"
        self.client: Optional[AsyncGroq] = None
        if self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[LLMToken, None]:
        if not self.client:
            logger.error("Groq client not initialized (missing GROQ_API_KEY)")
            yield LLMToken(text="Theek hai ji.", is_final=True)
            return

        chat_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            chat_messages.append({"role": m["role"], "content": m["content"]})

        groq_tools = None
        if tools:
            groq_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]

        first_token = True
        try:
            kwargs = {
                "model": self.model,
                "messages": chat_messages,
                "temperature": 0.3,
                "max_tokens": 250,
                "stream": True,
            }
            if groq_tools:
                kwargs["tools"] = groq_tools
                kwargs["tool_choice"] = "auto"

            try:
                stream = await self.client.chat.completions.create(**kwargs)
            except Exception as model_err:
                logger.warning(
                    f"Groq request with {self.model} failed ({model_err}). Falling back to qwen/qwen3.8-27b..."
                )
                kwargs["model"] = "qwen/qwen3.8-27b"
                stream = await self.client.chat.completions.create(**kwargs)

            tool_calls_accumulator = {}

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                if delta.content:
                    yield LLMToken(text=delta.content, is_first=first_token, is_final=False)
                    first_token = False

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function and tc.function.name else "",
                                "arguments": "",
                            }
                        if tc.function and tc.function.arguments:
                            tool_calls_accumulator[idx]["arguments"] += tc.function.arguments

            # Dispatch completed tool calls
            for tc in tool_calls_accumulator.values():
                name = tc["name"]
                args_str = tc["arguments"]
                try:
                    args = json.loads(args_str) if args_str else {}
                except Exception:
                    args = {}
                yield LLMToken(tool_call={"name": name, "arguments": args}, is_final=True)

            yield LLMToken(text="", is_final=True)
        except Exception as e:
            logger.error(f"Groq streaming error: {e}")
            yield LLMToken(text="Theek hai ji, dhanyavaad.", is_final=True)

