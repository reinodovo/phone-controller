FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY sdk/pyproject.toml sdk/pyproject.toml
COPY src src
RUN uv sync --frozen --no-dev --no-editable
ENV PATH=/app/.venv/bin:$PATH PHONE_CONTROLLER_DATA=/data
CMD ["python", "-m", "controller"]
