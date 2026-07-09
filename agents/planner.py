# ============================================
# Planner: план дня и план развития
# ============================================

import datetime
import json

from agents import video
from agents.plan_generator import PlanGenerationError, generate_blocks, load_profile
from config import load_prompt
from llm.router import get_provider
from timeutils import now_local, today_local

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
                            "duration_min": {"type": "integer", "description": "Длительность в минутах, оцени сам, если не названа"},
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
                "duration_min": {"type": "integer", "description": "Длительность в минутах. Если пользователь не назвал — оцени реалистично сам (лаба ~120, созвон ~60); не передавай только если оценить невозможно"},
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
        "name": "move_task",
        "description": "Перенести невыполненную задачу на другую дату («перенеси лабу на завтра»). Ищет задачу по названию среди невыполненных за ±7 дней от сегодня; если на целевой день есть план — задача встанет в свободный слот по времени.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Название задачи или его часть"},
                "target_date": {"type": "string", "description": "Куда перенести, YYYY-MM-DD"},
            },
            "required": ["query", "target_date"],
        },
    },
    {
        "name": "show_day_plan",
        "description": "Полный список задач дня: все задачи, отсортированные по времени, со статусами. Вызывай на «покажи список задач», «что в плане», «что на сегодня», а также чтобы назвать первую/следующую невыполненную задачу.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата YYYY-MM-DD, по умолчанию сегодня"}
            },
        },
    },
    {
        "name": "add_video_tasks",
        "description": "Добавить YouTube-видео как задачи плана: название и длительность подтянутся из метаданных. Вызывай, когда пользователь просит добавить в план видео по ссылкам.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "YouTube-ссылки из запроса, без изменений"},
                "date": {"type": "string", "description": "Дата YYYY-MM-DD, по умолчанию сегодня"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "analyze_videos",
        "description": "Проанализировать YouTube-видео: в каком порядке смотреть, на что обратить внимание, что можно фоном. Вызывай, когда пользователь спрашивает про содержимое или порядок просмотра видео.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "YouTube-ссылки из запроса, без изменений"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "generate_day_plan",
        "description": "Сгенерировать план дня из сфер развития (учёба, чтение, спорт, отдых, еда) блоками по 30 минут. Использовать, когда пользователь просто просит составить/сгенерировать план дня. Уже существующие невыполненные задачи дня сохранятся и будут вписаны в план.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата плана YYYY-MM-DD, по умолчанию сегодня"},
                "notes": {"type": "string", "description": "Вводные пользователя: пары до 15:00, вечером встреча, устал и т.п."},
            },
        },
    },
    {
        "name": "replan_day",
        "description": "Пересобрать остаток сегодняшнего дня: выполненные задачи не трогаются, невыполненные перераскладываются с текущего момента с учётом нового вводного.",
        "parameters": {
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "Что изменилось: освободился в 16, добавилась встреча, нет сил и т.п."},
            },
        },
    },
    {
        "name": "log_progress",
        "description": "Записать прогресс по сфере: прочитанные страницы, подходы подтягиваний, просмотренный фильм и т.п.",
        "parameters": {
            "type": "object",
            "properties": {
                "sphere_name": {"type": "string", "description": "Имя сферы или его часть: книга, подтягивания, матан"},
                "value": {
                    "type": "object",
                    "description": "Значение прогресса, ключи по смыслу сферы",
                    "properties": {
                        "pages": {"type": "integer", "description": "Прочитано страниц"},
                        "reps": {"type": "integer", "description": "Повторений в подходе"},
                        "sets": {"type": "integer", "description": "Число подходов"},
                        "weight_kg": {"type": "number", "description": "Дополнительный вес, кг"},
                        "minutes": {"type": "integer", "description": "Потрачено минут"},
                        "title": {"type": "string", "description": "Название фильма/главы"},
                    },
                },
                "note": {"type": "string", "description": "Свободный комментарий"},
            },
            "required": ["sphere_name"],
        },
    },
    {
        "name": "update_sphere_config",
        "description": "Изменить настройки сферы: «читаю теперь 40 страниц», «готовка раз в 3 дня». Если на сегодня есть план — он автоматически пересоберётся.",
        "parameters": {
            "type": "object",
            "properties": {
                "sphere_name": {"type": "string", "description": "Имя сферы или его часть"},
                "config_updates": {
                    "type": "object",
                    "description": "Изменяемые ключи конфига",
                    "properties": {
                        "pages_per_day": {"type": "integer", "description": "Страниц в день (чтение)"},
                        "per_day": {"type": "integer", "description": "Штук в день (фильм)"},
                        "meals_per_day": {"type": "integer", "description": "Приёмов пищи в день"},
                        "cook_batch_days": {"type": "integer", "description": "Готовка раз в N дней"},
                        "deadline": {"type": "string", "description": "Дедлайн YYYY-MM-DD"},
                        "chapters": {"type": "string", "description": "Главы, например 5-9"},
                        "goal": {"type": "string", "description": "Цель сферы"},
                    },
                },
            },
            "required": ["sphere_name", "config_updates"],
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
    return today_local().isoformat()


def _minutes(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(total_minutes):
    return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"


# Пересчитывает агрегат дня из таблицы tasks по факту (не инкрементами):
# replan удаляет и создаёт задачи, инкременты разъехались бы с реальностью
def _recompute_daily_stats(db_conn, date):
    row = db_conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(status = 'done'), 0) AS done "
        "FROM tasks WHERE scheduled_date = ?",
        (date,),
    ).fetchone()
    total, done = row["total"], row["done"]
    rate = round(done / total, 3) if total else None
    db_conn.execute(
        "INSERT INTO daily_stats (stat_date, tasks_total, tasks_done, completion_rate) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(stat_date) DO UPDATE SET tasks_total = excluded.tasks_total, "
        "tasks_done = excluded.tasks_done, completion_rate = excluded.completion_rate",
        (date, total, done, rate),
    )


# Сфера по имени (частичное совпадение). Возвращает (row, error_text):
# ровно одна — (row, None), иначе (None, текст для пользователя)
def _find_sphere(db_conn, sphere_name):
    matches = db_conn.execute(
        "SELECT id, name, config FROM spheres WHERE active = 1 AND name LIKE ?",
        (f"%{sphere_name.strip().lower()}%",),
    ).fetchall()
    if len(matches) == 1:
        return matches[0], None
    all_names = ", ".join(
        row["name"] for row in db_conn.execute("SELECT name FROM spheres WHERE active = 1 ORDER BY priority DESC")
    )
    if not matches:
        return None, f"Не нашёл сферу «{sphere_name}». Активные сферы: {all_names}."
    options = ", ".join(row["name"] for row in matches)
    return None, f"Под «{sphere_name}» подходит несколько сфер: {options}. Уточни какая."


# --- Реализации tools: обычные функции с SQL ---

# Длительность из конфига сферы, чьё имя встречается в названии задачи:
# прямой duration_min, для чтения — pages_per_day / pages_per_hour
def _duration_from_spheres(db_conn, title):
    title_lower = title.lower()
    for row in db_conn.execute("SELECT name, sphere_type, config FROM spheres WHERE active = 1"):
        if row["name"].lower() not in title_lower:
            continue
        config = json.loads(row["config"])
        if config.get("duration_min"):
            return _round30(config["duration_min"])
        if row["sphere_type"] == "reading" and config.get("pages_per_day") and config.get("pages_per_hour"):
            return _round30(config["pages_per_day"] / config["pages_per_hour"] * 60)
    return None


# Итоговая длительность задачи: явная/оценка LLM важнее, потом конфиг
# сферы; None — так и не определили, генератор оценит при перепланировании
def _resolve_duration(db_conn, title, duration_min):
    if duration_min:
        return _round30(duration_min)
    return _duration_from_spheres(db_conn, title)


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
        duration = _resolve_duration(db_conn, task["title"], task.get("duration_min"))
        db_conn.execute(
            "INSERT INTO tasks (plan_id, title, task_type, scheduled_date, duration_min) VALUES (?, ?, ?, ?, ?)",
            (plan_id, task["title"], task_type, date, duration),
        )
        added_titles.append(task["title"])

    _recompute_daily_stats(db_conn, date)
    return f"{plan_note} Задачи ({len(added_titles)}): " + "; ".join(added_titles)


def tool_add_task(db_conn, title, task_type="work", date=None, duration_min=None):
    scheduled_date = date or _today()
    duration = _resolve_duration(db_conn, title, duration_min)
    # Прикрепляем к плану дня этой даты, если он существует
    plan = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (scheduled_date,),
    ).fetchone()
    plan_id = plan["id"] if plan else None
    db_conn.execute(
        "INSERT INTO tasks (plan_id, title, task_type, scheduled_date, duration_min) VALUES (?, ?, ?, ?, ?)",
        (plan_id, title, task_type, scheduled_date, duration),
    )
    _recompute_daily_stats(db_conn, scheduled_date)
    attached = "в план дня" if plan_id else "вне плана (плана на эту дату нет)"
    duration_note = f", ~{duration} мин" if duration else ""
    return f"Добавил задачу «{title}» ({task_type}{duration_note}) на {scheduled_date}, {attached}."


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
    _recompute_daily_stats(db_conn, task["scheduled_date"])
    return f"Задача «{task['title']}» отмечена выполненной."


