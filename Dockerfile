# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin kadi \
 && mkdir -p /data /config && chown kadi:kadi /data

WORKDIR /src
COPY . .
RUN pip install --no-cache-dir . && rm -rf /src

WORKDIR /data
USER kadi
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["kadi"]
# Binds 0.0.0.0 inside the container, so KADI_TOKEN is mandatory (the server refuses to start without it).
CMD ["serve", "--config", "/config/kadi.toml", "--host", "0.0.0.0"]
