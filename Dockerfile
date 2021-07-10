FROM python:3.8-slim-buster

ARG DJANGO_VERSION=django32
ENV DJANGO_VERSION=$DJANGO_VERSION

ENV PYTHONDONTWRITEBYTECODE=1

ARG GROUP_ID=1000
ARG USER_ID=1000

# Run all initial setup with root user. This is the default but mentioned here
# for documentation.
# We won't switch to the `olympia` user inside the dockerfile
# but rather use the `user` option in docker-compose.yml instead
USER root

# Add support for https apt repos and gpg signed repos
RUN apt-get update && apt-get install -y \
        apt-transport-https              \
        gnupg2                           \
    && rm -rf /var/lib/apt/lists/*
# Add keys and repos for node and mysql
COPY docker/*.gpg.key /etc/pki/gpg/
RUN APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn \
    apt-key add /etc/pki/gpg/nodesource.gpg.key \
    && APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn \
    apt-key add /etc/pki/gpg/mysql.gpg.key
COPY docker/*.list /etc/apt/sources.list.d/

# IMPORTANT: When editing this list below, make sure to also update
# `Dockerfile.deploy`.
# Allow scripts to detect we're running in our own container and install
# packages.
RUN touch /addons-server-docker-container \
    && apt-get update && apt-get -t buster install -y \
        # General (dev-) dependencies
        bash-completion \
        build-essential \
        curl \
        libcap-dev \
        libjpeg-dev \
        libpcre3-dev \
        libsasl2-dev \
        libxml2-dev \
        libxslt-dev \
        locales \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
        libpcre3-dev \
        nodejs \
        # Git, because we're using git-checkout dependencies
        git \
        # Dependencies for mysql-python (from mysql apt repo, not debian)
        mysql-client \
        libmysqlclient-dev \
        swig \
        gettext \
        # Use rsvg-convert to render our static theme previews
        librsvg2-bin \
        # Use pngcrush to optimize the PNGs uploaded by developers
        pngcrush \
        # Use libmaxmind for speedy geoip lookups
        libmaxminddb0                    \
        libmaxminddb-dev                 \
    && apt-get -t buster-backports install -y \
        libgit2-dev \
    && rm -rf /var/lib/apt/lists/*

# IMPORTANT: When editing one of these lists below, make sure to also update
# `Dockerfile.deploy`.
ADD docker/etc/mime.types /etc/mime.types

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8

# Set the locale. This is mainly so that tests can write non-ascii files to
# disk.
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

COPY . /code
WORKDIR /code

RUN groupadd -g ${GROUP_ID} olympia
RUN useradd -g ${GROUP_ID} -u ${USER_ID} -Md /deps/ olympia

# Create /deps/ and move ownership over to `olympia` user so that
# we can install things there
# Also run `chown` on `/code/` which technically doesn't change permissions
# on the host but ensures that the image knows about correct permissions.
RUN mkdir /deps/ && chown -R olympia:olympia /deps/ /code/

ENV PIP_BUILD=/deps/build/
ENV PIP_CACHE_DIR=/deps/cache/
ENV PIP_SRC=/deps/src/

# Allow us to install all dependencies to the `olympia` users
# home directory (which is `/deps/`)
ENV PIP_USER=true
ENV PYTHONUSERBASE=/deps

# Make sure that installed binaries are accessible
ENV PATH $PYTHONUSERBASE/bin:$PATH

ENV NPM_CONFIG_PREFIX=/deps/
ENV SWIG_FEATURES="-D__x86_64__"

# From now on run everything with the `olympia` user by default.
USER olympia

RUN ln -s /code/package.json /deps/package.json && \
    ln -s /code/package-lock.json /deps/package-lock.json && \
    make update_deps && \
    rm -rf /deps/build/ /deps/cache/

# Preserve bash history across image updates.
# This works best when you link your local source code
# as a volume.
ENV HISTFILE /code/docker/artifacts/bash_history

# Configure bash history.
ENV HISTSIZE 50000
ENV HISTIGNORE ls:exit:"cd .."

# This prevents dupes but only in memory for the current session.
ENV HISTCONTROL erasedups

ENV CLEANCSS_BIN /deps/node_modules/.bin/cleancss
ENV LESS_BIN /deps/node_modules/.bin/lessc
ENV JS_MINIFIER_BIN /deps/node_modules/.bin/terser
ENV ADDONS_LINTER_BIN /deps/node_modules/.bin/addons-linter
