FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
# Editable install: the code finds sql/ and config/ next to src/.
RUN pip install --no-cache-dir -e .

COPY sql ./sql
COPY config ./config

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000

# Each start builds a fresh demo: 7 days ending today, with errors and the four scenarios.
# The import may report failed runs: the screen must start anyway.
CMD ["sh", "-c", "feedhub init-db && feedhub generate --days 7 --inject-errors --scenario truncated-file --scenario price-crash --scenario dirty-file --scenario api-down && (feedhub import --all || true) && exec feedhub serve --host 0.0.0.0 --port ${PORT} --demo"]
