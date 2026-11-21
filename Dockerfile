FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ALPHASIFT_DATA_DIR=/app/data

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin alphasift \
    && mkdir -p /app/data \
    && chown -R alphasift:alphasift /app/data

WORKDIR /app

COPY pyproject.toml MANIFEST.in README.md SKILL.md .env.example LICENSE ./
COPY alphasift ./alphasift
COPY strategies ./strategies
COPY patterns ./patterns
COPY agents ./agents

RUN pip install --no-cache-dir .

USER alphasift

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)"

CMD ["alphasift", "serve", "--host", "0.0.0.0", "--port", "8765"]
