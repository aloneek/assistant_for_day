# ============================================
# Структурированный JSON от цепочки моделей: ошибка парсинга или
# валидации → один ретрай той же модели с текстом ошибки в промпте,
# затем следующая модель цепочки (при 429/503 — сразу следующая).
# Используют plan_generator и explorer
# ============================================

import json
import logging

from llm.router import get_provider_chain, is_transient

logger = logging.getLogger(__name__)

# Попыток на одну модель: первая + один ретрай с текстом ошибки
ATTEMPTS_PER_MODEL = 2


class StructuredRequestError(Exception):
    pass


def _extract_json_array(text):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("в ответе нет JSON-массива")
    return json.loads(text[start:end + 1])


# validate(raw) — проверяет разобранный JSON и возвращает нормализованный
# результат; при нарушении бросает ValueError с текстом для ретрая
def request_json_array(agent_name, system_prompt, user_message, validate):
    error_feedback = None
    for provider in get_provider_chain(agent_name):
        for attempt in range(ATTEMPTS_PER_MODEL):
            attempt_message = user_message
            if error_feedback:
                attempt_message += (
                    f"\n\n# Ошибка прошлой попытки\n\n{error_feedback}\n"
                    "Исправь её и верни весь JSON-массив заново."
                )
            try:
                response = provider.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": attempt_message},
                ])
            except Exception as error:
                if is_transient(error):
                    logger.warning("%s: %s недоступна (%s), следующая модель",
                                   agent_name, provider.model, str(error)[:120])
                    break  # к следующей модели цепочки
                raise

            try:
                return validate(_extract_json_array(response["content"]))
            except (ValueError, json.JSONDecodeError) as error:
                error_feedback = str(error)
                logger.warning("%s: %s, попытка %d — %s",
                               agent_name, provider.model, attempt + 1, error_feedback)

    raise StructuredRequestError("Ни одна модель не вернула корректный JSON")
