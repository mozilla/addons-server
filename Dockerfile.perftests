FROM python:2.7-alpine

COPY . /code
WORKDIR /code

RUN apk --no-cache add --virtual=.build-dep build-base git \
    && pip install --no-cache-dir -r /code/requirements/perftests.txt \
    && apk del .build-dep \
    && rm -f /tmp/* /etc/apk/cache/*

EXPOSE 8089 5557 5558
