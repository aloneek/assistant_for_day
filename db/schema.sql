-- ============================================
-- Глобальный ассистент: схема SQLite
-- ============================================

-- Планы: план дня или план развития на 1–2 месяца
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_type TEXT NOT NULL CHECK (plan_type IN ('daily', 'longterm')),
    title TEXT NOT NULL,                -- «План на 7 июля» / «Освоить FastAPI за месяц»
    date_from TEXT NOT NULL,            -- YYYY-MM-DD
    date_to TEXT,                       -- для daily = date_from
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'revised')),
    idea_id INTEGER,                    -- из какой идеи вырос план (NULL = не из идеи)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE SET NULL
);

-- Задачи: единицы плана дня (блоки по 30 минут при генерации из сфер)
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER,                    -- к какому плану относится (NULL = вне плана)
    title TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'work' CHECK (task_type IN ('work', 'study', 'rest')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'skipped')),
    scheduled_date TEXT,                -- YYYY-MM-DD, на какой день назначена
    sphere_id INTEGER REFERENCES spheres(id) ON DELETE SET NULL,  -- из какой сферы (NULL = вне сфер)
    time_start TEXT,                    -- HH:MM, начало блока в плане дня
    duration_min INTEGER,               -- длительность блока, кратна 30
    completed_at TEXT,                  -- когда фактически выполнена
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE SET NULL
);

-- Сферы развития: источники, из которых генерируется план дня
CREATE TABLE IF NOT EXISTS spheres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,          -- python, матан, книга, ...
    sphere_type TEXT NOT NULL CHECK (sphere_type IN ('learning', 'reading', 'fitness', 'leisure', 'food')),
    config TEXT NOT NULL DEFAULT '{}',  -- JSON: параметры сферы (pages_per_day, deadline, ...)
    priority INTEGER NOT NULL DEFAULT 0,-- выше значение = важнее при нехватке времени в дне
    active INTEGER NOT NULL DEFAULT 1,  -- 0 = сфера на паузе, в план не попадает
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Журнал прогресса по сферам: страницы, подходы, просмотренные фильмы
CREATE TABLE IF NOT EXISTS sphere_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sphere_id INTEGER NOT NULL,
    log_date TEXT NOT NULL,             -- YYYY-MM-DD
    value TEXT NOT NULL DEFAULT '{}',   -- JSON: {"pages": 30} / {"reps": 8, "weight_kg": 10}
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (sphere_id) REFERENCES spheres(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sphere_log_date ON sphere_log(sphere_id, log_date);

-- Навыки: что я умею и что изучаю
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,          -- название навыка (python, aiogram, esp32)
    level TEXT NOT NULL DEFAULT 'learning' CHECK (level IN ('learning', 'confident', 'expert')),
    source TEXT,                        -- откуда узнали: manual | github | plan
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Идеи: мои + сгенерированные Muse
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    origin TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('user', 'muse')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'explored', 'in_progress', 'rejected', 'archived')),
    exploration_result TEXT,            -- вывод Explorer: аналоги, отличия, ниша
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Контекст: интересы, предпочтения, факты обо мне
CREATE TABLE IF NOT EXISTS user_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,           -- interest_robotics, pref_rest_movies
    value TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'interest', 'preference', 'fact')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- История выполнения: сырьё для скользящего среднего Coach
CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_date TEXT NOT NULL UNIQUE,     -- YYYY-MM-DD
    tasks_total INTEGER NOT NULL DEFAULT 0,
    tasks_done INTEGER NOT NULL DEFAULT 0,
    completion_rate REAL                -- done / total, считается при закрытии дня
);

-- Индексы под основные запросы: план дня и выборка по плану
CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(scheduled_date, status);
CREATE INDEX IF NOT EXISTS idx_tasks_plan ON tasks(plan_id);

-- Триггеры: автообновление updated_at
CREATE TRIGGER IF NOT EXISTS trg_skills_updated_at
AFTER UPDATE ON skills
FOR EACH ROW
BEGIN
    UPDATE skills SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_user_context_updated_at
AFTER UPDATE ON user_context
FOR EACH ROW
BEGIN
    UPDATE user_context SET updated_at = datetime('now') WHERE id = NEW.id;
END;
