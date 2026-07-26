FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (cached unless deps change).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000

# DATABASE_URL is provided at runtime (Postgres in compose).
CMD ["uv", "run", "--no-dev", "uvicorn", "bastus.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
