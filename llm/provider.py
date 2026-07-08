# ============================================
# Базовый класс LLM-провайдера
# ============================================

# Единый формат сообщений на входе:
#   [{"role": "system" | "user" | "assistant", "content": str}, ...]
#
# Единый формат ответа chat():
#   {"type": "text",      "content": str, "tool_name": None, "tool_args": None}
#   {"type": "tool_call", "content": "",  "tool_name": str,  "tool_args": dict}
#
# tools — список JSON-описаний в формате
#   {"name": str, "description": str, "parameters": {json-schema}}


class LLMProvider:
    def chat(self, messages, tools=None):
        raise NotImplementedError


# Хелперы, чтобы провайдеры собирали ответ одинаково
def text_response(content):
    return {"type": "text", "content": content, "tool_name": None, "tool_args": None}


def tool_call_response(tool_name, tool_args):
    return {"type": "tool_call", "content": "", "tool_name": tool_name, "tool_args": tool_args}
