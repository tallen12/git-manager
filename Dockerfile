# Runtime image skeleton. Process isolation (supervisor and the gm, gm-claude and
# gm-tests users), the Claude CLI, gh and gh-stack arrive in M1; see design-docs/spec.md.
FROM ghcr.io/astral-sh/uv:0.13.4 AS uv
FROM python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
ARG APP_UID=10001
ARG APP_GID=10001
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" gm \
    && useradd --create-home --uid "$APP_UID" --gid "$APP_GID" gm
WORKDIR /app
# Dependencies first, so source edits reuse the cached dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH"
USER gm
ENTRYPOINT ["git-manager"]
CMD ["web", "--host", "0.0.0.0"]
