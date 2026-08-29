FROM restgym/user-management-api:1.0.0

COPY ./infrastructure/ /infrastructure/
COPY ./apis/user-management/entrypoint.sh /entrypoint.sh

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/
RUN cd /infrastructure/mitmproxy/mutations && uv sync
EXPOSE 9090

ENTRYPOINT ["/entrypoint.sh"]