
FROM docker:dind

# Install system deps
RUN apk update && \
    apk add --no-cache git nodejs npm make sudo nano curl docker-compose && \
    rm -rf /var/cache/apk/*

COPY ./setup_docker.sh /setup_docker.sh
RUN /setup_docker.sh

CMD dockerd &> docker.log & tail -f docker.log

