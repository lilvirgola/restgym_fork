FROM restgym/genome-nexus-api:1.0.0 AS base

FROM mongo:7.0

ENV API=genome-nexus
ENV DEBIAN_FRONTEND=noninteractive

RUN mkdir -p /api \
    /results \
    /infrastructure

# Copy Genome Nexus application artifacts from the old image
COPY --from=base /api/ /api/

COPY --from=base /api/specifications/ /specifications/

# Copy our infrastructure
COPY ./infrastructure/ /infrastructure/

# Entrypoint
COPY ./apis/genome-nexus/entrypoint.sh /entrypoint.sh

# uv
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

RUN chmod +x /entrypoint.sh \
    /infrastructure/jacoco/*.sh \
    && apt-get update \
    && apt-get install -y \
        openjdk-11-jdk \
    && cd /infrastructure/mitmproxy/mutations && uv sync \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/entrypoint.sh"]