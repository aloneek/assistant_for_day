# ============================================
# Инлайн-клавиатуры: кнопки «✅ Выполнено» у задач плана
# ============================================

import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Строка невыполненной задачи в выводе show_today, время опционально:
#   ⬜️ [7] Урок aiogram (study)
#   ⬜️ [7] 09:00–10:00 · Урок aiogram (study)
PENDING_TASK_LINE = re.compile(
    r"^⬜️ \[(\d+)\] (?:\d{1,2}:\d{2}–\d{1,2}:\d{2} · )?(.+?)(?: \((?:work|study|rest)\))?$",
    re.MULTILINE,
)

# Любая строка задачи (для пересчёта счётчика)
ANY_TASK_LINE = re.compile(r"^(⬜️|✅|⏭) \[\d+\]", re.MULTILINE)
DONE_TASK_LINE = re.compile(r"^✅ \[\d+\]", re.MULTILINE)
COUNTER_LINE = re.compile(r"Выполнено: \d+ из \d+")

# Максимальная длина названия задачи на кнопке
BUTTON_TITLE_LIMIT = 30


# Собирает клавиатуру по тексту ответа: кнопка на каждую невыполненную
# задачу. Если строк задач в тексте нет — клавиатура не нужна (None).
def build_plan_keyboard(answer_text):
    buttons = []
    for match in PENDING_TASK_LINE.finditer(answer_text):
        task_id, title = match.group(1), match.group(2)
        if len(title) > BUTTON_TITLE_LIMIT:
            title = title[: BUTTON_TITLE_LIMIT - 1] + "…"
        buttons.append([
            InlineKeyboardButton(text=f"✅ {title}", callback_data=f"task_done:{task_id}")
        ])
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Правит текст сообщения после нажатия кнопки: меняет иконку задачи
# на ✅ и пересчитывает строку «Выполнено: N из M»
def mark_task_done_in_text(message_text, task_id):
    new_text = message_text.replace(f"⬜️ [{task_id}]", f"✅ [{task_id}]")
    total = len(ANY_TASK_LINE.findall(new_text))
    done = len(DONE_TASK_LINE.findall(new_text))
    if total:
        new_text = COUNTER_LINE.sub(f"Выполнено: {done} из {total}", new_text)
    return new_text
