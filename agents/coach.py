# ============================================
# Coach: недельное ревью по фактам из БД.
# Собирает метрики (daily_stats, sphere_log, задачи), считает
# адаптивное предложение по конфигу сферы и синтезирует текст.
# Сам ничего не меняет — применение только кнопкой пользователя
# ============================================

import datetime
import json
import logging

from agents.plan_generator import load_profile
from config import load_prompt
from llm.router import get_provider
from timeutils import in_wake_window, today_local

logger = logging.getLogger(__name__)

# Пороги адаптивной нагрузки: две недели подряд ниже — предлагаем
# снизить объём, две недели выше — предлагаем аккуратно добавить
LOW_THRESHOLD = 0.6
HIGH_THRESHOLD = 0.85


def _average_rate(day_rows):
    rates = [row["completion_rate"] for row in day_rows if row["completion_rate"] is not None]
    return round(sum(rates) / len(rates), 3) if rates else None


# Суммирует JSON-значения sphere_log за период: числовые ключи
# складываются, вес — максимум (интересен рабочий вес, а не сумма)
def _aggregate_logs(db_conn, sphere_id, date_from, date_to):
    rows = db_conn.execute(
        "SELECT value FROM sphere_log WHERE sphere_id = ? AND log_date > ? AND log_date <= ?",
        (sphere_id, date_from, date_to),
    ).fetchall()
    if not rows:
        return None

    totals = {"записей": len(rows)}
    for row in rows:
        for key, value in json.loads(row["value"]).items():
            if not isinstance(value, (int, float)):
                continue
            if key == "weight_kg":
                totals["max_weight_kg"] = max(totals.get("max_weight_kg", 0), value)
            else:
                totals[key] = totals.get(key, 0) + value
    return totals


def collect_metrics(db_conn):
    today = today_local()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    two_weeks_ago = (today - datetime.timedelta(days=14)).isoformat()
    today_iso = today.isoformat()

    day_rows = db_conn.execute(
        "SELECT stat_date, tasks_total, tasks_done, completion_rate FROM daily_stats "
        "WHERE stat_date > ? AND stat_date <= ? ORDER BY stat_date",
        (two_weeks_ago, today_iso),
    ).fetchall()
    current_week = [row for row in day_rows if row["stat_date"] > week_ago]
    previous_week = [row for row in day_rows if row["stat_date"] <= week_ago]

    sphere_progress = {}
    for sphere in db_conn.execute("SELECT id, name FROM spheres WHERE active = 1"):
        current = _aggregate_logs(db_conn, sphere["id"], week_ago, today_iso)
        previous = _aggregate_logs(db_conn, sphere["id"], two_weeks_ago, week_ago)
        if current or previous:
            sphere_progress[sphere["name"]] = {"эта_неделя": current, "прошлая_неделя": previous}

    sphere_completion = [dict(row) for row in db_conn.execute(
        "SELECT s.id AS sphere_id, s.name, COUNT(*) AS total, COALESCE(SUM(t.status = 'done'), 0) AS done "
        "FROM tasks t JOIN spheres s ON t.sphere_id = s.id "
        "WHERE t.scheduled_date > ? AND t.scheduled_date <= ? GROUP BY s.id ORDER BY s.priority DESC",
        (week_ago, today_iso),
    )]

    done_titles = [row["title"] for row in db_conn.execute(
        "SELECT title FROM tasks WHERE status = 'done' AND scheduled_date > ? ORDER BY scheduled_date DESC LIMIT 15",
        (week_ago,),
    )]
    stuck_titles = [row["title"] for row in db_conn.execute(
        "SELECT title FROM tasks WHERE status = 'pending' AND scheduled_date > ? AND scheduled_date < ? LIMIT 10",
        (week_ago, today_iso),
    )]

    return {
        "по_дням": [dict(row) for row in current_week],
        "среднее_эта_неделя": _average_rate(current_week),
        "среднее_прошлая_неделя": _average_rate(previous_week),
        "скользящее_14_дней": _average_rate(day_rows),
        "прогресс_сфер": sphere_progress,
        "выполнение_по_сферам": sphere_completion,
        "выполнено_за_неделю": done_titles,
        "зависшие_задачи": stuck_titles,
    }


