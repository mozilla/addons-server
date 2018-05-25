FROM python:3.6-alpine

COPY run-locust.sh /

RUN apk --no-cache add --virtual=.build-dep build-base \
    && apk --no-cache add libzmq \
    && pip install --no-cache-dir -r ../../requirements/perftests.txt \
    && apk del .build-dep \
    && chmod +x /run-locust.sh

RUN  mkdir /locust
WORKDIR /locust
EXPOSE 8089 5557 5558

ENTRYPOINT ["/run-locust.sh"]
