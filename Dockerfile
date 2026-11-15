# Pocket Agent: one small container that long-polls Telegram 24/7.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Everything that must survive a restart lives on the /data volume:
    DB_PATH=/data/pocket.db \
    LOG_DIR=/data/logs \
    BACKUP_DIR=/data/backups \
    # Whisper model cache, so it isn't re-downloaded on every restart.
    HF_HOME=/data/hf-cache

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot ./bot

# Don't run as root: a bug in the bot then can't touch the rest of the container.
RUN useradd --create-home --uid 1000 pocket && mkdir /data && chown pocket:pocket /data
USER pocket
VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
