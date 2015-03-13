FROM python:2.7

RUN apt-get update
RUN apt-get install -y python-dev python-virtualenv libxml2-dev libxslt1-dev libmysqlclient-dev memcached libssl-dev swig openssl curl libjpeg-dev zlib1g-dev libsasl2-dev nodejs npm mysql-client
RUN ln -s /usr/bin/nodejs /usr/bin/node

WORKDIR /code

ADD . /code

RUN pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/ --src=/pip-src/
RUN pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/docs.txt --find-links https://pyrepo.addons.mozilla.org/ --src=/pip-src/
RUN npm install
RUN make update_assets
