# ============================================
# Видео: метаданные YouTube для задач и анализ содержимого.
# Анализ — нативный video-input Gemini (модель сама смотрит YouTube URL);
# при исчерпании видео-лимита free tier — деградация до анализа
# по метаданным через обычную текстовую цепочку моделей
# ============================================

import asyncio
import json
import logging

import httpx
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, VIDEO_MODEL, YOUTUBE_API_KEY, load_prompt
from llm.router import get_provider
from search import youtube

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0

# Не скармливаем Gemini больше видео за раз — бережём дневной видео-лимит
MAX_VIDEOS_PER_ANALYSIS = 5


# Метаданные по ссылкам из текста; [] — нет ключа, нет ссылок или API упал
def get_metadata(text):
    video_ids = youtube.extract_video_ids(text)
    if not video_ids:
        return []
    if not YOUTUBE_API_KEY:
        logger.info("YOUTUBE_API_KEY не задан — метаданные видео недоступны")
        return []

    async def _fetch():
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            return await youtube.fetch_metadata(client, video_ids)

    try:
        return asyncio.run(_fetch())
    except Exception as error:
        logger.warning("YouTube API недоступен: %s", str(error)[:120])
        return []


def analyze(urls, metadata):
    urls = urls[:MAX_VIDEOS_PER_ANALYSIS]
    try:
        return _analyze_native(urls)
    except Exception as error:
        # Любая ошибка видео-входа (исчерпан дневной лимит видео-часов,
        # недоступное видео) — переходим на анализ по метаданным
        logger.warning("Видео-анализ Gemini не удался (%s), деградация до метаданных",
                       str(error)[:120])
        return _analyze_by_metadata(urls, metadata)


# Нативный путь: ссылки уходят в Gemini как video-парты
def _analyze_native(urls):
    client = genai.Client(api_key=GEMINI_API_KEY)
    parts = [types.Part(text="Проанализируй эти видео по правилам из системной инструкции.")]
    for url in urls:
        parts.append(types.Part(file_data=types.FileData(file_uri=url)))

    response = client.models.generate_content(
        model=VIDEO_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(system_instruction=load_prompt("video_analysis")),
    )
    if not response.text:
        raise ValueError("пустой ответ видео-модели")
    return response.text


def _analyze_by_metadata(urls, metadata):
    if not metadata:
        return ("Не получилось посмотреть видео (лимит видео-анализа), "
                "а метаданных нет (нужен YOUTUBE_API_KEY) — попробуй завтра.")
    provider = get_provider("video_meta")
    response = provider.chat([
        {"role": "system", "content": load_prompt("video_analysis")},
        {"role": "user", "content": "Само содержимое видео недоступно, работай по метаданным:\n"
                                    + json.dumps(metadata, ensure_ascii=False)},
    ])
    return response["content"]
