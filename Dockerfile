FROM mozillamarketplace/centos-mysql-mkt:0.2

# Set the locale. This is mainly so that tests can write non-ascii files to
# disk.
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

# Fix multilib issues when installing openssl-devel.
RUN yum install -y --enablerepo=centosplus libselinux-devel && yum clean all

ADD docker-mysql.repo /etc/yum.repos.d/mysql.repo

RUN yum update -y \
    && yum install -y \
        supervisor \
        bash-completion \
        gcc-c++ \
        curl \
        libjpeg-devel \
        cyrus-sasl-devel \
        libxml2-devel \
        libxslt-devel \
        nodejs \
        zlib-devel \
        mysql-community-libs-compat-5.6.14-3.el6.x86_64 \
    && yum clean all

# The version in the above image is ancient, and does not support the
# --no-binary flag used in our requirements files.
# We also need to install wheels.
RUN pip install -U pip wheel

COPY requirements /pip/requirements/
RUN cd /pip && \
    pip install --build ./build --cache-dir ./cache \
        --find-links https://pyrepo.stage.mozaws.net/ \
        --no-index --no-deps \
        -r requirements/docker.txt && \
    rm -r build cache

# Install the node_modules.
RUN mkdir -p /srv/olympia-node
ADD package.json /srv/olympia-node/package.json
WORKDIR /srv/olympia-node
RUN npm install

COPY . /code
WORKDIR /code

# Preserve bash history across image updates.
# This works best when you link your local source code
# as a volume.
ENV HISTFILE /code/docker/artifacts/bash_history
# Configure bash history.
ENV HISTSIZE 50000
ENV HISTIGNORE ls:exit:"cd .."
# This prevents dupes but only in memory for the current session.
ENV HISTCONTROL erasedups

ENV CLEANCSS_BIN /srv/olympia-node/node_modules/clean-css/bin/cleancss
ENV LESS_BIN /srv/olympia-node/node_modules/less/bin/lessc
ENV STYLUS_BIN /srv/olympia-node/node_modules/stylus/bin/stylus
ENV UGLIFY_BIN /srv/olympia-node/node_modules/uglify-js/bin/uglifyjs
ENV VALIDATOR_BIN /srv/olympia-node/node_modules/addons-validator/addons-validator
