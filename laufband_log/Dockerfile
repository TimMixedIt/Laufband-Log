# BUILD_ARCH setzt der Supervisor beim Bauen (amd64 / aarch64)
ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

RUN apk add --no-cache python3 py3-aiohttp

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
