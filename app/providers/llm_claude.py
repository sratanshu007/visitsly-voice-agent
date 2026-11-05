import json
import logging
from typing import AsyncGenerator, Dict, List, Optional, Any
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.providers.base import LLMProvider, LLMToken

logger = logging.getLogger("voice_agent.llm.claude")


class ClaudeLLM(LLMProvider):
    """Anthropic Claude streaming LLM with tool calling support."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.ANTHROPIC_API_KEY
        self.model = self.settings.CLAUDE_MODEL or "claude-3-5-sonnet-20241022"
        self.client: Optional[AsyncAnthropic] = None
        if self.api_key:
            self.client = AsyncAnthropic(api_key=self.api_key)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[LLMToken, None]:
        if not self.client:
            logger.error("Claude client not initialized (missing ANTHROPIC_API_KEY)")
            yield LLMToken(text="Maaf kijiye, main abhi connect nahi ho pa raha hoon.", is_final=True)
            return

        formatted_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "assistant"
            formatted_messages.append({"role": role, "content": msg["content"]})

        tool_definitions = []
        if tools:
            for t in tools:
                tool_definitions.append({
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {}),
                })

        first_token = True
        try:
            kwargs = {
                "model": self.model,
                "max_tokens": 300,
                "temperature": 0.3,
                "system": system_prompt,
                "messages": formatted_messages,
            }
            if tool_definitions:
                kwargs["tools"] = tool_definitions

            async with self.client.messages.stream(**kwargs) as stream:
                current_tool_call = None
                tool_input_json = ""

                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool_call = {
                                "name": event.content_block.name,
                                "id": event.content_block.id,
                            }
                            tool_input_json = ""
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            text = event.delta.text
                            yield LLMToken(text=text, is_first=first_token, is_final=False)
                            first_token = False
                        elif event.delta.type == "input_json_delta":
                            tool_input_json += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool_call:
                            try:
                                parsed_args = json.loads(tool_input_json) if tool_input_json else {}
                            except Exception:
                                parsed_args = {}
                            current_tool_call["arguments"] = parsed_args
                            yield LLMToken(tool_call=current_tool_call, is_final=True)
                            current_tool_call = None

                yield LLMToken(text="", is_final=True)
        except Exception as e:
            logger.error(f"Claude streaming error: {e}")
            yield LLMToken(text="Theek hai ji.", is_final=True)

