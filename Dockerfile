## syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie@sha256:b3c543b6c4f23a5f2df22866bd7857e5d304b67a564f4feab6ac22044dde719b AS uv_source
FROM tianon/gosu:1.19-trixie@sha256:3b176695959c71e123eb390d427efc665eeb561b1540e82679c15e992006b8b9 AS gosu_source
FROM debian:13.4

ARG DOTNET_CHANNEL=8.0
ARG DOTNET_INSTALL_SCRIPT_URL=https://dot.net/v1/dotnet-install.sh
ARG DOTNET_INSTALL_FEED=
ARG HERMES_DOCKER_EXTRAS=all
ARG HERMES_DOCKER_EXTRA_PACKAGES=anthropic==0.87.0
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security

# Disable Python stdout buffering to ensure logs are printed immediately
ENV PYTHONUNBUFFERED=1

# Store Playwright browsers outside the volume mount so the build-time
# install survives the /opt/data volume overlay at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright
ENV DOTNET_ROOT=/usr/share/dotnet
ENV HERMES_WORKSPACE=/opt/workspace
ENV TERMINAL_CWD=/opt/workspace

# Install system dependencies in one layer, with cached apt metadata.
# Notes:
# - ffmpeg intentionally omitted: only needed for voice/TTS-heavy deployments
# - docker-cli intentionally omitted: only needed for the docker terminal backend
# - build-essential intentionally omitted: keep the smaller gcc/python3-dev/libffi-dev
#   subset for common Python extension builds without pulling the full toolchain meta-package
# - tini reaps orphaned zombie processes when hermes runs as PID 1 (#15012)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    printf '%s\n' \
      "deb ${APT_MIRROR} trixie main contrib non-free non-free-firmware" \
      "deb ${APT_MIRROR} trixie-updates main contrib non-free non-free-firmware" \
      "deb ${APT_SECURITY_MIRROR} trixie-security main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list.d/hermes.sources.list && \
    rm -f /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates nodejs npm python3 ripgrep gcc python3-dev libffi-dev procps git openssh-client tini \
        unzip fontconfig fonts-liberation fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p "$DOTNET_ROOT" && \
    curl -fsSL \
        --retry 6 \
        --retry-delay 5 \
        --retry-all-errors \
        --connect-timeout 20 \
        "$DOTNET_INSTALL_SCRIPT_URL" \
        -o /tmp/dotnet-install.sh && \
    dotnet_install_args="--channel $DOTNET_CHANNEL --install-dir $DOTNET_ROOT" && \
    if [ -n "$DOTNET_INSTALL_FEED" ]; then \
        dotnet_install_args="$dotnet_install_args --azure-feed $DOTNET_INSTALL_FEED"; \
    fi && \
    bash /tmp/dotnet-install.sh $dotnet_install_args && \
    ln -sf "$DOTNET_ROOT/dotnet" /usr/local/bin/dotnet && \
    rm -f /tmp/dotnet-install.sh

# Non-root user for runtime; UID can be overridden via HERMES_UID at runtime
RUN useradd -u 10000 -m -d /opt/data hermes

COPY --chmod=0755 --from=gosu_source /gosu /usr/local/bin/
COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

WORKDIR /opt/hermes

# ---------- Layer-cached dependency install ----------
# Copy only package manifests first so npm install + Playwright are cached
# unless the lockfiles themselves change.
COPY package.json package-lock.json ./

RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm install --prefer-offline --no-audit && \
    npx playwright install --with-deps chromium --only-shell && \
    npm cache clean --force

# ---------- Source code ----------
# .dockerignore excludes node_modules, so the installs above survive.
COPY --chown=hermes:hermes . .
RUN sed -i 's/\r$//' /opt/hermes/docker/entrypoint.sh && \
    chmod 0755 /opt/hermes/docker/entrypoint.sh

# ---------- Permissions ----------
# Make install dir world-readable so any HERMES_UID can read it at runtime.
# The venv needs to be traversable too.
USER root
RUN chmod -R a+rX /opt/hermes
# Start as root so the entrypoint can usermod/groupmod + gosu.
# If HERMES_UID is unset, the entrypoint drops to the default hermes user (10000).

# ---------- Python virtualenv ----------
RUN uv venv && \
    uv pip install --no-cache-dir -e ".[${HERMES_DOCKER_EXTRAS}]" && \
    if [ -n "$HERMES_DOCKER_EXTRA_PACKAGES" ]; then \
        uv pip install --no-cache-dir $HERMES_DOCKER_EXTRA_PACKAGES; \
    fi

# ---------- Runtime ----------
ENV HERMES_HOME=/opt/data
ENV PATH="/opt/data/.local/bin:${DOTNET_ROOT}:${PATH}"
VOLUME [ "/opt/data", "/opt/workspace" ]
ENTRYPOINT [ "/usr/bin/tini", "-g", "--", "/opt/hermes/docker/entrypoint.sh" ]
