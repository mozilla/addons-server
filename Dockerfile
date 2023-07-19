FROM python:3.10-slim-buster

# Should change it to use ARG instead of ENV for OLYMPIA_UID/OLYMPIA_GID
# once the jenkins server is upgraded to support docker >= v1.9.0
ENV OLYMPIA_UID=9500 \
    OLYMPIA_GID=9500
RUN groupadd -g ${OLYMPIA_GID} olympia && useradd -u ${OLYMPIA_UID} -g ${OLYMPIA_GID} -s /sbin/nologin -d /data/olympia olympia

# Add support for https apt repos, gpg signed repos, curl to download packages
# directly to build a local mirror.
RUN apt-get update && apt-get install -y \
        apt-transport-https              \
        gnupg2                           \
        curl                             \
    && rm -rf /var/lib/apt/lists/*
# Add keys and repos for node and mysql
COPY docker/*.gpg.key /etc/pki/gpg/
RUN APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn \
    apt-key add /etc/pki/gpg/nodesource.gpg.key \
    && APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn \
    apt-key add /etc/pki/gpg/mysql.gpg.key
COPY docker/*.list /etc/apt/sources.list.d/

# Override mysql repos with our own locally built one while upstream is broken.
RUN mkdir /opt/apt-local-repository
COPY docker/mysql/* /opt/apt-local-repository
RUN /opt/apt-local-repository/local-mysql-repos.sh

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
COPY --chown=olympia:olympia . ${HOME}
WORKDIR ${HOME}

# Set up directories and links that we'll need later, before switching to the
# olympia user.
RUN mkdir /deps \
    && chown olympia:olympia /deps \
    && rm -rf ${HOME}/src/olympia.egg-info \
    && mkdir ${HOME}/src/olympia.egg-info \
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
RUN ln -s ${HOME}/package.json /deps/package.json \
    && ln -s ${HOME}/package-lock.json /deps/package-lock.json \
    && make update_deps

WORKDIR ${HOME}

# Build locales, assets, build id.
RUN echo "from olympia.lib.settings_base import *\n" \
> settings_local.py && DJANGO_SETTINGS_MODULE='settings_local' locale/compile-mo.sh locale \
    && DJANGO_SETTINGS_MODULE='settings_local' python manage.py compress_assets \
    && DJANGO_SETTINGS_MODULE='settings_local' python manage.py generate_jsi18n_files \
    && DJANGO_SETTINGS_MODULE='settings_local' python manage.py collectstatic --noinput \
    && npm prune --production \
    && ./scripts/generate_build.py > build.py \
    && rm -f settings_local.py settings_local.pyc
