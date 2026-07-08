# ============================================
# Роутер: агент → цепочка провайдеров, обработка 429/503
# ============================================

import logging

from config import AGENT_MODELS
from llm.gemini import GeminiProvider
from llm.groq import GroqProvider
from llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Логическое имя модели из config → фабрика провайдера.
# Фабрика, а не инстанс: клиент создаётся только когда реально нужен.
MODEL_FACTORIES = {
    "gemini-flash-lite": lambda: GeminiProvider("gemini-3.1-flash-lite"),
    "gemini-flash": lambda: GeminiProvider("gemini-2.5-flash"),
    "groq-llama": lambda: GroqProvider("llama-3.3-70b-versatile"),
}


# Временная ошибка = имеет смысл пробовать другую модель:
# 429 / RESOURCE_EXHAUSTED — кончилась квота (RPM или RPD),
# 503 / UNAVAILABLE — модель перегружена на стороне Google.
# SDK бросает разные классы исключений, но код и статус
# есть в тексте ошибки всегда.
def is_transient(error):
    error_text = str(error)
    return any(
        marker in error_text
        for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")
    )


class FallbackProvider(LLMProvider):
    # Пробует провайдеров по очереди: если модель ответила 429/503 —
    # идём к следующей в цепочке. Свой ретрай той же модели не делаем:
    # SDK google-genai уже ретраит 503 внутри себя (tenacity),
    # а при 429 повторять бессмысленно — квота не восстановится за секунды.
    def __init__(self, providers):
        self.providers = providers

    def chat(self, messages, tools=None):
        last_error = None
        for provider in self.providers:
            try:
                return provider.chat(messages, tools)
            except Exception as error:
                if not is_transient(error):
                    raise
                logger.warning(
                    "Модель %s недоступна (%s), пробую следующую в цепочке",
                    getattr(provider, "model", "?"),
                    str(error)[:120],
                )
                last_error = error
        raise last_error


# Кэш: один клиент на модель и одна цепочка на агента,
# а не новые объекты на каждый запрос
_provider_cache = {}
_chain_cache = {}


def _get_single_provider(model_name):
    if model_name not in _provider_cache:
        _provider_cache[model_name] = MODEL_FACTORIES[model_name]()
    return _provider_cache[model_name]


def get_provider(agent_name):
    if agent_name not in _chain_cache:
        _chain_cache[agent_name] = FallbackProvider(get_provider_chain(agent_name))
    return _chain_cache[agent_name]


# Список отдельных провайдеров цепочки — для кода, которому нужен
# свой цикл эскалации (генератор плана эскалирует не только при 429/503,
# но и при ошибках парсинга/валидации, FallbackProvider так не умеет)
def get_provider_chain(agent_name):
    return [_get_single_provider(name) for name in AGENT_MODELS[agent_name]]
