FROM python:2.7.14-slim-stretch

ENV PYTHONDONTWRITEBYTECODE=1

# Allow scripts to detect we're running in our own container
RUN touch /addons-server-docker-container

# Add nodesource repository and requirements
ADD docker/nodesource.gpg.key /etc/pki/gpg/GPG-KEY-nodesource
RUN apt-get update && apt-get install -y \
        gnupg2 \
    && rm -rf /var/lib/apt/lists/*
RUN cat /etc/pki/gpg/GPG-KEY-nodesource | apt-key add -
ADD docker/debian-stretch-nodesource-repo /etc/apt/sources.list.d/nodesource.list

# Upgrade git
RUN apt-get update && apt-get install -y \
        # General (dev-) dependencies
        bash-completion \
        build-essential \
        curl \
        libjpeg-dev \
        libsasl2-dev \
        libxml2-dev \
        libxslt-dev \
        locales \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
        python-dev \
        python-pip \
        nodejs \
        npm \
        # Git, because we're using git-checkout dependencies
        git \
        # Dependencies for mysql-python
        mysql-client \
        default-libmysqlclient-dev \
        swig \
        gettext \
        # Use rsvg-convert to render our static theme previews
        librsvg2-bin \
        # Use pngcrush to optimize the PNGs uploaded by developers
        pngcrush \
    && rm -rf /var/lib/apt/lists/*

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8

# Set the locale. This is mainly so that tests can write non-ascii files to
# disk.
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

COPY . /code
WORKDIR /code

ENV PIP_BUILD=/deps/build/
ENV PIP_CACHE_DIR=/deps/cache/
ENV PIP_SRC=/deps/src/
ENV NPM_CONFIG_PREFIX=/deps/
ENV SWIG_FEATURES="-D__x86_64__"

# Install all python requires
RUN mkdir -p /deps/{build,cache,src}/ && \
    ln -s /code/package.json /deps/package.json && \
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
ENV UGLIFY_BIN /deps/node_modules/.bin/uglifyjs
ENV ADDONS_LINTER_BIN /deps/node_modules/.bin/addons-linter
