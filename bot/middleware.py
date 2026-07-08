# ============================================
# Авторизация: бот личный, работает только с владельцем.
# Outer-middleware на уровне Update — покрывает сразу все типы
# апдейтов (сообщения, голосовые, callback-кнопки)
# ============================================

import logging

from aiogram import BaseMiddleware

from config import TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # TELEGRAM_CHAT_ID не задан — дев-режим без авторизации
        # (на проде переменная обязана быть заполнена, см. DEPLOY.md)
        if not TELEGRAM_CHAT_ID:
            return await handler(event, data)

        # event_from_user aiogram кладёт в data для любого типа апдейта;
        # в личном чате id пользователя == id чата
        user = data.get("event_from_user")
        if user is None or str(user.id) != str(TELEGRAM_CHAT_ID):
            foreign_id = user.id if user else "unknown"
            logger.info("Чужой апдейт от id=%s — игнорирую без ответа", foreign_id)
            return None
        return await handler(event, data)
