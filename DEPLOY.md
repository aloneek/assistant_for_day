# Деплой на VPS (Aeza, Ubuntu)

Все команды выполняются по SSH от root (или через `sudo`). Из Франкфурта
Gemini и Groq доступны напрямую — VPN не нужен.

## 1. Системные пакеты и пользователь

```bash
apt update && apt install -y python3 python3-venv git sqlite3

# Отдельный пользователь без пароля и sudo — бот не должен работать от root
useradd --system --create-home --shell /usr/sbin/nologin assistant
```

## 2. Код и окружение

```bash
git clone https://github.com/aloneek/assistant_for_day.git /opt/global-assistant
cd /opt/global-assistant

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 3. Переменные окружения

```bash
cp .env.example .env
nano .env    # заполнить TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, GROQ_API_KEY, TELEGRAM_CHAT_ID
chmod 600 .env   # ключи не должны читаться другими пользователями
```

`TELEGRAM_CHAT_ID` на проде обязателен: это и адрес для идей Muse, и
авторизация — бот молча игнорирует все апдейты от других людей.
Узнать свой id проще всего у бота @userinfobot (поле Id).

## 4. База: перенос существующей или инициализация с нуля

Если бот уже работал локально — перенеси базу ДО первого старта сервиса,
чтобы не потерять план, сферы и идеи.

ВАЖНО: команда ниже выполняется НА МАКЕ в новом окне терминала (не в
SSH-сессии VPS!) — scp запускают на той машине, где лежит файл-источник:

```bash
scp /Users/albertosipov/unik/my_largest_project/global-assistant/db/assistant.db root@<IP-VPS>:/opt/global-assistant/db/assistant.db
```

Затем на VPS (init_db безопасен для существующей базы — только догонит
миграции; сид пропустит уже существующие записи):

```bash
cd /opt/global-assistant
.venv/bin/python db/database.py
.venv/bin/python db/seed.py
chown -R assistant:assistant /opt/global-assistant
```

Если базы нет — те же три команды создадут её с нуля.

## 5. systemd-юнит

```bash
cat > /etc/systemd/system/assistant.service <<'EOF'
[Unit]
Description=Global Assistant Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=assistant
WorkingDirectory=/opt/global-assistant
ExecStart=/opt/global-assistant/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now assistant
```

Логи пишутся в journald автоматически (stdout/stderr сервиса):

```bash
systemctl status assistant          # состояние
journalctl -u assistant -f          # хвост логов вживую
journalctl -u assistant --since today
```

## 6. Бэкап SQLite

Ежедневная копия в 04:00 через `.backup` (безопасно для открытой базы,
в отличие от cp), файлы старше 14 дней удаляются:

```bash
mkdir -p /opt/global-assistant/backups
chown assistant:assistant /opt/global-assistant/backups

crontab -u assistant -e
```

Добавить строку (одной строкой):

```
0 4 * * * sqlite3 /opt/global-assistant/db/assistant.db ".backup '/opt/global-assistant/backups/assistant-$(date +\%F).db'" && find /opt/global-assistant/backups -name 'assistant-*.db' -mtime +14 -delete
```

## 7. Обновление после нового коммита

```bash
cd /opt/global-assistant
sudo -u assistant git pull
.venv/bin/pip install -r requirements.txt   # если менялся requirements.txt
systemctl restart assistant
```

Миграции схемы применяются сами при старте (`init_db` идемпотентен).

## Заметки

- Первое голосовое сообщение скачает модель Whisper small (~500 МБ) и
  займёт пару минут — это разово. Если на VPS меньше 2 ГБ RAM и распознавание
  падает по памяти, в `bot/voice.py` поменяй `WhisperModel("small", ...)`
  на `"base"`.
- Часовой пояс бота задаётся переменной `TIMEZONE` в `.env`
  (по умолчанию Europe/Moscow), системный TZ сервера не важен.
