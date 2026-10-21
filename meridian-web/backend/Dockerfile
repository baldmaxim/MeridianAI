FROM python:3.13-slim

WORKDIR /app

# ffmpeg: сжатие аудио перед распознаванием (opus) + нарезка фрагментов
# openssh-client: сервис asr-tunnel (SSH-туннель к ASR-серверу GigaAM)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Не root: uid 10001 владеет приложением и каталогами записи (uploads, transcriptions).
# Остальное в /app — только чтение; /tmp доступен всем.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p uploads transcriptions \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
