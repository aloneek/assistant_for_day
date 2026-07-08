# ============================================
# Сид: 7 сфер развития и профиль пользователя.
# Запуск из корня проекта: python3 db/seed.py
# Повторный запуск безопасен: существующие записи не трогает
# (INSERT OR IGNORE), чтобы не затереть правки, сделанные ботом.
# ============================================

import json
import sys
from pathlib import Path

# Скрипт запускается как db/seed.py — добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import get_connection, init_db

# --- Профиль пользователя ---
# key → (value, category); времена в HH:MM, meal_times через запятую
PROFILE = {
    "weight_kg": ("55", "fact"),
    "height_cm": ("181", "fact"),
    "age": ("18", "fact"),
    "wake_time": ("09:00", "preference"),
    "sleep_time": ("00:00", "preference"),
    "meal_times": ("10:00,19:00", "preference"),
}

# --- Сферы развития: из них generate_day_plan собирает день ---
SPHERES = [
    {
        "name": "python",
        "sphere_type": "learning",
        "priority": 80,
        "config": {"goal": "джун-разработчик", "focus": "pet-проекты и практика"},
    },
    {
        "name": "матан",
        "sphere_type": "learning",
        "priority": 90,
        "config": {"chapters": "5-9", "deadline": "2026-09-01"},
    },
    {
        "name": "книга",
        "sphere_type": "reading",
        "priority": 60,
        "config": {"pages_per_day": 30, "pages_per_hour": 30},
    },
    {
        "name": "фильм",
        "sphere_type": "leisure",
        "priority": 30,
        "config": {"per_day": 1, "duration_min": 120},
    },
    {
        "name": "прогулка",
        "sphere_type": "leisure",
        "priority": 40,
        "config": {"adaptive": True, "duration_min": 60},
    },
    {
        "name": "готовка",
        "sphere_type": "food",
        "priority": 70,
        "config": {"meals_per_day": 2, "cook_batch_days": 2},
    },
    {
        "name": "подтягивания",
        "sphere_type": "fitness",
        "priority": 50,
        "config": {"weighted": True, "duration_min": 30},
    },
]


def seed(conn):
    added_spheres = 0
    for sphere in SPHERES:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO spheres (name, sphere_type, config, priority) VALUES (?, ?, ?, ?)",
            (sphere["name"], sphere["sphere_type"], json.dumps(sphere["config"], ensure_ascii=False), sphere["priority"]),
        )
        added_spheres += cursor.rowcount

    added_profile = 0
    for key, (value, category) in PROFILE.items():
        cursor = conn.execute(
            "INSERT OR IGNORE INTO user_context (key, value, category) VALUES (?, ?, ?)",
            (key, value, category),
        )
        added_profile += cursor.rowcount

    conn.commit()
    return added_spheres, added_profile


if __name__ == "__main__":
    init_db()
    connection = get_connection()
    try:
        spheres_count, profile_count = seed(connection)
        print(f"Сфер добавлено: {spheres_count} из {len(SPHERES)}, "
              f"записей профиля: {profile_count} из {len(PROFILE)} (существующие пропущены)")
    finally:
        connection.close()
