# ============================================
# Точка входа: сборка бота и запуск polling
# ============================================

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from bot.handlers import router as handlers_router
from bot.voice import router as voice_router
from db.database import get_connection, init_db
from scheduler.jobs import register_jobs

logger = logging.getLogger(__name__)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан — заполни .env (см. .env.example)")
        sys.exit(1)

    # База: применяем схему (идемпотентно) и открываем соединение.
    # check_same_thread=False — обработчики работают с БД из пула потоков.
    init_db()
    db_conn = get_connection(check_same_thread=False)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dispatcher = Dispatcher()
    dispatcher.include_router(handlers_router)
    dispatcher.include_router(voice_router)

    # Планировщик проактивных джоб (Muse) — в этом же event loop
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    register_jobs(scheduler, bot, db_conn)
    scheduler.start()
    if not config.TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID не задан — проактивные идеи Muse выключены")

    logger.info("Бот запущен, начинаю polling")
    try:
        # db_conn попадает в обработчики через workflow data aiogram
        await dispatcher.start_polling(bot, db_conn=db_conn)
    finally:
        scheduler.shutdown(wait=False)
        db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