# Нечёткое совпадение: подстрока целиком, либо каждое значимое слово
# запроса совпадает с каким-то словом названия — как подстрока или по
# общему префиксу от 3 букв («лаба» ~ «лабораторная»). LIKE в SQLite
# не умеет кириллицу без регистра, поэтому сравниваем в Python
def _words_alike(query_word, title_word):
    if query_word in title_word or title_word in query_word:
        return True
    prefix = 0
    for query_char, title_char in zip(query_word, title_word):
        if query_char != title_char:
            break
        prefix += 1
    return prefix >= 3


def _fuzzy_match(query, title):
    query_lower = query.lower().strip()
    title_lower = title.lower()
    if query_lower in title_lower:
        return True
    query_words = [word for word in query_lower.split() if len(word) > 2]
    title_words = title_lower.split()
    return bool(query_words) and all(
        any(_words_alike(query_word, title_word) for title_word in title_words)
        for query_word in query_words
    )


# Первый свободный слот нужной длины в дне с планом; None — слота нет
def _find_free_slot(db_conn, date, duration_min):
    profile = load_profile(db_conn)
    window_start = _minutes(profile.get("wake_time", "09:00"))
    window_end = _minutes(profile.get("sleep_time", "23:30"))
    if window_end <= window_start:
        window_end += 24 * 60
    if date == _today():
        now = now_local()
        window_start = max(window_start, ((now.hour * 60 + now.minute + 29) // 30) * 30)

    busy_blocks = []
    rows = db_conn.execute(
        "SELECT time_start, duration_min FROM tasks "
        "WHERE scheduled_date = ? AND time_start IS NOT NULL AND status != 'skipped'",
        (date,),
    ).fetchall()
    for row in rows:
        block_start = _minutes(row["time_start"])
        if block_start < window_start - 12 * 60:
            block_start += 24 * 60  # блок за полуночью
        busy_blocks.append((block_start, row["duration_min"] or 30))

    cursor = window_start
    for block_start, block_duration in sorted(busy_blocks):
        if block_start - cursor >= duration_min:
            return _hhmm(cursor)
        cursor = max(cursor, block_start + block_duration)
    if window_end - cursor >= duration_min:
        return _hhmm(cursor)
    return None


def tool_move_task(db_conn, query, target_date):
    today = today_local()
    date_from = (today - datetime.timedelta(days=7)).isoformat()
    date_to = (today + datetime.timedelta(days=7)).isoformat()
    rows = db_conn.execute(
        "SELECT id, title, scheduled_date, duration_min FROM tasks "
        "WHERE status = 'pending' AND scheduled_date BETWEEN ? AND ? ORDER BY scheduled_date",
        (date_from, date_to),
    ).fetchall()
    matches = [row for row in rows if _fuzzy_match(query, row["title"])]

    if not matches:
        return f"Не нашёл невыполненной задачи похожей на «{query}» в диапазоне {date_from}…{date_to}."
    if len(matches) > 1:
        options = "; ".join(f"«{row['title']}» ({row['scheduled_date']})" for row in matches)
        return f"Подходит несколько задач, уточни какую: {options}"

    task = matches[0]
    source_date = task["scheduled_date"]
    if source_date == target_date:
        return f"Задача «{task['title']}» и так стоит на {target_date}."

    # На целевой день есть план — перевставляем по времени в свободный слот
    target_plan = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (target_date,),
    ).fetchone()
    plan_id = target_plan["id"] if target_plan else None
    time_start = None
    time_note = ""
    if plan_id:
        time_start = _find_free_slot(db_conn, target_date, task["duration_min"] or 30)
        time_note = f", время {time_start}" if time_start else ", свободного слота нет — без времени"

    db_conn.execute(
        "UPDATE tasks SET scheduled_date = ?, plan_id = ?, time_start = ? WHERE id = ?",
        (target_date, plan_id, time_start, task["id"]),
    )
    _recompute_daily_stats(db_conn, source_date)
    _recompute_daily_stats(db_conn, target_date)
    return f"Перенёс «{task['title']}» с {source_date} на {target_date}{time_note}."


# Чистый дамп дня из БД: ВСЕ задачи по порядку времени, без анализа
# и сокращений. Формат строки завязан на кнопки (bot/keyboards.py)
def tool_show_day_plan(db_conn, date=None):
    target_date = date or _today()
    plan = db_conn.execute(
        "SELECT id, title FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (target_date,),
    ).fetchone()
    tasks = db_conn.execute(
        "SELECT t.id, t.title, t.status, t.time_start, t.duration_min, s.name AS sphere_name "
        "FROM tasks t LEFT JOIN spheres s ON t.sphere_id = s.id "
        "WHERE t.scheduled_date = ? ORDER BY t.time_start IS NULL, t.time_start, t.id",
        (target_date,),
    ).fetchall()

    if not plan and not tasks:
        return f"На {target_date} нет ни плана, ни задач."

    header = plan["title"] if plan else f"Задачи на {target_date} (без плана)"
    lines = [header]
    for task in tasks:
        icon = STATUS_ICONS.get(task["status"], "⬜️")
        line = f"{icon} [{task['id']}] "
        if task["time_start"] and task["duration_min"]:
            line += f"{task['time_start']}–{_hhmm(_minutes(task['time_start']) + task['duration_min'])} · "
        line += task["title"]
        if task["sphere_name"]:
            line += f" · ({task['sphere_name']})"
        lines.append(line)
    done_count = sum(1 for task in tasks if task["status"] == "done")
    lines.append(f"Выполнено: {done_count} из {len(tasks)}")
    return "\n".join(lines)


# Общий низ generate_day_plan и replan_day: генерирует блоки из сфер,
# заменяет невыполненные задачи даты новыми, done не трогает
def _rebuild_day(db_conn, date, notes, window_start):
    # Переносим только задачи вне сфер (лабы, встречи, видео): сферные
    # блоки генератор пересоздаёт сам из конфигов — если передавать их
    # как обязательные, повторная генерация плодит дубли
    carry_rows = db_conn.execute(
        "SELECT title, task_type, duration_min FROM tasks "
        "WHERE scheduled_date = ? AND status = 'pending' AND sphere_id IS NULL",
        (date,),
    ).fetchall()
    carry_tasks = [dict(row) for row in carry_rows]
    done_rows = db_conn.execute(
        "SELECT title, time_start, duration_min FROM tasks WHERE scheduled_date = ? AND status = 'done'",
        (date,),
    ).fetchall()
    done_tasks = [dict(row) for row in done_rows]

    blocks = generate_blocks(db_conn, date, notes=notes, carry_tasks=carry_tasks,
                             window_start=window_start, done_tasks=done_tasks)

    existing = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (date,),
    ).fetchone()
    if existing:
        plan_id = existing["id"]
    else:
        cursor = db_conn.execute(
            "INSERT INTO plans (plan_type, title, date_from, date_to) VALUES ('daily', ?, ?, ?)",
            (f"План на {date}", date, date),
        )
        plan_id = cursor.lastrowid

    # Старые pending удаляем: их содержимое уже переразложено в новые блоки
    db_conn.execute("DELETE FROM tasks WHERE scheduled_date = ? AND status = 'pending'", (date,))
    for block in blocks:
        db_conn.execute(
            "INSERT INTO tasks (plan_id, title, task_type, scheduled_date, sphere_id, time_start, duration_min) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_id, block["title"], block["task_type"], date,
             block["sphere_id"], block["time_start"], block["duration_min"]),
        )
    _recompute_daily_stats(db_conn, date)
    return tool_show_day_plan(db_conn, date)


