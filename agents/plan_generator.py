# ============================================
# Генератор плана дня: сферы + профиль → блоки, кратные 30 минутам.
# Свой цикл эскалации поверх цепочки моделей: ошибка JSON или
# валидации → один ретрай той же модели с текстом ошибки в промпте,
# затем переход к следующей модели (как при 429/503)
# ============================================

import json
import logging
import re

from config import load_prompt
from llm.router import get_provider_chain, is_transient
from timeutils import now_local

logger = logging.getLogger(__name__)

# Попыток на одну модель: первая + один ретрай с текстом ошибки
ATTEMPTS_PER_MODEL = 2

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")

VALID_TASK_TYPES = {"work", "study", "rest"}

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


class PlanGenerationError(Exception):
    pass


def _minutes(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(total_minutes):
    return f"{(total_minutes // 60) % 24:02d}:{total_minutes % 60:02d}"


def load_profile(db_conn):
    rows = db_conn.execute("SELECT key, value FROM user_context").fetchall()
    return {row["key"]: row["value"] for row in rows}


def _load_active_spheres(db_conn):
    rows = db_conn.execute(
        "SELECT id, name, sphere_type, config, priority FROM spheres WHERE active = 1 ORDER BY priority DESC"
    ).fetchall()
    return [dict(row) for row in rows]


# Окно дня в минутах от полуночи. Отбой раньше подъёма (00:00) —
# значит день заканчивается уже за полуночью, добавляем сутки
def _day_window(window_start, sleep_time):
    start = _minutes(window_start)
    end = _minutes(sleep_time)
    if end <= start:
        end += 24 * 60
    return start, end


def _build_request(plan_date, window_start, sleep_time, profile, spheres, carry_tasks, notes, done_tasks):
    lines = [
        f"# Дата плана\n\n{plan_date}",
        f"# Окно дня\n\nс {window_start} до {sleep_time} (отбой)",
        f"# Сейчас\n\n{now_local().strftime('%Y-%m-%d %H:%M')}, {WEEKDAYS[now_local().weekday()]}",
        "# Профиль пользователя\n\n" + json.dumps(profile, ensure_ascii=False),
        "# Сферы развития (по убыванию приоритета)\n\n" + json.dumps(spheres, ensure_ascii=False),
    ]
    if done_tasks:
        lines.append(
            "# Уже выполнено в этот день (не повторяй; их время занято, если оно ещё впереди)\n\n"
            + json.dumps(done_tasks, ensure_ascii=False)
        )
    if carry_tasks:
        lines.append("# Разместить обязательно (невыполненные задачи)\n\n" + json.dumps(carry_tasks, ensure_ascii=False))
    if notes:
        lines.append(f"# Вводные пользователя\n\n{notes}")
    lines.append("Составь план. Верни только JSON-массив блоков.")
    return "\n\n".join(lines)


def _extract_json(text):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("в ответе нет JSON-массива")
    return json.loads(text[start:end + 1])


# Проверяет план и приводит к записываемому виду.
# Бросает ValueError с текстом, который уйдёт модели в ретрай
def _validate_blocks(raw_blocks, start_min, end_min, sphere_ids_by_name):
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("ожидается непустой JSON-массив блоков")

    normalized = []
    for index, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict):
            raise ValueError(f"блок {index} — не объект")
        title = str(block.get("title") or "").strip()
        if not title:
            raise ValueError(f"блок {index}: пустой title")

        time_start = str(block.get("time_start") or "")
        if not TIME_PATTERN.match(time_start):
            raise ValueError(f"блок {index} «{title}»: time_start должен быть в формате HH:MM, получено «{time_start}»")
        duration = block.get("duration_min")
        if not isinstance(duration, int) or duration <= 0 or duration % 30 != 0:
            raise ValueError(f"блок {index} «{title}»: duration_min должен быть положительным и кратным 30, получено {duration!r}")

        block_start = _minutes(time_start)
        # Время после полуночи (00:30 при отбое 01:00) — это конец того же дня
        if block_start < start_min:
            block_start += 24 * 60
        if block_start % 30 != 0:
            raise ValueError(f"блок {index} «{title}»: начало должно быть кратно 30 минутам (:00 или :30)")
        if block_start < start_min or block_start + duration > end_min:
            raise ValueError(
                f"блок {index} «{title}» ({time_start}, {duration} мин) выходит за окно дня "
                f"{_hhmm(start_min)}–{_hhmm(end_min)}"
            )

        sphere_name = block.get("sphere")
        sphere_id = None
        if sphere_name:
            sphere_id = sphere_ids_by_name.get(str(sphere_name).lower())
            if sphere_id is None:
                valid_names = ", ".join(sphere_ids_by_name)
                raise ValueError(f"блок {index} «{title}»: неизвестная сфера «{sphere_name}», допустимые: {valid_names} или null")

        task_type = block.get("task_type")
        if task_type not in VALID_TASK_TYPES:
            task_type = "work"

        normalized.append({
            "start_min": block_start,
            "time_start": _hhmm(block_start),
            "duration_min": duration,
            "title": title,
            "sphere_id": sphere_id,
            "task_type": task_type,
        })

    normalized.sort(key=lambda block: block["start_min"])
    for previous, current in zip(normalized, normalized[1:]):
        if current["start_min"] < previous["start_min"] + previous["duration_min"]:
            raise ValueError(
                f"блоки «{previous['title']}» и «{current['title']}» пересекаются "
                f"({previous['time_start']} + {previous['duration_min']} мин и {current['time_start']})"
            )
    return normalized


# Главная функция: список валидных блоков или PlanGenerationError.
# carry_tasks — невыполненные задачи, которые обязаны попасть в план,
# window_start — начало окна (подъём или «сейчас» при перепланировании)
def generate_blocks(db_conn, plan_date, notes="", carry_tasks=None, window_start=None, done_tasks=None):
    profile = load_profile(db_conn)
    spheres = _load_active_spheres(db_conn)
    if not spheres:
        raise PlanGenerationError("Нет активных сфер — заполни таблицу spheres (python3 db/seed.py)")

    wake_time = profile.get("wake_time", "08:00")
    sleep_time = profile.get("sleep_time", "23:30")
    window_start = window_start or wake_time
    start_min, end_min = _day_window(window_start, sleep_time)
    sphere_ids_by_name = {sphere["name"].lower(): sphere["id"] for sphere in spheres}

    request = _build_request(plan_date, window_start, sleep_time, profile, spheres, carry_tasks, notes, done_tasks)
    system_prompt = load_prompt("plan_generator")

    error_feedback = None
    for provider in get_provider_chain("plan_generator"):
        for attempt in range(ATTEMPTS_PER_MODEL):
            user_message = request
            if error_feedback:
                user_message += (
                    f"\n\n# Ошибка прошлой попытки\n\n{error_feedback}\n"
                    "Исправь её и верни весь JSON-массив заново."
                )
            try:
                response = provider.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ])
            except Exception as error:
                if is_transient(error):
                    logger.warning("Генерация плана: %s недоступна (%s), следующая модель",
                                   provider.model, str(error)[:120])
                    break  # к следующей модели цепочки
                raise

            try:
                raw_blocks = _extract_json(response["content"])
                return _validate_blocks(raw_blocks, start_min, end_min, sphere_ids_by_name)
            except (ValueError, json.JSONDecodeError) as error:
                error_feedback = str(error)
                logger.warning("Генерация плана: %s, попытка %d — %s",
                               provider.model, attempt + 1, error_feedback)

    raise PlanGenerationError("Ни одна модель не вернула корректный план")
