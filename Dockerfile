FROM python:3.9-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    python-telegram-bot==13.7 \
    aiohttp \
    requests \
    strenum \
    typing_extensions

COPY qbreader/ ./qbreader/
COPY config.py settings.py scores.py round.py keyboards.py handlers.py main.py ./

CMD ["python", "main.py"]
