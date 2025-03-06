##### Important information for maintaining this Dockerfile ########################################
# Read docs/topics/development/building_and_running_services.md for more info about this Dockerfile.
####################################################################################################

# This is the root stage that should be used to set up the base environment
# there should be nothing defined here that depends on dynamic build arguments
# and should have the fewest number of dependencies as possible.
FROM python:3.12-slim-bookworm AS root

# Set shell to bash with logs and errors for build
SHELL ["/bin/bash", "-xue", "-c"]

# Hard coded environment variables globally available for all stages
ENV OLYMPIA_UID=9500
ENV BUILD_INFO=/build-info.json
ENV ENV=build
ENV HOME=/data/olympia
ENV DEPS_DIR=${HOME}/deps
# https://docs.python.org/3/using/cmdline.html#envvar-PYTHONUSERBASE
ENV PYTHONUSERBASE=${DEPS_DIR}
ENV PIP_USER=true
ENV PIP_BUILD=${DEPS_DIR}/build/
ENV PIP_CACHE_DIR=${DEPS_DIR}/cache/
ENV PIP_SRC=${DEPS_DIR}/src/
ENV PYTHONUSERBASE=${DEPS_DIR}
ENV PIP_CACHE_DIR=${DEPS_DIR}/cache/pip
ENV NPM_CACHE_DIR=${DEPS_DIR}/cache/npm
ENV NPM_DEPS_DIR=${HOME}/node_modules
ENV PATH=${DEPS_DIR}/bin:$PATH
ENV PIP_CONFIG_FILE=${HOME}/pip.conf

# Create the olympia user and group
RUN <<EOF
groupadd -g ${OLYMPIA_UID} olympia
useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_UID} -s /sbin/nologin -d ${HOME} olympia
EOF

# Create the home directory and set permissions
WORKDIR ${HOME}
RUN chown -R olympia:olympia ${HOME}

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
# For backwards-compatibility purposes, set up links to uwsgi. Note that
# the target does not exist yet at this point, but it will later.
ln -s ${DEPS_DIR}/bin/uwsgi /usr/bin/uwsgi
ln -s /usr/bin/uwsgi /usr/sbin/uwsgi
EOF

# This stage should include build args that are saved to a read only
# file in the image. This file can be used at runtime to provide build
# information that cannot be overriden in the container environment.
FROM root AS info

ARG DOCKER_BUILD
ARG DOCKER_COMMIT
ARG DOCKER_TAG
ARG DOCKER_TARGET
ARG DOCKER_VERSION
ARG OLYMPIA_DEPS

# Create the build file hard coding build variables to the image
RUN <<EOF
cat <<INNEREOF > ${BUILD_INFO}
{
  "build": "${DOCKER_BUILD}",
  "commit": "${DOCKER_COMMIT}",
  "tag": "${DOCKER_TAG}",
  "target": "${DOCKER_TARGET}",
  "source": "https://github.com/mozilla/addons-server",
  "version": "${DOCKER_VERSION}",
  "deps": "${OLYMPIA_DEPS}"
}
INNEREOF
# Set permissions to make the file readable by all but only writable by root
chmod 644 ${BUILD_INFO}
EOF

# This stage is where we switch to the olympia user
# and should be used as a root branch for all subsequent stages
FROM root AS olympia

# Copy the pip.conf to globally configure pip
COPY pip.conf ${HOME}/pip.conf
# Ensure build info is available to all build stages
COPY --from=info ${BUILD_INFO} ${BUILD_INFO}

USER olympia:olympia

# All we need in "base" is pip to be installed
#this let's other layers install packages using the correct version.
RUN \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,source=scripts/install_deps.py,target=${HOME}/scripts/install_deps.py \
    --mount=type=bind,source=scripts/clean_directory.py,target=${HOME}/scripts/clean_directory.py \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/pip.txt,target=${HOME}/requirements/pip.txt \
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
<<EOF
${HOME}/scripts/install_deps.py pip
EOF

