FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS builder

WORKDIR /app

RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends gcc libpq-dev; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 默认使用官方 HTTPS 源；网络受限环境可通过 build-arg 覆盖为可信 HTTPS 镜像。
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt && pip check

COPY . .

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

WORKDIR /app

# 系统依赖：PostgreSQL 客户端 + Playwright Chromium 运行时所需库
ARG DEBIAN_MIRROR=
RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    if [ -n "${DEBIAN_MIRROR}" ]; then \
      sed -i \
        -e "s|https://deb.debian.org/debian-security|${DEBIAN_MIRROR}/debian-security|g" \
        -e "s|https://deb.debian.org/debian|${DEBIAN_MIRROR}/debian|g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get -o Acquire::Retries=5 update; \
    attempt=1; \
    while ! apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        libpq5 curl ffmpeg \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0; do \
      if [ "$attempt" -ge 5 ]; then exit 1; fi; \
      attempt=$((attempt + 1)); \
      apt-get -o Acquire::Retries=5 update; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Playwright browser install location (shared path readable by appuser).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# 留空使用 Playwright 官方 CDN；网络受限环境可覆盖为可信镜像。
ARG PLAYWRIGHT_DOWNLOAD_HOST=

# Install Chromium in a cacheable layer before copying application source.
RUN set -eux; \
    mkdir -p /ms-playwright; \
    if [ -n "${PLAYWRIGHT_DOWNLOAD_HOST}" ]; then \
        PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST}" python -m playwright install chromium --no-shell; \
    else \
        python -m playwright install chromium --no-shell; \
    fi; \
    chmod -R 775 /ms-playwright

COPY --from=builder /app /app

# Validate the browser with the application's executable discovery logic.
RUN python -c "from app.integrations.synapse_engine.utils.playwright_provider import assert_chromium_ready; exe=assert_chromium_ready(headless=True); print(f'Playwright Chromium executable: {exe}')"
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 非 root 用户运行
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app /entrypoint.sh /ms-playwright
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS -H "Host: ${HEALTHCHECK_HOST:-health.internal}" http://127.0.0.1:8000/health/ready || exit 1

CMD ["/entrypoint.sh"]
