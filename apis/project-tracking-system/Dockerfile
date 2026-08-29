FROM restgym/project-tracking-system-api:1.0.0

COPY ./infrastructure/ /infrastructure/
COPY ./apis/project-tracking-system/entrypoint.sh /entrypoint.sh

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/
RUN cd /infrastructure/mitmproxy/mutations && uv sync 

ENTRYPOINT ["/entrypoint.sh"]