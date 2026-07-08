# ============================================
# YouTube Data API v3: метаданные видео (название, длительность)
# ============================================

import math
import re

from config import YOUTUBE_API_KEY

API_URL = "https://www.googleapis.com/youtube/v3/videos"

# youtube.com/watch?v=ID, youtu.be/ID, shorts/ID, live/ID
VIDEO_ID_PATTERN = re.compile(
    r"(?:youtube\.com/(?:watch\?[^\s]*?v=|shorts/|live/)|youtu\.be/)([\w-]{11})"
)

# ISO 8601 длительность: PT1H23M45S
ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


# Уникальные id видео из текста, порядок появления сохраняется
def extract_video_ids(text):
    return list(dict.fromkeys(VIDEO_ID_PATTERN.findall(text)))


def _duration_minutes(iso_duration):
    match = ISO_DURATION.match(iso_duration or "")
    if not match:
        return None
    hours, minutes, seconds = (int(group or 0) for group in match.groups())
    return max(1, math.ceil(hours * 60 + minutes + seconds / 60))


async def fetch_metadata(client, video_ids):
    response = await client.get(API_URL, params={
        "part": "snippet,contentDetails",
        "id": ",".join(video_ids[:50]),
        "key": YOUTUBE_API_KEY,
    })
    response.raise_for_status()

    results = []
    for item in response.json().get("items", []):
        results.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "duration_min": _duration_minutes(item["contentDetails"].get("duration")),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })
    return results
