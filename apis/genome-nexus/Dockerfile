FROM ghcr.io/astral-sh/uv:0.12.2 AS uv

# Makeing this work was hell :')
FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /build

COPY infrastructure/mitmproxy/mutations/ .

RUN uv venv --python 3.12 --clear /build/.venv

RUN uv sync --frozen --no-dev

FROM restgym/genome-nexus-api:1.0.0

USER root

# Copy only the already-built environment.
COPY --from=builder /build/.venv /opt/mutation-venv

COPY infrastructure/mitmproxy/mutations \
    /infrastructure/mitmproxy/mutations

COPY apis/genome-nexus/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENV PATH="/opt/mutation-venv/bin:${PATH}"

ENTRYPOINT ["/entrypoint.sh"]