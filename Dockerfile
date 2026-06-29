FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY app/ app/
COPY main.py .

RUN uv sync --no-dev --no-editable

CMD ["uv", "run", "python", "main.py"]
