# ============================================
# Провайдер Gemini через официальный SDK google-genai
# ============================================

from google import genai
from google.genai import types

from config import GEMINI_API_KEY
from llm.provider import LLMProvider, text_response, tool_call_response


class GeminiProvider(LLMProvider):
    def __init__(self, model):
        self.model = model
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def chat(self, messages, tools=None):
        # system-сообщение у Gemini передаётся отдельно от диалога
        system_instruction = None
        contents = []
        for message in messages:
            if message["role"] == "system":
                system_instruction = message["content"]
            else:
                # роли Gemini: user / model
                role = "model" if message["role"] == "assistant" else "user"
                contents.append(
                    types.Content(role=role, parts=[types.Part(text=message["content"])])
                )

        config_kwargs = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if tools:
            # наш JSON-формат tools совпадает с FunctionDeclaration:
            # name / description / parameters (json-schema)
            declarations = [types.FunctionDeclaration(**tool) for tool in tools]
            config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        # Нормализация: tool call приоритетнее текста
        if response.function_calls:
            call = response.function_calls[0]
            return tool_call_response(call.name, dict(call.args))
        return text_response(response.text or "")
