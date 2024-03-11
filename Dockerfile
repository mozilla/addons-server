##### Important information for maintaining this Dockerfile ########################################
# Read the docs/topics/development/docker.md file for more information about this Dockerfile.
####################################################################################################

FROM python:3.10-slim-buster as base

# Should change it to use ARG instead of ENV for OLYMPIA_UID/OLYMPIA_GID
# once the jenkins server is upgraded to support docker >= v1.9.0
ENV OLYMPIA_UID=9500 \
    OLYMPIA_GID=9500
RUN groupadd -g ${OLYMPIA_GID} olympia && useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_GID} -s /sbin/nologin -d /data/olympia olympia

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

# Allow scripts to detect we're running in our own container and install
# packages.
RUN touch /addons-server-docker-container \
    && apt-get update && apt-get install -y \
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
    && rm -rf /var/lib/apt/lists/*

# Add our custom mime types (required for for ts/json/md files)
ADD docker/etc/mime.types /etc/mime.types

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

ENV HOME /data/olympia

# version.json is overwritten by CircleCI (see circle.yml).
# The pipeline v2 standard requires the existence of /app/version.json
# inside the docker image, thus it's copied there.
COPY version.json /app/version.json
WORKDIR ${HOME}
# give olympia access to the HOME directory
RUN chown -R olympia:olympia ${HOME}

# Set up directories and links that we'll need later, before switching to the
# olympia user.
RUN mkdir /deps \
    && chown -R olympia:olympia /deps \
    && rm -rf ${HOME}/src/olympia.egg-info \
    && mkdir -p ${HOME}/src/olympia.egg-info \
    && chown olympia:olympia ${HOME}/src/olympia.egg-info \
    # For backwards-compatibility purposes, set up links to uwsgi. Note that
    # the target doesn't exist yet at this point, but it will later.
    && ln -s /deps/bin/uwsgi /usr/bin/uwsgi \
    && ln -s /usr/bin/uwsgi /usr/sbin/uwsgi

USER olympia:olympia

# Install all dependencies, and add symlink for old uwsgi binary paths
ENV PIP_USER=true
ENV PIP_BUILD=/deps/build/
ENV PIP_CACHE_DIR=/deps/cache/
ENV PIP_SRC=/deps/src/
ENV PYTHONUSERBASE=/deps
ENV PATH $PYTHONUSERBASE/bin:$PATH
ENV NPM_CONFIG_PREFIX=/deps/
ENV NPM_CACHE_DIR=/deps/cache/npm
ENV NPM_DEBUG=true

RUN \
    # Files needed to run the make command
    --mount=type=bind,source=Makefile,target=${HOME}/Makefile \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=setup.py,target=${HOME}/setup.py \
    --mount=type=bind,source=./requirements,target=${HOME}/requirements \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_GID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_GID} \
    # Command to install dependencies
    ln -s ${HOME}/package.json /deps/package.json \
    && ln -s ${HOME}/package-lock.json /deps/package-lock.json \
    && make update_deps_prod

FROM base as builder
ARG LOCALE_DIR=${HOME}/locale
# Compile locales
# Copy the locale files from the host so it is writable by the olympia user
COPY --chown=olympia:olympia locale ${LOCALE_DIR}
# Copy the executable individually to improve the cache validity
RUN --mount=type=bind,source=locale/compile-mo.sh,target=${HOME}/compile-mo.sh \
    ${HOME}/compile-mo.sh ${LOCALE_DIR}

FROM base as final
# Only copy our source files after we have installed all dependencies
# TODO: split this into a separate stage to make even blazingly faster
WORKDIR ${HOME}
# Copy compiled locales from builder
COPY --from=builder --chown=olympia:olympia ${HOME}/locale ${HOME}/locale
# Copy the rest of the source files from the host
COPY --chown=olympia:olympia . ${HOME}

# Finalize the build
# TODO: We should move update_assets to the `builder` stage once we can efficiently
# Run that command without having to copy the whole source code
# This will shave nearly 1 minute off the best case build time
RUN echo "from olympia.lib.settings_base import *" > settings_local.py \
    && DJANGO_SETTINGS_MODULE="settings_local" make update_assets \
    && make prune_deps \
    && ./scripts/generate_build.py > build.py \
    && rm -f settings_local.py settings_local.pyc
