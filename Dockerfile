# Runtime image: the daemon, Claude and the test commands run as three users under a
# supervisor (see Process isolation in design-docs/spec.md). Run it with compose.yaml,
# which drops every capability except the four the supervisor keeps.
FROM ghcr.io/astral-sh/uv:0.13.4-python3.14-trixie-slim

# Pinned tool versions; bump deliberately.
ARG NODE_VERSION=24.22.1
ARG GH_VERSION=2.103.2
ARG GH_STACK_VERSION=v0.2.1
ARG CLAUDE_CODE_VERSION=2.1.310
ARG TARGETARCH

# tini is PID 1 (reaps orphans, forwards signals); just and make serve repos' test commands.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git just make openssh-client tini \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    archive="gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz"; \
    cd "$(mktemp -d)"; \
    curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${archive}"; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
        | grep " ${archive}\$" | sha256sum -c -; \
    tar -xzf "${archive}"; \
    install -m 0755 "gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh; \
    cd /; rm -rf "${OLDPWD}"

# Claude Code needs Node 22 or later; Debian ships 20, so use the official build.
RUN set -eu; \
    case "${TARGETARCH}" in amd64) arch=x64 ;; arm64) arch=arm64 ;; \
        *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; esac; \
    archive="node-v${NODE_VERSION}-linux-${arch}.tar.gz"; \
    cd "$(mktemp -d)"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/${archive}"; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" \
        | grep " ${archive}\$" | sha256sum -c -; \
    tar -xzf "${archive}" -C /usr/local --strip-components=1 --no-same-owner \
        --exclude='*/CHANGELOG.md' --exclude='*/LICENSE' --exclude='*/README.md'; \
    cd /; rm -rf "${OLDPWD}"

RUN npm install --global "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

# gm runs the daemon and owns /data; gm-claude runs Claude; gm-tests runs setup, test and
# lint. Only gm is in gm-admin, the group that may use the API socket.
ARG GM_UID=10001
ARG GM_CLAUDE_UID=10002
ARG GM_TESTS_UID=10003
ARG GM_ADMIN_GID=10000
RUN groupadd --gid "$GM_ADMIN_GID" gm-admin \
    && useradd --uid "$GM_UID" --user-group --groups gm-admin --create-home \
        --shell /usr/sbin/nologin gm \
    && useradd --uid "$GM_CLAUDE_UID" --user-group --create-home \
        --shell /usr/sbin/nologin gm-claude \
    && useradd --uid "$GM_TESTS_UID" --user-group --create-home \
        --shell /usr/sbin/nologin gm-tests \
    && chmod 0700 /home/gm /home/gm-claude /home/gm-tests

ENV GH_NO_UPDATE_NOTIFIER=1 \
    GH_STACK_NO_UPDATE_NOTIFIER=1 \
    GH_PROMPT_DISABLED=1 \
    DISABLE_AUTOUPDATER=1

# gh extensions are per user; only gm runs gh. The root file system is read-only at run
# time, so the pinned extension is installed here, into gm's home.
USER gm
RUN gh extension install github/gh-stack --pin "${GH_STACK_VERSION}"
USER root

WORKDIR /app
# Bytecode is compiled at build time: the root file system is read-only at run time.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
# Dependencies first, so source edits reuse the cached dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-cache
ENV PATH="/app/.venv/bin:$PATH"

# The daemon runs in local mode against the mounted config (see design-docs/spec.md).
ENV GM_TARGET__CONFIG=/etc/git-manager/config.yaml \
    GM_HTTP__HOST=0.0.0.0

# The supervisor needs root (with only CAP_CHOWN, CAP_KILL, CAP_SETGID and CAP_SETUID) to
# start the daemon as gm and commands as gm-claude or gm-tests.
USER root
ENTRYPOINT ["tini", "--", "git-manager-supervisor"]
CMD ["git-manager", "serve"]
