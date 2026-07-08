# ============================================
# Глобальный ассистент: подключение к SQLite
# ============================================

import sqlite3
from pathlib import Path

# Пути: база и схема лежат рядом с этим файлом
DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "assistant.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


# Возвращает соединение с включённой проверкой внешних ключей.
# SQLite по умолчанию их не проверяет — PRAGMA нужна на каждое соединение.
# check_same_thread=False нужен боту: обработчики гоняют блокирующие
# вызовы через asyncio.to_thread, и соединение живёт в нескольких потоках
def get_connection(check_same_thread=True):
    conn = sqlite3.connect(DB_PATH, check_same_thread=check_same_thread)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# Читает schema.sql и применяет к базе.
# Схема идемпотентна (IF NOT EXISTS), можно вызывать повторно.
def init_db():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


# Ручная инициализация: python db/database.py
if __name__ == "__main__":
    init_db()
    print(f"База инициализирована: {DB_PATH}")
