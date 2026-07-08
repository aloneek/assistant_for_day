# ============================================
# Голосовые сообщения: ogg → faster-whisper → общий пайплайн
# ============================================

import asyncio
import io
import logging

from aiogram import F, Router
from aiogram.types import Message

from bot.handlers import process_user_text

router = Router()
logger = logging.getLogger(__name__)

# Модель Whisper тяжёлая (несколько секунд на инициализацию) —
# грузим лениво один раз и держим в глобальной переменной
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        logger.info("Загружаю модель Whisper (small, cpu, int8) — это делается один раз")
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model


# Блокирующее распознавание — зовётся только из потока через to_thread
def transcribe(audio_bytes):
    model = get_whisper_model()
    segments, _info = model.transcribe(io.BytesIO(audio_bytes), language="ru")
    return "".join(segment.text for segment in segments).strip()


@router.message(F.voice)
async def on_voice(message: Message, db_conn):
    await message.bot.send_chat_action(message.chat.id, "typing")

    # Скачиваем ogg в память — файлы голосовых маленькие
    audio_buffer = io.BytesIO()
    await message.bot.download(message.voice, destination=audio_buffer)

    try:
        recognized_text = await asyncio.to_thread(transcribe, audio_buffer.getvalue())
    except Exception:
        logger.exception("Ошибка распознавания голосового")
        await message.answer("Не смог распознать голосовое, попробуй ещё раз.")
        return

    if not recognized_text:
        await message.answer("Не расслышал слов в голосовом, попробуй ещё раз.")
        return

    # Показываем распознанный текст, дальше — тот же путь, что у текста
    await message.answer(f"🎙 Распознал: «{recognized_text}»")
    await process_user_text(message, recognized_text, db_conn)
