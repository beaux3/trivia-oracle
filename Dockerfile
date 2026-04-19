FROM python:3.9-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    python-telegram-bot==13.7 \
    aiohttp \
    requests \
    strenum \
    typing_extensions

COPY qbreader/ ./qbreader/
COPY main.py .

CMD ["python", "main.py"]
