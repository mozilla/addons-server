##### Important information for maintaining this Dockerfile ########################################
# Read the docs/topics/development/docker.md file for more information about this Dockerfile.
####################################################################################################

FROM python:3.11-slim-bookworm AS olympia

# Set shell to bash with logs and errors for build
SHELL ["/bin/bash", "-xue", "-c"]

ENV OLYMPIA_UID=9500
RUN <<EOF
groupadd -g ${OLYMPIA_UID} olympia
useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_UID} -s /sbin/nologin -d /data/olympia olympia
EOF

# give olympia access to the HOME directory
ENV HOME=/data/olympia
WORKDIR ${HOME}
RUN chown -R olympia:olympia ${HOME}

FROM olympia AS base
# Add keys and repos for node and mysql
# TODO: replace this with a bind mount on the RUN command
COPY docker/*.gpg.asc /etc/apt/trusted.gpg.d/
COPY docker/*.list /etc/apt/sources.list.d/

RUN <<EOF
# Add support for https apt repos and gpg signed repos
apt-get update
apt-get install -y apt-transport-https gnupg2
rm -rf /var/lib/apt/lists/*
EOF

RUN --mount=type=bind,source=docker/debian_packages.txt,target=/debian_packages.txt \
<<EOF
# Allow scripts to detect we are running in our own container
touch /addons-server-docker-container
# install packages.
apt-get update
grep -v '^#' /debian_packages.txt | xargs apt-get -y install
rm -rf /var/lib/apt/lists/*
EOF

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

RUN <<EOF
# Create directory for dependencies
mkdir /deps
chown -R olympia:olympia /deps


# For backwards-compatibility purposes, set up links to uwsgi. Note that
# the target does not exist yet at this point, but it will later.
ln -s /deps/bin/uwsgi /usr/bin/uwsgi
ln -s /usr/bin/uwsgi /usr/sbin/uwsgi

# link to the package*.json at ${HOME} so npm can install in /deps
ln -s ${HOME}/package.json /deps/package.json
ln -s ${HOME}/package-lock.json /deps/package-lock.json

# Create the storage directory and the test file to verify nginx routing
mkdir -p ${HOME}/storage
chown -R olympia:olympia ${HOME}/storage
EOF

USER olympia:olympia

ENV PIP_USER=true
ENV PIP_BUILD=/deps/build/
ENV PIP_CACHE_DIR=/deps/cache/
ENV PIP_SRC=/deps/src/
ENV PYTHONUSERBASE=/deps
ENV PATH=$PYTHONUSERBASE/bin:$PATH
ENV NPM_CONFIG_PREFIX=/deps/
ENV NPM_CACHE_DIR=/deps/cache/npm
ENV NPM_DEBUG=true
# Set python path to the project root and src to resolve olympia modules correctly
ENV PYTHONPATH=${HOME}:${HOME}/src

ENV PIP_COMMAND="python3 -m pip"
ENV NPM_ARGS="--prefix ${NPM_CONFIG_PREFIX} --cache ${NPM_CACHE_DIR} --loglevel verbose"

# All we need in "base" is pip to be installed
#this let's other layers install packages using the correct version.
RUN \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/pip.txt,target=${HOME}/requirements/pip.txt \
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
<<EOF
# Work arounds "Multiple .dist-info directories" issue.
rm -rf /deps/build/*
${PIP_COMMAND} install --progress-bar=off --no-deps --exists-action=w -r requirements/pip.txt
EOF

# Expose the DOCKER_TARGET variable to all subsequent stages
# This value is used to determine if we are building for production or development
ARG DOCKER_TARGET
ENV DOCKER_TARGET=${DOCKER_TARGET}

# Add our custom mime types (required for for ts/json/md files)
COPY docker/etc/mime.types /etc/mime.types


# Define production dependencies as a single layer
# let's the rest of the stages inherit prod dependencies
# and makes copying the /deps dir to the final layer easy.
FROM base AS pip_production

RUN \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/prod.txt,target=${HOME}/requirements/prod.txt \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
<<EOF
${PIP_COMMAND} install --progress-bar=off --no-deps --exists-action=w -r requirements/prod.txt
npm ci ${NPM_ARGS} --include=prod
EOF

# In the local development image, we stop with dependencies
# Everything else is about compiling production assets which is not needed
# in the typical development workflow.
FROM base AS development

RUN \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/prod.txt,target=${HOME}/requirements/prod.txt \
    --mount=type=bind,source=./requirements/dev.txt,target=${HOME}/requirements/dev.txt \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    make update_deps

FROM base AS locales
ARG LOCALE_DIR=${HOME}/locale
# Compile locales
# Copy the locale files from the host so it is writable by the olympia user
COPY --chown=olympia:olympia locale ${LOCALE_DIR}
# Copy the executable individually to improve the cache validity
RUN \
    --mount=type=bind,source=requirements/locale.txt,target=${HOME}/requirements/locale.txt \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,source=locale/compile-mo.sh,target=${HOME}/compile-mo.sh \
    make -f Makefile-docker compile_locales

# More efficient caching by mounting the exact files we need
# and copying only the static/ & locale/ directory.
FROM pip_production AS assets

# In order to create js i18n files with all of our strings, we need to include
# the compiled locale files
COPY --from=locales --chown=olympia:olympia ${HOME}/locale/ ${HOME}/locale/
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
<<EOF
echo "from olympia.lib.settings_base import *" > settings_local.py
DJANGO_SETTINGS_MODULE="settings_local" make -f Makefile-docker update_assets
EOF

FROM base AS production

ARG DOCKER_BUILD DOCKER_COMMIT DOCKER_VERSION

ENV DOCKER_BUILD=${DOCKER_BUILD}
ENV DOCKER_COMMIT=${DOCKER_COMMIT}
ENV DOCKER_VERSION=${DOCKER_VERSION}

# Copy the rest of the source files from the host
COPY --chown=olympia:olympia . ${HOME}
# Copy compiled locales from builder
COPY --from=locales --chown=olympia:olympia ${HOME}/locale ${HOME}/locale
# Copy assets from assets
COPY --from=assets --chown=olympia:olympia ${HOME}/site-static ${HOME}/site-static
COPY --from=assets --chown=olympia:olympia ${HOME}/static-build ${HOME}/static-build
# Copy dependencies from `pip_production`
COPY --from=pip_production --chown=olympia:olympia /deps /deps

# Set shell back to sh until we can prove we can use bash at runtime
SHELL ["/bin/sh", "-c"]