# Начало окна планирования: на будущую дату — с подъёма (None = решит
# генератор), на сегодня — с ближайшей получасовой отметки от «сейчас»
def _window_start_for(db_conn, date):
    if date != _today():
        return None
    now = now_local()
    rounded_up = ((now.hour * 60 + now.minute + 29) // 30) * 30
    wake_minutes = _minutes(load_profile(db_conn).get("wake_time", "08:00"))
    return _hhmm(max(rounded_up, wake_minutes))


def tool_generate_day_plan(db_conn, date=None, notes=""):
    target_date = date or _today()
    try:
        return _rebuild_day(db_conn, target_date, notes, _window_start_for(db_conn, target_date))
    except PlanGenerationError as error:
        return f"Не получилось сгенерировать план: {error}"


def tool_replan_day(db_conn, notes=""):
    today = _today()
    try:
        return _rebuild_day(db_conn, today, notes, _window_start_for(db_conn, today))
    except PlanGenerationError as error:
        return f"Не получилось пересобрать план: {error}"


def tool_log_progress(db_conn, sphere_name, value=None, note=None):
    sphere, error_text = _find_sphere(db_conn, sphere_name)
    if sphere is None:
        return error_text
    value_json = json.dumps(value or {}, ensure_ascii=False)
    db_conn.execute(
        "INSERT INTO sphere_log (sphere_id, log_date, value, note) VALUES (?, ?, ?, ?)",
        (sphere["id"], _today(), value_json, note),
    )
    note_part = f" ({note})" if note else ""
    return f"Записал прогресс по «{sphere['name']}»: {value_json}{note_part}"


def tool_update_sphere_config(db_conn, sphere_name, config_updates):
    sphere, error_text = _find_sphere(db_conn, sphere_name)
    if sphere is None:
        return error_text
    config = json.loads(sphere["config"])
    config.update(config_updates)
    db_conn.execute(
        "UPDATE spheres SET config = ? WHERE id = ?",
        (json.dumps(config, ensure_ascii=False), sphere["id"]),
    )
    updates_text = json.dumps(config_updates, ensure_ascii=False)
    result = f"Конфиг сферы «{sphere['name']}» обновлён: {updates_text}."

    # На сегодня есть активный план — пересобираем его с новым конфигом
    today = _today()
    has_plan = db_conn.execute(
        "SELECT 1 FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (today,),
    ).fetchone()
    if has_plan:
        try:
            plan_text = _rebuild_day(
                db_conn, today,
                notes=f"изменение настроек сферы «{sphere['name']}»: {updates_text}",
                window_start=_window_start_for(db_conn, today),
            )
            result += f"\nПлан на сегодня пересобран:\n{plan_text}"
        except PlanGenerationError as error:
            result += f"\nКонфиг сохранён, но пересобрать план не вышло: {error}"
    return result


# Округление длительности вверх до получаса, минимум 30 минут
def _round30(minutes):
    return max(30, ((int(minutes) + 29) // 30) * 30)


def tool_add_video_tasks(db_conn, urls, date=None):
    scheduled_date = date or _today()
    metadata = video.get_metadata(" ".join(urls))

    plan = db_conn.execute(
        "SELECT id FROM plans WHERE plan_type = 'daily' AND date_from = ? AND status = 'active'",
        (scheduled_date,),
    ).fetchone()
    plan_id = plan["id"] if plan else None

    added_lines = []
    if metadata:
        for item in metadata:
            duration = _round30(item["duration_min"]) if item["duration_min"] else None
            db_conn.execute(
                "INSERT INTO tasks (plan_id, title, task_type, scheduled_date, duration_min) "
                "VALUES (?, ?, 'study', ?, ?)",
                (plan_id, f"Видео: {item['title']}", scheduled_date, duration),
            )
            duration_note = f"{item['duration_min']} мин → блок {duration}" if duration else "длительность неизвестна"
            added_lines.append(f"«{item['title']}» ({duration_note})")
    else:
        # Нет ключа или API упал — добавляем по ссылкам без длительности
        for url in urls:
            db_conn.execute(
                "INSERT INTO tasks (plan_id, title, task_type, scheduled_date) VALUES (?, ?, 'study', ?)",
                (plan_id, f"Видео: {url}", scheduled_date),
            )
            added_lines.append(url)
        added_lines.append("(метаданные недоступны — названия и длительность не подтянулись)")

    _recompute_daily_stats(db_conn, scheduled_date)
    return f"Добавил видео на {scheduled_date}:\n" + "\n".join(added_lines)


def tool_analyze_videos(db_conn, urls):
    metadata = video.get_metadata(" ".join(urls))
    return video.analyze(urls, metadata)


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
    "move_task": tool_move_task,
    "show_day_plan": tool_show_day_plan,
    "add_video_tasks": tool_add_video_tasks,
    "analyze_videos": tool_analyze_videos,
    "generate_day_plan": tool_generate_day_plan,
    "replan_day": tool_replan_day,
    "log_progress": tool_log_progress,
    "update_sphere_config": tool_update_sphere_config,
    "add_skill": tool_add_skill,
    "list_skills": tool_list_skills,
}


# Отметить задачу по id — для инлайн-кнопки «✅ Выполнено» (bot/keyboards.py)
def complete_task_by_id(db_conn, task_id):
    row = db_conn.execute("SELECT title, scheduled_date FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    db_conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = datetime('now') WHERE id = ?",
        (task_id,),
    )
    if row["scheduled_date"]:
        _recompute_daily_stats(db_conn, row["scheduled_date"])
    db_conn.commit()
    return row["title"]


# Точка входа: запрос от оркестратора → ответ пользователю
def run(user_request, db_conn):
    provider = get_provider("planner")
    now = now_local()
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    system_prompt = load_prompt("planner") + (
        f"\n\n# Текущая дата и время\n\nСегодня {now.date().isoformat()}, "
        f"{weekdays[now.weekday()]}, сейчас {now.strftime('%H:%M')}."
    )

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
