FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS builder

WORKDIR /srv/creatorproof
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN python -m pip install --no-cache-dir uv==0.11.33
COPY pyproject.toml uv.lock ./
# Render runs only the API coordinator. Learned models and the optional EVM
# runtime execute elsewhere, so neither dev nor blockchain extras belong here.
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS runtime

WORKDIR /srv/creatorproof
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/creatorproof/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 creatorproof \
    && useradd --system --uid 10001 --gid creatorproof --home-dir /srv/creatorproof creatorproof

COPY --from=builder /srv/creatorproof/.venv ./.venv
COPY --chown=creatorproof:creatorproof app ./app
COPY --chown=creatorproof:creatorproof model_lab ./model_lab
COPY --chown=creatorproof:creatorproof scripts ./scripts
COPY --chown=creatorproof:creatorproof benchmarks ./benchmarks
COPY --chown=creatorproof:creatorproof alembic.ini ./alembic.ini
COPY --chown=creatorproof:creatorproof migrations ./migrations
COPY --chown=creatorproof:creatorproof pyproject.toml requirements*.txt ./
COPY --chown=creatorproof:creatorproof uv.lock ./uv.lock
RUN mkdir -p /srv/creatorproof/data && chown creatorproof:creatorproof /srv/creatorproof/data

USER creatorproof
EXPOSE 8000
CMD ["python", "-m", "scripts.render_start"]
