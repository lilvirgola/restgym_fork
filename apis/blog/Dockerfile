FROM ubuntu:22.04

ENV API=blog
ENV DEBIAN_FRONTEND=noninteractive

RUN mkdir /api && \
    mkdir /results && \
    mkdir /infrastructure

COPY ./apis/blog/ /api/
COPY ./infrastructure/ /infrastructure/
COPY ./apis/blog/entrypoint.sh /entrypoint.sh
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

RUN chmod +x /entrypoint.sh && \
    apt update && \
    apt -y upgrade && \
    apt -y install openjdk-11-jdk mysql-server && \
    cd /infrastructure/mitmproxy/mutations && uv sync && \
    usermod -d /var/lib/mysql/ mysql && \
    /etc/init.d/mysql start && \
    mysql -e "CREATE DATABASE blogapi" && \
    mysql -e "CREATE USER blog@localhost IDENTIFIED BY 'blog'" && \
    mysql -e "GRANT ALL PRIVILEGES ON blogapi.* TO blog@localhost" && \
    mysql blogapi < /api/database/blogapi.sql && \
    apt -y autoremove && \
    rm -rf /var/lib/apt/lists/* && \
    mysqladmin shutdown

ENTRYPOINT ["/entrypoint.sh"]