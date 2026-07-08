# ============================================
# Оркестратор: маршрутизирует запрос к суб-агентам
# ============================================

from agents import coach, explorer, github_sync, planner
from config import load_prompt
from llm.router import get_provider

# Описания tools для LLM: по ним модель выбирает суб-агента
TOOLS = [
    {
        "name": "planner",
        "description": "Планирование: создать/показать/изменить план дня или план развития на 1-2 месяца, отметить задачу выполненной, добавить/показать навыки. Всё, что касается задач, расписания и прогресса обучения.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_request": {
                    "type": "string",
                    "description": "Запрос пользователя, переформулированный ясно и полно, с сохранением всех деталей (даты, названия задач)",
                }
            },
            "required": ["user_request"],
        },
    },
    {
        "name": "explorer",
        "description": "Исследование идеи: пользователь описал идею проекта и хочет узнать, что уже сделано (статьи arXiv, проекты GitHub), чем его идея отличается и где ниша.",
        "parameters": {
            "type": "object",
            "properties": {
                "idea_title": {"type": "string", "description": "Короткое название идеи"},
                "idea_description": {"type": "string", "description": "Суть идеи своими словами, полно"},
            },
            "required": ["idea_title", "idea_description"],
        },
    },
    {
        "name": "coach",
        "description": "Ревью и поддержка: провален день, усталость, ревью недели, пересборка плана под меньшую нагрузку, предложения отдыха (фильмы, прогулки, спорт, готовка).",
        "parameters": {
            "type": "object",
            "properties": {
                "user_request": {"type": "string", "description": "Запрос пользователя полностью"}
            },
            "required": ["user_request"],
        },
    },
    {
        "name": "sync_github",
        "description": "Обновить профиль проектов из GitHub пользователя: «подтяни/обнови мои проекты с гитхаба», «синхронизируй github». Без аргументов.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "direct_answer",
        "description": "Прямой ответ без суб-агентов: болтовня, общие вопросы, уточнение непонятного запроса.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "Готовый ответ пользователю по-русски"}
            },
            "required": ["answer"],
        },
    },
]


# Точка входа: текст пользователя → ответ ассистента
def handle_message(user_text, db_conn):
    provider = get_provider("orchestrator")
    messages = [
        {"role": "system", "content": load_prompt("orchestrator")},
        {"role": "user", "content": user_text},
    ]
    response = provider.chat(messages, tools=TOOLS)

    # Модель может ответить текстом без tool call — отдаём как есть
    if response["type"] == "text":
        return response["content"]

    tool_name = response["tool_name"]
    tool_args = response["tool_args"]

    if tool_name == "direct_answer":
        return tool_args["answer"]
    if tool_name == "planner":
        return planner.run(tool_args["user_request"], db_conn)
    if tool_name == "explorer":
        return explorer.run(tool_args["idea_title"], tool_args["idea_description"], db_conn)
    if tool_name == "coach":
        return coach.run(tool_args["user_request"], db_conn)
    if tool_name == "sync_github":
        return github_sync.run(db_conn)

    # Модель вызвала неизвестный tool — не должно случаться
    return "Не понял запрос, попробуй переформулировать."
