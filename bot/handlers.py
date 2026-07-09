# ============================================
# Обработчики Telegram: /start, текст, кнопки задач
# ============================================

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from agents import explorer, orchestrator, planner
from bot.keyboards import build_plan_keyboard, mark_task_done_in_text
from bot.messaging import split_message

router = Router()
logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Привет! Я твой ассистент: помогаю с планом дня, развитием навыков, "
    "идеями и балансом работы и отдыха.\n\n"
    "Напиши или наговори голосом, что нужно — например:\n"
    "• «составь план на завтра: лаба по физике, урок aiogram, прогулка»\n"
    "• «покажи план на сегодня»\n"
    "• «я сделал лабу»\n"
    "• «какие у меня навыки?»"
)

ERROR_TEXT = "Что-то пошло не так, попробуй ещё раз."


@router.message(CommandStart())
async def on_start(message: Message):
    await message.answer(WELCOME_TEXT)


# Общий путь текста и распознанного голоса: оркестратор → ответ.
# LLM-вызовы блокирующие, поэтому уводим их из event loop в поток.
async def process_user_text(message: Message, user_text: str, db_conn):
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await asyncio.to_thread(orchestrator.handle_message, user_text, db_conn)
    except Exception:
        # Полный traceback — в лог, пользователю — человеческое сообщение
        logger.exception("Ошибка обработки сообщения: %r", user_text)
        await message.answer(ERROR_TEXT)
        return
    # Длинный ответ — несколькими сообщениями; кнопки задач строятся
    # по каждой части отдельно, так что план не теряет «✅ Выполнено»
    for part in split_message(answer):
        await message.answer(part, reply_markup=build_plan_keyboard(part))


@router.message(F.text)
async def on_text(message: Message, db_conn):
    await process_user_text(message, message.text, db_conn)


# Кнопка «✅ Выполнено»: прямой UPDATE в БД без LLM,
# статус в сообщении с планом меняется на месте
@router.callback_query(F.data.startswith("task_done:"))
async def on_task_done(callback: CallbackQuery, db_conn):
    task_id = int(callback.data.split(":", 1)[1])
    task_title = planner.complete_task_by_id(db_conn, task_id)
    if task_title is None:
        await callback.answer("Задача не найдена")
        return

    new_text = mark_task_done_in_text(callback.message.text, task_id)
    if new_text != callback.message.text:
        await callback.message.edit_text(new_text, reply_markup=build_plan_keyboard(new_text))
    await callback.answer(f"«{task_title}» выполнена 🎉")


# Кнопка «🔍 Исследовать» под идеей от Muse: полный пайплайн Explorer
@router.callback_query(F.data.startswith("idea_explore:"))
async def on_idea_explore(callback: CallbackQuery, db_conn):
    idea_id = int(callback.data.split(":", 1)[1])
    idea = db_conn.execute(
        "SELECT title, description FROM ideas WHERE id = ?", (idea_id,)
    ).fetchone()
    if idea is None:
        await callback.answer("Идея не найдена")
        return

    await callback.answer("Исследую, это займёт полминуты…")
    await callback.message.bot.send_chat_action(callback.message.chat.id, "typing")
    answer = await asyncio.to_thread(
        explorer.explore_idea, idea_id, idea["title"], idea["description"] or "", db_conn
    )
    for part in split_message(answer):
        await callback.message.answer(part)


# Кнопка «📥 В архив»: идея скрывается из выдачи Muse и дедупликации не мешает
@router.callback_query(F.data.startswith("idea_archive:"))
async def on_idea_archive(callback: CallbackQuery, db_conn):
    idea_id = int(callback.data.split(":", 1)[1])
    db_conn.execute("UPDATE ideas SET status = 'archived' WHERE id = ?", (idea_id,))
    db_conn.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Идея в архиве 📥")


# Кнопка «✅ Применить» под ревью Coach: правка конфига сферы через
# готовый инструмент Planner (он же пересоберёт план на сегодня)
@router.callback_query(F.data.startswith("review_apply:"))
async def on_review_apply(callback: CallbackQuery, db_conn):
    _, sphere_id, config_key, config_value = callback.data.split(":")
    sphere = db_conn.execute("SELECT name FROM spheres WHERE id = ?", (int(sphere_id),)).fetchone()
    if sphere is None:
        await callback.answer("Сфера не найдена")
        return

    await callback.answer("Применяю…")
    await callback.message.bot.send_chat_action(callback.message.chat.id, "typing")

    def apply_change():
        result = planner.tool_update_sphere_config(db_conn, sphere["name"], {config_key: int(config_value)})
        db_conn.commit()
        return result

    result = await asyncio.to_thread(apply_change)
    await callback.message.edit_reply_markup(reply_markup=None)
    for part in split_message(result):
        await callback.message.answer(part, reply_markup=build_plan_keyboard(part))


@router.callback_query(F.data == "review_keep")
async def on_review_keep(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Ок, оставляем как есть")
