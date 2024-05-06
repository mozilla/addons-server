##### Important information for maintaining this Dockerfile ########################################
# Read the docs/topics/development/docker.md file for more information about this Dockerfile.
####################################################################################################

FROM python:3.10-slim-bookworm as base

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
        locales \
        zlib1g-dev \
        libffi-dev \
        libssl-dev \
        nodejs \
        # Git, because we're using git-checkout dependencies
        git \
        # Dependencies for mysql-python (from mysql apt repo, not debian)
        pkg-config \
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
    && ln -s /usr/bin/uwsgi /usr/sbin/uwsgi \
    && ln -s ${HOME}/package.json /deps/package.json \
    && ln -s ${HOME}/package-lock.json /deps/package-lock.json

USER olympia:olympia

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
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/pip.txt,target=${HOME}/requirements/pip.txt \
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    # Command to install dependencies
    make -f Makefile-docker update_deps_pip

FROM base as pip_production

RUN \
    # Files needed to run the make command
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/prod.txt,target=${HOME}/requirements/prod.txt \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_GID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_GID} \
    # Command to install dependencies
    make -f Makefile-docker update_deps_production

FROM pip_production as locales
ARG LOCALE_DIR=${HOME}/locale
# Compile locales
# Copy the locale files from the host so it is writable by the olympia user
COPY --chown=olympia:olympia locale ${LOCALE_DIR}
# Copy the executable individually to improve the cache validity
RUN \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,source=locale/compile-mo.sh,target=${HOME}/compile-mo.sh \
    --mount=type=bind,source=requirements/locale.txt,target=${HOME}/requirements/locale.txt \
    make -f Makefile-docker compile_locales

FROM pip_production as assets

# TODO: This stage depends on `olympia` being installed.
# We should decouple the logic from the `olympia` installation
# So it can cache more efficiently
RUN \
    # Files needed to run the make command
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=setup.py,target=${HOME}/setup.py \
    --mount=type=bind,source=pyproject.toml,target=${HOME}/pyproject.toml \
    # Command to install dependencies
    make -f Makefile-docker update_deps_olympia

# TODO: only copy the files we need for compiling assets
COPY --chown=olympia:olympia static/ ${HOME}/static/

# Finalize the build
# TODO: We should move update_assets to the `builder` stage once we can efficiently
# Run that command without having to copy the whole source code
# This will shave nearly 1 minute off the best case build time
RUN \
    --mount=type=bind,src=src,target=${HOME}/src \
    --mount=type=bind,src=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,src=manage.py,target=${HOME}/manage.py \
    echo "from olympia.lib.settings_base import *" > settings_local.py \
    && DJANGO_SETTINGS_MODULE="settings_local" make -f Makefile-docker update_assets

FROM base as sources

RUN --mount=type=bind,src=scripts/generate_build.py,target=/generate_build.py \
    /generate_build.py > build.py

# Copy the rest of the source files from the host
COPY --chown=olympia:olympia . ${HOME}
# Copy compiled locales from builder
COPY --from=locales --chown=olympia:olympia ${HOME}/locale ${HOME}/locale
# Copy assets from assets
COPY --from=assets --chown=olympia:olympia ${HOME}/site-static ${HOME}/site-static

# version.json is overwritten by CircleCI (see circle.yml).
# The pipeline v2 standard requires the existence of /app/version.json
# inside the docker image, thus it's copied there.
COPY version.json /app/version.json

FROM sources as production

# Copy dependencies from `pip_production`
COPY --from=pip_production --chown=olympia:olympia /deps /deps

# We have to reinstall olympia after copying source
# to ensure the installation syncs files in the src/ directory
RUN make -f Makefile-docker update_deps_olympia
