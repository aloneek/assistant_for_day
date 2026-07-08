# ============================================
# Фоновые джобы. Планировщик (AsyncIOScheduler) живёт в главном
# event loop; сами джобы — async, а блокирующая работа (LLM, HTTP,
# БД) уводится в поток через to_thread — тот же паттерн, что у handlers
# ============================================

import asyncio
import logging

from agents import github_sync, muse
from bot.keyboards import build_idea_keyboard
from bot.messaging import split_message
from config import TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def register_jobs(scheduler, bot, db_conn):
    # Тик каждый час дешёвый (пара SQL-запросов): is_due сам решает,
    # пора ли — интервал MUSE_INTERVAL_DAYS + тихие часы вне окна
    # бодрствования из профиля. Генерация запускается только когда пора
    scheduler.add_job(muse_tick, "interval", hours=1, args=[bot, db_conn])
    # Раз в неделю обновляем профиль проектов из GitHub (тихо, без сообщения)
    scheduler.add_job(github_tick, "cron", day_of_week="mon", hour=12, args=[db_conn])


async def github_tick(db_conn):
    result = await asyncio.to_thread(github_sync.run, db_conn)
    logger.info("Недельный sync_github: %s", result.split(chr(10))[0])


async def muse_tick(bot, db_conn):
    if not await asyncio.to_thread(muse.is_due, db_conn):
        return

    logger.info("Muse: пора приносить идеи, запускаю генерацию")
    ideas = await asyncio.to_thread(muse.run, db_conn)
    for idea in ideas:
        text = f"💡 Идея от Muse: {idea['title']}\n\n{idea['description']}"
        parts = split_message(text)
        # Кнопки — на последней части, чтобы были под текстом целиком
        for part in parts[:-1]:
            await bot.send_message(TELEGRAM_CHAT_ID, part)
        await bot.send_message(TELEGRAM_CHAT_ID, parts[-1], reply_markup=build_idea_keyboard(idea["id"]))