# Add our custom mime types (required for for ts/json/md files)
COPY docker/etc/mime.types /etc/mime.types

FROM olympia AS development

# Copy build info from info
COPY --from=info ${BUILD_INFO} ${BUILD_INFO}

# Define production dependencies as a single layer
# let's the rest of the stages inherit prod dependencies
# and makes copying the /data/olympia/deps dir to the final layer easy.
FROM olympia AS pip_production

COPY --from=info ${BUILD_INFO} ${BUILD_INFO}

RUN \
    --mount=type=bind,source=scripts/install_deps.py,target=${HOME}/scripts/install_deps.py \
    # Files required to install pip dependencies
    --mount=type=bind,source=./requirements/prod.txt,target=${HOME}/requirements/prod.txt \
    # Files required to install npm dependencies
    --mount=type=bind,source=package.json,target=${HOME}/package.json \
    --mount=type=bind,source=package-lock.json,target=${HOME}/package-lock.json \
    # Mounts for caching dependencies These paths should be kept in sync with
    # .npmrc and pip.conf in the repository root.
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=cache,target=${NPM_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
    --mount=type=bind,source=.npmrc,target=${HOME}/.npmrc \
<<EOF
${HOME}/scripts/install_deps.py prod
EOF

FROM olympia AS locales
ARG LOCALE_DIR=${HOME}/locale
# Compile locales
# Copy the locale files from the host so it is writable by the olympia user
COPY --chown=olympia:olympia locale ${LOCALE_DIR}
# Copy the executable individually to improve the cache validity
RUN \
    --mount=type=bind,source=requirements/locale.txt,target=${HOME}/requirements/locale.txt \
    --mount=type=bind,source=Makefile-docker,target=${HOME}/Makefile-docker \
    --mount=type=bind,source=scripts/compile_locales.py,target=${HOME}/scripts/compile_locales.py \
    --mount=type=bind,source=scripts/clean_directory.py,target=${HOME}/scripts/clean_directory.py \
    --mount=type=bind,source=scripts/install_deps.py,target=${HOME}/scripts/install_deps.py \
    --mount=type=cache,target=${PIP_CACHE_DIR},uid=${OLYMPIA_UID},gid=${OLYMPIA_UID} \
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
    --mount=type=bind,src=scripts/update_assets.py,target=${HOME}/scripts/update_assets.py \
    --mount=type=bind,src=scripts/clean_directory.py,target=${HOME}/scripts/clean_directory.py \
    --mount=type=bind,src=manage.py,target=${HOME}/manage.py \
    --mount=type=bind,src=package.json,target=${HOME}/package.json \
    --mount=type=bind,src=package-lock.json,target=${HOME}/package-lock.json \
    --mount=type=bind,src=vite.config.js,target=${HOME}/vite.config.js \
<<EOF
make -f Makefile-docker update_assets
EOF

FROM olympia AS production
# Copy the rest of the source files from the host
COPY --chown=olympia:olympia . ${HOME}
# Copy compiled locales from builder
COPY --from=locales --chown=olympia:olympia ${HOME}/locale ${HOME}/locale
# Copy assets from assets
COPY --from=assets --chown=olympia:olympia ${HOME}/site-static ${HOME}/site-static
COPY --from=assets --chown=olympia:olympia ${HOME}/static-build ${HOME}/static-build
# Copy build info from info
COPY --from=info ${BUILD_INFO} ${BUILD_INFO}
# Copy compiled locales from builder
COPY --from=locales --chown=olympia:olympia ${HOME}/locale ${HOME}/locale
# Copy pip dependencies from `pip_production`
COPY --from=pip_production --chown=olympia:olympia ${DEPS_DIR} ${DEPS_DIR}
# Copy npm dependencies from `pip_production`
COPY --from=pip_production --chown=olympia:olympia ${NPM_DEPS_DIR} ${NPM_DEPS_DIR}
