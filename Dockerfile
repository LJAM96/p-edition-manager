FROM --platform=$TARGETPLATFORM python:3.12-slim-bullseye
ARG TARGETPLATFORM

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        cron \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libx11-6 \
        libxkbcommon0 \
        libxrender1 \
        libxrandr2 \
        libxi6 \
        libxext6 \
        libasound2 && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r app && useradd -r -g app app

WORKDIR $APP_HOME

COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app config config
COPY --chown=app:app edition-manager.py edition-manager-gui.py edition-manager-gui.pyw edition-manager-gui.sh modules ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY edition-manager-cron.sh /usr/local/bin/edition-manager-cron.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/edition-manager-cron.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "edition-manager.py"]

USER app