# Конкретная правка конфига сферы-кандидата; None — крутилки нет
def _config_change(db_conn, sphere_id, action):
    row = db_conn.execute("SELECT config FROM spheres WHERE id = ?", (sphere_id,)).fetchone()
    config = json.loads(row["config"])
    if config.get("pages_per_day"):
        pages = config["pages_per_day"]
        new_pages = max(10, round(pages * 0.7 / 5) * 5) if action == "reduce" else pages + 10
        return ("pages_per_day", pages, new_pages) if new_pages != pages else None
    if config.get("duration_min"):
        duration = config["duration_min"]
        new_duration = duration - 30 if action == "reduce" else duration + 30
        return ("duration_min", duration, new_duration) if new_duration >= 30 else None
    return None


def build_suggestion(db_conn, metrics):
    current = metrics["среднее_эта_неделя"]
    previous = metrics["среднее_прошлая_неделя"]
    if current is None or previous is None:
        return None

    if current < LOW_THRESHOLD and previous < LOW_THRESHOLD:
        action = "reduce"
        # тянет вниз сфера с худшим выполнением (при заметном числе задач)
        candidates = sorted(
            (row for row in metrics["выполнение_по_сферам"] if row["total"] >= 2),
            key=lambda row: row["done"] / row["total"],
        )
    elif current > HIGH_THRESHOLD and previous > HIGH_THRESHOLD:
        action = "add"
        # добавляем туда, где стабильнее всего получается
        candidates = sorted(
            (row for row in metrics["выполнение_по_сферам"] if row["total"] >= 2),
            key=lambda row: row["done"] / row["total"],
            reverse=True,
        )
    else:
        return None

    for candidate in candidates:
        change = _config_change(db_conn, candidate["sphere_id"], action)
        if change:
            key, old_value, new_value = change
            return {
                "action": action,
                "sphere_id": candidate["sphere_id"],
                "sphere_name": candidate["name"],
                "key": key,
                "old": old_value,
                "value": new_value,
            }
    return None


def _suggestion_text(suggestion):
    verb = "снизить объём" if suggestion["action"] == "reduce" else "аккуратно добавить"
    return (f"{verb} в сфере «{suggestion['sphere_name']}»: "
            f"{suggestion['key']} {suggestion['old']} → {suggestion['value']}")


# Главная функция: (текст ревью, suggestion или None); ревью
# сохраняется в reviews для истории
def build_weekly_review(db_conn, user_request=""):
    metrics = collect_metrics(db_conn)
    suggestion = build_suggestion(db_conn, metrics)

    sections = ["# Метрики\n\n" + json.dumps(metrics, ensure_ascii=False)]
    if suggestion:
        sections.append("# Готовое предложение (перескажи именно его)\n\n" + _suggestion_text(suggestion))
    else:
        sections.append("# Предложение\n\nГотового расчётного нет — предложи одно маленькое "
                        "конкретное улучшение сам, без изменения конфигов сфер.")
    if user_request:
        sections.append("# Вопрос пользователя\n\n" + user_request)

    provider = get_provider("coach")
    response = provider.chat([
        {"role": "system", "content": load_prompt("coach")},
        {"role": "user", "content": "\n\n".join(sections)},
    ])
    review_text = response["content"]

    db_conn.execute(
        "INSERT INTO reviews (review_date, metrics, review_text) VALUES (?, ?, ?)",
        (today_local().isoformat(), json.dumps(metrics, ensure_ascii=False), review_text),
    )
    db_conn.commit()
    return review_text, suggestion


# Готов ли Coach к воскресной отправке: окно бодрствования
# и сегодня ревью ещё не было (защита от повторов при рестартах)
def ready_for_review(db_conn):
    profile = load_profile(db_conn)
    if not in_wake_window(profile.get("wake_time", "09:00"), profile.get("sleep_time", "23:30")):
        return False
    already = db_conn.execute(
        "SELECT 1 FROM reviews WHERE review_date = ?", (today_local().isoformat(),)
    ).fetchone()
    return already is None


# Ручной вызов через оркестратора («как прошла неделя», усталость)
def run(user_request, db_conn):
    review_text, _suggestion = build_weekly_review(db_conn, user_request)
    return review_text
