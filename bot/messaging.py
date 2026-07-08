# ============================================
# Разбиение длинных ответов под лимит Telegram (4096 символов).
# Общий для handlers и будущих проактивных отправок (Muse)
# ============================================

TELEGRAM_LIMIT = 4096


# Режет текст по абзацам; абзац длиннее лимита — по строкам,
# строку длиннее лимита — жёстко по символам
def split_message(text, limit=TELEGRAM_LIMIT):
    if len(text) <= limit:
        return [text]

    parts = []
    current = ""
    for paragraph in text.split("\n\n"):
        for piece in _split_paragraph(paragraph, limit):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                parts.append(current)
                current = piece
    if current:
        parts.append(current)
    return parts


def _split_paragraph(paragraph, limit):
    if len(paragraph) <= limit:
        return [paragraph]
    pieces = []
    for line in paragraph.split("\n"):
        while len(line) > limit:
            pieces.append(line[:limit])
            line = line[limit:]
        pieces.append(line)
    return pieces
