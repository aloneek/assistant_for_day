# ============================================
# Planner: план дня и план развития
# ============================================

import datetime
import json

from config import load_prompt
from llm.router import get_provider

# Сколько tool-вызовов подряд разрешаем за один запрос
MAX_TOOL_STEPS = 5

# Иконки статусов задач для вывода пользователю
STATUS_ICONS = {"pending": "⬜️", "done": "✅", "skipped": "⏭"}

# Порядок и подписи уровней навыков
SKILL_LEVELS = [("expert", "📕 Эксперт"), ("confident", "📘 Уверенно"), ("learning", "📗 Изучаю")]

# Описания tools для LLM
PLANNER_TOOLS = [
    {
        "name": "create_daily_plan",
        "description": "Создать план дня с задачами. Если план на эту дату уже есть — задачи добавятся в него.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата плана, YYYY-MM-DD"},
                "tasks": {
                    "type": "array",
                    "description": "Задачи плана",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Название задачи"},
                            "task_type": {"type": "string", "enum": ["work", "study", "rest"], "description": "Тип задачи"},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["date", "tasks"],
        },
    },
    {
        "name": "add_task",
        "description": "Добавить одну задачу на дату. Прикрепится к плану дня этой даты, если он есть.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название задачи"},
                "task_type": {"type": "string", "enum": ["work", "study", "rest"], "description": "Тип задачи, по умолчанию work"},
                "date": {"type": "string", "description": "Дата YYYY-MM-DD, по умолчанию сегодня"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": "Отметить задачу выполненной. Ищет невыполненную задачу по названию (частичное совпадение).",
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "Название задачи или его часть"}
            },
            "required": ["task_title"],
        },
    },
    {
        "name": "show_today",
        "description": "Показать план и задачи на дату со статусами.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата YYYY-MM-DD, по умолчанию сегодня"}
            },
        },
    },
    {
        "name": "add_skill",
        "description": "Добавить навык или обновить его уровень.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Название навыка, например python или aiogram"},
                "level": {"type": "string", "enum": ["learning", "confident", "expert"], "description": "Уровень, по умолчанию learning"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_skills",
        "description": "Показать все навыки, сгруппированные по уровню.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _today():
    return datetime.date.today().isoformat()


# --- Реализации tools: обычные функции с SQL ---

def tool_create_daily_plan(db_conn, date, tasks):
    # Если активный план дня на эту дату уже есть — дополняем его
    existing = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (date,),
    ).fetchone()
    if existing:
        plan_id = existing["id"]
        plan_note = f"План на {date} уже был — добавил задачи в него."
    else:
        cursor = db_conn.execute(
            "INSERT INTO plans (plan_type, title, date_from, date_to) VALUES ('daily', ?, ?, ?)",
            (f"План на {date}", date, date),
        )
        plan_id = cursor.lastrowid
        plan_note = f"Создал план на {date}."

    added_titles = []
    for task in tasks:
        task_type = task.get("task_type") or "work"
        db_conn.execute(
            "INSERT INTO tasks (plan_id, title, task_type, scheduled_date) VALUES (?, ?, ?, ?)",
            (plan_id, task["title"], task_type, date),
        )
        added_titles.append(task["title"])

    return f"{plan_note} Задачи ({len(added_titles)}): " + "; ".join(added_titles)


def tool_add_task(db_conn, title, task_type="work", date=None):
    scheduled_date = date or _today()
    # Прикрепляем к плану дня этой даты, если он существует
    plan = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (scheduled_date,),
    ).fetchone()
    plan_id = plan["id"] if plan else None
    db_conn.execute(
        "INSERT INTO tasks (plan_id, title, task_type, scheduled_date) VALUES (?, ?, ?, ?)",
        (plan_id, title, task_type, scheduled_date),
    )
    attached = "в план дня" if plan_id else "вне плана (плана на эту дату нет)"
    return f"Добавил задачу «{title}» ({task_type}) на {scheduled_date}, {attached}."


