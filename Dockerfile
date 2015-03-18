FROM python:2.7

RUN apt-get update \
    && apt-get install -y \
        curl \
        libjpeg-dev \
        libmysqlclient-dev \
        libsasl2-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        memcached \
        mysql-client \
        nodejs \
        npm \
        python-dev \
        python-virtualenv \
        swig openssl \
        zlib1g-dev \
    && ln -s /usr/bin/nodejs /usr/bin/node

ADD . /code
WORKDIR /code

RUN pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache \
    -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/ \
    --src=/pip-src/

