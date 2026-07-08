# ============================================
# Провайдер Groq через официальный SDK groq
# ============================================

import json

from groq import Groq

from config import GROQ_API_KEY
from llm.provider import LLMProvider, text_response, tool_call_response


class GroqProvider(LLMProvider):
    def __init__(self, model):
        self.model = model
        self.client = Groq(api_key=GROQ_API_KEY)

    def chat(self, messages, tools=None):
        # Groq использует OpenAI-формат: наши messages подходят как есть,
        # system-сообщение отдельно выносить не нужно
        request_kwargs = {}
        if tools:
            # наш формат {name, description, parameters} →
            # OpenAI-обёртка {"type": "function", "function": {...}}
            request_kwargs["tools"] = [
                {"type": "function", "function": tool} for tool in tools
            ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **request_kwargs,
        )

        # Нормализация: tool call приоритетнее текста.
        # Аргументы приходят JSON-строкой — разбираем в dict
        answer = response.choices[0].message
        if answer.tool_calls:
            call = answer.tool_calls[0]
            return tool_call_response(call.function.name, json.loads(call.function.arguments))
        return text_response(answer.content or "")