def tool_complete_task(db_conn, task_title):
    matches = db_conn.execute(
        "SELECT id, title, scheduled_date FROM tasks WHERE status = 'pending' AND title LIKE ? ORDER BY scheduled_date",
        (f"%{task_title}%",),
    ).fetchall()

    if not matches:
        return f"Не нашёл невыполненной задачи с названием похожим на «{task_title}»."
    if len(matches) > 1:
        options = "; ".join(f"«{row['title']}» ({row['scheduled_date']})" for row in matches)
        return f"Нашёл несколько подходящих задач, уточни какую: {options}"

    task = matches[0]
    db_conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = datetime('now') WHERE id = ?",
        (task["id"],),
    )
    return f"Задача «{task['title']}» отмечена выполненной."


def tool_show_today(db_conn, date=None):
    target_date = date or _today()
    plan = db_conn.execute(
        "SELECT id, title FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (target_date,),
    ).fetchone()
    tasks = db_conn.execute(
        "SELECT id, title, task_type, status FROM tasks WHERE scheduled_date = ? ORDER BY id",
        (target_date,),
    ).fetchall()

    if not plan and not tasks:
        return f"На {target_date} нет ни плана, ни задач."

    header = plan["title"] if plan else f"Задачи на {target_date} (без плана)"
    lines = [header]
    for task in tasks:
        icon = STATUS_ICONS.get(task["status"], "⬜️")
        lines.append(f"{icon} [{task['id']}] {task['title']} ({task['task_type']})")
    done_count = sum(1 for task in tasks if task["status"] == "done")
    lines.append(f"Выполнено: {done_count} из {len(tasks)}")
    return "\n".join(lines)


def tool_add_skill(db_conn, name, level="learning"):
    # upsert: навык уже есть — обновляем уровень
    db_conn.execute(
        "INSERT INTO skills (name, level, source) VALUES (?, ?, 'manual') "
        "ON CONFLICT(name) DO UPDATE SET level = excluded.level",
        (name, level),
    )
    return f"Навык «{name}» записан с уровнем {level}."


def tool_list_skills(db_conn):
    rows = db_conn.execute("SELECT name, level FROM skills ORDER BY name").fetchall()
    if not rows:
        return "Навыков пока нет."
    lines = []
    for level_key, level_label in SKILL_LEVELS:
        names = [row["name"] for row in rows if row["level"] == level_key]
        if names:
            lines.append(f"{level_label}: " + ", ".join(names))
    return "\n".join(lines)


TOOL_HANDLERS = {
    "create_daily_plan": tool_create_daily_plan,
    "add_task": tool_add_task,
    "complete_task": tool_complete_task,
    "show_today": tool_show_today,
    "add_skill": tool_add_skill,
    "list_skills": tool_list_skills,
}


# Отметить задачу по id — для инлайн-кнопки «✅ Выполнено» (bot/keyboards.py)
def complete_task_by_id(db_conn, task_id):
    row = db_conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    db_conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = datetime('now') WHERE id = ?",
        (task_id,),
    )
    db_conn.commit()
    return row["title"]


# Точка входа: запрос от оркестратора → ответ пользователю
def run(user_request, db_conn):
    provider = get_provider("planner")
    today = datetime.date.today()
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    system_prompt = load_prompt("planner") + f"\n\n# Текущая дата\n\nСегодня {today.isoformat()}, {weekdays[today.weekday()]}."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]

    # Цикл: LLM зовёт инструменты, пока не даст финальный текст
    last_tool_result = None
    for _ in range(MAX_TOOL_STEPS):
        response = provider.chat(messages, tools=PLANNER_TOOLS)

        if response["type"] == "text":
            return response["content"]

        handler = TOOL_HANDLERS.get(response["tool_name"])
        if handler is None:
            return "Не смог обработать запрос, попробуй переформулировать."

        result = handler(db_conn, **response["tool_args"])
        db_conn.commit()
        last_tool_result = result

        # Результат инструмента возвращаем в диалог, у нашего формата
        # сообщений нет отдельной роли tool — используем пару assistant/user
        messages.append({
            "role": "assistant",
            "content": f"Вызываю {response['tool_name']} с аргументами {json.dumps(response['tool_args'], ensure_ascii=False)}",
        })
        messages.append({
            "role": "user",
            "content": f"[Результат инструмента]\n{result}\n\nЕсли нужно — вызови следующий инструмент, иначе дай финальный ответ.",
        })

    # Лимит шагов исчерпан — отдаём хотя бы результат последнего инструмента
    return last_tool_result or "Не получилось обработать запрос, попробуй ещё раз."
