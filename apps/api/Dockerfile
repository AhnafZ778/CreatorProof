FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

WORKDIR /srv/creatorproof
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv==0.11.33
COPY pyproject.toml uv.lock ./
# Ship the locked EAS runtime in the official image. The chain remains disabled
# until an operator supplies a schema and signer through deployment secrets.
RUN uv sync --frozen --no-dev --extra blockchain
COPY requirements*.txt ./
COPY app ./app
COPY model_lab ./model_lab
COPY scripts ./scripts
COPY benchmarks ./benchmarks
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
