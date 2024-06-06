##### Important information for maintaining this Dockerfile ########################################
# Read the docs/topics/development/docker.md file for more information about this Dockerfile.
####################################################################################################

FROM python:3.11-slim-bookworm as olympia

ENV OLYMPIA_UID=9500
RUN <<EOF
groupadd -g ${OLYMPIA_UID} olympia
useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_UID} -s /sbin/nologin -d /data/olympia olympia
EOF

# give olympia access to the HOME directory
ENV HOME /data/olympia
WORKDIR ${HOME}
RUN chown -R olympia:olympia ${HOME}

FROM olympia as base
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
/bin/bash  <<EOF
# Allow scripts to detect we're running in our own container
touch /addons-server-docker-container
# install packages.
apt-get update
xargs apt-get -y install < <(grep -v '^#' /debian_packages.txt)
rm -rf /var/lib/apt/lists/*
EOF

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN <<EOF
# Create directory for dependencies
# Anyone in the 9500 group should have read/write/exec permissions
mkdir -p -m 775 /deps
chown -R olympia:olympia /deps

# Remove any existing egg info directory and create a new one
rm -rf ${HOME}/src/olympia.egg-info
mkdir -p ${HOME}/src/olympia.egg-info
chown olympia:olympia ${HOME}/src/olympia.egg-info

# For backwards-compatibility purposes, set up links to uwsgi. Note that
# the target doesn't exist yet at this point, but it will later.
ln -s /deps/bin/uwsgi /usr/bin/uwsgi
ln -s /usr/bin/uwsgi /usr/sbin/uwsgi

# link to the package*.json at ${HOME} so npm can install in /deps
ln -s ${HOME}/package.json /deps/package.json
ln -s ${HOME}/package-lock.json /deps/package-lock.json
EOF

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

# All we need in "base" is pip to be installed
#this let's other layers install packages using the correct version.
RUN \
    # Files needed to run the make command
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/pip.txt,target=${HOME}/requirements/pip.txt \
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    # Command to install dependencies
    make -f Makefile-docker update_deps_pip

# Define production dependencies as a single layer
# let's the rest of the stages inherit prod dependencies
# and makes copying the /deps dir to the final layer easy.
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
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    # Command to install dependencies
    make -f Makefile-docker update_deps_production

FROM pip_production as pip_development

RUN \
    # Files needed to run the make command
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/dev.txt,target=${HOME}/requirements/dev.txt \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    # Command to install dependencies
    make -f Makefile-docker update_deps_development

FROM pip_development as locales
ARG LOCALE_DIR=${HOME}/locale
# Compile locales
# Copy the locale files from the host so it is writable by the olympia user
COPY --chown=olympia:olympia locale ${LOCALE_DIR}
# Copy the executable individually to improve the cache validity
RUN \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,source=locale/compile-mo.sh,target=${HOME}/compile-mo.sh \
    make -f Makefile-docker compile_locales

# More efficient caching by mounting the exact files we need
# and copying only the static/ directory.
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

# Add our custom mime types (required for for ts/json/md files)
COPY docker/etc/mime.types /etc/mime.types
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

# We have to reinstall olympia after copying source
# to ensure the installation syncs files in the src/ directory
RUN make -f Makefile-docker update_deps_olympia

FROM sources as development

# Copy dependencies from `pip_development`
COPY --from=pip_development --chown=olympia:olympia /deps /deps

FROM sources as production

# Copy dependencies from `pip_production`
COPY --from=pip_production --chown=olympia:olympia /deps /deps


