FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    H2S_DATA_DIR=/data \
    H2S_HOST=0.0.0.0 \
    TZ=Europe/Amsterdam

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && rm -rf /src

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data /config \
    && chown app:app /data /config

USER app
# a config file mounted at /config/config.toml is picked up as ./config.toml
WORKDIR /config
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=1m --timeout=5s --start-period=30s CMD ["h2s-alerts", "health"]

ENTRYPOINT ["h2s-alerts"]
CMD ["watch"]
